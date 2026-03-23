#!/usr/bin/env python3
"""
REST + WebSocket API Server for Zigbee Light Control.

Allows any app (Home Assistant, web dashboard, VS Code extension,
GitHub Copilot, Cursor, mobile apps) to control lights over HTTP/WS.

Usage:
    python api_server.py                        # default port 8080
    python api_server.py --port 9090
    python api_server.py --host 0.0.0.0         # bind all interfaces

Endpoints:
    GET  /lights                    — list discovered lights
    POST /lights/{name}/color/hsv   — set color (HSV)
    POST /lights/{name}/color/rgb   — set color (RGB)
    POST /lights/{name}/brightness  — set brightness
    POST /lights/{name}/on          — turn on
    POST /lights/{name}/off         — turn off
    POST /lights/{name}/effect      — trigger effect
    POST /presets/{name}/apply      — apply color preset
    GET  /presets                   — list all presets
    GET  /state                     — current controller state snapshot
    WS   /ws                        — real-time state push (JSON events)

"all" is accepted as light_name to target every discovered light.
"""

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    print("fastapi/uvicorn not installed. Run: pip install fastapi 'uvicorn[standard]'", file=sys.stderr)
    sys.exit(1)

from zigbee_light_controller import ZigbeeLightController

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_controller: ZigbeeLightController | None = None
_lights: list[str] = []
_presets: dict = {}
_ws_clients: list[WebSocket] = []
_state: dict[str, Any] = {
    "lights_on": True,
    "brightness": 200,
    "hue": 0,
    "saturation": 100,
    "preset": None,
    "effect": None,
}


def _get_controller() -> ZigbeeLightController:
    global _controller, _lights
    if _controller is None or not _controller.connected:
        _controller = ZigbeeLightController()
        if not _controller.connect():
            raise RuntimeError("MQTT broker unreachable")
        _lights = _controller.discover_lights()
    return _controller


def _load_presets() -> dict:
    global _presets
    if not _presets:
        path = Path(__file__).parent / "color_presets.json"
        if path.exists():
            _presets = json.loads(path.read_text())
    return _presets


async def _broadcast(event: dict):
    """Push JSON event to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _controller, _lights
    _controller = ZigbeeLightController()
    _controller.connect()
    _lights = _controller.discover_lights()
    yield
    if _controller:
        _controller.disconnect()


app = FastAPI(
    title="Zigbee Light API",
    description="REST + WebSocket API for controlling Zigbee smart lights via Zigbee2MQTT.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class HSVRequest(BaseModel):
    hue: int = Field(ge=0, le=360, description="Hue 0–360")
    saturation: int = Field(default=100, ge=0, le=100, description="Saturation 0–100")
    brightness: int = Field(default=200, ge=0, le=254, description="Brightness 0–254")
    transition: float = Field(default=0.5, ge=0, le=10, description="Fade time in seconds")


class RGBRequest(BaseModel):
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)
    brightness: int = Field(default=200, ge=0, le=254)
    transition: float = Field(default=0.5, ge=0, le=10)


class BrightnessRequest(BaseModel):
    brightness: int = Field(ge=0, le=254)
    transition: float = Field(default=0.5, ge=0, le=10)


class EffectRequest(BaseModel):
    effect: str = Field(description="colorloop | blink | breathe | candle_flicker | fireplace | none")


# ---------------------------------------------------------------------------
# Helper: resolve "all" to every light
# ---------------------------------------------------------------------------

def _targets(light_name: str) -> list[str]:
    if light_name == "all":
        return _lights
    if light_name not in _lights:
        raise HTTPException(404, f"Light '{light_name}' not found. Known: {_lights}")
    return [light_name]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/lights", summary="List all discovered Zigbee color lights")
async def get_lights():
    ctrl = _get_controller()
    lights = ctrl.discover_lights()
    return {"lights": lights, "count": len(lights)}


@app.post("/lights/{light_name}/color/hsv", summary="Set color using HSV")
async def color_hsv(light_name: str, req: HSVRequest):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.set_color_hue(light, req.hue, req.saturation, req.brightness, req.transition)
    _state.update({"hue": req.hue, "saturation": req.saturation, "brightness": req.brightness})
    await _broadcast({"event": "color_hsv", "targets": targets, **req.model_dump()})
    return {"ok": True, "targets": targets}


@app.post("/lights/{light_name}/color/rgb", summary="Set color using RGB")
async def color_rgb(light_name: str, req: RGBRequest):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.set_color_rgb(light, req.r, req.g, req.b, req.brightness, req.transition)
    await _broadcast({"event": "color_rgb", "targets": targets, **req.model_dump()})
    return {"ok": True, "targets": targets}


@app.post("/lights/{light_name}/brightness", summary="Set brightness only")
async def set_brightness(light_name: str, req: BrightnessRequest):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.set_brightness(light, req.brightness, req.transition)
    _state["brightness"] = req.brightness
    await _broadcast({"event": "brightness", "targets": targets, **req.model_dump()})
    return {"ok": True, "targets": targets}


@app.post("/lights/{light_name}/on", summary="Turn light(s) on")
async def turn_on(light_name: str):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.turn_on(light)
    _state["lights_on"] = True
    await _broadcast({"event": "on", "targets": targets})
    return {"ok": True, "targets": targets, "state": "ON"}


@app.post("/lights/{light_name}/off", summary="Turn light(s) off")
async def turn_off(light_name: str):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.turn_off(light)
    _state["lights_on"] = False
    await _broadcast({"event": "off", "targets": targets})
    return {"ok": True, "targets": targets, "state": "OFF"}


@app.post("/lights/{light_name}/effect", summary="Trigger a light effect")
async def apply_effect(light_name: str, req: EffectRequest):
    ctrl = _get_controller()
    targets = _targets(light_name)
    for light in targets:
        ctrl.effect(light, req.effect)
    _state["effect"] = req.effect
    await _broadcast({"event": "effect", "targets": targets, "effect": req.effect})
    return {"ok": True, "targets": targets, "effect": req.effect}


@app.get("/presets", summary="List all color presets")
async def list_presets():
    presets = _load_presets()
    return {"presets": list(presets.keys()), "count": len(presets)}


@app.post("/presets/{preset_name}/apply", summary="Apply a color preset to lights")
async def apply_preset(preset_name: str, light_name: str = "all"):
    presets = _load_presets()
    if preset_name not in presets:
        raise HTTPException(404, f"Preset '{preset_name}' not found. Available: {list(presets.keys())}")

    preset = presets[preset_name]
    ctrl = _get_controller()
    targets = _targets(light_name)
    brightness = preset.get("default_brightness", 200)
    transition = preset.get("transition", 0.5)
    colors = preset.get("colors", {})

    if colors:
        first = next(iter(colors.values()))
        hue, sat = first.get("hue", 0), first.get("saturation", 100)
        for light in targets:
            ctrl.set_color_hue(light, hue, sat, brightness, transition)
        _state.update({"preset": preset_name, "hue": hue, "saturation": sat, "brightness": brightness})

    await _broadcast({"event": "preset", "preset": preset_name, "targets": targets})
    return {"ok": True, "preset": preset_name, "targets": targets}


@app.get("/state", summary="Get current light state snapshot")
async def get_state():
    return {"state": _state, "lights": _lights}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    await ws.send_json({"event": "connected", "state": _state, "lights": _lights})
    try:
        while True:
            # Keep-alive: echo any incoming pings
            data = await ws.receive_text()
            await ws.send_json({"event": "pong", "echo": data})
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Zigbee Light REST/WebSocket API")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")
    args = parser.parse_args()

    uvicorn.run(
        "api_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
