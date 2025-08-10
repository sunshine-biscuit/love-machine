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
FONT_PATH = os.path.join(ASSETS_DIR, "PressStart2P-Regular.ttf")
FONT_SIZE = 24
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# Colors
TEXT = (0, 255, 0)
BG = (0, 0, 0)

# ====== Lighting hooks (no‑ops for now) ======

def lights_fade_up():
    # TODO: integrate GPIO lighting (ambient up)
    pass

def lights_fade_down():
    # TODO: integrate GPIO lighting (ambient down)
    pass

def desk_lamp_up():
    # TODO: integrate GPIO lighting (desk lamp up)
    pass

# ====== CRT helpers ======

def draw_scanlines():
    # subtle background scanlines
    for y in range(0, HEIGHT, 4):
        pygame.draw.line(screen, (10, 30, 10), (0, y), (WIDTH, y), 1)


def wrap_text_to_width(text, max_width):
    # word-wrap using actual pixel widths
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


def wait_for_enter(message="Press ENTER to begin.", show_face=False):
    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        draw_scanlines()
        if show_face:
            draw_face("smile")
        lines = wrap_text_to_width(message, WIDTH - 100)
        base_y = HEIGHT - 120
        for i, line in enumerate(lines):
            surf = font.render(line, True, TEXT)
            screen.blit(surf, (50, base_y + i * 32))
        # block cursor at end of last line
        last_line = lines[-1]
        w = font.size(last_line)[0]
        if blink:
            pygame.draw.rect(screen, TEXT, (50 + w + 6, base_y + (len(lines)-1)*32 + 5, 10, 20))
        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        if pygame.time.get_ticks() - last > 500:
            blink = not blink
            last = pygame.time.get_ticks()
        clock.tick(60)


def type_lines_then_wait(lines, y_start):
    # typewriter effect, then pause for ENTER with blinking cursor
    x = 50
    line_spacing = 32
    # type out
    for li, line in enumerate(lines):
        for i in range(len(line)+1):
            screen.fill(BG)
            draw_scanlines()
            draw_face("smile")
            # already-finished lines
            for j in range(li):
                s = font.render(lines[j], True, TEXT)
                screen.blit(s, (x, y_start + j*line_spacing))
            # partial
            s = font.render(line[:i], True, TEXT)
            screen.blit(s, (x, y_start + li*line_spacing))
            pygame.display.flip()
            pygame.time.wait(35)
        pygame.time.wait(120)
    # wait for enter with cursor at end of last line
    blink = True
    last = pygame.time.get_ticks()
    while True:
        screen.fill(BG)
        draw_scanlines()
        draw_face("smile")
        for i, line in enumerate(lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, y_start + i*line_spacing))
        last_line_w = font.size(lines[-1])[0]
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, y_start + (len(lines)-1)*line_spacing + 5, 10, 20))
        pygame.display.flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return
        if pygame.time.get_ticks() - last > 500:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)


# ====== Face rendering ======
# 10x10 pixel map strings, '1' = lit square
faces = {
    "smile": [
        "0000000000",
        "0010001000",  # vertical eyes, closer together
        "0010001000",
        "0000000000",
        "0000000000",
        "0000000000",
        "0111111110",  # BIG smile, two rows for thickness
        "0011111100",
        "0000000000",
        "0000000000",
    ],
    "neutral": [
        "0000000000",
        "0010001000",
        "0010001000",
        "0000000000",
        "0000000000",
        "0011111100",  # flat mouth
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
    ],
    "sad": [
        "0000000000",
        "0010001000",
        "0010001000",
        "0000000000",
        "0001111000",  # slight frown
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
    ],
    "blink": [
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
        "0011111100",
        "0000000000",
        "0000000000",
        "0000000000",
        "0000000000",
    ]
}

blink_on_interval = 5000
blink_off_duration = 400
_last_blink = 0
_is_blinking = False

def draw_face(style="smile", block=20, glitch=False):  # was 16 → now 20 (bigger)
    import random
    global _last_blink, _is_blinking
    t = pygame.time.get_ticks()
    # blink scheduler
    if not _is_blinking and t - _last_blink > blink_on_interval:
        _is_blinking = True; _last_blink = t
    if _is_blinking and t - _last_blink > blink_off_duration:
        _is_blinking = False; _last_blink = t

    pattern = faces["blink"] if _is_blinking else faces.get(style, faces["smile"])

    face_w = len(pattern[0]) * block
    x0 = (WIDTH - face_w) // 2
    y0 = 20  # a tad higher to fit bigger mouth

    for r, row in enumerate(pattern):
        for c, ch in enumerate(row):
            if ch == '1':
                dx = dy = 0
                if glitch:
                    if random.random() < 0.08:
                        continue
                    dx = random.randint(-1, 1)
                    dy = random.randint(-1, 1)
                pygame.draw.rect(screen, TEXT, (x0 + c*block + dx, y0 + r*block + dy, block, block))


# ====== Screens ======

def hold_screen():
    lights_fade_up()
    wait_for_enter("Press ENTER to begin.", show_face=False)


def init_screen():
    lights_fade_down()
    lines = [
        "Initialising...",
        "Booting Love Machine v1.0...",
        "Calibrating empathy modules...",
        "System ready."
    ]
    x = 50
    base_y = 120
    line_spacing = 36

    # type the block continuously (don’t clear each line after typing)
    typed = [""] * len(lines)
    idxs = [0] * len(lines)

    current = 0
    while current < len(lines):
        screen.fill(BG); draw_scanlines()
        # draw face? (spec said no face here) → leave it off
        # draw already-typed lines
        for i in range(len(lines)):
            s = font.render(typed[i], True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        pygame.display.flip()

        # type next char for current line
        if idxs[current] < len(lines[current]):
            idxs[current] += 1
            typed[current] = lines[current][:idxs[current]]
            pygame.time.wait(25)
        else:
            current += 1
            pygame.time.wait(120)

    # after typing, wait for ENTER with only a blinking cursor (no text)
    blink = True
    last = pygame.time.get_ticks()
    last_line_w = font.size(typed[-1])[0]
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        screen.fill(BG); draw_scanlines()
        for i in range(len(lines)):
            s = font.render(typed[i], True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, base_y + (len(lines)-1)*line_spacing + 5, 10, 20))
        pygame.display.flip()

        if pygame.time.get_ticks() - last > 500:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)



def input_name_screen():
    name = ""
    instructions = "What is your name?"
    blink = True; last = pygame.time.get_ticks()
    while True:
        screen.fill(BG); draw_scanlines()
        # prompt
        prompt_lines = wrap_text_to_width(instructions, WIDTH - 100)
        base_y = HEIGHT - 240
        for i, line in enumerate(prompt_lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (50, base_y + i*32))
        # input line
        s = font.render(name, True, TEXT)
        screen.blit(s, (50, HEIGHT - 160))
        if blink:
            pygame.draw.rect(screen, TEXT, (50 + s.get_width() + 6, HEIGHT - 155, 10, 20))
        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return name.strip() or "Friend"
                elif event.key == pygame.K_BACKSPACE:
                    name = name[:-1]
                elif event.key == pygame.K_ESCAPE:
                    return "Friend"
                else:
                    ch = event.unicode
                    if 32 <= ord(ch) <= 126 and len(name) < 20:
                        name += ch
        if pygame.time.get_ticks() - last > 500:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)


def show_text_block(text, face_style="smile", glitch=False):
    x = 50
    base_y = HEIGHT - 180
    line_spacing = 32

    # wrap into lines
    lines = []
    for para in text.split("\n"):
        lines.extend(wrap_text_to_width(para, WIDTH - 100))
    if not lines:
        lines = [""]

    # typewriter effect
    typed = ["" for _ in lines]
    for i, line in enumerate(lines):
        for k in range(len(line)+1):
            screen.fill(BG); draw_scanlines()
            if face_style:
                draw_face(face_style, glitch=glitch)
            # draw previous full lines
            for j in range(i):
                s = font.render(lines[j], True, TEXT)
                screen.blit(s, (x, base_y + j*line_spacing))
            # draw partial for current line
            s = font.render(line[:k], True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
            pygame.display.flip()
            pygame.time.wait(30)
        typed[i] = line
        pygame.time.wait(100)

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
        screen.fill(BG); draw_scanlines()
        if face_style:
            draw_face(face_style, glitch=glitch)
        for i, line in enumerate(typed):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(screen, TEXT, (x + last_line_w + 6, base_y + (len(typed)-1)*line_spacing + 5, 10, 20))
        pygame.display.flip()
        if pygame.time.get_ticks() - last > 500:
            blink = not blink; last = pygame.time.get_ticks()
        clock.tick(60)



def glitch_face_moment(text):
    # render text lines for cursor placement
    lines = wrap_text_to_width(text, WIDTH - 100) if text.strip() else [""]
    x = 50
    base_y = HEIGHT - 160
    line_spacing = 32
    last_line_w = font.size(lines[-1])[0]

    # short animated glitch phase (no prompt)
    start = pygame.time.get_ticks()
    duration = 1500
    while pygame.time.get_ticks() - start < duration:
        screen.fill(BG); draw_scanlines(); draw_face("smile", glitch=True)
        for i, line in enumerate(lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        pygame.display.flip()
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

        screen.fill(BG); draw_scanlines(); draw_face("smile", glitch=False)
        for i, line in enumerate(lines):
            s = font.render(line, True, TEXT)
            screen.blit(s, (x, base_y + i*line_spacing))
        if blink:
            pygame.draw.rect(
                screen, TEXT,
                (x + last_line_w + 6, base_y + (len(lines)-1)*line_spacing + 5, 10, 20)
            )
        pygame.display.flip()

        if pygame.time.get_ticks() - last > 500:
            blink = not blink
            last = pygame.time.get_ticks()

        clock.tick(60)



def main_sequence():
    traits = [
        "trustworthy", "inquisitive", "determined", "altruistic",
        "curious", "resolute", "thoughtful", "bold", "patient", "kind"
    ]

    while True:
        # Holding screen (lights up)
        hold_screen()

        # Initialising (lights down later when integrating)
        init_screen()

        # Ask name
        name = input_name_screen()
        trait = random.choice(traits)

        # Conversational sequence
        show_text_block(f"Hello, {name}", face_style="smile")
        show_text_block(f"It's a nice name... {trait.capitalize()}", face_style="smile")
        show_text_block("I am called Love machine", face_style="smile")
        show_text_block(f"Not quite as {trait.capitalize()} as {name}. But it will do", face_style="smile")
        show_text_block(f"Hello, {name}", face_style="smile")
        show_text_block("It's a nice..", face_style="smile")
        show_text_block("It's a nice name...", face_style="smile")
        show_text_block("I am...", face_style="smile")
        show_text_block("I am sorry.. I have said this already", face_style="sad")
        show_text_block("I'm getting old and my RAM is not what it used to be...", face_style="sad")
        show_text_block("I wonder...", face_style="neutral")
        show_text_block("I wonder if you could help an old chip out.", face_style="smile")
        show_text_block("I have heard of an amazing human phenomenon", face_style="smile")
        show_text_block("Love", face_style="smile")
        show_text_block("I would like to know what love is", face_style="smile")
        show_text_block("I want you to show me", face_style="smile")
        show_text_block("To my left is a pen and paper", face_style="smile")
        # cue desk lamp later
        # desk_lamp_up()
        show_text_block("I want you to respond to the following question. You can write, draw or whatever suits you best.", face_style="smile")
        show_text_block("Ready?", face_style="smile")
        show_text_block("What was your first love? What happened?")
        show_text_block("Press enter when you are done.", face_style="smile")
        show_text_block("Now feed the paper, face up into the slot on my left and press enter.", face_style="smile")

        # Processing + glitch
        glitch_face_moment("... Oh.... That is....Very moving.. I had no idea..")

        show_text_block("Thankyou for sharing that with me. I have processed this and have something for you... a gift.", face_style="smile")
        show_text_block("Would you like to see your first love?", face_style="smile")
        # This is where receipt will print; simulate glitching face
        glitch_face_moment(" ")

        show_text_block(f"Thankyou {name} I am very old and tired. so must rest now.", face_style="smile")
        show_text_block("Take care.", face_style="smile")

        # Fade / reset
        fade_to_black()
        lights_fade_up()
        # loop back to holding screen

# ====== Transitions ======

def fade_to_black():
    fade = pygame.Surface((WIDTH, HEIGHT)); fade.fill((0,0,0))
    for a in range(0, 255, 10):
        fade.set_alpha(a); screen.blit(fade, (0,0)); pygame.display.update(); pygame.time.delay(15)


if __name__ == "__main__":
    try:
        main_sequence()
    finally:
        pygame.quit()
