#!/usr/bin/env python3
"""Quick test to verify gamepad detection"""

import sys
sys.path.insert(0, '/media/sparrow/data/Documents/SLOTA/MS/venv/lib/python3.12/site-packages')

from evdev import InputDevice, list_devices, categorize, ecodes

print("╔══════════════════════════════════════════════════════════════╗")
print("║            GAMEPAD DETECTION TEST                            ║")
print("╚══════════════════════════════════════════════════════════════╝\n")

# List all input devices
print("→ Available input devices:")
devices = [InputDevice(path) for path in list_devices()]

for device in devices:
    print(f"  • {device.path}: {device.name}")
    if 'gamepad' in device.name.lower() or 'shanwan' in device.name.lower():
        print(f"    ✓ GAMEPAD FOUND!")

print()

# Try to open the specific gamepad
try:
    gamepad = InputDevice('/dev/input/event28')
    print(f"✓ Successfully opened gamepad:")
    print(f"  Name: {gamepad.name}")
    print(f"  Path: {gamepad.path}")
    print(f"  Physical: {gamepad.phys}")
    print()
    print("✓ Gamepad is ready to use!")
    print()
    print("→ Press any button on the gamepad (will read 5 events)...")
    print("  (or Ctrl+C to skip)")
    print()

    count = 0
    try:
        for event in gamepad.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:
                button_name = ecodes.BTN[event.code] if event.code in ecodes.BTN else f"BTN_{event.code}"
                print(f"  ✓ Button detected: {button_name} (code: {event.code})")
                count += 1
                if count >= 5:
                    break
            elif event.type == ecodes.EV_ABS:
                axis_name = ecodes.ABS[event.code] if event.code in ecodes.ABS else f"ABS_{event.code}"
                if 'HAT' in axis_name and event.value != 0:
                    print(f"  ✓ D-Pad detected: {axis_name} = {event.value}")
                    count += 1
                    if count >= 5:
                        break
    except KeyboardInterrupt:
        print("\n  (skipped)")

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              ✓ GAMEPAD TEST SUCCESSFUL! ✓                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")

except PermissionError:
    print("✗ Permission denied to access /dev/input/event28")
    print()
    print("  Solutions:")
    print("  1. Add yourself to 'input' group:")
    print("     sudo usermod -a -G input $USER")
    print("     (then log out and log back in)")
    print()
    print("  2. Or run with sudo (not recommended):")
    print("     sudo python3 test_gamepad.py")
    sys.exit(1)

except FileNotFoundError:
    print("✗ Gamepad not found at /dev/input/event28")
    print("  Check gamepad connection and look for it in the list above")
    sys.exit(1)
