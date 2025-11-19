#!/bin/bash
# Launcher for IPEGA Gamepad → Zigbee Light Controller

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       🎮 GAMEPAD LIGHT CONTROLLER LAUNCHER 🎮               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Change to script directory
cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "→ Creating Python virtual environment..."
    python3 -m venv venv
    echo "  ✓ Virtual environment created"
fi

# Activate venv
echo "→ Activating virtual environment..."
source venv/bin/activate

# Check/install dependencies
echo "→ Checking dependencies..."
pip list | grep -q evdev || {
    echo "  → Installing evdev..."
    pip install evdev
}
pip list | grep -q paho-mqtt || {
    echo "  → Installing paho-mqtt..."
    pip install paho-mqtt
}
echo "  ✓ Dependencies ready"

# Check if gamepad is connected
echo ""
echo "→ Checking gamepad connection..."

if [ -e "/dev/input/event28" ]; then
    echo "  ✓ Gamepad device found at /dev/input/event28"
elif [ -e "/dev/input/js0" ]; then
    echo "  ✓ Gamepad device found at /dev/input/js0"
else
    echo "  ⚠ Warning: No gamepad device detected"
    echo "    Expected: /dev/input/event28 or /dev/input/js0"
    echo ""
    echo "  Available input devices:"
    ls -1 /dev/input/event* 2>/dev/null | head -5
    echo ""
    echo "  Continue anyway? (y/n): "
    read -r response
    if [ "$response" != "y" ]; then
        echo "  Aborted."
        exit 1
    fi
fi

# Check if user is in input group (for /dev/input access)
if ! groups | grep -q input; then
    echo ""
    echo "  ⚠ Warning: You are not in the 'input' group"
    echo "    You may need to run with sudo or add yourself to input group:"
    echo "    sudo usermod -a -G input $USER"
    echo "    (then log out and log back in)"
    echo ""
    echo "  Continue anyway? (y/n): "
    read -r response
    if [ "$response" != "y" ]; then
        echo "  Aborted."
        exit 1
    fi
fi

# Check MQTT broker
echo ""
echo "→ Checking MQTT broker..."
if systemctl is-active --quiet mosquitto; then
    echo "  ✓ Mosquitto MQTT broker is running"
else
    echo "  ⚠ Mosquitto is not running"
    echo "    Attempting to start..."
    sudo systemctl start mosquitto
    echo "  ✓ Mosquitto started"
fi

# Check Zigbee2MQTT (optional)
if [ -d "/opt/zigbee2mqtt" ]; then
    if systemctl is-active --quiet zigbee2mqtt; then
        echo "  ✓ Zigbee2MQTT is running"
    else
        echo "  ⚠ Zigbee2MQTT is not running"
        echo "    Start it? (y/n): "
        read -r response
        if [ "$response" = "y" ]; then
            sudo systemctl start zigbee2mqtt
            sleep 2
            echo "  ✓ Zigbee2MQTT started"
        fi
    fi
fi

# Check config files
echo ""
echo "→ Checking configuration files..."
if [ ! -f "gamepad_config.json" ]; then
    echo "  ✗ Error: gamepad_config.json not found"
    exit 1
fi
echo "  ✓ gamepad_config.json"

if [ ! -f "color_presets.json" ]; then
    echo "  ✗ Error: color_presets.json not found"
    exit 1
fi
echo "  ✓ color_presets.json"

if [ ! -f "zigbee_light_controller.py" ]; then
    echo "  ✗ Error: zigbee_light_controller.py not found"
    exit 1
fi
echo "  ✓ zigbee_light_controller.py"

if [ ! -f "gamepad_light_controller.py" ]; then
    echo "  ✗ Error: gamepad_light_controller.py not found"
    exit 1
fi
echo "  ✓ gamepad_light_controller.py"

# Ready to launch
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  READY TO LAUNCH! 🚀                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Services:"
echo "  • MQTT Broker: localhost:1883"
if [ -d "/opt/zigbee2mqtt" ]; then
    echo "  • Zigbee2MQTT Web: http://localhost:8080"
fi
echo ""
echo "Tips:"
echo "  • Make sure your Zigbee bulbs are paired and powered on"
echo "  • Press Home/Guide button on gamepad to quit"
echo "  • Use face buttons (A/B/X/Y) for quick color changes"
echo "  • Use L1/R1 to cycle through color presets"
echo ""
echo "Press Enter to start the gamepad controller, or Ctrl+C to abort..."
read

echo ""
echo "🎮 Starting gamepad controller..."
echo ""

# Launch the controller!
python gamepad_light_controller.py

# Deactivate venv on exit
deactivate

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              Gamepad controller stopped 🎮                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
