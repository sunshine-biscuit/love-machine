import pygame
import sys
import time
import os
import random

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
FONT_SIZE = 26
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# Colors
TEXT = (0, 255, 0)   # bright neon green
BG   = (0, 2, 0)     # dark, almost black

# ====== Typing speed (time‑based) ======
TYPE_CPS = 110        # characters per second on Pi (try 90–140)
LINE_PAUSE_MS = 60

# ====== Pi speed config ======
PI_FAST = True
TYPE_CHAR_MS       = 6 if PI_FAST else 10
POST_LINE_PAUSE_MS = 60
BLINK_INTERVAL_MS  = 450

# CRT effect costs
CRT_ENABLE_GLOW       = True     # glow on
CRT_GLOW_EVERY_N      = 1        # recompute every frame to avoid trails
CRT_BRIGHTNESS_BOOST  = 12       # slightly lower boost (reduces smear look)
SCANLINE_ALPHA        = 20       # a touch lighter scanlines
VIGNETTE_STRENGTH     = 0.10     # lighter vignette = crisper text edges

# ====== CRT pipeline / effects ======
class CRTPipeline:
    def __init__(self, size, palette="green"):
        self.w, self.h = size
        self.fx = pygame.Surface(size).convert_alpha()
        # Prebuilt overlays
        self.scan = self._make_scanlines(alpha=SCANLINE_ALPHA)
        self.vign = self._make_vignette(strength=VIGNETTE_STRENGTH) if VIGNETTE_STRENGTH > 0 else None
        self.mask = None
        self.brightness_boost = CRT_BRIGHTNESS_BOOST

        # Glow toggle
        self.enable_glow = CRT_ENABLE_GLOW
        self.frame = 0

        self.palette = {"green": ((0,255,102), (6,18,8)),
                        "amber": ((255,176,0), (20,12,6))}.get(palette, ((0,255,102),(6,18,8)))

    def _make_scanlines(self, alpha=36):
        s = pygame.Surface((self.w, self.h), flags=pygame.SRCALPHA)
        dark = (0,0,0,alpha)
        for y in range(0, self.h, 2):
            s.fill(dark, (0, y, self.w, 1))
        return s

    def _make_vignette(self, strength=0.24):
        s = pygame.Surface((self.w, self.h), flags=pygame.SRCALPHA)
        cx, cy = self.w/2, self.h/2
        maxd = (cx**2 + cy**2) ** 0.5
        arr = pygame.PixelArray(s)
        for y in range(self.h):
            for x in range(self.w):
                d = ((x-cx)**2 + (y-cy)**2) ** 0.5 / maxd
                a = int(255 * (d**1.8) * strength)
                arr[x, y] = (0<<24) | (0<<16) | (0<<8) | a
        del arr
        return s

    def _blur(self, surf, passes=1):
        # Cheaper than smoothscale on the Pi
        tmp = surf
        for _ in range(passes):
            small = pygame.transform.scale(tmp, (max(1, self.w//2), max(1, self.h//2)))
            tmp = pygame.transform.scale(small, (self.w, self.h))
        return tmp

    def compose(self, source_surface):
        # Work on a clean target each call
        self.fx.fill((0,0,0,0))
        self.fx.blit(source_surface, (0,0))

        # Glow with no cache = no ghosting
        if self.enable_glow:
            glow = self._blur(source_surface, passes=1)  # fast scale down/up
            glow.set_alpha(56)                           # 48–64 is a good range
            self.fx.blit(glow, (0,0), special_flags=pygame.BLEND_ADD)

        # Scanlines
        if self.scan:
            self.fx.blit(self.scan, (0,0))

        # Vignette
        if self.vign:
            self.fx.blit(self.vign, (0,0))

        # Global brightness boost
        if self.brightness_boost:
            lift = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            lift.fill((self.brightness_boost, self.brightness_boost, self.brightness_boost, 0))
            self.fx.blit(lift, (0,0), special_flags=pygame.BLEND_ADD)

        self.frame += 1
        return self.fx

crt = CRTPipeline((WIDTH, HEIGHT), palette="green")

def present():
    final = crt.compose(screen)
    # We already drew into `screen`; `compose` built `final` on top of that snapshot.
    screen.blit(final, (0,0))
    pygame.display.flip()

# ====== Lighting hooks ======
def lights_fade_up(): pass
def lights_fade_down(): pass
def desk_lamp_up(): pass

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

# ====== Time-based typing helpers ======
def _pump_basic_events():
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit(); sys.exit()

def type_out_line(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    """Time-based typewriter so speed is consistent even if FPS dips."""
    target = (line or "").lower()
    shown = 0
    accum = 0.0
    while shown < len(target):
        dt = clock.tick(60) / 1000.0
        accum += TYPE_CPS * dt
        add = int(accum)
        if add > 0:
            shown = min(len(target), shown + add)
            accum -= add

        _pump_basic_events()
        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)
        # draw previous full lines
        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        # draw current partial
        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines)*line_spacing))
        present()

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
    message = (message or "").lower()
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
                return

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)

# ====== Face rendering (two vertical eyes, straight mouth w/ upturned ends) ======
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

    # blink scheduler
    if not _is_blinking and t - _last_blink > blink_on_interval:
        _is_blinking = True
        _last_blink = t
    if _is_blinking and t - _last_blink > blink_off_duration:
        _is_blinking = False
        _last_blink = t

    pattern = faces["blink"] if _is_blinking else faces.get(style, faces["smile"])

    face_w = len(pattern[0]) * block
    x0 = (WIDTH - face_w) // 2
    y0 = 20  # adjust if you want it higher/lower

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

# ====== Screens ======
def hold_screen():
    lights_fade_up()
    wait_for_enter("press enter to begin.", show_face=False)

def init_screen():
    lights_fade_down()
    lines = [
        "initialising...",
        "booting love machine v1.0...",
        "calibrating empathy modules...",
        "system ready."
    ]
    x = 50
    base_y = 120
    line_spacing = 36

    # time-based typing for each line
    typed = []
    for line in lines:
        type_out_line(line, typed, x, base_y, line_spacing, draw_face_style=None)
        typed.append(line.lower())

    # blink & wait for ENTER
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
        for i in range(len(typed)):
            s = font.render(typed[i], True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, base_y + (len(typed)-1)*line_spacing + 5, 10, 20))
        present()
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)

def input_name_screen():
    name = ""
    instructions = "what is your name?"
    blink = True; last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        # prompt
        prompt_lines = wrap_text_to_width(instructions.lower(), WIDTH - 100)
        base_y = HEIGHT - 240
        for i, line in enumerate(prompt_lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (50, base_y + i*32))
        # input line (always lowercase)
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
                    return (name.strip() or "friend")
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    return "friend"
                else:
                    ch = event.unicode
                    if ch:
                        ch = ch.lower()
                        if 32 <= ord(ch) <= 126 and len(name) < 20:
                            name += ch
        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)

def show_text_block(text, face_style="smile", glitch=False):
    x = 50
    base_y = HEIGHT - 180
    line_spacing = 32

    # lowercase and wrap
    lines = []
    for para in (text or "").lower().split("\n"):
        lines.extend(wrap_text_to_width(para, WIDTH - 100))
    if not lines:
        lines = [""]

    # time-based typewriter for each line
    typed = []
    for line in lines:
        type_out_line(line, typed, x, base_y, line_spacing, draw_face_style=face_style, glitch=glitch)
        typed.append(line)

    # wait for ENTER with blinking cursor only
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
    # render text lines for cursor placement (lowercase)
    lines = wrap_text_to_width((text or "").lower(), WIDTH - 100) if (text or "").strip() else [""]
    x = 50
    base_y = HEIGHT - 160
    line_spacing = 32
    last_line_w = font.size(lines[-1])[0]

    # short animated glitch phase (no prompt)
    start = pygame.time.get_ticks()
    duration = 1500
    while pygame.time.get_ticks() - start < duration:
        screen.fill(BG); draw_face("smile", glitch=True)
        for i, line in enumerate(lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        present()
        clock.tick(60)

    # then wait for ENTER with blinking cursor only
    blink = True
    last = pygame.time.get_ticks()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        screen.fill(BG); draw_face("smile", glitch=False)
        for i, line in enumerate(lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(
                screen, TEXT,
                (x + last_line_w + 6, base_y + (len(lines)-1)*line_spacing + 5, 10, 20)
            )
        present()

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink
            last = pygame.time.get_ticks()

        clock.tick(60)

# ====== Transitions ======
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
        # Holding screen (lights up)
        hold_screen()
        wait_for_enter_release()

        # Initialising (lights down later when integrating)
        init_screen()
        wait_for_enter_release()

        # Ask name
        name = input_name_screen()
        trait = random.choice(traits)

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
        show_text_block("what was your first love? what happened? take your time, there is no rush. press enter when you are done."); wait_for_enter_release()
        show_text_block("all finished? great", face_style="smile"); wait_for_enter_release()
        show_text_block("now feed the paper, face up into the slot on your left and press enter.", face_style="smile"); wait_for_enter_release()

        # Processing + glitch
        glitch_face_moment("... oh.... that is.... very moving.. i had no idea..")
        wait_for_enter_release()

        show_text_block("thank you for sharing that with me. i have processed this and have something for you... a gift.", face_style="smile"); wait_for_enter_release()
        show_text_block("would you like to see your first love?", face_style="smile"); wait_for_enter_release()
        glitch_face_moment(" ")
        wait_for_enter_release()

        show_text_block(f"thank you {name}", face_style="smile"); wait_for_enter_release()
        show_text_block("take care.", face_style="smile"); wait_for_enter_release()

        # Fade / reset
        fade_to_black()
        lights_fade_up()
        # loop back to holding screen

if __name__ == "__main__":
    try:
        main_sequence()
    finally:
        pygame.quit()
