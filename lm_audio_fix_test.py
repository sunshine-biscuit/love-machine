#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
import pygame

# Use the right audio backend on Pi OS (PipeWire/PulseAudio)
os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")

# Init pygame + mixer (pre_init MUST be before pygame.init)
pygame.mixer.pre_init(44100, -16, 2, 1024)
pygame.init()

def init_mixer_with_retry(retries=5, delay=0.5):
    last = None
    for _ in range(retries):
        try:
            pygame.mixer.init()
            return True
        except Exception as e:
            last = e
            time.sleep(delay)
    print(f"[!] mixer.init failed: {last}")
    return False

if not init_mixer_with_retry():
    sys.exit(1)

# Try to list devices (optional)
try:
    n = pygame.mixer.get_num_audio_devices(False)
    devs = [pygame.mixer.get_audio_device_name(i, False) for i in range(n)]
    print("Output devices:", devs)
except Exception:
    pass

base = Path(__file__).resolve().parent
sounds_dir = base / "sounds"

candidates = []
if sounds_dir.is_dir():
    for pattern in ("startup.*", "boot.*", "intro.*"):
        candidates += list(sounds_dir.glob(pattern))

# Prefer WAV/OGG (fastest/most reliable), then MP3
candidates = sorted(
    candidates, key=lambda p: (p.suffix.lower() not in (".wav", ".ogg"), p.name)
)

target = str(candidates[0]) if candidates else "/usr/share/sounds/alsa/Front_Center.wav"
print("Trying to play:", target)

try:
    if target.lower().endswith((".wav", ".ogg", ".mp3", ".flac")):
        pygame.mixer.music.load(target)
        pygame.mixer.music.set_volume(0.9)
        pygame.mixer.music.play()
        # keep process alive while playback starts/continues
        for _ in range(40):
            time.sleep(0.25)
            if not pygame.mixer.music.get_busy():
                pass
        print("Done.")
    else:
        snd = pygame.mixer.Sound(target)
        snd.set_volume(0.9)
        snd.play()
        time.sleep(3)
except Exception as e:
    print("Playback error:", e)
    sys.exit(1)
