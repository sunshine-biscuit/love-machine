# ====== Imports (order matters for audio) ======
import os, sys, time, random, subprocess, math, threading

# Force PulseAudio on Pi OS (PipeWire) BEFORE importing pygame
os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")

import pygame
from crt_effects import CRTEffects

# Pi pin setup before pygame init
subprocess.run(["sudo","/usr/local/bin/pinctrl","set","12","a0"], check=False)

from pwm_helper import init_pwm, set_brightness
init_pwm()                   # start hardware PWM
set_brightness(0.22)         # force ambient immediately (0.22 = 22%)

from quiz_data import QUESTIONS, CATEGORY_BLURBS


# ====== Audio: robust initialisation ======
def _init_audio(retries=5, delay=0.4):
    # pre_init must be before pygame.init()
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


# ====== Screen ======
WIDTH, HEIGHT = 800, 480
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Love Machine")
clock = pygame.time.Clock()

# ====== Paths & font ======
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH  = os.path.join(ASSETS_DIR, "Px437_IBM_DOS_ISO8.ttf")
FONT_SIZE  = 28
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# ====== Music (Title track: Foreigner) ======
MUSIC_DIR = os.path.join(ASSETS_DIR, "music")
_AUDIO_EXTS = (".wav", ".ogg", ".mp3", ".flac")

# Put YOUR converted filename(s) here, in priority order.
# If you created only one, keep just that line.
_TITLE_CANDIDATES = [
    "Foreigner - know what love is.ogg",          # <-- converted OGG (recommended)
    "Foreigner - know what love is (PCM).wav",    # <-- if you made a PCM WAV
    "Foreigner - know what love is.wav",          # <-- original (kept as last fallback)
]

def _find_title_track():
    # 1) exact filenames (in the order above)
    for name in _TITLE_CANDIDATES:
        p = os.path.join(MUSIC_DIR, name)
        if os.path.isfile(p):
            return p
    # 2) fuzzy match (case-insensitive) e.g. if you renamed slightly
    try:
        for fname in os.listdir(MUSIC_DIR):
            low = fname.lower()
            if low.endswith(_AUDIO_EXTS) and ("foreigner" in low) and ("know what love is" in low):
                return os.path.join(MUSIC_DIR, fname)
    except FileNotFoundError:
        pass
    # 3) any audio file in the folder (last resort)
    try:
        for fname in sorted(os.listdir(MUSIC_DIR)):
            if fname.lower().endswith(_AUDIO_EXTS):
                return os.path.join(MUSIC_DIR, fname)
    except FileNotFoundError:
        pass
    return None

TITLE_MUSIC = _find_title_track()

def _load_title_music():
    """Load the Foreigner title track; use OGG/PCM WAV to avoid codec issues."""
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


# ====== Colours & typing ======
TEXT = (0, 255, 0)   # bright green
BG   = (0, 2, 0)     # dark, almost black

TYPE_CHAR_MS   = 22
LINE_PAUSE_MS  = 90
BLINK_INTERVAL_MS = 450
ELLIPSIS_CHAR_MS = TYPE_CHAR_MS * 3
ELLIPSIS_RAMP = 0.45
ELLIPSIS_DOT_PAUSE_MS = 120
ELLIPSIS_AFTER_PAUSE_MS = 350

# ====== Title fade timing ======
TITLE_FADE_MS = 3000

# ====== CRT visuals ======
crt = CRTEffects((WIDTH, HEIGHT), enable_flicker=False)
def present():
    crt.apply(screen, 0.0)
    pygame.display.flip()


# ==== Quiz stats persistence ====
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(PROJECT_ROOT, "data")
STATS_PATH   = os.path.join(DATA_DIR, "stats_quiz.json")

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
    """Increment count for `chosen_category` and return (percent_int, counts_dict, total)."""
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
SHOW_LIGHT    = 0.90

class LightPWM:
    def __init__(self, ambient=AMBIENT_LIGHT):
        self.level       = ambient
        self.target      = ambient
        self.duration    = 0.2
        self.start_time  = time.time()
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
            self.start_time  = time.time()
            self.start_level = self.level
            self.target      = 0.0 if level01 < 0 else (1.0 if level01 > 1.0 else level01)
            self.duration    = 0.05 if duration_s < 0.05 else float(duration_s)

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
        try: self._thread.join(timeout=1)
        except: pass
        try: self._apply(0.0 if turn_off else self.level)
        except: pass

_light = LightPWM(ambient=AMBIENT_LIGHT)

def lights_fade_up():
    _light.fade_up(to=SHOW_LIGHT, duration_ms=2500)

def lights_fade_down():
    _light.fade_down_to_ambient(ambient=AMBIENT_LIGHT, duration_ms=TITLE_FADE_MS)
# =======================================================================


# ====== Utility timing ======
def soft_wait(ms):
    end = pygame.time.get_ticks() + ms
    while pygame.time.get_ticks() < end:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
        clock.tick(240)

def wait_for_enter_release():
    released = False
    while not released:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYUP and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                released = True
        clock.tick(60)


# ====== Letter-by-letter typing helpers ======
def type_out_line_letterwise(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    target = (line or "")   # keep case
    shown = 0
    timer_ms = 0.0

    while shown < len(target):
        dt = clock.tick(60) / 1000.0
        timer_ms += dt * 1000.0

        if timer_ms >= TYPE_CHAR_MS:
            timer_ms -= TYPE_CHAR_MS
            shown += 1

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)

        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))

        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines)*line_spacing))

        present()

    soft_wait(LINE_PAUSE_MS)

def type_out_line_letterwise_thoughtful(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    target = (line or "")
    shown = 0
    timer_ms = 0.0
    ellipsis_pause_ms = 0
    ellipsis_after_run = False

    while shown < len(target):
        if target[shown] == '.':
            j = shown
            while j > 0 and target[j-1] == '.':
                j -= 1
            k = shown
            while k < len(target) and target[k] == '.':
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

            if just_revealed_char == '.':
                idx = shown - 1
                j = idx
                while j > 0 and target[j-1] == '.':
                    j -= 1
                k = idx + 1
                while k < len(target) and target[k] == '.':
                    k += 1
                run_len = k - j
                if run_len >= 3:
                    pos_in_run = idx - j
                    ramp = (1.0 + ELLIPSIS_RAMP * pos_in_run)
                    ellipsis_pause_ms = int(ELLIPSIS_DOT_PAUSE_MS * ramp)
                    ellipsis_after_run = (idx + 1 == k)
                else:
                    ellipsis_pause_ms = 0
                    ellipsis_after_run = False
            else:
                ellipsis_pause_ms = 0
                ellipsis_after_run = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

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
        test = (current + (" " if current else "") + w)
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


# ====== Title/hold & boot screens ======
def wait_for_enter(message="press enter to begin.", show_face=False):
    global title_music_started
    message = (message or "").lower()

    # ---- Start looping title music with fade-up (only once) ----
    if not title_music_started:
        try:
            if not pygame.mixer.get_init():
                _init_audio()
            # If music failed to load at startup (e.g., codec), try again now
            if not _music_ready:
                if not _load_title_music():
                    raise RuntimeError("Startup music not available (see earlier error).")

            pygame.mixer.music.set_volume(0.9)   # set target volume first
            pygame.mixer.music.play(loops=-1, fade_ms=2500)  # fade from 0 → 0.9
            lights_fade_up()  # match fade
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
            pygame.draw.rect(screen, TEXT, (50 + w + 6, base_y + (len(lines)-1)*32 + 5, 10, 20))
        present()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                # Fade music + lights + screen together
                try:
                    pygame.mixer.music.fadeout(TITLE_FADE_MS)
                except Exception:
                    pass
                lights_fade_down()  # sync lights to same duration
                title_fade_out()    # visual fade matches duration
                title_music_started = False
                return

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)

def hold_screen():
    # Title screen with music
    lights_fade_up()
    wait_for_enter("press enter to begin.", show_face=False)

def init_screen():
    BOOT_FONT_SIZE = 20
    CHAR_MS        = 8
    GAP_MS         = 20
    TOP_MARGIN     = 60
    BOTTOM_MARGIN  = 40
    LEFT_MARGIN    = 28
    LINE_GAP       = 4

    boot_font = pygame.font.Font(FONT_PATH, BOOT_FONT_SIZE)
    line_h    = boot_font.get_linesize() + LINE_GAP

    messages = [
        "Initialising system v1.0.3",
        "Loading kernel modules v1.14.2",
        "Detecting hardware bus v0.7.1",
        "Mounting /dev/love v0.9.0   [OK]",
        "Starting empathy-services v2.3.1",
        "Calibrating affective-heuristics v0.8.7",
        "Checking secure sockets v1.2.0   [OK]",
        "Entropy pool seeded v3.2",
        "Boot sequence complete v1.0   [OK]",
        "System ready.",
    ]

    view_h = HEIGHT - TOP_MARGIN - BOTTOM_MARGIN
    log_h = max(view_h, len(messages) * line_h + 40)
    log_surface = pygame.Surface((WIDTH, log_h)).convert()
    log_surface.fill(BG)

    next_y = 0

    overlay = pygame.Surface((WIDTH, HEIGHT))
    overlay.fill((0, 0, 0))
    for alpha in range(255, -1, -30):
        screen.fill(BG)
        overlay.set_alpha(alpha)
        screen.blit(overlay, (0, 0))
        present()
        soft_wait(15)

    for msg in messages:
        partial = ""
        char_timer = 0.0
        while len(partial) < len(msg):
            dt = clock.tick(60) / 1000.0
            char_timer += dt * 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()

            if char_timer >= CHAR_MS:
                char_timer -= CHAR_MS
                partial += msg[len(partial)]

                log_surface.fill(BG, (0, next_y, WIDTH, line_h))
                s = boot_font.render(partial, True, TEXT)
                log_surface.blit(s, (LEFT_MARGIN, next_y))

                bottom_needed = next_y + line_h
                scroll = max(0, bottom_needed - view_h)
                screen.fill(BG)
                screen.blit(log_surface, (0, TOP_MARGIN),
                            area=pygame.Rect(0, scroll, WIDTH, view_h))
                present()

        next_y += line_h
        soft_wait(GAP_MS)

    last_text = messages[-1]
    last_w = boot_font.size(last_text)[0]
    cursor_x = LEFT_MARGIN + last_w + 6
    cursor_y_log = next_y - line_h + 4

    blink = True
    last_tick = pygame.time.get_ticks()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        bottom_needed = next_y
        scroll = max(0, bottom_needed - view_h)
        screen.fill(BG)
        screen.blit(log_surface, (0, TOP_MARGIN),
                    area=pygame.Rect(0, scroll, WIDTH, view_h))

        if blink:
            cy = cursor_y_log - scroll + TOP_MARGIN
            pygame.draw.rect(screen, TEXT, (cursor_x, cy, 10, 18))

        present()
        if pygame.time.get_ticks() - last_tick > BLINK_INTERVAL_MS:
            blink = not blink
            last_tick = pygame.time.get_ticks()
        clock.tick(60)


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
        type_out_line_letterwise(ln, typed_prompt, x, prompt_base_y, line_spacing,
                                 draw_face_style=None)
        typed_prompt.append(ln)

    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        for i, line in enumerate(typed_prompt):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, prompt_base_y + i*line_spacing))

        s = font.render(name, True, TEXT)
        screen.blit(s, (50, HEIGHT - 160))
        if blink:
            pygame.draw.rect(screen, TEXT, (50 + s.get_width() + 6, HEIGHT - 155, 10, 20))
        present()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
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
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)


# ====== Text blocks (normal & glitch moment) ======
def show_text_block(text, face_style="smile", glitch=False):
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
        type_out_line_letterwise(line, typed, x, base_y, line_spacing,
                                 draw_face_style=face_style, glitch=glitch)
        typed.append(line)

    blink = True
    last = pygame.time.get_ticks()
    last_line_w = font.size(typed[-1])[0]
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return
        screen.fill(BG)
        if face_style:
            draw_face(face_style, glitch=glitch)
        for i, line in enumerate(typed):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, base_y + (len(typed)-1)*line_spacing + 5, 10, 20))
        present()
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink; last = pygame.time.get_ticks()
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
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        screen.fill(BG); draw_face("smile", glitch=False)
        for i, line in enumerate(typed):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, base_y + (len(typed)-1)*line_spacing + 5, 10, 20))
        present()

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()

        clock.tick(60)


# ====== Transitions ======
def title_fade_out():
    """Fade the current screen to black over TITLE_FADE_MS and start lights fading down."""
    lights_fade_down()  # trigger lighting fade now

    overlay = pygame.Surface((WIDTH, HEIGHT))
    overlay.fill((0, 0, 0))

    start = pygame.time.get_ticks()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        elapsed = pygame.time.get_ticks() - start
        t = min(1.0, elapsed / max(1, TITLE_FADE_MS))   # 0 → 1 over duration
        overlay.set_alpha(int(255 * t))

        screen.blit(overlay, (0, 0))
        present()

        if t >= 1.0:
            break
        clock.tick(60)

    screen.fill((0, 0, 0))
    present()

def fade_to_black():
    fade = pygame.Surface((WIDTH, HEIGHT)); fade.fill((0,0,0))
    for a in range(0, 255, 10):
        screen.blit(fade, (0,0))
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
        "0000111111110000",
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
        "0000111111110000",
        "0000000000000000",
        "0000000000000000",
    ],
}

blink_on_interval = 5000
blink_off_duration = 400
_last_blink = pygame.time.get_ticks()
_is_blinking = False

def draw_face(style="smile", block=13, glitch=False):
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
    y0 = 20

    for r, row in enumerate(pattern):
        for c, ch in enumerate(row):
            if ch == '1':
                dx = dy = 0
                if glitch and random.random() < 0.02:
                    dx = random.choice((-1,0,1))
                    dy = random.choice((-1,0,1))
                pygame.draw.rect(
                    screen, TEXT,
                    (x0 + c * block + dx, y0 + r * block + dy, block, block)
                )


# ====== Minimal blank print screen ======
def show_mostly_blank_status(message="generating your first love..."):
    screen.fill(BG)
    status = message or ""
    if status:
        s = font.render(status, True, TEXT)
        screen.blit(s, (24, HEIGHT - 40))
    present()


# ====== External print trigger helper ======
def run_print_script(participant_name, assigned_trait):
    script_path = os.path.join(os.path.dirname(__file__), "print_random_art.py")
    try:
        subprocess.run(
            ["python3", script_path, "--name", str(participant_name), "--trait", str(assigned_trait)],
            check=True
        )
    except Exception as e:
        print(f"[ERROR] Print script failed: {e}")


# ====== QUIZ (Love Machine-styled) ======
def run_quiz_lm_style(screen, clock, font, participant_name=None):
    """
    Love Machine-styled 3-question quiz with persistent stats.
    - Face + green theme
    - Types prompt + all options on the SAME slide
    - ↑/↓ to select, ENTER to confirm
    - Persists counts to data/stats_quiz.json
    - Shows reveal + percentage screens
    - Returns (CATEGORY_UPPER, blurb, percent_int)
    """
    # --- helpers ---
    def score_from_weights(chosen_weight_maps):
        from collections import defaultdict
        totals = defaultdict(int)
        for m in chosen_weight_maps:
            for k, v in m.items():
                totals[k] += v
        if not totals:
            return "REALIST"
        return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def draw_frame(lines, highlight_idx=None, options_start_idx=None, hint_text=None, face_style="smile"):
        screen.fill(BG)
        if face_style:
            draw_face(face_style, glitch=False)

        base_x = 50
        base_y = HEIGHT - 200
        line_spacing = 32

        for i, ln in enumerate(lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (base_x, base_y + i*line_spacing))

        # selector arrow
        if highlight_idx is not None and options_start_idx is not None:
            rel = highlight_idx - options_start_idx
            arrow_y = base_y + (options_start_idx + rel)*line_spacing
            pygame.draw.polygon(
                screen, TEXT,
                [(base_x-18, arrow_y+6), (base_x-6, arrow_y+12), (base_x-18, arrow_y+18)]
            )

        if hint_text:
            s = font.render(hint_text, True, TEXT)
            screen.blit(s, (24, HEIGHT - 40))

        present()

    # --- quiz flow ---
    chosen_weights = []
    labels = ["A) ", "B) ", "C) "]

    for q in QUESTIONS:
        # Build lines: prompt (wrapped) + A/B/C (short; wrap later if needed)
        prompt_lines = wrap_text_to_width(q["prompt"], WIDTH - 100)
        option_texts = [f"{labels[i]}{q['options'][i][0]}" for i in range(3)]
        option_lines = option_texts

        # Type everything onto the same slide (accumulating)
        drawn_lines = []
        x = 50
        base_y = HEIGHT - 200
        line_spacing = 32

        for line in prompt_lines:
            type_out_line_letterwise(line, drawn_lines, x, base_y, line_spacing,
                                     draw_face_style="smile", glitch=False)
            drawn_lines.append(line)

        for opt_line in option_lines:
            type_out_line_letterwise(opt_line, drawn_lines, x, base_y, line_spacing,
                                     draw_face_style="smile", glitch=False)
            drawn_lines.append(opt_line)

        all_lines = drawn_lines[:]  # prompt + options on screen
        options_start_idx = len(prompt_lines)

        # Selection loop
        selected = 0
        hint = "use ↑/↓ to select • press ENTER"
        selecting = True
        while selecting:
            draw_frame(
                lines=all_lines,
                highlight_idx=options_start_idx + selected,
                options_start_idx=options_start_idx,
                hint_text=hint,
                face_style="smile"
            )
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_UP, pygame.K_w):
                        selected = (selected - 1) % 3
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        selected = (selected + 1) % 3
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        selecting = False
            clock.tick(60)

        # Save the weights for the chosen answer
        chosen_weights.append(q["options"][selected][1])
        soft_wait(120)

    # Compute result
    category = score_from_weights(chosen_weights)
    blurb = CATEGORY_BLURBS.get(category, "")

    # Persist + compute percentage
    pct, counts_snapshot, _total = _tally_category_count(category)

    # 1) Reveal line (wrapped + typed)
    reveal = f"oh... that's very interesting.. you're a {category} then."
    wrapped_reveal = wrap_text_to_width(reveal, WIDTH - 100)
    drawn = []
    x = 50
    base_y = HEIGHT - 200
    line_spacing = 32
    for ln in wrapped_reveal:
        type_out_line_letterwise_thoughtful(ln, drawn, x, base_y, line_spacing,
                                            draw_face_style="smile", glitch=False)
        drawn.append(ln)
    wait_for_enter_release()

    # 2) Percentage line (wrapped + typed)
    perc_line = f"it's funny, i've conversed with a few people now and {pct}% of people are also {category}s"
    wrapped_perc = wrap_text_to_width(perc_line, WIDTH - 100)
    drawn = []
    for ln in wrapped_perc:
        type_out_line_letterwise_thoughtful(ln, drawn, x, base_y, line_spacing,
                                            draw_face_style="smile", glitch=False)
        drawn.append(ln)
    wait_for_enter_release()

    return category.upper(), blurb, pct


# ====== Main flow ======
def main_sequence():
    while True:
        # Title -> press ENTER -> slow synced fade to black
        hold_screen()             # returns after fade completes

        # Automatically start init NOW (no extra press here)
        init_screen()
        wait_for_enter_release()

        # Ask name
        name = input_name_screen()

        # Conversational sequence (pre-quiz)
        show_text_block(f"hello, {name}", face_style="smile"); wait_for_enter_release()
        show_text_block("i am called love machine", face_style="smile"); wait_for_enter_release()
        show_text_block("i wonder...", face_style="neutral"); wait_for_enter_release()
        show_text_block("i have heard of an amazing human phenomenon", face_style="smile"); wait_for_enter_release()
        show_text_block("love", face_style="smile"); wait_for_enter_release()

        # ====== QUIZ (ambient lighting only; same look & typing) ======
        trait, blurb, pct = run_quiz_lm_style(screen, clock, font, participant_name=name)
        os.environ["LM_PRINT_HEADER"]      = f"{name} — {trait}"
        os.environ["LM_PRINT_TRAIT"]       = trait
        os.environ["LM_PRINT_TRAIT_BLURB"] = blurb or ""
        os.environ["LM_PRINT_TRAIT_PCT"]   = str(pct)

        # Post-quiz trait-based dialogue (now uses the archetype)
        show_text_block(f"it's a nice name... {trait}", face_style="smile"); wait_for_enter_release()
        show_text_block(f"not quite as {trait} as {name}. but it will do", face_style="smile"); wait_for_enter_release()

        # Writing task sequence
        show_text_block("i would like to know what love is", face_style="smile"); wait_for_enter_release()
        show_text_block("i want you to show me", face_style="smile"); wait_for_enter_release()
        show_text_block("to your right is a pen and paper", face_style="smile"); wait_for_enter_release()
        # desk_lamp_up()  # later when GPIO added
        show_text_block("i want you to respond to the following question. you can write, draw or whatever suits you best.", face_style="smile"); wait_for_enter_release()
        show_text_block("ready?", face_style="smile"); wait_for_enter_release()
        show_text_block("What was your first love? What happened?\nTake your time, there is no rush. Press enter when you are done"); wait_for_enter_release()
        show_text_block("all finished? great", face_style="smile"); wait_for_enter_release()
        show_text_block("now feed the paper, face up into the slot on your left and press enter.", face_style="smile"); wait_for_enter_release()

        glitch_face_moment("... oh... that is... very moving... i had no idea...")
        wait_for_enter_release()

        show_text_block("thank you for sharing that with me. i have processed this and have something for you... a gift.", face_style="smile"); wait_for_enter_release()
        show_text_block("would you like to see your first love?", face_style="smile"); wait_for_enter_release()

        # ======= PRINT MOMENT =======
        show_mostly_blank_status("generating your first love...")
        run_print_script(name, trait)

        glitch_face_moment(" ")
        wait_for_enter_release()

        show_text_block(f"thank you {name}", face_style="smile"); wait_for_enter_release()
        show_text_block("take care.", face_style="smile"); wait_for_enter_release()

        # Fade / reset
        fade_to_black()
        lights_fade_up()  # bring ambience back for title loop


if __name__ == "__main__":
    try:
        main_sequence()
    finally:
        try:
            pygame.mixer.music.fadeout(1500)
        except: pass
        # stop lighting PWM cleanly (leave ambient on exit? set turn_off=True to go dark)
        try:
            _light.stop(turn_off=False)
        except: pass
        pygame.quit()
