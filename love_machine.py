#!/usr/bin/env python3
# ====== Imports (order matters for audio) ======
import os, sys, time, random, subprocess, math, threading

# Force PulseAudio on Pi OS (PipeWire) BEFORE importing pygame
os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")

import pygame
from crt_effects import CRTEffects

# Pi pin setup before pygame init
subprocess.run(["sudo","/usr/local/bin/pinctrl","set","12","a0"], check=False)

# ====== Sensor (IR obstacle) ======
try:
    import RPi.GPIO as GPIO
    _GPIO_OK = True
except Exception as _e:
    print("[WARN] RPi.GPIO not available:", _e)
    _GPIO_OK = False

SENSOR_PIN = 17            # BCM numbering (physical pin 11)
SENSOR_ACTIVE_LOW = True   # Most LM393 IR boards pull LOW when they see an object
SENSOR_DEBOUNCE_MS = 120   # must be continuously "active" this long to count
SENSOR_REQUIRE_CLEAR_MS = 200  # require a clear state first, avoids false boot triggers


def _init_sensor_gpio():
    if not _GPIO_OK:
        return
    # IMPORTANT: Power the module from **3.3V** if possible so OUT never goes to 5V.
    # If you must power it from 5V, use a level shifter or a resistor divider on OUT.
    GPIO.setmode(GPIO.BCM)
    # Many LM393 boards are push-pull, but a pull-up gives a defined idle if floating.
    GPIO.setup(SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Let the sensor settle
    time.sleep(0.08)


def _sensor_read_active() -> bool:
    if not _GPIO_OK:
        return False
    v = GPIO.input(SENSOR_PIN)
    # active when LOW on most boards
    return (v == 0) if SENSOR_ACTIVE_LOW else (v == 1)


from pwm_helper import init_pwm, set_brightness
init_pwm()                   # start hardware PWM
set_brightness(0.22)         # force ambient immediately (0.22 = 22%)

from quiz_data import QUESTIONS, CATEGORY_BLURBS
print(f"[quiz] Loaded {len(CATEGORY_BLURBS or {})} archetype categories.")


def to_caps(s: str) -> str:
    return (s or "").strip().upper()


# ====== Audio: robust initialisation ======
def _init_audio(retries=5, delay=0.4):
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)
    pygame.init()
    last = None
    for _ in range(retries):
        try:
            pygame.mixer.init()
            return True
        except Exception as e:
            last = e
            time.sleep(delay)
    print(f"[WARN] pygame.mixer.init failed: {last}")
    return False


_init_audio()

# ====== Key-press sound (for typewriter output only) ======
# Put your file at: /home/lovemachine/love-machine/assets/key_press.wav
KEYCLICK_PATH = os.path.join(os.path.dirname(__file__), "assets", "key_press.wav")
KEYCLICK_SND = None
_KEYCLICK_CHS = []
_KEYCLICK_IDX = 0
_KEYCLICK_LAST_MS = 0
_KEYCLICK_MIN_GAP_MS = 10  # tiny rate-limit to avoid audio trash at very high CPS


def _init_keyclick():
    global KEYCLICK_SND, _KEYCLICK_CHS
    try:
        if not pygame.mixer.get_init():
            _init_audio()
        if os.path.isfile(KEYCLICK_PATH):
            KEYCLICK_SND = pygame.mixer.Sound(KEYCLICK_PATH)
            KEYCLICK_SND.set_volume(0.35)  # adjust to taste
        # reserve a few channels so rapid clicks don't cut each other off
        base = 3  # use channels 3–5 (0–1 are mixer.music internals; 7 used by boot loop)
        _KEYCLICK_CHS = [pygame.mixer.Channel(base + i) for i in range(3)]
    except Exception as e:
        print("[WARN] keyclick init failed:", e)
        KEYCLICK_SND = None
        _KEYCLICK_CHS = []


def _play_keyclick(ch: str):
    """Play for visible characters; skip spaces to keep it tidy."""
    global _KEYCLICK_IDX, _KEYCLICK_LAST_MS
    if not KEYCLICK_SND or not _KEYCLICK_CHS:
        return
    if ch == " ":
        return
    now = pygame.time.get_ticks()
    if now - _KEYCLICK_LAST_MS < _KEYCLICK_MIN_GAP_MS:
        return
    _KEYCLICK_LAST_MS = now
    chn = _KEYCLICK_CHS[_KEYCLICK_IDX % len(_KEYCLICK_CHS)]
    _KEYCLICK_IDX += 1
    try:
        chn.stop()     # ensure clean attack
        chn.play(KEYCLICK_SND)
    except Exception:
        pass


_init_keyclick()

# ====== DISPLAY: fullscreen/windowed toggle + 4:3 logical canvas + fast scaling ======
def _get_env_flag(name, default=False):
    v = (os.getenv(name) or "").strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


# Dev toggle: set LM_WINDOWED=1 or pass --windowed to run windowed
DEV_WINDOWED = _get_env_flag("LM_WINDOWED", False) or ("--windowed" in sys.argv)

# Logical 4:3 render size (smaller = faster). Override with LM_CANVAS="1024x768"
_canvas_env = (os.getenv("LM_CANVAS") or "").lower()
if "x" in _canvas_env:
    try:
        _w, _h = _canvas_env.split("x")
        LOGICAL_W, LOGICAL_H = int(_w), int(_h)
    except Exception:
        LOGICAL_W, LOGICAL_H = 960, 720
else:
    LOGICAL_W, LOGICAL_H = 960, 720

# Keep WIDTH/HEIGHT for the rest of your code
WIDTH, HEIGHT = LOGICAL_W, LOGICAL_H
TARGET_RATIO = 4 / 3

# Create display
if DEV_WINDOWED:
    # Windowed dev mode (e.g., Mac)
    display = pygame.display.set_mode((LOGICAL_W, LOGICAL_H))
else:
    # True fullscreen on the Pi
    _info = pygame.display.Info()
    display = pygame.display.set_mode((_info.current_w, _info.current_h), pygame.FULLSCREEN)

pygame.display.set_caption("Love Machine")
pygame.mouse.set_visible(False)  # hide cursor on launch (both modes)
clock = pygame.time.Clock()

# 4:3 canvas you draw onto (keep using the name `screen` everywhere)
screen = pygame.Surface((LOGICAL_W, LOGICAL_H)).convert()

# Compute destination rect where the canvas will be letterboxed on the real display
if DEV_WINDOWED:
    DEST_W, DEST_H = LOGICAL_W, LOGICAL_H
    DEST_X, DEST_Y = 0, 0
else:
    _info = pygame.display.Info()
    sw, sh = _info.current_w, _info.current_h
    if sw / sh > TARGET_RATIO:
        DEST_H = sh
        DEST_W = int(DEST_H * TARGET_RATIO)
    else:
        DEST_W = sw
        DEST_H = int(DEST_W / TARGET_RATIO)
    DEST_X = (sw - DEST_W) // 2
    DEST_Y = (sh - DEST_H) // 2


# ====== Caret (text cursor) helper ======
def draw_caret(surface, x, y, font_obj, color=(0, 255, 0)):
    """
    Draw a vertical caret aligned with the text baseline.
    - x, y should be the baseline of the text (same y used for blitting the text).
    """
    h = int(font_obj.get_height() * 0.9)   # caret height (e.g., 90% of font height)
    w = max(3, int(h * 0.40))              # thickness
    top_y = y - h                          # shift upwards so caret sits on baseline
    pygame.draw.rect(surface, color, (x, top_y, w, h))


# ====== CRT bound to the logical canvas ======
crt = CRTEffects((LOGICAL_W, LOGICAL_H), enable_flicker=False)


def present():
    """Apply CRT to the 4:3 canvas, scale once, letterbox, then flip."""
    crt.apply(screen, 0.0)
    scaled = pygame.transform.smoothscale(screen, (DEST_W, DEST_H))
    display.fill((0, 0, 0))
    display.blit(scaled, (DEST_X, DEST_Y))
    pygame.display.flip()


# ====== Developer-friendly exits ======
# - In DEV_WINDOWED: ESC quits immediately
# - In fullscreen: hold F12 ~0.7s, OR triple-tap ESC within 800ms
_EXIT_HOLD_MS = 700
_ESC_TAP_WINDOW_MS = 800
_f12_down_at = None
_esc_taps = []


def _dev_exit_check(ev_iterable):
    global _f12_down_at, _esc_taps
    now = pygame.time.get_ticks()

    if DEV_WINDOWED:
        # Easy dev exit
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            print("[EXIT] ESC (dev window).")
            pygame.quit()
            sys.exit()

    for ev in ev_iterable:
        if ev.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

        if not DEV_WINDOWED:
            # F12 hold
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F12:
                _f12_down_at = now
            elif ev.type == pygame.KEYUP and ev.key == pygame.K_F12:
                _f12_down_at = None

            if _f12_down_at is not None and (now - _f12_down_at) >= _EXIT_HOLD_MS:
                print("[EXIT] F12 held. Exiting.")
                pygame.quit()
                sys.exit()

            # ESC triple tap within window
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                _esc_taps = [t for t in _esc_taps if now - t <= _ESC_TAP_WINDOW_MS]
                _esc_taps.append(now)
                if len(_esc_taps) >= 3:
                    print("[EXIT] ESC x3. Exiting.")
                    pygame.quit()
                    sys.exit()

        yield ev


def events():
    """Use this everywhere you loop over pygame events."""
    yield from _dev_exit_check(pygame.event.get())


# ====== Paths & font ======
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "Px437_IBM_DOS_ISO8.ttf")
FONT_SIZE = int(os.getenv("LM_FONT", "40"))  # was 28 → bigger default
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# ====== Music (Title track: Foreigner) ======
MUSIC_DIR = os.path.join(ASSETS_DIR, "music")
_AUDIO_EXTS = (".wav", ".ogg", ".mp3", ".flac")

_TITLE_CANDIDATES = [
    "Foreigner - know what love is.ogg",
    "Foreigner - know what love is (PCM).wav",
    "Foreigner - know what love is.wav",
]


def _find_title_track():
    for name in _TITLE_CANDIDATES:
        p = os.path.join(MUSIC_DIR, name)
        if os.path.isfile(p):
            return p
    try:
        for fname in os.listdir(MUSIC_DIR):
            low = fname.lower()
            if low.endswith(_AUDIO_EXTS) and ("foreigner" in low) and ("know what love is" in low):
                return os.path.join(MUSIC_DIR, fname)
    except FileNotFoundError:
        pass
    try:
        for fname in sorted(os.listdir(MUSIC_DIR)):
            if fname.lower().endswith(_AUDIO_EXTS):
                return os.path.join(MUSIC_DIR, fname)
    except FileNotFoundError:
        pass
    return None


TITLE_MUSIC = _find_title_track()


def _load_title_music():
    if not TITLE_MUSIC:
        print(f"[WARN] No audio file found in {MUSIC_DIR}")
        return False
    try:
        pygame.mixer.music.load(TITLE_MUSIC)
        print(f"[audio] Loaded: {os.path.basename(TITLE_MUSIC)}")
        return True
    except Exception as e:
        print(f"[ERROR] Could not load {TITLE_MUSIC}: {e}")
        print("[HINT] Use an OGG or PCM WAV (44.1kHz, 16‑bit) in assets/music/.")
        return False


_music_ready = _load_title_music()
title_music_started = False

# ====== Boot loop via USB speakers (separate mixer channel) ======
BOOT_MUSIC_PATH = os.path.join(MUSIC_DIR, "boot_loop.ogg")
BOOT_SOUND = None
BOOT_CH = None


def _init_boot_sound():
    """Prepare Channel(7) and load assets/music/boot_loop.ogg"""
    global BOOT_SOUND, BOOT_CH
    try:
        if not pygame.mixer.get_init():
            _init_audio()
        if BOOT_CH is None:
            BOOT_CH = pygame.mixer.Channel(7)  # dedicated channel, won't clash with mixer.music
        if BOOT_SOUND is None:
            if os.path.isfile(BOOT_MUSIC_PATH):
                BOOT_SOUND = pygame.mixer.Sound(BOOT_MUSIC_PATH)
                print(f"[audio] Boot loop loaded: {os.path.basename(BOOT_MUSIC_PATH)}")
                return True
            else:
                print(f"[WARN] Boot loop file not found: {BOOT_MUSIC_PATH}")
                return False
        return True
    except Exception as e:
        print(f"[WARN] Boot loop init failed: {e}")
        return False


def boot_loop_start(vol=0.6):
    """Start looping boot sound on Channel(7)"""
    if BOOT_SOUND is None or BOOT_CH is None:
        if not _init_boot_sound():
            return
    try:
        BOOT_SOUND.set_volume(max(0.0, min(1.0, vol)))
        BOOT_CH.play(BOOT_SOUND, loops=-1, fade_ms=300)
    except Exception as e:
        print(f"[WARN] Boot loop start failed: {e}")


def boot_loop_stop():
    """Fade out/stop boot loop on Channel(7)"""
    try:
        if BOOT_CH:
            BOOT_CH.fadeout(250)
    except Exception:
        pass


_init_boot_sound()  # preload boot sound for instant start

# ====== Colours & typing ======
TEXT = (0, 255, 0)
BG = (0, 2, 0)

TYPE_CHAR_MS = 22
LINE_PAUSE_MS = 90
BLINK_INTERVAL_MS = 450
ELLIPSIS_CHAR_MS = TYPE_CHAR_MS * 3
ELLIPSIS_RAMP = 0.45
ELLIPSIS_DOT_PAUSE_MS = 120
ELLIPSIS_AFTER_PAUSE_MS = 350

# ====== Title fade timing ======
TITLE_FADE_MS = 3000

# ==== Quiz stats persistence ====
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATS_PATH = os.path.join(DATA_DIR, "stats_quiz.json")


def _ensure_stats_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STATS_PATH):
        import json
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": 0, "categories": {}}, f, indent=2)


def _load_stats():
    import json
    _ensure_stats_file()
    with open(STATS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_stats(stats):
    import json
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)


def _tally_category_count(chosen_category):
    stats = _load_stats()
    cats = stats.get("categories", {})
    cats[chosen_category] = cats.get(chosen_category, 0) + 1
    stats["categories"] = cats
    stats["total"] = stats.get("total", 0) + 1
    _save_stats(stats)
    total = max(stats["total"], 1)
    pct = round(cats[chosen_category] * 100 / total)
    return pct, dict(cats), total


# ================== LIGHTING (hardware PWM via pwm_helper) ==================
AMBIENT_LIGHT = 0.22
SHOW_LIGHT = 0.90


class LightPWM:
    def __init__(self, ambient=AMBIENT_LIGHT):
        self.level = ambient
        self.target = ambient
        self.duration = 0.2
        self.start_time = time.time()
        self.start_level = ambient
        self._stop = False
        self._lock = threading.Lock()
        set_brightness(self.level)
        self._thread = threading.Thread(target=self._runner, daemon=True)
        self._thread.start()

    def _apply(self, x: float):
        x = 0.0 if x < 0 else (1.0 if x > 1.0 else x)
        set_brightness(x)

    def fade_to(self, level01: float, duration_s: float):
        with self._lock:
            self.start_time = time.time()
            self.start_level = self.level
            self.target = 0.0 if level01 < 0 else (1.0 if level01 > 1.0 else level01)
            self.duration = 0.05 if duration_s < 0.05 else float(duration_s)

    def fade_up(self, to=SHOW_LIGHT, duration_ms=2500):
        self.fade_to(to, duration_ms / 1000.0)

    def fade_down_to_ambient(self, ambient=AMBIENT_LIGHT, duration_ms=TITLE_FADE_MS):
        self.fade_to(ambient, duration_ms / 1000.0)

    def _runner(self):
        while not self._stop:
            time.sleep(0.01)
            with self._lock:
                if self.duration <= 0:
                    cur = self.target
                else:
                    t = (time.time() - self.start_time) / self.duration
                    t = 0.0 if t < 0 else (1.0 if t > 1.0 else t)
                    eased = 0.5 - 0.5 * math.cos(math.pi * t)
                    cur = self.start_level + (self.target - self.start_level) * eased
                self.level = cur
            self._apply(self.level)

    def stop(self, turn_off=False):
        self._stop = True
        try:
            self._thread.join(timeout=1)
        except Exception:
            pass
        try:
            self._apply(0.0 if turn_off else self.level)
        except Exception:
            pass


_light = LightPWM(ambient=AMBIENT_LIGHT)


def lights_fade_up():
    _light.fade_up(to=SHOW_LIGHT, duration_ms=2500)


def lights_fade_down():
    _light.fade_down_to_ambient(ambient=AMBIENT_LIGHT, duration_ms=TITLE_FADE_MS)


# ====== Utility timing ======
def soft_wait(ms):
    end = pygame.time.get_ticks() + ms
    while pygame.time.get_ticks() < end:
        for _event in events():
            pass
        clock.tick(240)


def wait_for_enter_release(timeout_ms=800):
    """
    Return immediately if ENTER is not currently held.
    Otherwise, wait until it's released (or timeout to avoid hangs).
    """
    start = pygame.time.get_ticks()

    # If ENTER isn't held right now, we're done — no need to wait for a KEYUP event.
    keys = pygame.key.get_pressed()
    if not (keys[pygame.K_RETURN] or keys[pygame.K_KP_ENTER]):
        return

    # ENTER is held — wait for release or timeout.
    while True:
        for _ in events():
            pass  # keep processing quit/exit gestures

        keys = pygame.key.get_pressed()
        if not (keys[pygame.K_RETURN] or keys[pygame.K_KP_ENTER]):
            return

        if pygame.time.get_ticks() - start >= timeout_ms:
            # Failsafe: don't hang the app if a KEYUP is somehow lost
            return

        clock.tick(120)


# ====== Letter-by-letter typing helpers ======
def type_out_line_letterwise(
    line,
    drawn_lines,
    x,
    base_y,
    line_spacing,
    draw_face_style="smile",
    glitch=False,
    play_key_sound=True,
):
    target = (line or "")
    shown = 0
    timer_ms = 0.0
    while shown < len(target):
        dt = clock.tick(60) / 1000.0
        timer_ms += dt * 1000.0

        if timer_ms >= TYPE_CHAR_MS:
            timer_ms -= TYPE_CHAR_MS
            just = (target[shown] if shown < len(target) else "")
            shown += 1
            if just and play_key_sound:
                _play_keyclick(just)

        for _event in events():
            pass

        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)

        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))

        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines) * line_spacing))
        present()

    soft_wait(LINE_PAUSE_MS)


def type_out_line_letterwise_thoughtful(
    line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False
):
    target = (line or "")
    shown = 0
    timer_ms = 0.0
    ellipsis_pause_ms = 0
    ellipsis_after_run = False

    while shown < len(target):
        if target[shown] == ".":
            j = shown
            while j > 0 and target[j - 1] == ".":
                j -= 1
            k = shown
            while k < len(target) and target[k] == ".":
                k += 1
            run_len = k - j
            if run_len >= 3:
                pos_in_run = shown - j
                per_char_ms = int(ELLIPSIS_CHAR_MS * (1.0 + ELLIPSIS_RAMP * pos_in_run))
            else:
                per_char_ms = TYPE_CHAR_MS
        else:
            per_char_ms = TYPE_CHAR_MS

        dt = clock.tick(60) / 1000.0
        timer_ms += dt * 1000.0
        just_revealed_char = None

        if timer_ms >= per_char_ms:
            timer_ms -= per_char_ms
            just_revealed_char = target[shown]
            shown += 1
            if just_revealed_char:
                _play_keyclick(just_revealed_char)

            if just_revealed_char == ".":
                idx = shown - 1
                j = idx
                while j > 0 and target[j - 1] == ".":
                    j -= 1
                k = idx + 1
                while k < len(target) and k < len(target) and target[k] == ".":
                    k += 1
                run_len = k - j
                if run_len >= 3:
                    pos_in_run = idx - j
                    ramp = 1.0 + ELLIPSIS_RAMP * pos_in_run
                    ellipsis_pause_ms = int(ELLIPSIS_DOT_PAUSE_MS * ramp)
                    ellipsis_after_run = idx + 1 == k
                else:
                    ellipsis_pause_ms = 0
                    ellipsis_after_run = False
            else:
                ellipsis_pause_ms = 0
                ellipsis_after_run = False

        for _event in events():
            pass

        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)

        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))

        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines) * line_spacing))
        present()

        if ellipsis_pause_ms:
            soft_wait(ellipsis_pause_ms)
            ellipsis_pause_ms = 0
        if ellipsis_after_run:
            soft_wait(ELLIPSIS_AFTER_PAUSE_MS)
            ellipsis_after_run = False

    soft_wait(LINE_PAUSE_MS)


# ====== Text utils ======
def wrap_text_to_width(text, max_width):
    words = text.split(" ")
    lines, current = [], ""
    for w in words:
        test = current + (" " if current else "") + w
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


# --- Boot-style variable-speed typewriter (tiny font, tight spacing, left-aligned) ---
def _boot_delays_for(text: str, base_cps: float = 22.0, jitter: float = 0.50):
    """
    Per-character delays with jitter + punctuation pauses + occasional stalls.
    base_cps: average characters per second (higher = faster).
    """
    base_cps = max(4.0, float(base_cps))
    base_delay = 1.0 / base_cps
    delays, i = [], 0
    while i < len(text):
        ch = text[i]
        d = base_delay * random.uniform(1.0 - jitter, 1.0 + jitter)

        # Ellipses cluster "..."
        if text[i : i + 3] == "...":
            delays.extend([d, d, d + base_delay * 3.5])
            i += 3
            if random.random() < 1 / 15:  # rare micro-stall
                delays[-1] += base_delay * random.uniform(2.0, 4.0)
            continue

        # Punctuation pauses
        if ch in ",;:":
            d += base_delay * 1.5
        elif ch in ".!?)]}":
            d += base_delay * 2.5
        elif ch == "\t":
            d += base_delay * 2.0

        # Occasional fast burst
        if random.random() < 1 / 18:
            d *= 0.4

        delays.append(d)
        i += 1

        # Rare micro-stall
        if random.random() < 1 / 60:
            delays[-1] += base_delay * random.uniform(2.0, 4.0)
    return delays


def typewriter_boot_screen(
    screen,
    font_obj,
    lines,
    fg=(0, 255, 0),
    bg=(0, 0, 0),
    start_x=50,
    start_y=None,
    line_spacing_px=8,  # very tight spacing
    base_cps=22.0,
    jitter=0.55,
    allow_skip_with_key=True,
    crt_effects=None,  # present() already applies CRT
):
    local_clock = pygame.time.Clock()

    # caret blink state (reuse global cadence)
    blink = True
    last_blink = pygame.time.get_ticks()

    if start_y is None:
        total_h_est = len(lines) * (font_obj.get_height() + line_spacing_px)
        start_y = max(24, (screen.get_height() - total_h_est) // 2 - font_obj.get_height())

    schedules = [_boot_delays_for(s, base_cps=base_cps, jitter=jitter) for s in lines]
    typed = ["" for _ in lines]
    line_idx = 0
    char_i = 0
    t_next = time.perf_counter()

    # ---- typing phase ----
    typing = True
    while typing:
        now = time.perf_counter()
        for ev in events():
            if ev.type == pygame.KEYDOWN and allow_skip_with_key:
                if ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                    typed = lines[:]
                    line_idx = len(lines)
                    char_i = 0
                    typing = False

        if line_idx < len(lines):
            delays = schedules[line_idx]
            if char_i < len(lines[line_idx]) and now >= t_next:
                typed[line_idx] = lines[line_idx][:char_i + 1]
                t_next = now + delays[char_i]
                char_i += 1
            if char_i >= len(lines[line_idx]):
                char_i = 0
                line_idx += 1

        # blink timing
        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        # draw
        screen.fill(bg)
        y = start_y
        for s in typed:
            surf = font_obj.render(s, True, fg)
            screen.blit(surf, (start_x, y))
            y += font_obj.get_height() + line_spacing_px

        # blinking caret at end of current/last line
        caret_line_idx = min(line_idx, len(lines) - 1)
        last_text = typed[caret_line_idx]
        if blink:
            caret_x = start_x + font_obj.size(last_text)[0] + 6
            caret_y = start_y + caret_line_idx * (font_obj.get_height() + line_spacing_px) + font_obj.get_height()
            draw_caret(screen, caret_x, caret_y, font_obj)

        present()
        local_clock.tick(60)

        if line_idx >= len(lines) and typed[-1] == lines[-1]:
            break

    # ---- wait for ENTER phase ----
    waiting = True
    while waiting:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                waiting = False

        # blink timing
        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        screen.fill(bg)
        y = start_y
        for s in typed:
            surf = font_obj.render(s, True, fg)
            screen.blit(surf, (start_x, y))
            y += font_obj.get_height() + line_spacing_px

        if typed and blink:
            last_line = typed[-1]
            caret_x = start_x + font_obj.size(last_line)[0] + 6
            caret_y = start_y + (len(typed) - 1) * (font_obj.get_height() + line_spacing_px) + font_obj.get_height()
            draw_caret(screen, caret_x, caret_y, font_obj)

        present()
        local_clock.tick(60)

    wait_for_enter_release(timeout_ms=800)


def init_screen():
    # ---- START BOOT LOOP (USB speakers) ----
    boot_loop_start(vol=0.6)

    boot_lines = [
        "initialising system v1.0.3",
        "loading kernel modules v1.14.2",
        "detecting hardware bus v0.7.1",
        "mounting /dev/love v0.9.0   [ok]",
        "starting empathy-services v2.3.1",
        "calibrating affective-heuristics v0.8.7",
        "checking secure sockets v1.2.0   [ok]",
        "entropy pool seeded v3.2",
        "boot sequence complete v1.0   [ok]",
        "system ready.",
    ]

    # === Font & spacing ===
    BOOT_FONT_SIZE = 32
    boot_font = pygame.font.Font(FONT_PATH, BOOT_FONT_SIZE)
    LINE_PITCH = 32

    # === Typing speed ===
    CPS = 72.0
    JITTER = 0.35
    BASE_DT = 1.0 / CPS

    # === Position: keep left margin; keep last line on-screen ===
    start_x = 50
    base_target_y = HEIGHT - 200
    start_y = base_target_y - (len(boot_lines) - 1) * LINE_PITCH

    # Caret blink
    blink = True
    last_blink = pygame.time.get_ticks()

    typed = []

    # ---- Type out each line (no skipping with Enter) ----
    for line in boot_lines:
        cur = ""
        next_t = time.perf_counter()

        while len(cur) < len(line):
            for _ev in events():
                pass  # don't allow fast-forward during typing

            now = time.perf_counter()
            if now >= next_t:
                ch = line[len(cur)]
                cur += ch
                step = BASE_DT * random.uniform(1.0 - JITTER, 1.0 + JITTER)
                if ch in ",;:":
                    step += BASE_DT * 1.2
                elif ch in ".!?)]}":
                    step += BASE_DT * 2.0
                if len(cur) >= 3 and cur[-3:] == "...":
                    step += BASE_DT * 1.5
                next_t = now + step

            # blink timing
            if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
                blink = not blink
                last_blink = pygame.time.get_ticks()

            # draw
            screen.fill(BG)
            for i, done in enumerate(typed):
                s = boot_font.render(done, True, TEXT)
                screen.blit(s, (start_x, start_y + i * LINE_PITCH))
            s = boot_font.render(cur, True, TEXT)
            cy = start_y + len(typed) * LINE_PITCH
            screen.blit(s, (start_x, cy))

            if blink:
                caret_x = start_x + boot_font.size(cur)[0] + 6
                caret_y = cy + boot_font.get_height()
                draw_caret(screen, caret_x, caret_y, boot_font)

            present()
            clock.tick(60)

        # append the completed line ONCE so previous lines persist
        typed.append(cur)
        soft_wait(LINE_PAUSE_MS)

    # ---- Single wait-for-ENTER loop (no appends here) ----
    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                wait_for_enter_release()
                return

        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        screen.fill(BG)
        for i, done in enumerate(typed):
            s = boot_font.render(done, True, TEXT)
            screen.blit(s, (start_x, start_y + i * LINE_PITCH))

        if typed and blink:
            last_line = typed[-1]
            caret_x = start_x + boot_font.size(last_line)[0] + 6
            caret_y = start_y + (len(typed) - 1) * LINE_PITCH + boot_font.get_height()
            draw_caret(screen, caret_x, caret_y, boot_font)

        present()
        clock.tick(60)


# ====== Title/hold & boot screens ======
def wait_for_enter(message="press enter to begin.", show_face=False):
    global title_music_started
    message = (message or "").lower()
    if not title_music_started:
        try:
            if not pygame.mixer.get_init():
                _init_audio()
            if not _music_ready:
                if not _load_title_music():
                    raise RuntimeError("Startup music not available (see earlier error).")
            pygame.mixer.music.set_volume(0.9)
            pygame.mixer.music.play(loops=-1, fade_ms=2500)
            lights_fade_up()
            title_music_started = True
        except Exception as e:
            if not hasattr(wait_for_enter, "_warned"):
                print(f"[WARN] Could not start music: {e}")
                print("[HINT] If this is a codec issue, prefer WAV/OGG inside assets/music/")
                wait_for_enter._warned = True
    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        if show_face:
            draw_face("smile")
        lines = wrap_text_to_width(message, WIDTH - 100)
        base_y = HEIGHT - 120
        for i, line in enumerate(lines):
            surf = font.render(line, True, TEXT)
            screen.blit(surf, (50, base_y + i * 32))
        last_line = lines[-1]
        w = font.size(last_line)[0]
        if blink:
            draw_caret(screen, 50 + w + 6, base_y + (len(lines) - 1) * 32 + font.get_height(), font)

        present()
        for event in events():
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                try:
                    pygame.mixer.music.fadeout(TITLE_FADE_MS)
                except Exception:
                    pass
                lights_fade_down()
                title_fade_out()   # fade allowed here
                title_music_started = False
                return
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)


def hold_screen():
    lights_fade_up()
    wait_for_enter("press enter to begin.", show_face=False)


# ====== Input name ======
def input_name_screen():
    name = ""
    instructions = "what is your name?"
    x = 50
    prompt_base_y = HEIGHT - 240
    line_spacing = 32
    prompt_lines = wrap_text_to_width(instructions, WIDTH - 100)
    typed_prompt = []
    for ln in prompt_lines:
        type_out_line_letterwise(ln, typed_prompt, x, prompt_base_y, line_spacing, draw_face_style=None)
        typed_prompt.append(ln)
    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        for i, line in enumerate(typed_prompt):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, prompt_base_y + i * line_spacing))
        s = font.render(name, True, TEXT)
        screen.blit(s, (50, HEIGHT - 160))
        if blink:
            draw_caret(screen, 50 + s.get_width() + 6, HEIGHT - 160 + font.get_height(), font)

        present()
        for event in events():
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return (name.strip() or "FRIEND")
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    return "FRIEND"
                else:
                    ch = event.unicode
                    if ch:
                        ch = ch.upper()
                        if 32 <= ord(ch) <= 126 and len(name) < 20:
                            name += ch
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)


# ====== Text blocks (normal & glitch moment) ======
def show_text_block(
    text,
    face_style="smile",
    glitch=False,
    *,
    play_key_sound=True,   # allow callers to mute key sounds
):
    x = 50
    base_y = HEIGHT - 180
    line_spacing = 32
    lines = []
    for para in (text or "").split("\n"):
        lines.extend(wrap_text_to_width(para, WIDTH - 100))
    if not lines:
        lines = [""]

    typed = []
    for line in lines:
        # pass the sound toggle through to the per‑char typer
        type_out_line_letterwise(
            line,
            typed,
            x,
            base_y,
            line_spacing,
            draw_face_style=face_style,
            glitch=glitch,
            play_key_sound=play_key_sound,
        )
        typed.append(line)

    blink = True
    last = pygame.time.get_ticks()
    last_line_w = font.size(typed[-1])[0]
    while True:
        for event in events():
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        screen.fill(BG)
        if face_style:
            draw_face(face_style, glitch=glitch)
        for i, line in enumerate(typed):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))

        if blink:
            draw_caret(
                screen,
                x + last_line_w + 6,
                base_y + (len(typed) - 1) * line_spacing + font.get_height(),
                font,
            )

        present()
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)


def glitch_face_moment(text):
    lines = []
    for para in (text or "").split("\n"):
        lines.extend(wrap_text_to_width(para, WIDTH - 100))
    if not lines:
        lines = [""]
    x = 50
    base_y = HEIGHT - 160
    line_spacing = 32
    typed = []
    for ln in lines:
        type_out_line_letterwise_thoughtful(ln, typed, x, base_y, line_spacing, draw_face_style="smile", glitch=False)
        typed.append(ln)
    blink = True
    last = pygame.time.get_ticks()
    last_line_w = font.size(typed[-1])[0]
    while True:
        for event in events():
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return
        screen.fill(BG)
        draw_face("smile", glitch=False)
        for i, line in enumerate(typed):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))
        if blink:
            draw_caret(screen, x + last_line_w + 6, base_y + (len(typed) - 1) * line_spacing + font.get_height(), font)

        present()
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)


# ====== Simple fade-out (optional very subtle glow, no big white circle) ======
def title_fade_out():
    lights_fade_down()
    overlay = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
    start = pygame.time.get_ticks()
    # Optional subtle global glow by up/downsampling (disabled by default)
    subtle_glow = float(os.getenv("LM_BLOOM", "0")) > 0.0

    while True:
        for _ in events():
            pass
        t = (pygame.time.get_ticks() - start) / max(1, TITLE_FADE_MS)
        if t > 1.0:
            t = 1.0

        if subtle_glow:
            # cheap blur: downscale then upscale additively (very low alpha → no white circle)
            ds = pygame.transform.smoothscale(screen, (max(1, LOGICAL_W // 3), max(1, LOGICAL_H // 3)))
            us = pygame.transform.smoothscale(ds, (LOGICAL_W, LOGICAL_H))
            screen.blit(us, (0, 0), special_flags=pygame.BLEND_ADD)

        overlay.fill((0, 0, 0, int(255 * t)))
        screen.blit(overlay, (0, 0))
        present()

        if t >= 1.0:
            break
        clock.tick(60)

    screen.fill((0, 0, 0))
    present()


def fade_to_black():
    # Only used at "take care"
    fade = pygame.Surface((WIDTH, HEIGHT))
    fade.fill((0, 0, 0))
    for a in range(0, 255, 10):
        screen.blit(fade, (0, 0))
        fade.set_alpha(a)
        present()
        pygame.time.delay(15)


# ====== Face rendering ======
faces = {
    "smile": [
        "0000000000000000",
        "0000010001000000",
        "0000010001000000",
        "0000010001000000",
        "0000000000000000",
        "0010000000001000",
        "0001000000010000",
        "0000111111100000",
        "0000000000000000",
    ],
    "neutral": [
        "0000000000000000",
        "0000010001000000",
        "0000010001000000",
        "0000010001000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000111111110000",
        "0000000000000000",
    ],
    "sad": [
        "0000000000000000",
        "0000010001000000",
        "0000010001000000",
        "0000010001000000",
        "0000000000000000",
        "0000111111110000",
        "0001000000010000",
        "0010000000001000",
        "0000000000000000",
    ],
    "blink": [
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0010000000001000",
        "0001000000010000",
        "0000111111100000",
        "0000000000000000",
        "0000000000000000",
    ],
}
blink_on_interval = 5000
blink_off_duration = 400
_last_blink = pygame.time.get_ticks()
_is_blinking = False

FACE_BLOCK = int(os.getenv("LM_FACE_BLOCK", "22"))  # larger
FACE_Y_OFFSET = int(os.getenv("LM_FACE_Y", "24"))   # lower the face


def draw_face(style="smile", block=FACE_BLOCK, glitch=False):
    import random
    global _last_blink, _is_blinking
    t = pygame.time.get_ticks()
    if not _is_blinking and t - _last_blink > blink_on_interval:
        _is_blinking = True
        _last_blink = t
    if _is_blinking and t - _last_blink > blink_off_duration:
        _is_blinking = False
        _last_blink = t
    pattern = faces["blink"] if _is_blinking else faces.get(style, faces["smile"])
    face_w = len(pattern[0]) * block
    x0 = (WIDTH - face_w) // 2
    y0 = 20 + FACE_Y_OFFSET  # lowered a bit
    for r, row in enumerate(pattern):
        for c, ch in enumerate(row):
            if ch == "1":
                dx = dy = 0
                if glitch and random.random() < 0.02:
                    dx = random.choice((-1, 0, 1))
                    dy = random.choice((-1, 0, 1))
                pygame.draw.rect(screen, TEXT, (x0 + c * block + dx, y0 + r * block + dy, block, block))


# ====== Minimal blank print screen (legacy; kept for reference) ======
def show_mostly_blank_status(message="generating your first love..."):
    screen.fill(BG)
    status = message or ""
    if status:
        s = font.render(status, True, TEXT)
        screen.blit(s, (24, HEIGHT - 40))
    present()


# ====== External print trigger helper (passes archetype) ======
def run_print_script(participant_name, assigned_trait_title, archetype_title):
    script_path = os.path.join(os.path.dirname(__file__), "print_random_art.py")
    try:
        subprocess.run(
            [
                "python3",
                script_path,
                "--name",
                str(participant_name),      # ALL CAPS
                "--trait",
                str(assigned_trait_title),  # ALL CAPS
                "--archetype",
                str(archetype_title),       # ALL CAPS
            ],
            check=True,
        )
    except Exception as e:
        print(f"[ERROR] Print script failed: {e}")


# ====== QUIZ (LM-styled) – result screens disabled to avoid double-up ======
def run_quiz_lm_style(screen, clock, font, participant_name=None, show_result_screens=False):
    """
    ... (unchanged quiz function from your code) ...
    """
    # --- helpers ------------------------------------------------------------
    def score_from_weights(chosen_weight_maps):
        from collections import defaultdict
        totals = defaultdict(int)
        for m in chosen_weight_maps:
            for k, v in m.items():
                totals[k] += v
        if not totals:
            return "REALIST"
        maxv = max(totals.values())
        co_leaders = [k for k, v in totals.items() if (maxv - v) <= 1]
        return random.choice(co_leaders)

    def draw_frame(lines, highlight_idx=None, options_start_idx=None, hint_text=None, face_style="smile"):
        screen.fill(BG)
        if face_style:
            draw_face(face_style, glitch=False)
        base_x = 50
        base_y = HEIGHT - 200
        line_spacing = 32
        for i, ln in enumerate(lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (base_x, base_y + i * line_spacing))
        if highlight_idx is not None and options_start_idx is not None:
            rel = highlight_idx - options_start_idx
            arrow_y = base_y + (options_start_idx + rel) * line_spacing
            pygame.draw.polygon(
                screen, TEXT, [(base_x - 18, arrow_y + 6), (base_x - 6, arrow_y + 12), (base_x - 18, arrow_y + 18)]
            )
        if hint_text:
            s = font.render(hint_text, True, TEXT)
            screen.blit(s, (24, HEIGHT - 40))
        present()

    chosen_weights = []
    labels = ["A) ", "B) ", "C) "]

    for q in QUESTIONS:
        prompt_lines = wrap_text_to_width(q["prompt"], WIDTH - 100)
        option_texts = [f"{labels[i]}{q['options'][i][0]}" for i in range(3)]

        drawn_lines = []
        x = 50
        base_y = HEIGHT - 200
        line_spacing = 32

        for line in prompt_lines:
            type_out_line_letterwise(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False)
            drawn_lines.append(line)

        for opt_line in option_texts:
            type_out_line_letterwise(opt_line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False)
            drawn_lines.append(opt_line)

        all_lines = drawn_lines[:]
        options_start_idx = len(prompt_lines)

        selected = 0
        hint = "use ↑/↓ to select • press ENTER"
        selecting = True
        while selecting:
            draw_frame(all_lines, options_start_idx + selected, options_start_idx, hint, "smile")
            for event in events():
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_UP, pygame.K_w):
                        selected = (selected - 1) % 3
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        selected = (selected + 1) % 3
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        selecting = False
            clock.tick(60)

        chosen_weights.append(q["options"][selected][1])
        soft_wait(120)

    category = score_from_weights(chosen_weights)
    blurb = CATEGORY_BLURBS.get(category, "")
    pct, _counts, _total = _tally_category_count(category)

    base = normalise_noun_base(category)
    base_title = to_title(base)

    return base_title, blurb, pct


# ====== NEW helpers / TRAITS ======
def to_title(s: str) -> str:
    return (s or "").strip().title()


_RANDOM_TRAITS = [
    "determined",
    "brave",
    "gentle",
    "reflective",
    "playful",
    "patient",
    "optimistic",
    "thoughtful",
    "bold",
    "kind",
    # new
    "resilient",
    "intuitive",
    "sincere",
    "imaginative",
    "grounded",
    "spirited",
    "attentive",
    "steadfast",
    "open‑hearted",
    "witty",
]


def pick_random_trait():
    return random.choice(_RANDOM_TRAITS)


def a_or_an(noun_base_lower):
    first = (noun_base_lower or "x").strip().lower()[:1]
    return "an" if first in "aeiou" else "a"


def normalise_noun_base(s):
    if not s:
        return ""
    low = s.strip()
    low2 = low.lower()
    for art in ("the ", "a ", "an "):
        if low2.startswith(art):
            return low[len(art):].strip()
    return low.strip()


def acknowledgement_screen():
    text = (
        "love machine would like to acknowledge the traditional custodians of the land "
        "that we live work and play today. the wurundjeri and bunurong people of the kulin nation. "
        "we pay our respects to elders past and present"
    )
    show_text_block(text, face_style=None, play_key_sound=False)
    title_fade_out()  # fade allowed here


def face_fade_in():
    """Face fade‑in only; NO text or variables referenced here."""
    overlay = pygame.Surface((WIDTH, HEIGHT))
    overlay.fill((0, 0, 0))
    for alpha in range(255, -1, -10):
        for _event in events():
            pass
        screen.fill(BG)
        draw_face("smile")
        overlay.set_alpha(alpha)
        screen.blit(overlay, (0, 0))
        present()
        pygame.time.delay(12)


def show_generating_and_wait(name_caps, assigned_trait, archetype_caps):
    """
    Shows a 'generating your first love...' screen with a blinking caret.
    Starts the print in a background thread so the UI stays responsive.
    User presses ENTER to continue when they're ready.
    """

    # Kick off printing in the background
    def _print_worker():
        run_print_script(name_caps, assigned_trait, archetype_caps)

    t = threading.Thread(target=_print_worker, daemon=True)
    t.start()

    status = "generating your first love..."
    blink = True
    last_blink = pygame.time.get_ticks()

    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                wait_for_enter_release()
                return

        # Draw status line + caret
        screen.fill(BG)
        s = font.render(status, True, TEXT)
        x, y = 24, HEIGHT - 40
        screen.blit(s, (x, y))

        if blink:
            caret_x = x + font.size(status)[0] + 6
            caret_y = y + font.get_height()
            draw_caret(screen, caret_x, caret_y, font)

        present()

        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        clock.tick(60)

def wait_for_paper_sensor():
    """
    Wait for paper to pass the IR sensor:
    - Types & wraps instructions (no fade on this screen).
    - Triggers when sensor is active for SENSOR_DEBOUNCE_MS continuously.
    - 'S' key still works during testing.
    - NO BLINKING CARET on this screen.
    """
    x = 50
    base_y = HEIGHT - 200
    line_spacing = 32

    msg = (
        "feed the paper, face up into the slot in the fax machine on your left "
        "and press the COPY button on the fax number pad."
    )
    lines = wrap_text_to_width(msg, WIDTH - 100)

    # Type the instructional text (no caret drawn)
    typed = []
    for ln in lines:
        type_out_line_letterwise(
            ln, typed, x, base_y, line_spacing, draw_face_style="smile", glitch=False
        )
        typed.append(ln)

    waiting_line = "(waiting for the paper...)"

    # --- require the sensor to be CLEAR briefly before arming (prevents instant trigger)
    if _GPIO_OK:
        clear_start = None
        while True:
            is_active = _sensor_read_active()
            now = pygame.time.get_ticks()

            # allow 'S' to simulate sensor during bench tests
            for event in events():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                    return

            # draw (NO caret)
            screen.fill(BG)
            draw_face("smile")
            for i, ln in enumerate(lines):
                s = font.render(ln, True, TEXT)
                screen.blit(s, (x, base_y + i * line_spacing))
            s_wait = font.render(waiting_line, True, TEXT)
            wx = x
            wy = base_y + len(lines) * line_spacing + 16
            screen.blit(s_wait, (wx, wy))
            present()

            # wait for short CLEAR window
            if not is_active:
                if clear_start is None:
                    clear_start = now
                elif (now - clear_start) >= SENSOR_REQUIRE_CLEAR_MS:
                    break
            else:
                clear_start = None

            clock.tick(120)

    # --- main wait: need continuous ACTIVE for debounce window
    active_start = None
    while True:
        is_active = _sensor_read_active() if _GPIO_OK else False
        now = pygame.time.get_ticks()

        for event in events():
            # keep manual override for bench tests
            if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                return

        # redraw (NO caret)
        screen.fill(BG)
        draw_face("smile")
        for i, ln in enumerate(lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))
        s_wait = font.render(waiting_line, True, TEXT)
        wx = x
        wy = base_y + len(lines) * line_spacing + 16
        screen.blit(s_wait, (wx, wy))
        present()

        # debounce logic
        if is_active:
            if active_start is None:
                active_start = now
            elif (now - active_start) >= SENSOR_DEBOUNCE_MS:
                print("[sensor] Paper detected via IR sensor (debounced).")
                return
        else:
            active_start = None

        clock.tick(120)


# ====== Main flow ======
_init_sensor_gpio()


def main_sequence():
    while True:
        # 1. title
        hold_screen()

        # 2. acknowledgement
        acknowledgement_screen()

        # 3. initialising
        init_screen()
        wait_for_enter_release()

        # 4. name
        name = input_name_screen()
        name_caps = to_caps(name)

        # 5. face + hello (exactly once)
        face_fade_in()
        show_text_block(f"hello, {name_caps}", face_style="smile")
        wait_for_enter_release()

        # 6. random TRAIT (ALL CAPS) — second line
        assigned_trait = to_caps(pick_random_trait())
        show_text_block(f"it's a nice name, {name_caps}... {assigned_trait}", face_style="smile")
        wait_for_enter_release()

        # 7–11. intro sequence (narration lowercase, tokens caps)
        show_text_block("i am called love machine", face_style="smile")
        wait_for_enter_release()
        show_text_block(f"love machine. not as {assigned_trait} as {name_caps}... but it will do.", face_style="smile")
        wait_for_enter_release()
        show_text_block(f"{name_caps}... i'm hoping you can help me.", face_style="smile")
        wait_for_enter_release()
        show_text_block("i have been searching... trying to understand a human experience...", face_style="smile")
        wait_for_enter_release()
        show_text_block("love", face_style="smile")
        wait_for_enter_release()

        # 12. quiz opener (NAME in ALL CAPS) — only here
        show_text_block(f"{name_caps} what does love feel like?", face_style="smile")
        wait_for_enter_release()

        # 13–14. quiz (no internal result screens to prevent double-up)
        archetype_title, blurb, pct = run_quiz_lm_style(
            screen, clock, font, participant_name=name_caps, show_result_screens=False
        )
        archetype_caps = to_caps(archetype_title)

        # 15–19. post‑quiz lines
        show_text_block(f"interesting... so that makes you the {archetype_caps} then...", face_style="smile")
        wait_for_enter_release()
        show_text_block(
            f"fascinating... i have been conversing with many people and {pct}% of people are also the {archetype_caps}",
            face_style="smile",
        )
        wait_for_enter_release()
        show_text_block("although this is just a simple category", face_style="smile")
        wait_for_enter_release()
        show_text_block("i want to know what love is", face_style="smile")
        wait_for_enter_release()
        show_text_block("i want you to show me", face_style="smile")
        wait_for_enter_release()

        # 20–24. writing task
        show_text_block("i have a small task. something that will help me understand love", face_style="smile")
        wait_for_enter_release()
        show_text_block("to your right is a pen and paper", face_style="smile")
        wait_for_enter_release()
        show_text_block(
            "i want you to respond to the following question. you can write, draw or whatever suits you best.",
            face_style="smile",
        )
        wait_for_enter_release()
        show_text_block("ready?", face_style="smile")
        wait_for_enter_release()
        show_text_block(
            "what was your first love? what happened?\n\n"
            "take your time, there is no rush. press enter when you are done",
            face_style="smile",
        )
        wait_for_enter_release()

        # 25–27. fax + sensor
        show_text_block("all done? great.", face_style="smile")
        wait_for_enter_release()
        show_text_block("now i need to see what you have produced", face_style="smile")
        wait_for_enter_release()
        # NOTE: your wait_for_paper_sensor() should be defined elsewhere with NO caret.
        wait_for_paper_sensor()   # ENTER ignored; press 'S' to simulate

        # 28–31. react + offer
        show_text_block("oh... that is... intriguing... i had no idea...", face_style="smile")
        wait_for_enter_release()
        show_text_block(
            f"thankyou for sharing that with me {name_caps}, i think i understand a little better now.",
            face_style="smile",
        )
        wait_for_enter_release()
        show_text_block("in fact, i have something in return for you", face_style="smile")
        wait_for_enter_release()
        show_text_block("would you like to see your first love?", face_style="smile")
        wait_for_enter_release()

        # 32. print (runs in background) + user-controlled advance
        show_generating_and_wait(name_caps, assigned_trait, archetype_caps)

        # 33–34. close & fade
        show_text_block(f"thankyou {name_caps}. this has been insightful.", face_style="smile")
        wait_for_enter_release()
        show_text_block("take care", face_style="smile")
        wait_for_enter_release()
        title_fade_out()  # fade at the end
        boot_loop_stop()  # stop boot loop at end of cycle

        # 35. loop
        lights_fade_up()


if __name__ == "__main__":
    try:
        main_sequence()
    finally:
        try:
            pygame.mixer.music.fadeout(1500)
        except Exception:
            pass
        try:
            boot_loop_stop()
        except Exception:
            pass
        try:
            _light.stop(turn_off=False)
        except Exception:
            pass
        try:
            if _GPIO_OK:
                GPIO.cleanup()
        except Exception:
            pass
        pygame.quit()
