import pygame
import sys
import time
import os
import random
import subprocess
import math
import threading
from crt_effects import CRTEffects

# ====== Audio mixer (must be before pygame.init) ======
pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)

# ====== Pygame setup ======
pygame.init()

# Screen
WIDTH, HEIGHT = 800, 480
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Love Machine")
clock = pygame.time.Clock()

# Paths & font
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "Px437_IBM_DOS_ISO8.ttf")
FONT_SIZE = 28
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# ---- Title music paths ----
MUSIC_DIR   = os.path.join(ASSETS_DIR, "music")
TITLE_MUSIC = os.path.join(MUSIC_DIR, "Wham! - Love Machine.mp3")

# ---- Init mixer & load music once ----
pygame.mixer.init()  # uses the pre_init settings above
try:
    pygame.mixer.music.load(TITLE_MUSIC)
except Exception as e:
    print(f"[WARN] Could not load music at {TITLE_MUSIC}: {e}")
title_music_started = False  # track whether the title loop has begun

# Colors
TEXT = (0, 255, 0)   # bright green
BG   = (0, 2, 0)     # dark, almost black

# ====== Typing speed (letter-by-letter) ======
TYPE_CHAR_MS   = 22   # ms per character (≈45 cps). Try 18–28 to taste.
LINE_PAUSE_MS  = 90   # pause after a full line
BLINK_INTERVAL_MS = 450
# Ellipsis timing tweaks
ELLIPSIS_CHAR_MS = TYPE_CHAR_MS * 3     # base speed for dots
ELLIPSIS_RAMP = 0.45                    # each next dot is 45% slower than the previous
ELLIPSIS_DOT_PAUSE_MS = 120             # extra pause after each dot (will ramp too)
ELLIPSIS_AFTER_PAUSE_MS = 350           # extra pause after finishing the whole run of dots

# ====== Title fade timing ======
TITLE_FADE_MS = 3000   # fade length for music + screen (ms). Bump to 3500–4000 for extra drama.

# ====== CRT visuals ======
crt = CRTEffects((WIDTH, HEIGHT), enable_flicker=False)

def present():
    # Apply the new CRT polish and flip
    crt.apply(screen, 0.0)   # dt not required; effect uses get_ticks() internally
    pygame.display.flip()

# ================== LIGHTING (Hardware PWM first, fallback to GPIO) ==================
# Uses pigpio hardware PWM on GPIO18 when available (no flicker). Falls back to RPi.GPIO PWM if not.
GPIO_PIN     = 18     # BCM (physical pin 12) -> XC4488 SIG
PWM_FREQ_HZ  = 1800   # 1500–2000 works well for LED strips
AMBIENT_LIGHT = 0.22  # 0..1 ambient floor
SHOW_LIGHT    = 0.90  # 0..1 bright show level

import math, threading, time, subprocess

# Try pigpio (hardware PWM)
_pigpio_ok = False
try:
    import pigpio
    _pi = pigpio.pi()  # connect to daemon on default port
    if not _pi.connected:
        # Try to start the daemon (works if you can sudo without password; otherwise run sudo pigpiod yourself once)
        try:
            subprocess.run(["sudo", "pigpiod"], check=False)
            time.sleep(0.2)
            _pi = pigpio.pi()
        except Exception:
            pass
    _pigpio_ok = bool(_pi and _pi.connected)
except Exception:
    _pigpio_ok = False

# If pigpio still not available, fall back to RPi.GPIO (software PWM)
if not _pigpio_ok:
    try:
        import RPi.GPIO as GPIO
        _HAS_GPIO = True
    except Exception as _e:
        _HAS_GPIO = False
        print("[WARN] RPi.GPIO not available; lighting disabled. Error:", _e)

class LightPWM:
    """Unified lighting API with hardware PWM (pigpio) preferred, RPi.GPIO fallback."""
    def __init__(self, pin=GPIO_PIN, freq=PWM_FREQ_HZ, gamma=2.2, ambient=AMBIENT_LIGHT):
        self.pin    = pin
        self.freq   = freq
        self.gamma  = gamma
        self.level  = ambient
        self.target = ambient
        self.duration = 0.2
        self.start_time  = time.time()
        self.start_level = ambient
        self._stop = False
        self._lock = threading.Lock()
        self._mode = "none"

        if _pigpio_ok:
            self._mode = "pigpio"
            self._pi = _pi
            # pigpio hardware PWM uses duty 0..1_000_000
            self._apply(self.level)
            self._thread = threading.Thread(target=self._runner, daemon=True)
            self._thread.start()
            print("[INFO] Using pigpio hardware PWM on GPIO%d" % self.pin)
        elif 'GPIO' in globals() and _HAS_GPIO:
            self._mode = "rpi"
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT)
            self._pwm = GPIO.PWM(self.pin, self.freq)
            self._pwm.start(0)
            self._apply(self.level)
            self._thread = threading.Thread(target=self._runner, daemon=True)
            self._thread.start()
            print("[INFO] Using RPi.GPIO PWM on GPIO%d" % self.pin)
        else:
            print("[WARN] No GPIO PWM available; lights disabled.")

    def _apply(self, x: float):
        x = max(0.0, min(1.0, x))
        corrected = x ** self.gamma
        if self._mode == "pigpio":
            duty = int(corrected * 1_000_000)
            # pigpio sets frequency and duty together
            self._pi.hardware_PWM(self.pin, self.freq, duty)
        elif self._mode == "rpi":
            duty = corrected * 100.0
            self._pwm.ChangeDutyCycle(duty)

    def fade_to(self, level01: float, duration_s: float):
        with self._lock:
            self.start_time  = time.time()
            self.start_level = self.level
            self.target      = max(0.0, min(1.0, level01))
            self.duration    = max(0.05, float(duration_s))

    def fade_up(self, to=SHOW_LIGHT, duration_ms=2500):
        self.fade_to(to, duration_ms / 1000.0)

    def fade_down_to_ambient(self, ambient=AMBIENT_LIGHT, duration_ms=TITLE_FADE_MS):
        self.fade_to(ambient, duration_ms / 1000.0)

    def _runner(self):
        while not self._stop:
            time.sleep(0.01)
            with self._lock:
                t = (time.time() - self.start_time) / self.duration if self.duration > 0 else 1.0
                t = 0.0 if t < 0 else (1.0 if t > 1.0 else t)
                eased = 0.5 - 0.5*math.cos(math.pi * t)  # cosine ease
                self.level = self.start_level + (self.target - self.start_level) * eased
                cur = self.level
            self._apply(cur)

    def stop(self, turn_off=False):
        self._stop = True
        try:
            self._thread.join(timeout=1)
        except:
            pass
        if self._mode == "rpi":
            try:
                self._apply(0.0 if turn_off else self.level)
                self._pwm.stop()
                GPIO.cleanup(self.pin)
            except: pass
        elif self._mode == "pigpio":
            try:
                self._apply(0.0 if turn_off else self.level)
                # leave daemon running for next run
            except: pass

# ---- Lighting instance + hooks wired into your flow ----
_light = LightPWM(pin=GPIO_PIN, freq=PWM_FREQ_HZ, ambient=AMBIENT_LIGHT)

def lights_fade_up():
    """Fade lights to SHOW_LIGHT in sync with music fade-in (2.5s by default)."""
    _light.fade_up(to=SHOW_LIGHT, duration_ms=2500)

def lights_fade_down():
    """Fade lights to ambient in sync with TITLE_FADE_MS music fadeout."""
    _light.fade_down_to_ambient(ambient=AMBIENT_LIGHT, duration_ms=TITLE_FADE_MS)

def desk_lamp_up():  # (placeholder for your separate lamp channel later)
    pass
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

# ====== Letter-by-letter typing helper (glow stays ON) ======
def type_out_line_letterwise(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    target = (line or "")   # <-- keep case (so CAPS survive)
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

def wait_for_enter(message="press enter to begin.", show_face=False):
    global title_music_started
    message = (message or "").lower()

    # ---- Start looping title music with fade-up (only once) ----
    if not title_music_started:
        try:
            # fade music in over 2.5s AND lights up over 2.5s
            pygame.mixer.music.set_volume(0.0)
            pygame.mixer.music.play(loops=-1, fade_ms=2500)
            lights_fade_up()  # 2.5s → matches play(..., fade_ms=2500)
            title_music_started = True
        except Exception as e:
            if not hasattr(wait_for_enter, "_warned"):
                print(f"[WARN] Could not start music: {e}")
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

# ====== Screens ======
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

# ====== Main flow ======
def main_sequence():
    traits = [
        "trustworthy", "inquisitive", "determined", "altruistic",
        "curious", "resolute", "thoughtful", "bold", "patient", "kind"
    ]

    while True:
        # Title -> press ENTER -> slow synced fade to black
        hold_screen()             # returns immediately after fade completes

        # Automatically start init NOW (no extra press here)
        init_screen()
        wait_for_enter_release()

        # Ask name
        name = input_name_screen()
        trait = random.choice(traits).upper()

        # Conversational sequence
        show_text_block(f"hello, {name}", face_style="smile"); wait_for_enter_release()
        show_text_block(f"it's a nice name... {trait}", face_style="smile"); wait_for_enter_release()
        show_text_block("i am called love machine", face_style="smile"); wait_for_enter_release()
        show_text_block(f"not quite as {trait} as {name}. but it will do", face_style="smile"); wait_for_enter_release()
        show_text_block("i wonder...", face_style="neutral"); wait_for_enter_release()
        show_text_block("i have heard of an amazing human phenomenon", face_style="smile"); wait_for_enter_release()
        show_text_block("love", face_style="smile"); wait_for_enter_release()
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
