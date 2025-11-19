#!/usr/bin/env python3
"""
IPEGA Gamepad → Zigbee Light Controller
Controls Zigbee color bulbs using gamepad input
"""

import sys
import json
import time
import threading
from pathlib import Path
from evdev import InputDevice, categorize, ecodes
from zigbee_light_controller import ZigbeeLightController


class GamepadLightController:
    def __init__(self, config_path='gamepad_config.json', presets_path='color_presets.json'):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        with open(presets_path, 'r') as f:
            self.presets_data = json.load(f)

        # Initialize gamepad
        self.gamepad = None
        self.init_gamepad()

        # Initialize light controller
        self.light_controller = ZigbeeLightController()
        self.light_controller.connect()

        # Discover lights
        print("→ Discovering Zigbee lights...")
        self.lights = self.light_controller.discover_lights()
        if not self.lights:
            print("  ⚠ No lights discovered. Continue in simulation mode? (y/n)")
            response = input().strip().lower()
            if response != 'y':
                sys.exit(1)
            print("  → Running in SIMULATION MODE (no actual lights)")
            self.simulation_mode = True
        else:
            print(f"  ✓ Found {len(self.lights)} light(s): {', '.join(self.lights)}")
            self.simulation_mode = False

        # State tracking
        self.current_preset_index = 0
        self.presets_list = self.config['presets']['cycle_order']
        self.current_preset = self.presets_list[0]

        self.current_brightness = 200
        self.current_transition = 0.5
        self.current_hue = 0
        self.current_saturation = 100
        self.lights_on = True
        self.strobe_mode = False
        self.rainbow_mode = False

        # Analog stick state (for throttling)
        self.last_analog_update = 0
        self.analog_values = {
            'ABS_X': 128, 'ABS_Y': 128,
            'ABS_RX': 128, 'ABS_RY': 128
        }

        # Running flag
        self.running = True

        # Rainbow thread
        self.rainbow_thread = None

        print(f"\n✓ Initialized with preset: {self.current_preset}")
        self.print_help()

    def init_gamepad(self):
        """Initialize gamepad device - supports multiple controllers"""
        # First, try devices from the devices list (if present)
        if 'devices' in self.config:
            for device_info in self.config['devices']:
                # Try primary path
                try:
                    device = InputDevice(device_info['path'])
                    # Verify it matches by checking name or vendor/product ID
                    device_name_lower = device.name.lower()
                    if (device_info['name'].lower() in device_name_lower or 
                        'shanwan' in device_name_lower):
                        self.gamepad = device
                        print(f"✓ Gamepad connected: {self.gamepad.name}")
                        print(f"  Device: {device_info['name']} ({device_info['vendor_id']}:{device_info['product_id']})")
                        print(f"  Path: {device_info['path']}")
                        return
                except (FileNotFoundError, OSError):
                    pass
                
                # Try fallback path
                if 'fallback_path' in device_info:
                    try:
                        device = InputDevice(device_info['fallback_path'])
                        device_name_lower = device.name.lower()
                        if (device_info['name'].lower() in device_name_lower or 
                            'shanwan' in device_name_lower):
                            self.gamepad = device
                            print(f"✓ Gamepad connected: {self.gamepad.name}")
                            print(f"  Device: {device_info['name']} ({device_info['vendor_id']}:{device_info['product_id']})")
                            print(f"  Path: {device_info['fallback_path']}")
                            return
                    except (FileNotFoundError, OSError):
                        pass

        # Fallback to legacy single device config
        if 'device' in self.config:
            device_path = self.config['device']['path']
            try:
                self.gamepad = InputDevice(device_path)
                print(f"✓ Gamepad connected: {self.gamepad.name}")
                print(f"  Device: {device_path}")
                return
            except FileNotFoundError:
                pass

        # Last resort: search all input devices
        print("  Searching for gamepad in /dev/input/...")
        import glob
        for event_path in glob.glob('/dev/input/event*'):
            try:
                device = InputDevice(event_path)
                if 'gamepad' in device.name.lower() or 'shanwan' in device.name.lower():
                    self.gamepad = device
                    print(f"  ✓ Found gamepad at {event_path}: {device.name}")
                    return
            except:
                continue

        print("  ✗ Could not find gamepad. Please check connection.")
        sys.exit(1)

    def print_help(self):
        """Print control help"""
        print("\n╔═══════════════════════════════════════════════════════════╗")
        print("║            GAMEPAD LIGHT CONTROLLER - HELP               ║")
        print("╚═══════════════════════════════════════════════════════════╝")
        help_text = self.config['help_text']
        print(f"  Face Buttons:  {help_text['face_buttons']}")
        print(f"  Shoulders:     {help_text['shoulders']}")
        print(f"  D-Pad:         {help_text['dpad']}")
        print(f"  Analog Sticks: {help_text['sticks']}")
        print(f"  Special:       {help_text['special']}")
        print("╚═══════════════════════════════════════════════════════════╝\n")

    def get_preset(self, preset_name):
        """Get preset configuration by name"""
        for preset in self.presets_data['presets']:
            if preset['name'] == preset_name:
                return preset
        return None

    def set_direct_color(self, color_name):
        """Set lights to a direct color"""
        if color_name not in self.presets_data['direct_colors']:
            print(f"  ✗ Unknown color: {color_name}")
            return

        color = self.presets_data['direct_colors'][color_name]
        self.current_hue = color['hue']
        self.current_saturation = color['saturation']
        self.current_brightness = color.get('brightness', self.current_brightness)

        print(f"  🎨 Color: {color_name.upper()}")

        if self.simulation_mode:
            print(f"     [SIM] Hue={self.current_hue}, Sat={self.current_saturation}, Bright={self.current_brightness}")
            return

        for light in self.lights:
            self.light_controller.set_color_hue(
                light,
                self.current_hue,
                self.current_saturation,
                self.current_brightness,
                self.current_transition
            )

    def next_preset(self):
        """Cycle to next color preset"""
        self.current_preset_index = (self.current_preset_index + 1) % len(self.presets_list)
        self.current_preset = self.presets_list[self.current_preset_index]
        self.apply_current_preset()

    def previous_preset(self):
        """Cycle to previous color preset"""
        self.current_preset_index = (self.current_preset_index - 1) % len(self.presets_list)
        self.current_preset = self.presets_list[self.current_preset_index]
        self.apply_current_preset()

    def apply_current_preset(self):
        """Apply the current preset to lights"""
        preset = self.get_preset(self.current_preset)
        if not preset:
            print(f"  ✗ Preset '{self.current_preset}' not found")
            return

        print(f"  🎨 Preset: {preset['name']} - {preset['description']}")

        # Update state from preset
        self.current_brightness = preset.get('default_brightness', 200)
        self.current_transition = preset.get('transition', 0.5)

        # Apply first color from preset (E chord as default)
        if 'E' in preset['colors']:
            color = preset['colors']['E']
            self.current_hue = color['hue']
            self.current_saturation = color['saturation']

            if self.simulation_mode:
                print(f"     [SIM] {color['name'].upper()}: Hue={self.current_hue}, Sat={self.current_saturation}")
                return

            for light in self.lights:
                self.light_controller.set_color_hue(
                    light,
                    self.current_hue,
                    self.current_saturation,
                    self.current_brightness,
                    self.current_transition
                )

    def increase_brightness(self, amount=25):
        """Increase brightness"""
        self.current_brightness = min(254, self.current_brightness + amount)
        print(f"  💡 Brightness: {self.current_brightness}")
        self._apply_brightness()

    def decrease_brightness(self, amount=25):
        """Decrease brightness"""
        self.current_brightness = max(0, self.current_brightness - amount)
        print(f"  💡 Brightness: {self.current_brightness}")
        self._apply_brightness()

    def set_brightness(self, value):
        """Set brightness to specific value"""
        self.current_brightness = max(0, min(254, value))
        print(f"  💡 Brightness: {self.current_brightness}")
        self._apply_brightness()

    def _apply_brightness(self):
        """Apply current brightness to all lights"""
        if self.simulation_mode:
            return

        for light in self.lights:
            self.light_controller.set_brightness(light, self.current_brightness, self.current_transition)

    def toggle_lights(self):
        """Toggle lights on/off"""
        self.lights_on = not self.lights_on

        if self.lights_on:
            print("  💡 Lights: ON")
            if not self.simulation_mode:
                for light in self.lights:
                    self.light_controller.turn_on(light)
        else:
            print("  💡 Lights: OFF")
            if not self.simulation_mode:
                for light in self.lights:
                    self.light_controller.turn_off(light)

    def reset_to_white(self):
        """Reset all lights to warm white"""
        print("  🔆 Reset to warm white")
        self.current_hue = 40
        self.current_saturation = 20
        self.current_brightness = 254

        if self.simulation_mode:
            return

        for light in self.lights:
            self.light_controller.set_color_hue(light, 40, 20, 254, 1.0)

    def increase_effect_speed(self):
        """Increase effect speed (decrease transition time)"""
        self.current_transition = max(0.0, self.current_transition - 0.1)
        print(f"  ⚡ Transition: {self.current_transition:.1f}s (faster)")

    def decrease_effect_speed(self):
        """Decrease effect speed (increase transition time)"""
        self.current_transition = min(2.0, self.current_transition + 0.1)
        print(f"  🐢 Transition: {self.current_transition:.1f}s (slower)")

    def toggle_strobe_mode(self):
        """Toggle strobe mode"""
        self.strobe_mode = not self.strobe_mode
        if self.strobe_mode:
            print("  ⚡ STROBE MODE: ON")
            self.current_transition = 0.05
        else:
            print("  ⚡ STROBE MODE: OFF")
            self.current_transition = 0.5

    def rainbow_cycle(self):
        """Start/stop rainbow cycling"""
        self.rainbow_mode = not self.rainbow_mode

        if self.rainbow_mode:
            print("  🌈 RAINBOW MODE: ON")
            if self.rainbow_thread is None or not self.rainbow_thread.is_alive():
                self.rainbow_thread = threading.Thread(target=self._rainbow_loop, daemon=True)
                self.rainbow_thread.start()
        else:
            print("  🌈 RAINBOW MODE: OFF")

    def _rainbow_loop(self):
        """Rainbow cycling loop"""
        hue = 0
        while self.rainbow_mode and self.running:
            self.current_hue = hue

            if not self.simulation_mode:
                for light in self.lights:
                    self.light_controller.set_color_hue(light, hue, 100, self.current_brightness, 0.5)

            hue = (hue + 10) % 360
            time.sleep(0.5)

    def adjust_hue(self, value):
        """Adjust hue from analog stick"""
        # Map 0-255 to 0-360
        self.current_hue = int((value / 255.0) * 360)

        if not self.simulation_mode:
            for light in self.lights:
                self.light_controller.set_color_hue(
                    light,
                    self.current_hue,
                    self.current_saturation,
                    self.current_brightness,
                    0.2
                )

    def adjust_saturation(self, value):
        """Adjust saturation from analog stick (inverted)"""
        # Map 0-255 to 100-0 (inverted Y-axis)
        self.current_saturation = int(100 - (value / 255.0) * 100)

        if not self.simulation_mode:
            for light in self.lights:
                self.light_controller.set_color_hue(
                    light,
                    self.current_hue,
                    self.current_saturation,
                    self.current_brightness,
                    0.2
                )

    def adjust_brightness_analog(self, value):
        """Adjust brightness from analog stick (inverted)"""
        # Map 0-255 to 254-0 (inverted Y-axis)
        self.current_brightness = int(254 - (value / 255.0) * 254)

        if not self.simulation_mode:
            for light in self.lights:
                self.light_controller.set_brightness(light, self.current_brightness, 0.2)

    def adjust_transition_speed(self, value):
        """Adjust transition speed from analog stick"""
        # Map 0-255 to 0.0-2.0
        self.current_transition = (value / 255.0) * 2.0

    def handle_button(self, button_code, button_name):
        """Handle button press events"""
        button_code_str = str(button_code)

        if button_code_str not in self.config['button_mappings']:
            return

        mapping = self.config['button_mappings'][button_code_str]
        action = mapping['action']

        print(f"  🎮 {mapping['name']}: {mapping['description']}")

        # Execute action
        if action == 'set_direct_color':
            self.set_direct_color(mapping['color'])
        elif action == 'next_preset':
            self.next_preset()
        elif action == 'previous_preset':
            self.previous_preset()
        elif action == 'toggle_lights':
            self.toggle_lights()
        elif action == 'reset_to_white':
            self.reset_to_white()
        elif action == 'increase_effect_speed':
            self.increase_effect_speed()
        elif action == 'decrease_effect_speed':
            self.decrease_effect_speed()
        elif action == 'toggle_strobe_mode':
            self.toggle_strobe_mode()
        elif action == 'rainbow_cycle':
            self.rainbow_cycle()
        elif action == 'quit':
            print("\n  👋 Exiting gamepad controller...")
            self.running = False

    def handle_dpad(self, axis_name, value):
        """Handle D-pad events"""
        if axis_name not in self.config['dpad_mappings']:
            return

        value_str = str(value)
        if value_str not in self.config['dpad_mappings'][axis_name]:
            return

        mapping = self.config['dpad_mappings'][axis_name][value_str]
        action = mapping['action']

        print(f"  🎮 {mapping['name']}: {mapping['description']}")

        if action == 'increase_brightness':
            self.increase_brightness(mapping['amount'])
        elif action == 'decrease_brightness':
            self.decrease_brightness(mapping['amount'])
        elif action == 'set_brightness':
            self.set_brightness(mapping['value'])

    def handle_analog(self, axis_name, value):
        """Handle analog stick movements with deadzone and throttling"""
        # Apply deadzone
        deadzone = self.config['behavior']['analog_deadzone']
        center = 128

        if abs(value - center) < deadzone:
            value = center

        # Store value
        self.analog_values[axis_name] = value

        # Throttle updates
        now = time.time() * 1000
        throttle = self.config['behavior']['analog_update_throttle_ms']

        if now - self.last_analog_update < throttle:
            return

        self.last_analog_update = now

        # Handle based on axis
        if axis_name == 'ABS_X':
            self.adjust_hue(value)
        elif axis_name == 'ABS_Y':
            self.adjust_saturation(value)
        elif axis_name == 'ABS_RX':
            self.adjust_transition_speed(value)
        elif axis_name == 'ABS_RY':
            self.adjust_brightness_analog(value)

    def run(self):
        """Main event loop"""
        print("\n🎮 Gamepad controller is running...")
        print("   Press Home/Guide button to quit\n")

        try:
            for event in self.gamepad.read_loop():
                if not self.running:
                    break

                # Button events
                if event.type == ecodes.EV_KEY:
                    if event.value == 1:  # Button press (not release)
                        self.handle_button(event.code, ecodes.BTN[event.code] if event.code in ecodes.BTN else f"BTN_{event.code}")

                # Absolute axis events (D-pad and analog sticks)
                elif event.type == ecodes.EV_ABS:
                    axis_name = ecodes.ABS[event.code] if event.code in ecodes.ABS else f"ABS_{event.code}"

                    # D-pad (HAT)
                    if 'HAT' in axis_name:
                        if event.value != 0:  # Only process when not centered
                            self.handle_dpad(axis_name, event.value)
                    # Analog sticks
                    else:
                        self.handle_analog(axis_name, event.value)

        except KeyboardInterrupt:
            print("\n  ⚠ Interrupted by user (Ctrl+C)")

        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        print("\n→ Cleaning up...")

        self.rainbow_mode = False
        self.running = False

        # Reset lights to white
        if not self.simulation_mode:
            print("  → Resetting lights to white...")
            for light in self.lights:
                self.light_controller.set_color_hue(light, 40, 20, 254, 1.0)

        # Disconnect
        self.light_controller.disconnect()

        print("  ✓ Gamepad controller stopped\n")


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║       🎮 GAMEPAD → ZIGBEE LIGHT CONTROLLER 🎮               ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    # Check if config files exist
    if not Path('gamepad_config.json').exists():
        print("✗ Error: gamepad_config.json not found")
        print("  Make sure you're running from the correct directory")
        sys.exit(1)

    if not Path('color_presets.json').exists():
        print("✗ Error: color_presets.json not found")
        sys.exit(1)

    # Create controller
    controller = GamepadLightController()

    # Run main loop
    controller.run()


if __name__ == '__main__':
    main()
