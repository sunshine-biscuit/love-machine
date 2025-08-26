import pygame
import sys
import time
import os
import random
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

# ====== Letter-by-letter typing helper (glow stays ON) ======
def type_out_line_letterwise(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    """
    Emits EXACTLY one character per timer tick based on TYPE_CHAR_MS.
    Glow stays enabled for your CRT look.
    """
    target = (line or "")   # <-- keep case (so CAPS survive)
    shown = 0
    timer_ms = 0.0

    while shown < len(target):
        dt = clock.tick(60) / 1000.0
        timer_ms += dt * 1000.0

        # Only reveal ONE character when timer reaches threshold
        if timer_ms >= TYPE_CHAR_MS:
            timer_ms -= TYPE_CHAR_MS
            shown += 1

        # events + draw
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)

        # previous full lines
        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))

        # current partial
        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines)*line_spacing))

        present()

    soft_wait(LINE_PAUSE_MS)

def type_out_line_letterwise_thoughtful(line, drawn_lines, x, base_y, line_spacing, draw_face_style="smile", glitch=False):
    """
    Types a line letter-by-letter, slowing and pausing on ellipses (`...`).
    Each successive dot in the same run takes longer than the previous one.
    Keeps ORIGINAL casing.
    """
    target = (line or "")
    shown = 0
    timer_ms = 0.0

    # pending pauses applied after we draw the current frame
    ellipsis_pause_ms = 0
    ellipsis_after_run = False

    while shown < len(target):
        # Determine per-char threshold
        if target[shown] == '.':
            # compute the full dot run [j, k)
            j = shown
            while j > 0 and target[j-1] == '.':
                j -= 1
            k = shown
            while k < len(target) and target[k] == '.':
                k += 1
            run_len = k - j
            # only treat as ellipsis if 3+ dots
            if run_len >= 3:
                # position within the run for the dot we are ABOUT to reveal (0-based)
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
            # reveal exactly one character
            just_revealed_char = target[shown]
            shown += 1

            # If we just revealed a dot, schedule pauses that ramp too
            if just_revealed_char == '.':
                # recompute run and position for the char we JUST revealed (index shown-1)
                idx = shown - 1
                j = idx
                while j > 0 and target[j-1] == '.':
                    j -= 1
                k = idx + 1
                while k < len(target) and target[k] == '.':
                    k += 1
                run_len = k - j
                if run_len >= 3:
                    pos_in_run = idx - j  # 0,1,2,...
                    ramp = (1.0 + ELLIPSIS_RAMP * pos_in_run)
                    ellipsis_pause_ms = int(ELLIPSIS_DOT_PAUSE_MS * ramp)
                    ellipsis_after_run = (idx + 1 == k)  # we just typed the last dot in the run
                else:
                    ellipsis_pause_ms = 0
                    ellipsis_after_run = False
            else:
                ellipsis_pause_ms = 0
                ellipsis_after_run = False

        # events + draw
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        screen.fill(BG)
        if draw_face_style:
            draw_face(draw_face_style, glitch=glitch)

        # previously completed lines
        for i, ln in enumerate(drawn_lines):
            s = font.render(ln, True, TEXT)
            screen.blit(s, (x, base_y + i * line_spacing))

        # current partial
        s = font.render(target[:shown], True, TEXT)
        screen.blit(s, (x, base_y + len(drawn_lines) * line_spacing))

        present()

        # Apply the scheduled pauses after drawing this frame
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
    global title_music_started  # music control
    message = (message or "").lower()

    # ---- Start looping title music with fade-up (only once) ----
    if not title_music_started:
        try:
            pygame.mixer.music.play(loops=-1, fade_ms=2500)  # fade in ~2.5s
            pygame.mixer.music.set_volume(1.0)               # 0.0–1.0
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
                # Fade music + screen together, dramatically
                try:
                    pygame.mixer.music.fadeout(TITLE_FADE_MS)
                except Exception:
                    pass
                title_fade_out()            # visual fade matches the same duration
                title_music_started = False
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
    # Title screen with music
    lights_fade_up()
    wait_for_enter("press enter to begin.", show_face=False)
    # After wait_for_enter returns, we've faded to black and are ready for init.

def init_screen():
    """
    Terminal-style boot log:
      - smaller font just for this screen
      - per-character typing (fast, smooth)
      - auto-scroll upward
      - fade-in at start
      - waits for ENTER only at the end
    """
    # ----- Config -----
    BOOT_FONT_SIZE = 20
    CHAR_MS        = 8       # ms per character (very fast typing)
    GAP_MS         = 20      # pause after finishing a line
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

    # ---- Fade-in ----
    overlay = pygame.Surface((WIDTH, HEIGHT))
    overlay.fill((0, 0, 0))
    for alpha in range(255, -1, -30):
        screen.fill(BG)
        overlay.set_alpha(alpha)
        screen.blit(overlay, (0, 0))
        present()
        soft_wait(15)

    # ---- Type each message char by char ----
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

                # redraw committed log
                log_surface.fill(BG, (0, next_y, WIDTH, line_h))  # clear this line area
                s = boot_font.render(partial, True, TEXT)
                log_surface.blit(s, (LEFT_MARGIN, next_y))

                # scroll view to bottom
                bottom_needed = next_y + line_h
                scroll = max(0, bottom_needed - view_h)
                screen.fill(BG)
                screen.blit(log_surface, (0, TOP_MARGIN),
                            area=pygame.Rect(0, scroll, WIDTH, view_h))
                present()

        # commit line (already there), then move down
        next_y += line_h
        soft_wait(GAP_MS)

    # ---- Final: blinking cursor ----
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
    instructions = "what is your name?"  # prompt text

    # ---- TYPE THE PROMPT LETTER-BY-LETTER ----
    x = 50
    prompt_base_y = HEIGHT - 240
    line_spacing = 32
    prompt_lines = wrap_text_to_width(instructions, WIDTH - 100)
    typed_prompt = []
    for ln in prompt_lines:
        type_out_line_letterwise(ln, typed_prompt, x, prompt_base_y, line_spacing,
                                 draw_face_style=None)
        typed_prompt.append(ln)

    # ---- INPUT LOOP (NAME IN ALL CAPS) ----
    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        # draw the typed prompt
        for i, line in enumerate(typed_prompt):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, prompt_base_y + i*line_spacing))

        # input line (ALL CAPS)
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
                    return (name.strip() or "FRIEND")  # return ALL CAPS default
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    return "FRIEND"
                else:
                    ch = event.unicode
                    if ch:
                        ch = ch.upper()  # FORCE CAPS
                        if 32 <= ord(ch) <= 126 and len(name) < 20:
                            name += ch

        if pygame.time.get_ticks() - last > BLINK_INTERVAL_MS:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)

def show_text_block(text, face_style="smile", glitch=False):
    x = 50
    base_y = HEIGHT - 180
    line_spacing = 32

    # keep case: DON'T force .lower() so NAME and TRAIT can be CAPS
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
    """
    Types the given text letter-by-letter (like other screens),
    slowing during '...' sequences. Then waits for ENTER.
    """
    # Wrap but KEEP case
    lines = []
    for para in (text or "").split("\n"):
        lines.extend(wrap_text_to_width(para, WIDTH - 100))
    if not lines:
        lines = [""]

    x = 50
    base_y = HEIGHT - 160
    line_spacing = 32

    # Type each line thoughtfully
    typed = []
    for ln in lines:
        type_out_line_letterwise_thoughtful(ln, typed, x, base_y, line_spacing, draw_face_style="smile", glitch=False)
        typed.append(ln)

    # Then wait for ENTER with blink (like others)
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

        # draw last frame, then darken with overlay, then CRT polish, then flip
        # (your loops already drew the last title frame before calling this)
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
        wait_for_enter_release()  # user presses ENTER at end of init; this just waits for key-up

        # Ask name
        name = input_name_screen()          # returns ALL CAPS
        trait = random.choice(traits).upper()  # TRAIT in ALL CAPS

        # Conversational sequence (NAME + TRAIT stay CAPS now)
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

        # Processing + glitch
        glitch_face_moment("... oh... that is... very moving... i had no idea...")
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
        # loop back to title

if __name__ == "__main__":
    try:
        main_sequence()
    finally:
        pygame.quit()
