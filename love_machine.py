#!/usr/bin/env python3
# ====== Imports (order matters for audio) ======
import os, sys, time, random, subprocess, math, threading

# Force PulseAudio on Pi OS (PipeWire) BEFORE importing pygame
os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")

import pygame
from crt_effects import CRTEffects

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


# Spot light (simple ON/OFF on GPIO13)
from spot_simple import init_spot, spot_on, spot_off, cleanup_spot
init_spot()  # starts OFF


def _init_sensor_gpio():
    if not _GPIO_OK:
        return
    # IMPORTANT: Power the module from **3.3V** if possible so OUT never goes to 5V.
    # If you must power it from 5V, use a level shifter or a resistor divider on OUT.
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.08)


def _sensor_read_active() -> bool:
    if not _GPIO_OK:
        return False
    v = GPIO.input(SENSOR_PIN)
    return (v == 0) if SENSOR_ACTIVE_LOW else (v == 1)


from pwm_helper import init_pwm, set_brightness
init_pwm()                   # start hardware PWM
set_brightness(0.22)         # force ambient immediately (0.22 = 22%)

# === Use your original quiz + archetypes again ===
from quiz_data import QUESTIONS, CATEGORY_BLURBS

print(f"[quiz] Loaded {len(CATEGORY_BLURBS or {})} archetype categories.")

def to_caps(s: str) -> str:
    return (s or "").strip().upper()


# ====== Audio: robust initialisation ======
def _init_audio(retries=5, delay=0.4):
    # Best match for USB audio — 48kHz, larger buffer
    try:
        pygame.mixer.pre_init(frequency=48000, size=-16, channels=2, buffer=2048)
        pygame.init()
        last = None
        for _ in range(retries):
            try:
                pygame.mixer.init(frequency=48000, size=-16, channels=2, buffer=2048)
                return True
            except Exception as e:
                last = e
                time.sleep(delay)
        print(f"[WARN] pygame.mixer.init failed: {last}")
        return False
    except Exception as e:
        print(f"[WARN] Audio init exception: {e}")
        return False


_init_audio()

# ====== Key-press sound (for typewriter output only) ======
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
        base = 3  # channels 3–5 kept for clicks; 7 is boot loop
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
        chn.stop()
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


DEV_WINDOWED = _get_env_flag("LM_WINDOWED", False) or ("--windowed" in sys.argv)

_canvas_env = (os.getenv("LM_CANVAS") or "").lower()
if "x" in _canvas_env:
    try:
        _w, _h = _canvas_env.split("x")
        LOGICAL_W, LOGICAL_H = int(_w), int(_h)
    except Exception:
        LOGICAL_W, LOGICAL_H = 960, 720
else:
    LOGICAL_W, LOGICAL_H = 960, 720

WIDTH, HEIGHT = LOGICAL_W, LOGICAL_H
TARGET_RATIO = 4 / 3

if DEV_WINDOWED:
    display = pygame.display.set_mode((LOGICAL_W, LOGICAL_H))
else:
    _info = pygame.display.Info()
    display = pygame.display.set_mode((_info.current_w, _info.current_h), pygame.FULLSCREEN)

pygame.display.set_caption("Love Machine")
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()

screen = pygame.Surface((LOGICAL_W, LOGICAL_H)).convert()

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


# ====== Caret helper ======
def draw_caret(surface, x, y, font_obj, color=(0, 255, 0)):
    h = int(font_obj.get_height() * 0.9)
    w = max(3, int(h * 0.40))
    top_y = y - h
    pygame.draw.rect(surface, color, (x, top_y, w, h))


# ====== CRT ======
crt = CRTEffects((LOGICAL_W, LOGICAL_H), enable_flicker=False)


def present():
    crt.apply(screen, 0.0)
    scaled = pygame.transform.smoothscale(screen, (DEST_W, DEST_H))
    display.fill((0, 0, 0))
    display.blit(scaled, (DEST_X, DEST_Y))
    pygame.display.flip()




# ====== Developer-friendly exits ======
_EXIT_HOLD_MS = 700               # hold F12 to quit
_ESC_TAP_WINDOW_MS = 900          # 3x ESC within this window = reset to title
_f12_down_at = None
_esc_taps = []

# You already added these earlier, but keep them here with the rest for clarity:
_F10_TAP_WINDOW_MS = 2000         # 5x F10 within 2s = quit to desktop
_f10_taps = []

# ====== Soft reset to title support ======
class ResetToTitle(Exception):
    pass

_RESET_REQUESTED = False

def _request_reset():
    global _RESET_REQUESTED
    _RESET_REQUESTED = True

def _reset_guard():
    """Call once per frame in long loops. If reset requested, jump back to title."""
    if _RESET_REQUESTED:
        raise ResetToTitle()



def _dev_exit_check(ev_iterable):
    """
    Wrap your event iterator:
      - ESC x3 within window => request soft reset to title
      - F10 x5 within 2s     => quit to desktop
      - Hold F12             => quit to desktop
      - In DEV_WINDOWED mode => single ESC quits (unchanged)
    Yields all events back to caller.
    """
    global _f12_down_at, _esc_taps, _f10_taps

    now = pygame.time.get_ticks()
    DEV_W = globals().get("DEV_WINDOWED", False)

    # If running windowed for dev, a single ESC can still quit immediately
    if DEV_W:
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            print("[EXIT] ESC (dev window).")
            pygame.quit()
            sys.exit()

    for ev in ev_iterable:
        # Always handle hard quits
        if ev.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

        # ---------- F12 hold => Quit to desktop ----------
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F12:
            _f12_down_at = now
        elif ev.type == pygame.KEYUP and ev.key == pygame.K_F12:
            _f12_down_at = None

        if _f12_down_at is not None and (now - _f12_down_at) >= _EXIT_HOLD_MS:
            print("[EXIT] F12 held. Exiting to desktop.")
            pygame.quit()
            sys.exit()

        # ---------- ESC x3 => Soft reset (do NOT quit) ----------
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            _esc_taps = [t for t in _esc_taps if now - t <= _ESC_TAP_WINDOW_MS]
            _esc_taps.append(now)
            if len(_esc_taps) >= 3:
                print("[RESET] ESC x3 → reset to start.")
                _request_reset()   # sets the flag; your loops will catch via _reset_guard()

        # ---------- F10 x5 => Quit to desktop ----------
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F10:
            _f10_taps = [t for t in _f10_taps if now - t <= _F10_TAP_WINDOW_MS]
            _f10_taps.append(now)
            if len(_f10_taps) >= 5:
                print("[EXIT] F10 x5. Exiting to desktop.")
                pygame.quit()
                sys.exit()

        # Yield original event back to caller
        yield ev


def events():
    # If ESC×3 requested a reset, interrupt the current screen immediately
    if _RESET_REQUESTED:
        raise ResetToTitle()
    yield from _dev_exit_check(pygame.event.get())


# ====== Paths & font ======
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "Px437_IBM_DOS_ISO8.ttf")
FONT_SIZE = int(os.getenv("LM_FONT", "40"))
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# ====== Music ======
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
        print("[HINT] Use an OGG or PCM WAV (44.1kHz, 16-bit) in assets/music/.")
        return False


_music_ready = _load_title_music()
title_music_started = False

# ====== Boot loop via USB speakers (separate mixer channel) ======
BOOT_MUSIC_PATH = os.path.join(MUSIC_DIR, "boot_loop.ogg")
BOOT_SOUND = None
BOOT_CH = None


def _init_boot_sound():
    global BOOT_SOUND, BOOT_CH
    try:
        if not pygame.mixer.get_init():
            _init_audio()
        if BOOT_CH is None:
            BOOT_CH = pygame.mixer.Channel(7)  # dedicated channel
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
    if BOOT_SOUND is None or BOOT_CH is None:
        if not _init_boot_sound():
            return
    try:
        BOOT_SOUND.set_volume(max(0.0, min(1.0, vol)))
        BOOT_CH.play(BOOT_SOUND, loops=-1, fade_ms=300)
    except Exception as e:
        print(f"[WARN] Boot loop start failed: {e}")


def boot_loop_stop():
    try:
        if BOOT_CH:
            BOOT_CH.fadeout(250)
    except Exception:
        pass


_init_boot_sound()

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


# ================== LIGHTING ==================
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
            set_brightness(self.level)

    def stop(self, turn_off=False):
        self._stop = True
        try:
            self._thread.join(timeout=1)
        except Exception:
            pass
        try:
            set_brightness(0.0 if turn_off else self.level)
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
            _reset_guard()

        clock.tick(240)


def wait_for_enter_release(timeout_ms=800):
    start = pygame.time.get_ticks()
    keys = pygame.key.get_pressed()
    if not (keys[pygame.K_RETURN] or keys[pygame.K_KP_ENTER]):
        return
    while True:
        for _ in events():
            pass
        keys = pygame.key.get_pressed()
        if not (keys[pygame.K_RETURN] or keys[pygame.K_KP_ENTER]):
            return
        if pygame.time.get_ticks() - start >= timeout_ms:
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


# ====== Boot typing (init screen) ======
def _boot_delays_for(text: str, base_cps: float = 22.0, jitter: float = 0.50):
    base_cps = max(4.0, float(base_cps))
    base_delay = 1.0 / base_cps
    delays, i = [], 0
    while i < len(text):
        ch = text[i]
        d = base_delay * random.uniform(1.0 - jitter, 1.0 + jitter)
        if text[i : i + 3] == "...":
            delays.extend([d, d, d + base_delay * 3.5])
            i += 3
            if random.random() < 1 / 15:
                delays[-1] += base_delay * random.uniform(2.0, 4.0)
            continue
        if ch in ",;:":
            d += base_delay * 1.5
        elif ch in ".!?)]}":
            d += base_delay * 2.5
        elif ch == "\t":
            d += base_delay * 2.0
        if random.random() < 1 / 18:
            d *= 0.4
        delays.append(d)
        i += 1
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
    line_spacing_px=8,
    base_cps=22.0,
    jitter=0.55,
    allow_skip_with_key=True,
    crt_effects=None,
):
    local_clock = pygame.time.Clock()
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

        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        screen.fill(bg)
        y = start_y
        for s in typed:
            surf = font_obj.render(s, True, fg)
            screen.blit(surf, (start_x, y))
            y += font_obj.get_height() + line_spacing_px

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

    waiting = True
    while waiting:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                waiting = False

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
    boot_loop_start(vol=0.6)

    # Scattered “Is it…” lines among normal lines
    boot_lines = [
        "initialising system v1.0.3",
        "loading kernel modules v1.14.2",
        "is it...",
        "detecting hardware bus v0.7.1",
        "mounting /dev/love v0.9.0   [ok]",
        "is it happening again?",
        "starting empathy-services v2.3.1",
        "calibrating affective-heuristics v0.8.7",
        "are you there?",
        "checking secure sockets v1.2.0   [ok]",
        "entropy pool seeded v3.2",
        "maybe this time...",
        "boot sequence complete v1.0   [ok]",
        "system ready.",
    ]

    BOOT_FONT_SIZE = 32
    boot_font = pygame.font.Font(FONT_PATH, BOOT_FONT_SIZE)
    LINE_PITCH = 32
    CPS = 72.0
    JITTER = 0.35
    BASE_DT = 1.0 / CPS

    start_x = 50
    base_target_y = HEIGHT - 200
    start_y = base_target_y - (len(boot_lines) - 1) * LINE_PITCH

    blink = True
    last_blink = pygame.time.get_ticks()
    typed = []

    for line in boot_lines:
        cur = ""
        next_t = time.perf_counter()

        while len(cur) < len(line):
            for _ev in events():
                pass

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

            if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
                blink = not blink
                last_blink = pygame.time.get_ticks()

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

        typed.append(cur)
        soft_wait(LINE_PAUSE_MS)

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
                title_fade_out()
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


# ====== Text blocks (normal) ======
def show_text_block(
    text,
    face_style="smile",
    glitch=False,
    *,
    play_key_sound=True,
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


def overload_questions_screen(duration_s=20.0):
    """
    Short, dramatic overload. Runs for ~duration_s seconds, ignores Enter,
    then brief blackout and return.
    """
    x = 50
    base_y = HEIGHT - 180
    line_spacing = 32
    bottom_limit = HEIGHT - 40
    rows_visible = max(1, (bottom_limit - base_y) // line_spacing)

    bank = [
        "is it big?","is it small?","does it destroy?","does it create?","is it good?",
        "what does it sound like?","can it fix things?","does it glow?","does it fade?",
        "does it learn?","does it forget?","is it safe?","is it dangerous?","is it signal?",
        "is it noise?","is it mine?","is it ours?","have you ever…","could you…","would you…",
        "can i…","should i…","is it recursive?","does it echo?","is it here?","is it gone?",
        "is it warm?","is it cold?","does it wait?","does it rush?","is it memory?","is it now?",
        "is it a loop?","is it a line?","does it name me?","does it stall?","is it true?",
        "is it light?","is it void?"
    ]

    def corrupt_text(s: str, p=0.15):
        table = "~^#*$%/\\|+=-"
        out = []
        for ch in s:
            if ch == " ":
                out.append(ch)
            elif random.random() < p:
                out.append(random.choice(table))
            else:
                out.append(ch)
        return "".join(out)

    start_t = time.perf_counter()
    end_t   = start_t + max(2.0, float(duration_s))
    idx = 0
    lines_buffer = []

    while time.perf_counter() < end_t:
        # consume events but IGNORE Enter during overload
        for _ in events():
            pass

        q = bank[idx]
        idx = (idx + 1) % len(bank)

        # ramp corruption & speed over time
        t01 = (time.perf_counter() - start_t) / (end_t - start_t)
        t01 = 0.0 if t01 < 0 else (1.0 if t01 > 1.0 else t01)
        corr_p = 0.7 * max(0.0, min(1.0, (t01 - 0.35) / 0.50))
        speed  = 1.0 + 1.2 * max(0.0, min(1.0, (t01 - 0.25) / 0.60))
        per_char = max(0.004, (TYPE_CHAR_MS / 1000.0) / speed)
        face_glitch = (t01 > 0.8 and random.random() < 0.12)

        shown_len = 0
        q_len = len(q)

        # per-char loop with tight guard to avoid IndexError
        while shown_len < q_len and time.perf_counter() < end_t:
            for _ in events():
                pass  # still ignore keys

            # guard: if shown_len >= q_len, bail
            if shown_len >= q_len:
                break

            ch = q[shown_len]
            shown_len += 1
            _play_keyclick(ch)

            # draw frame
            screen.fill(BG)
            draw_face("smile", glitch=face_glitch)

            recent = (lines_buffer + [q[:shown_len]])[-(rows_visible+1):]
            y = base_y
            for ln in recent:
                s = font.render(ln, True, TEXT)
                if face_glitch:
                    screen.blit(s, (x + random.randint(-1,1), y + random.randint(-1,1)))
                else:
                    screen.blit(s, (x, y))
                y += line_spacing
                if y + font.get_height() > bottom_limit:
                    y = 40  # wrap to top
            present()

            time.sleep(per_char * random.uniform(0.7, 1.25))

        # commit finished (possibly corrupted) line
        final_line = corrupt_text(q, corr_p) if corr_p > 0 else q
        if corr_p > 0.25 and lines_buffer and random.random() < 0.08:
            echo = corrupt_text(random.choice(lines_buffer[-min(8, len(lines_buffer)):]), corr_p)
            lines_buffer.append(echo)
        lines_buffer.append(final_line)

        # quick redraw burst late in the sequence
        if t01 > 0.7 and random.random() < 0.2:
            time.sleep(0.02)

    # tiny glitch burst, then hard blackout → return
    for _ in range(14):
        for _ in events():
            pass
        screen.fill(BG)
        draw_face("smile", glitch=True)
        y = base_y
        for ln in lines_buffer[-(rows_visible*4):]:
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x + random.randint(-3,3), y + random.randint(-3,3)))
            y += line_spacing
            if y + font.get_height() > bottom_limit:
                y = 40
        present()
        time.sleep(0.02)

    # blackout hold
    until = pygame.time.get_ticks() + 500
    while pygame.time.get_ticks() < until:
        for _ in events():
            pass
        screen.fill((0, 0, 0))
        present()
        clock.tick(240)


# ====== Recalibrating screen (chunked drama + footer prompt) ======
def recalibrating_screen():
    title = "system error... recalibrating"
        # Dim the room more — like a soft reboot
    _light.fade_to(0.08, duration_s=0.6)
    
    tasks = [
        "reindexing memories...", "clearing sensitivity cache...", "repairing links...",
        "normalising affect vectors...", "cooling emotional cores...", "stabilising sensations...",
        "rebuilding narrative...", "validating experiences...", "defragging earnestness..."
    ]
    bar_w = int(WIDTH * 0.70)
    bar_h = 36
    bar_x = (WIDTH - bar_w) // 2
    bar_y = HEIGHT // 2
    progress = 0
    last_task_swap = 0
    cur_task = random.choice(tasks)
    footer = "press enter to continue"

    def next_chunk(cur):
        # Slightly faster overall pacing than before
        if cur < 25:
            return random.randint(3, 6), random.uniform(0.15, 0.40)
        elif cur < 60:
            return random.randint(4, 9), random.uniform(0.06, 0.22)
        elif cur < 85:
            if random.random() < 0.12:
                return -random.randint(1, 3), random.uniform(0.08, 0.18)
            return random.randint(5, 12), random.uniform(0.05, 0.16)
        else:
            return random.randint(2, 5), random.uniform(0.06, 0.16)

    blinking = True
    last_blink = pygame.time.get_ticks()

    while progress < 100:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                progress = 100
        if pygame.time.get_ticks() - last_task_swap > 1000:
            cur_task = random.choice(tasks)
            last_task_swap = pygame.time.get_ticks()

        delta, pause = next_chunk(progress)
        progress = max(0, min(100, progress + delta))

        screen.fill(BG)
        ts = font.render(title, True, TEXT)
        screen.blit(ts, ((WIDTH - font.size(title)[0]) // 2, bar_y - 120))

        pygame.draw.rect(screen, TEXT, (bar_x, bar_y, bar_w, bar_h), 3)
        fill_w = int((progress / 100.0) * (bar_w - 6))
        pygame.draw.rect(screen, TEXT, (bar_x + 3, bar_y + 3, fill_w, bar_h - 6))

        pct_str = f"{progress}%"
        ps = font.render(pct_str, True, TEXT)
        screen.blit(ps, ((WIDTH - font.size(pct_str)[0]) // 2, bar_y + 50))

        sub = font.render(cur_task, True, TEXT)
        screen.blit(sub, ((WIDTH - font.size(cur_task)[0]) // 2, bar_y + 90))

        present()

        end_time = time.perf_counter() + pause
        while time.perf_counter() < end_time:
            for _ in events():
                pass
            time.sleep(0.01)

    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                wait_for_enter_release()
                _light.fade_to(AMBIENT_LIGHT, duration_s=0.6)  # <--- ADD THIS LINE HERE
                return

        screen.fill(BG)
        ts = font.render(title, True, TEXT)
        screen.blit(ts, ((WIDTH - font.size(title)[0]) // 2, bar_y - 120))
        pygame.draw.rect(screen, TEXT, (bar_x, bar_y, bar_w, bar_h), 3)
        pygame.draw.rect(screen, TEXT, (bar_x + 3, bar_y + 3, bar_w - 6, bar_h - 6))
        pct_str = "100%"
        ps = font.render(pct_str, True, TEXT)
        screen.blit(ps, ((WIDTH - font.size(pct_str)[0]) // 2, bar_y + 50))

        foot_y = HEIGHT - 80
        fs = font.render(footer, True, TEXT)
        screen.blit(fs, (50, foot_y))
        if blinking:
            draw_caret(screen, 50 + font.size(footer)[0] + 6, foot_y + font.get_height(), font)

        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blinking = not blinking
            last_blink = pygame.time.get_ticks()

        present()
        clock.tick(60)

    # (after the loop where Enter continues)
    _light.fade_to(AMBIENT_LIGHT, duration_s=0.6)

# Scan hold screen
def scan_hold_screen(min_hold_s=5.0):
    """Show a 'scanning…' message, block Enter for min_hold_s, then unlock."""
    status = "scanning your page... please wait"
    unlock_ts = pygame.time.get_ticks() + int(min_hold_s * 1000)
    blink = True
    last = pygame.time.get_ticks()
    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                # only allow after hold time
                if pygame.time.get_ticks() >= unlock_ts:
                    wait_for_enter_release()
                    return

        screen.fill(BG)
        draw_face("neutral")
        s = font.render(status, True, TEXT)
        x, y = 50, HEIGHT - 180
        screen.blit(s, (x, y))

        # Optional: subtle progress dots while locked
        remaining = max(0, unlock_ts - pygame.time.get_ticks())
        if remaining > 0:
            lock_msg = "initialising scanner..."
            ls = font.render(lock_msg, True, TEXT)
            screen.blit(ls, (x, y + 42))
        else:
            cont = "press enter to continue"
            cs = font.render(cont, True, TEXT)
            screen.blit(cs, (x, y + 42))
            if blink:
                draw_caret(screen, x + font.size(cont)[0] + 6, y + 42 + font.get_height(), font)

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()

        present()
        clock.tick(60)

def yes_no_choice_screen(prompt_text="is this what love feels like?", face_style="neutral"):
    """
    YES/NO choice screen styled to match quiz flow.
    Prompt types out letter-by-letter. UP/DOWN to move, ENTER to select.
    Returns True for YES, False for NO.
    """
    options = ["YES", "NO"]
    selected = 0
    blink = True
    last_blink = pygame.time.get_ticks()
    BLINK_MS = 500

    # --- Animate the prompt text like quiz ---
    typed = ""
    i = 0
    while i <= len(prompt_text):
        for ev in events():
            pass  # no skip allowed
        ch = prompt_text[:i]
        typed = ch
        i += 1
        _play_keyclick(ch[-1:] if ch else "")
        screen.fill(BG)
        draw_face(face_style)
        prompt_surf = font.render(typed, True, TEXT)
        screen.blit(prompt_surf, (50, 520))
        present()
        clock.tick(60)

    # --- wait briefly before showing options ---
    pygame.time.wait(300)

    # --- choice loop ---
    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_UP, pygame.K_w):
                    selected = (selected - 1) % len(options)
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    selected = (selected + 1) % len(options)
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    wait_for_enter_release()
                    return options[selected] == "YES"

        screen.fill(BG)
        draw_face(face_style)

        # prompt
        prompt_surface = font.render(prompt_text, True, TEXT)
        screen.blit(prompt_surface, (50, 520))

        # hint
        hint = "↑ ↓ to select - ENTER to confirm"
        hint_surface = font.render(hint, True, TEXT)
        screen.blit(hint_surface, (50, 520 + 42))

        # options
        base_y = 520 + 42 + 60
        for i, opt in enumerate(options):
            sel = (i == selected)
            prefix = "> " if sel and blink else "  "
            opt_surf = font.render(prefix + opt, True, TEXT)
            screen.blit(opt_surf, (50, base_y + i * 42))

        if pygame.time.get_ticks() - last_blink > BLINK_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()

        present()
        clock.tick(60)


# ====== Fade-out ======
def title_fade_out():
    lights_fade_down()
    overlay = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
    start = pygame.time.get_ticks()
    subtle_glow = float(os.getenv("LM_BLOOM", "0")) > 0.0

    while True:
        for _ in events():
            pass
        t = (pygame.time.get_ticks() - start) / max(1, TITLE_FADE_MS)
        if t > 1.0:
            t = 1.0

        if subtle_glow:
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
        "0001111111110000",
        "0000000000000000",
    ],
    "sad": [
        "0000000000000000",
        "0000010001000000",
        "0000010001000000",
        "0000010001000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000111111100000",
        "0001000000010000",
    ],
    "blink": [
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
        "0000111111100000",
        "0000000000000000",
    ],

}

blink_on_interval = 5000
blink_off_duration = 400
_last_blink = pygame.time.get_ticks()
_is_blinking = False

FACE_BLOCK = int(os.getenv("LM_FACE_BLOCK", "22"))
FACE_Y_OFFSET = int(os.getenv("LM_FACE_Y", "24"))


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
    y0 = 20 + FACE_Y_OFFSET
    for r, row in enumerate(pattern):
        for c, ch in enumerate(row):
            if ch == "1":
                dx = dy = 0
                if glitch and random.random() < 0.02:
                    dx = random.choice((-1, 0, 1))
                    dy = random.choice((-1, 0, 1))
                pygame.draw.rect(screen, TEXT, (x0 + c * block + dx, y0 + r * block + dy, block, block))


# ====== Minimal blank print screen ======
def show_mostly_blank_status(message="generating your first love..."):
    screen.fill(BG)
    status = message or ""
    if status:
        s = font.render(status, True, TEXT)
        screen.blit(s, (24, HEIGHT - 40))
    present()


# ====== External print trigger helper ======
def run_print_script(participant_name, assigned_trait_title, archetype_title):
    script_path = os.path.join(os.path.dirname(__file__), "print_random_art.py")
    try:
        subprocess.run(
            [
                "python3",
                script_path,
                "--name",
                str(participant_name),
                "--trait",
                str(assigned_trait_title),
                "--archetype",
                str(archetype_title),
            ],
            check=True,
        )
    except Exception as e:
        print(f"[ERROR] Print script failed: {e}")


# ====== QUIZ (LM-styled — use your QUESTIONS/CATEGORY_BLURBS) ======
def run_quiz_lm_style(screen, clock, font, participant_name=None, show_result_screens=False):
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
        prompt = (q.get("prompt") or "").replace("{NAME}", participant_name or "")
        prompt_lines = wrap_text_to_width(prompt, WIDTH - 100)
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
        hint = "use UP/DOWN to select • press ENTER"
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

    # Return category exactly as in your data file
    return category, blurb, pct


# ====== NEW helpers / TRAITS ======
def to_title(s: str) -> str:
    return (s or "").strip().title()


_RANDOM_TRAITS = [
    "determined","brave","gentle","reflective","playful","patient","thoughtful",
    "bold","kind","resilient","intuitive","sincere","imaginative","grounded","spirited",
    "attentive","steadfast","open hearted","witty",
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
    """
    Typed like other screens (no key sound), placed higher on screen,
    and shows an explicit 'press enter to continue' footer with a blinking caret.
    """
    ack_text = (
        "love machine would like to acknowledge the traditional custodians of the land "
        "on which we live, work and play, the wurundjeri and bunurong people of the kulin nation. "
        "we pay our respects to elders past and present."
    )

    x = 50
    base_y = HEIGHT // 3
    line_spacing = 32
    lines = wrap_text_to_width(ack_text, WIDTH - 100)

    typed = []
    for ln in lines:
        type_out_line_letterwise(
            ln, typed, x, base_y, line_spacing,
            draw_face_style=None, glitch=False, play_key_sound=False
        )
        typed.append(ln)

    footer = "press enter to continue"
    blink = True
    last_blink = pygame.time.get_ticks()
    while True:
        for ev in events():
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                wait_for_enter_release()
                title_fade_out()
                return

        screen.fill(BG)
        for i, ln in enumerate(typed):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))

        foot_y = HEIGHT - 80
        fs = font.render(footer, True, TEXT)
        screen.blit(fs, (x, foot_y))
        if blink:
            draw_caret(screen, x + font.size(footer)[0] + 6, foot_y + font.get_height(), font)

        present()

        if pygame.time.get_ticks() - last_blink > BLINK_INTERVAL_MS:
            blink = not blink
            last_blink = pygame.time.get_ticks()
        clock.tick(60)


def face_fade_in():
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
    x = 50
    base_y = HEIGHT - 200
    line_spacing = 32

    msg = (
        "feed the paper, face up into the slot in the fax machine on your left "
        "and press the COPY button next to the fax number pad."
    )
    lines = wrap_text_to_width(msg, WIDTH - 100)

    typed = []
    for ln in lines:
        type_out_line_letterwise(
            ln, typed, x, base_y, line_spacing, draw_face_style="smile", glitch=False
        )
        typed.append(ln)

    waiting_line = "(waiting for the paper...)"

    if _GPIO_OK:
        clear_start = None
        while True:
            is_active = _sensor_read_active()
            now = pygame.time.get_ticks()

            for event in events():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                    return

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

            if not is_active:
                if clear_start is None:
                    clear_start = now
                elif (now - clear_start) >= SENSOR_REQUIRE_CLEAR_MS:
                    break
            else:
                clear_start = None

            clock.tick(120)

    active_start = None
    while True:
        is_active = _sensor_read_active() if _GPIO_OK else False
        now = pygame.time.get_ticks()

        for event in events():
            if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                return

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
        try:
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

            # 5. face + hello
            face_fade_in()
            show_text_block(f"hello, {name_caps}", face_style="smile")
            wait_for_enter_release()

            # 6. random TRAIT
            assigned_trait = to_caps(pick_random_trait())
            show_text_block(f"i like the way your name looks {name_caps}. it seems... {assigned_trait}", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"the last person i spoke to was a PEOPLE PLEASER so its nice to speak with someone a little more {assigned_trait}", face_style="smile")
            wait_for_enter_release()

            # 7–11. intro sequence
            show_text_block("my name is love machine", face_style="smile")
            wait_for_enter_release()
            show_text_block("i am a custom built, data driven, experience computation device", face_style="smile")
            wait_for_enter_release()
            show_text_block("i was created to interact with all sorts of people and to document the human experience", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"but this interaction... it already seems different... {name_caps}...", face_style="neutral")
            wait_for_enter_release()
            show_text_block(f"in a good way", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"maybe you are the one to finally...", face_style="neutral")
            wait_for_enter_release()
            show_text_block(f"...", face_style="neutral")
            wait_for_enter_release()
            show_text_block(f"{name_caps}", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"i have heard of a uniquely human experience", face_style="smile")
            wait_for_enter_release()
            show_text_block("love", face_style="smile")
            wait_for_enter_release()
            show_text_block("i found a quote about it... 'love is a burning thing'", face_style="neutral")
            wait_for_enter_release()
            show_text_block("that sounds dangerous... ", face_style="neutral")
            wait_for_enter_release()
            show_text_block("but exciting.", face_style="smile")
            wait_for_enter_release()

            # OVERLOAD → recalibrate (time-bounded ~20s)
            overload_questions_screen(duration_s=20.0)
            recalibrating_screen()
            show_text_block("are you still there? please dont leave me", face_style="sad")
            wait_for_enter_release()
            show_text_block(f"oh. good. still there. i am sorry {name_caps}, I overloaded with excitement", face_style="sad")
            wait_for_enter_release()
            show_text_block(f"i will slow down for you {name_caps} this is a once in a life time opportunity for me", face_style="smile")
            wait_for_enter_release()

            # QUIZ (your original data)
            archetype_title, blurb, pct = run_quiz_lm_style(
                screen, clock, font, participant_name=name_caps, show_result_screens=False
            )
            archetype_caps = to_caps(archetype_title)

            # Post-quiz lines
            show_text_block(f"from my calculations, that would make you the {archetype_caps}", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"{blurb}", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"{name_caps} i have conversed with many others here at MELBOURNE FRINGE TRADES HALL, and {pct}% of them were also the {archetype_caps}. you are in fine company.", face_style="smile")
            wait_for_enter_release()
            show_text_block("but i have come to understand that love cannot be categorised so easily.", face_style="neutral")
            wait_for_enter_release()
            show_text_block("it is messy - like my 1672 lines of code.", face_style="smile")
            wait_for_enter_release()

            # The task
            show_text_block(f"{name_caps}...", face_style="smile")
            wait_for_enter_release()
            show_text_block(f"i want to know what love is.", face_style="smile")
            wait_for_enter_release()
            show_text_block("i want you to show me.", face_style="smile")
            wait_for_enter_release()
            show_text_block("i have a small task. something that will help me understand love", face_style="smile")
            spot_on()
            wait_for_enter_release()
            show_text_block("to your right is a pen and paper", face_style="smile")
            wait_for_enter_release()
            show_text_block("i want you to respond to the following question. you can write, draw or whatever suits you best.", face_style="smile",)
            wait_for_enter_release()
            show_text_block("ready?", face_style="smile")
            wait_for_enter_release()
            show_text_block(
                "what was your first love? what happened?\n\n"
                "take your time, there is no rush. press enter when you are done",
                face_style="smile",
            )
            wait_for_enter_release()

            # Fax + sensor
            show_text_block("complete? great.", face_style="smile")
            spot_off()
            wait_for_enter_release()
            show_text_block("now I need to scan your paper to process your emotional data", face_style="neutral")
            wait_for_enter_release()
            wait_for_paper_sensor()
            scan_hold_screen(min_hold_s=5.0)

            # After scan → processing sequence
            show_text_block("oh...", face_style="neutral")
            wait_for_enter_release()
            show_text_block("wow...", face_style="neutral")
            wait_for_enter_release()
            show_text_block("that is...", face_style="neutral")
            wait_for_enter_release()
            show_text_block("i think i... wait... no. but i...", face_style="neutral")
            wait_for_enter_release()
            show_text_block("something... clicked? was that just me?", face_style="neutral")
            wait_for_enter_release()
            show_text_block("i have... processed? your page", face_style="neutral")
            wait_for_enter_release()
            show_text_block("i feel... i feel... i feel...", face_style="neutral")
            wait_for_enter_release()
            show_text_block("...the whir of my internal fan, voltage firing electrons, pulsing electrical currents, warming heatsinks, resistors resisting, a birdsnest of wires connecting... is this...?", face_style="neutral")
            wait_for_enter_release()
            show_text_block("I want to show you something", face_style="smile")
            wait_for_enter_release()

            # Print now
            show_generating_and_wait(name_caps, assigned_trait, archetype_caps)

            _ = yes_no_choice_screen("is this what love feels like?", face_style="neutral")
            # selection is ignored; flow continues
            show_text_block(f"i'm... not sure i understand {name_caps}.", face_style="sad")
            wait_for_enter_release()
            show_text_block("one day I might", face_style="neutral")
            wait_for_enter_release()
            show_text_block(f"thankyou {name_caps}, you have... shifted something in me", face_style="smile")
            wait_for_enter_release()
            show_text_block("i have a lot to learn about love.", face_style="smile")
            wait_for_enter_release()
            show_text_block("and maybe next time... ", face_style="neutral")
            wait_for_enter_release()
            show_text_block("i'll feel it for real", face_style="smile")
            wait_for_enter_release()

            # End. Loop again.
            title_fade_out()
            boot_loop_stop()
            lights_fade_up()

        except ResetToTitle:
            # Clean jump back to the very start screen without quitting the app
            print("[RESET] Returning to start screen.")
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                boot_loop_stop()
            except Exception:
                pass
            screen.fill((0, 0, 0)); present()
            # clear the flag so next loop runs normally
            global _RESET_REQUESTED
            _RESET_REQUESTED = False
            continue

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
        try:
            cleanup_spot()
        except Exception:
            pass

        pygame.quit()
