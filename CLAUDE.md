# Zigbeendicate Sounds — Claude Code Context

## What this project does
Gamepad → audio → AI-driven Zigbee light controller. Controls smart color bulbs via:
- IPEGA / DualShock 4 gamepad (evdev)
- Microphone audio (FFT beat detection)
- Claude Desktop / Claude Code (MCP server)
- REST API (FastAPI)

All light commands go through `ZigbeeLightController` → paho-mqtt → Mosquitto → Zigbee2MQTT → bulbs.

## How to run

```bash
# Gamepad mode (requires physical gamepad + Zigbee2MQTT)
bash launch_gamepad.sh

# Audio reactive mode
python audio_analyzer.py --list-devices
python audio_analyzer.py --device 0

# MCP server (for Claude Desktop)
python mcp_zigbee_server.py            # stdio
python mcp_zigbee_server.py --sse      # SSE on :8000

# REST API
python api_server.py                   # http://localhost:8080
python api_server.py --host 0.0.0.0 --port 9090

# Tests
pytest tests/ -v
pytest tests/test_audio.py -v          # no hardware needed
pytest tests/test_zigbee.py -v         # no hardware needed
```

## Key architecture decisions
- `ZigbeeLightController` is the ONLY place that calls `mqtt.Client.publish()`. Never publish directly elsewhere.
- Button/axis mappings live exclusively in `gamepad_config.json` (not hard-coded).
- Presets live in `color_presets.json`.
- Audio bands: bass(60-250Hz)→hue, mid(250-2kHz)→saturation, treble(2-8kHz)→brightness.

## Claude Desktop MCP setup
Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "zigbee-lights": {
      "command": "python",
      "args": ["/home/user/zigbeendicate-sounds/mcp_zigbee_server.py"]
    }
  }
}
```
Available MCP tools: `list_lights`, `set_color_hsv`, `set_color_rgb`, `set_brightness`,
`turn_on`, `turn_off`, `apply_effect`, `list_presets`, `apply_preset`, `set_warm_white`.

## Dependencies
See `pyproject.toml`. Install dev deps with `pip install -e ".[dev]"`.

## MQTT payload reference
```
Topic:   zigbee2mqtt/{light_name}/set
Payload: {"color": {"hue": 0-360, "saturation": 0-100}, "brightness": 0-254, "transition": 0.5}
```
