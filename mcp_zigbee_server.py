#!/usr/bin/env python3
"""
MCP Server — Zigbee Light Control

Exposes Zigbee lights as tools consumable by Claude Desktop,
Claude Code, and any MCP-compatible client.

Usage:
    python mcp_zigbee_server.py               # stdio transport (Claude Desktop)
    python mcp_zigbee_server.py --sse          # SSE transport (web clients)

Claude Desktop config  (~/.config/claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "zigbee-lights": {
          "command": "python",
          "args": ["/home/user/zigbeendicate-sounds/mcp_zigbee_server.py"]
        }
      }
    }
"""

import json
import argparse
import sys
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("mcp package not installed. Run: pip install 'mcp[cli]' fastmcp", file=sys.stderr)
    sys.exit(1)

from zigbee_light_controller import ZigbeeLightController

# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="zigbee-lights",
    description=(
        "Control Zigbee smart lights via Zigbee2MQTT. "
        "Supports color (HSV/RGB), brightness, effects, presets, and on/off."
    ),
)

_controller: ZigbeeLightController | None = None
_lights: list[str] = []
_presets: dict = {}


def _get_controller() -> ZigbeeLightController:
    global _controller, _lights
    if _controller is None or not _controller.connected:
        _controller = ZigbeeLightController()
        ok = _controller.connect()
        if not ok:
            raise RuntimeError("Cannot connect to MQTT broker (is Mosquitto running?)")
        _lights = _controller.discover_lights()
    return _controller


def _load_presets() -> dict:
    global _presets
    if not _presets:
        preset_path = Path(__file__).parent / "color_presets.json"
        if preset_path.exists():
            _presets = json.loads(preset_path.read_text())
    return _presets


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_lights() -> dict:
    """List all discovered Zigbee color lights."""
    ctrl = _get_controller()
    lights = ctrl.discover_lights()
    return {"lights": lights, "count": len(lights)}


@mcp.tool()
def set_color_hsv(
    light_name: str,
    hue: int,
    saturation: int = 100,
    brightness: int = 200,
    transition: float = 0.5,
) -> dict:
    """
    Set a Zigbee light to a color using HSV (Hue-Saturation-Value).

    Args:
        light_name: Friendly name of the light (e.g. "living_room").
                    Use "all" to affect every discovered light.
        hue: Color hue 0–360 (0=red, 120=green, 240=blue).
        saturation: Color saturation 0–100 (0=white, 100=vivid).
        brightness: Brightness 0–254.
        transition: Fade duration in seconds (0 = instant).
    """
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.set_color_hue(light, hue, saturation, brightness, transition)
    return {"ok": True, "targets": targets, "hue": hue, "saturation": saturation, "brightness": brightness}


@mcp.tool()
def set_color_rgb(
    light_name: str,
    r: int,
    g: int,
    b: int,
    brightness: int = 200,
    transition: float = 0.5,
) -> dict:
    """
    Set a Zigbee light to a color using RGB values.

    Args:
        light_name: Friendly name or "all".
        r: Red 0–255.
        g: Green 0–255.
        b: Blue 0–255.
        brightness: Brightness 0–254.
        transition: Fade duration in seconds.
    """
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.set_color_rgb(light, r, g, b, brightness, transition)
    return {"ok": True, "targets": targets, "r": r, "g": g, "b": b}


@mcp.tool()
def set_brightness(light_name: str, brightness: int, transition: float = 0.5) -> dict:
    """
    Set brightness of a Zigbee light without changing its color.

    Args:
        light_name: Friendly name or "all".
        brightness: Brightness 0–254.
        transition: Fade duration in seconds.
    """
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.set_brightness(light, brightness, transition)
    return {"ok": True, "targets": targets, "brightness": brightness}


@mcp.tool()
def turn_on(light_name: str) -> dict:
    """Turn a Zigbee light on. Use "all" for every light."""
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.turn_on(light)
    return {"ok": True, "targets": targets, "state": "ON"}


@mcp.tool()
def turn_off(light_name: str) -> dict:
    """Turn a Zigbee light off. Use "all" for every light."""
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.turn_off(light)
    return {"ok": True, "targets": targets, "state": "OFF"}


@mcp.tool()
def apply_effect(light_name: str, effect: str) -> dict:
    """
    Trigger a built-in Zigbee light effect.

    Args:
        light_name: Friendly name or "all".
        effect: Effect name — "colorloop", "blink", "breathe", "okay", "channel_change",
                "candle_flicker", "fireplace", "random", "none".
    """
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.effect(light, effect)
    return {"ok": True, "targets": targets, "effect": effect}


@mcp.tool()
def list_presets() -> dict:
    """List all available color presets with their descriptions."""
    presets = _load_presets()
    result = {}
    for name, data in presets.items():
        result[name] = {
            "colors": list(data.get("colors", {}).keys()),
            "brightness": data.get("default_brightness", 200),
            "transition": data.get("transition", 0.5),
        }
    return {"presets": result, "count": len(result)}


@mcp.tool()
def apply_preset(preset_name: str, light_name: str = "all") -> dict:
    """
    Apply a named color preset to lights.

    Args:
        preset_name: Name of the preset (e.g. "Warm", "Ocean", "Party").
                     Call list_presets() to see available names.
        light_name: Friendly name or "all".
    """
    presets = _load_presets()
    if preset_name not in presets:
        available = list(presets.keys())
        raise ValueError(f"Unknown preset '{preset_name}'. Available: {available}")

    preset = presets[preset_name]
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    brightness = preset.get("default_brightness", 200)
    transition = preset.get("transition", 0.5)

    # Apply first color in preset to all target lights
    colors = preset.get("colors", {})
    if colors:
        first_color = next(iter(colors.values()))
        hue = first_color.get("hue", 0)
        sat = first_color.get("saturation", 100)
        for light in targets:
            ctrl.set_color_hue(light, hue, sat, brightness, transition)

    return {"ok": True, "preset": preset_name, "targets": targets}


@mcp.tool()
def set_warm_white(light_name: str = "all", brightness: int = 180) -> dict:
    """Set lights to warm white (hue=30, saturation=30). Good for reading or relaxing."""
    ctrl = _get_controller()
    targets = _lights if light_name == "all" else [light_name]
    for light in targets:
        ctrl.set_color_hue(light, 30, 30, brightness, 1.0)
    return {"ok": True, "targets": targets, "mode": "warm_white"}


# ---------------------------------------------------------------------------
# Resources — expose config as readable documents
# ---------------------------------------------------------------------------

@mcp.resource("zigbee://presets")
def presets_resource() -> str:
    """All color presets as JSON."""
    return json.dumps(_load_presets(), indent=2)


@mcp.resource("zigbee://lights")
def lights_resource() -> str:
    """Currently discovered lights."""
    ctrl = _get_controller()
    return json.dumps({"lights": ctrl.discover_lights()})


# ---------------------------------------------------------------------------
# Prompts — reusable prompt templates for Claude
# ---------------------------------------------------------------------------

@mcp.prompt()
def party_mode_prompt() -> str:
    """Prompt that tells Claude to set up a dynamic party lighting scene."""
    return (
        "Use the zigbee-lights MCP tools to create a party atmosphere. "
        "Turn all lights on, apply the 'Party' preset, then set a colorloop effect. "
        "Report which lights were affected."
    )


@mcp.prompt()
def movie_mode_prompt() -> str:
    """Prompt that dims and warms lights for movie watching."""
    return (
        "Use the zigbee-lights MCP tools to prepare for movie watching: "
        "dim all lights to brightness 60, set warm white color (hue=25, saturation=40), "
        "with a 3-second transition. Report the result."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Zigbee MCP Server")
    parser.add_argument("--sse", action="store_true", help="Use SSE transport instead of stdio")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE transport")
    args = parser.parse_args()

    if args.sse:
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
