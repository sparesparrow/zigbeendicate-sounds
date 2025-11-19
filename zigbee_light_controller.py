#!/usr/bin/env python3
"""
Zigbee Light Controller
Controls Zigbee color bulbs via MQTT (Zigbee2MQTT)
"""

import paho.mqtt.client as mqtt
import json
import time
from typing import List, Dict

class ZigbeeLightController:
    def __init__(self, mqtt_broker='localhost', mqtt_port=1883):
        self.broker = mqtt_broker
        self.port = mqtt_port
        self.client = mqtt.Client()
        self.connected = False
        self.devices = []

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            time.sleep(1)  # Wait for connection
            print(f"✓ Connected to MQTT broker at {self.broker}:{self.port}")
            return True
        except Exception as e:
            print(f"✗ Failed to connect to MQTT broker: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.connected = True
            # Subscribe to device announcements
            client.subscribe("zigbee2mqtt/bridge/devices")
            print("  Subscribed to zigbee2mqtt/bridge/devices")
        else:
            print(f"  Connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        try:
            payload = json.loads(msg.payload.decode())
            if msg.topic == "zigbee2mqtt/bridge/devices":
                self.devices = payload
                print(f"  Discovered {len(self.devices)} Zigbee devices")
        except Exception as e:
            pass  # Ignore parsing errors

    def discover_lights(self) -> List[str]:
        """Discover available Zigbee color lights"""
        # Request device list
        self.client.publish("zigbee2mqtt/bridge/request/devices", "")
        time.sleep(1)

        # Filter for lights with color capability
        lights = []
        for device in self.devices:
            if isinstance(device, dict):
                friendly_name = device.get('friendly_name', '')
                definition = device.get('definition', {})

                if definition and 'color' in str(definition).lower():
                    lights.append(friendly_name)

        print(f"\n  Found {len(lights)} color lights:")
        for light in lights:
            print(f"    - {light}")

        return lights

    def discover_motion_sensors(self) -> List[Dict[str, str]]:
        """
        Discover available Zigbee motion/occupancy sensors

        Returns:
            List of dicts with sensor info: {
                'friendly_name': str,
                'ieee_address': str,
                'model': str,
                'manufacturer': str
            }
        """
        # Request device list
        self.client.publish("zigbee2mqtt/bridge/request/devices", "")
        time.sleep(1)

        # Filter for motion/occupancy sensors
        motion_sensors = []
        for device in self.devices:
            if isinstance(device, dict):
                friendly_name = device.get('friendly_name', '')
                model = device.get('model_id', '').lower()
                definition = device.get('definition', {})
                description = definition.get('description', '').lower() if definition else ''

                # Check if it's a motion sensor
                is_motion_sensor = any([
                    'motion' in model,
                    'pir' in model,
                    'occupancy' in model,
                    'motion' in description,
                    'pir' in description,
                    'occupancy' in description
                ])

                if is_motion_sensor:
                    sensor_info = {
                        'friendly_name': friendly_name,
                        'ieee_address': device.get('ieee_address', ''),
                        'model': device.get('model_id', 'Unknown'),
                        'manufacturer': device.get('manufacturer', 'Unknown')
                    }
                    motion_sensors.append(sensor_info)

        print(f"\n  Found {len(motion_sensors)} motion sensors:")
        for sensor in motion_sensors:
            print(f"    - {sensor['friendly_name']}: {sensor['model']} ({sensor['manufacturer']})")

        return motion_sensors

    def set_color_hue(self, light_name: str, hue: int, saturation: int = 100, brightness: int = 254, transition: float = 0.0):
        """
        Set light color using HSV

        Args:
            light_name: Friendly name of the light
            hue: Hue value (0-360)
            saturation: Saturation (0-100)
            brightness: Brightness (0-254)
            transition: Transition time in seconds
        """
        payload = {
            'color': {
                'hue': hue,
                'saturation': saturation
            },
            'brightness': brightness,
            'transition': transition
        }

        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def set_color_rgb(self, light_name: str, r: int, g: int, b: int, brightness: int = 254, transition: float = 0.0):
        """
        Set light color using RGB

        Args:
            light_name: Friendly name of the light
            r, g, b: RGB values (0-255)
            brightness: Brightness (0-254)
            transition: Transition time in seconds
        """
        payload = {
            'color': {
                'r': r,
                'g': g,
                'b': b
            },
            'brightness': brightness,
            'transition': transition
        }

        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def set_brightness(self, light_name: str, brightness: int, transition: float = 0.0):
        """Set light brightness"""
        payload = {
            'brightness': brightness,
            'transition': transition
        }

        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def turn_on(self, light_name: str):
        """Turn light on"""
        payload = {'state': 'ON'}
        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def turn_off(self, light_name: str):
        """Turn light off"""
        payload = {'state': 'OFF'}
        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def effect(self, light_name: str, effect: str):
        """Trigger light effect"""
        payload = {'effect': effect}
        topic = f"zigbee2mqtt/{light_name}/set"
        self.client.publish(topic, json.dumps(payload))

    def all_lights(self, lights: List[str], action: callable, *args, **kwargs):
        """Apply action to all lights"""
        for light in lights:
            action(light, *args, **kwargs)

    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        print("✓ Disconnected from MQTT broker")

# Test code
if __name__ == '__main__':
    print("="*60)
    print("ZIGBEE LIGHT CONTROLLER TEST")
    print("="*60)

    controller = ZigbeeLightController()

    if controller.connect():
        # Discover lights
        lights = controller.discover_lights()

        if lights:
            print(f"\n→ Testing light control...")

            # Test: cycle through colors
            colors = [
                ('Red', 0),
                ('Green', 120),
                ('Blue', 240),
                ('Yellow', 60),
            ]

            for color_name, hue in colors:
                print(f"  Setting all lights to {color_name} (hue={hue})...")
                controller.all_lights(lights, controller.set_color_hue, hue, 100, 254, 0.5)
                time.sleep(2)

            # Reset to white
            print(f"  Resetting to white...")
            controller.all_lights(lights, controller.set_color_hue, 0, 0, 254, 1.0)

        else:
            print("\n⚠ No color lights discovered.")
            print("   Make sure:")
            print("   1. Zigbee2MQTT is running")
            print("   2. Lights are paired")
            print("   3. permit_join is enabled in configuration")

        controller.disconnect()
    else:
        print("\n⚠ Could not connect to MQTT broker.")
        print("   Make sure Mosquitto is running:")
        print("   sudo systemctl start mosquitto")

    print("="*60)
