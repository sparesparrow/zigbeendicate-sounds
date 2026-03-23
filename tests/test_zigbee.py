"""
Unit tests for ZigbeeLightController.

All MQTT I/O is mocked — no real broker or hardware required.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mqtt(monkeypatch):
    """Replace paho-mqtt Client with a mock throughout the module."""
    mock_client = MagicMock()
    mock_client.connect.return_value = None
    mock_client.loop_start.return_value = None
    mock_client.loop_stop.return_value = None
    mock_client.disconnect.return_value = None
    mock_client.publish.return_value = MagicMock(rc=0)
    mock_client.subscribe.return_value = None

    with patch("paho.mqtt.client.Client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def controller(mock_mqtt):
    """Return a ZigbeeLightController whose MQTT is fully mocked."""
    from zigbee_light_controller import ZigbeeLightController

    ctrl = ZigbeeLightController(mqtt_broker="localhost", mqtt_port=1883)
    # Simulate successful connection callback
    ctrl.connected = True
    return ctrl


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

class TestConnection:
    def test_connect_success(self, mock_mqtt):
        from zigbee_light_controller import ZigbeeLightController

        mock_mqtt.connect.return_value = None
        ctrl = ZigbeeLightController()
        result = ctrl.connect()

        assert result is True
        mock_mqtt.connect.assert_called_once_with("localhost", 1883, 60)
        mock_mqtt.loop_start.assert_called_once()

    def test_connect_failure(self, mock_mqtt):
        from zigbee_light_controller import ZigbeeLightController

        mock_mqtt.connect.side_effect = ConnectionRefusedError("broker down")
        ctrl = ZigbeeLightController()
        result = ctrl.connect()

        assert result is False

    def test_disconnect(self, controller, mock_mqtt):
        controller.disconnect()
        mock_mqtt.loop_stop.assert_called_once()
        mock_mqtt.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Color control tests
# ---------------------------------------------------------------------------

class TestColorControl:
    def _published_payload(self, mock_mqtt) -> dict:
        """Extract the JSON payload from the last publish call."""
        args = mock_mqtt.publish.call_args
        return json.loads(args[0][1])  # positional arg index 1 is the payload

    def _published_topic(self, mock_mqtt) -> str:
        args = mock_mqtt.publish.call_args
        return args[0][0]

    def test_set_color_hue_topic(self, controller, mock_mqtt):
        controller.set_color_hue("living_room", hue=120)
        assert self._published_topic(mock_mqtt) == "zigbee2mqtt/living_room/set"

    def test_set_color_hue_payload(self, controller, mock_mqtt):
        controller.set_color_hue("living_room", hue=240, saturation=80, brightness=200, transition=0.5)
        payload = self._published_payload(mock_mqtt)
        assert payload["color"]["hue"] == 240
        assert payload["color"]["saturation"] == 80
        assert payload["brightness"] == 200
        assert payload["transition"] == 0.5

    def test_set_color_rgb_payload(self, controller, mock_mqtt):
        controller.set_color_rgb("bedroom", r=255, g=0, b=128, brightness=150, transition=1.0)
        payload = self._published_payload(mock_mqtt)
        assert payload["color"]["r"] == 255
        assert payload["color"]["g"] == 0
        assert payload["color"]["b"] == 128
        assert payload["brightness"] == 150

    def test_set_brightness_only(self, controller, mock_mqtt):
        controller.set_brightness("kitchen", brightness=100, transition=0.0)
        payload = self._published_payload(mock_mqtt)
        assert payload["brightness"] == 100
        assert "color" not in payload

    def test_turn_on(self, controller, mock_mqtt):
        controller.turn_on("hall")
        payload = self._published_payload(mock_mqtt)
        assert payload["state"] == "ON"

    def test_turn_off(self, controller, mock_mqtt):
        controller.turn_off("hall")
        payload = self._published_payload(mock_mqtt)
        assert payload["state"] == "OFF"

    def test_effect(self, controller, mock_mqtt):
        controller.effect("living_room", "colorloop")
        payload = self._published_payload(mock_mqtt)
        assert payload["effect"] == "colorloop"

    def test_all_lights_calls_each(self, controller, mock_mqtt):
        lights = ["room_a", "room_b", "room_c"]
        controller.all_lights(lights, controller.turn_on)
        assert mock_mqtt.publish.call_count == len(lights)

        topics = [c[0][0] for c in mock_mqtt.publish.call_args_list]
        for light in lights:
            assert f"zigbee2mqtt/{light}/set" in topics


# ---------------------------------------------------------------------------
# Device discovery tests
# ---------------------------------------------------------------------------

class TestDiscovery:
    def _setup_devices(self, controller, devices: list):
        controller.devices = devices

    def test_discover_color_lights(self, controller, mock_mqtt):
        self._setup_devices(controller, [
            {"friendly_name": "bulb_1", "definition": {"exposes": [{"name": "color_xy"}]}},
            {"friendly_name": "sensor_1", "definition": {"exposes": [{"name": "occupancy"}]}},
            {"friendly_name": "bulb_2", "definition": {"exposes": [{"name": "color_hs"}]}},
        ])
        lights = controller.discover_lights()
        assert "bulb_1" in lights
        assert "bulb_2" in lights
        assert "sensor_1" not in lights

    def test_discover_empty(self, controller, mock_mqtt):
        controller.devices = []
        lights = controller.discover_lights()
        assert lights == []

    def test_discover_motion_sensors(self, controller, mock_mqtt):
        self._setup_devices(controller, [
            {"friendly_name": "pir_hall", "model_id": "MS-01", "definition": {"description": "PIR motion sensor"}, "ieee_address": "0x1", "manufacturer": "Aqara"},
            {"friendly_name": "bulb_1", "model_id": "CWA67", "definition": {"description": "Color light bulb"}, "ieee_address": "0x2", "manufacturer": "Ikea"},
        ])
        sensors = controller.discover_motion_sensors()
        assert len(sensors) == 1
        assert sensors[0]["friendly_name"] == "pir_hall"
