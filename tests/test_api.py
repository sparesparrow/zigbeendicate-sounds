"""
Integration tests for the FastAPI REST server.

Uses FastAPI's TestClient — no real MQTT or lights required.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_controller():
    ctrl = MagicMock()
    ctrl.connected = True
    ctrl.discover_lights.return_value = ["living_room", "bedroom"]
    return ctrl


@pytest.fixture
def client(mock_controller, tmp_path):
    """TestClient with MQTT mocked out."""
    # Write a minimal presets file the server can load
    presets = {
        "Warm": {
            "colors": {"A": {"hue": 30, "saturation": 80}},
            "default_brightness": 180,
            "transition": 1.0,
        },
        "Cool": {
            "colors": {"A": {"hue": 200, "saturation": 90}},
            "default_brightness": 200,
            "transition": 0.5,
        },
    }
    (tmp_path / "color_presets.json").write_text(json.dumps(presets))

    with (
        patch("api_server.ZigbeeLightController", return_value=mock_controller),
        patch("api_server._load_presets", return_value=presets),
        patch("api_server._lights", ["living_room", "bedroom"]),
        patch("api_server._controller", mock_controller),
    ):
        from api_server import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, mock_controller


# ---------------------------------------------------------------------------
# GET /lights
# ---------------------------------------------------------------------------

class TestGetLights:
    def test_returns_list(self, client):
        c, ctrl = client
        resp = c.get("/lights")
        assert resp.status_code == 200
        data = resp.json()
        assert "lights" in data
        assert isinstance(data["lights"], list)

    def test_returns_count(self, client):
        c, ctrl = client
        resp = c.get("/lights")
        data = resp.json()
        assert data["count"] == len(data["lights"])


# ---------------------------------------------------------------------------
# POST /lights/{name}/color/hsv
# ---------------------------------------------------------------------------

class TestColorHSV:
    def test_valid_payload(self, client):
        c, ctrl = client
        resp = c.post("/lights/living_room/color/hsv", json={"hue": 120, "saturation": 80, "brightness": 200})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_calls_controller(self, client):
        c, ctrl = client
        c.post("/lights/living_room/color/hsv", json={"hue": 240, "saturation": 100, "brightness": 150})
        ctrl.set_color_hue.assert_called()

    def test_hue_out_of_range(self, client):
        c, ctrl = client
        resp = c.post("/lights/living_room/color/hsv", json={"hue": 400})
        assert resp.status_code == 422

    def test_unknown_light(self, client):
        c, ctrl = client
        resp = c.post("/lights/unknown_light/color/hsv", json={"hue": 120})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /lights/{name}/color/rgb
# ---------------------------------------------------------------------------

class TestColorRGB:
    def test_valid_rgb(self, client):
        c, ctrl = client
        resp = c.post("/lights/bedroom/color/rgb", json={"r": 255, "g": 0, "b": 128})
        assert resp.status_code == 200
        ctrl.set_color_rgb.assert_called()

    def test_rgb_out_of_range(self, client):
        c, ctrl = client
        resp = c.post("/lights/bedroom/color/rgb", json={"r": 300, "g": 0, "b": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /lights/{name}/on and /off
# ---------------------------------------------------------------------------

class TestOnOff:
    def test_turn_on(self, client):
        c, ctrl = client
        resp = c.post("/lights/living_room/on")
        assert resp.status_code == 200
        assert resp.json()["state"] == "ON"
        ctrl.turn_on.assert_called_with("living_room")

    def test_turn_off(self, client):
        c, ctrl = client
        resp = c.post("/lights/bedroom/off")
        assert resp.status_code == 200
        assert resp.json()["state"] == "OFF"
        ctrl.turn_off.assert_called_with("bedroom")

    def test_all_on(self, client):
        c, ctrl = client
        resp = c.post("/lights/all/on")
        assert resp.status_code == 200
        assert ctrl.turn_on.call_count >= 1


# ---------------------------------------------------------------------------
# GET /presets and POST /presets/{name}/apply
# ---------------------------------------------------------------------------

class TestPresets:
    def test_list_presets(self, client):
        c, _ = client
        resp = c.get("/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert "Warm" in data["presets"]

    def test_apply_valid_preset(self, client):
        c, ctrl = client
        resp = c.post("/presets/Warm/apply")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_apply_unknown_preset(self, client):
        c, _ = client
        resp = c.post("/presets/NonExistent/apply")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /state
# ---------------------------------------------------------------------------

class TestState:
    def test_state_has_required_keys(self, client):
        c, _ = client
        resp = c.get("/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert "lights" in data
