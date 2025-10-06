#!/usr/bin/env bash
# Ensure pigpio daemon is running (used for fading RV lamp)
if ! systemctl is-active --quiet pigpiod; then
  echo "[run.sh] Starting pigpio daemon..."
  sudo systemctl start pigpiod
fi

cd "$(dirname "$0")"

# Stop user audio managers that block ALSA
killall -q wireplumber pipewire pipewire-pulse 2>/dev/null || true

# Use ALSA (USB card) and run with sudo so PWM sysfs is writable
exec sudo env SDL_AUDIODRIVER=alsa python3 love_machine.py
