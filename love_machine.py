import pygame
import sys
import time
import os
import textwrap
import random

# Initialise Pygame
pygame.init()
pygame.mixer.init()

# Screen setup
WIDTH, HEIGHT = 800, 480
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Love Machine")
clock = pygame.time.Clock()

# File paths
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(ASSETS_DIR, "PressStart2P-Regular.ttf")
STARTUP_SOUND_PATH = os.path.join(ASSETS_DIR, "startup.wav")
KEYPRESS_SOUND_PATH = os.path.join(ASSETS_DIR, "keypress.wav")

# Load sounds
startup_sound = pygame.mixer.Sound(STARTUP_SOUND_PATH)
keypress_sound = pygame.mixer.Sound(KEYPRESS_SOUND_PATH)
keypress_sound.set_volume(0.2)

# Load font
FONT_SIZE = 24
font = pygame.font.Font(FONT_PATH, FONT_SIZE)

# Text color and background
TEXT_COLOR = (0, 255, 0)
BG_COLOR = (0, 0, 0)

# Slides: (text, face_style)
slides = [
    ("Hello, and welcome to Love Machine.", "smile"),
    ("Please place your handwritten note in the tray.", "smile"),
    ("When you are ready, press ENTER to begin.", "smile"),
    ("We are reading your message...", "smile"),
    ("Love is being transformed...", "smile"),
    ("Here is your artifact. Take it with care.", "smile")
]

# Pixel-art faces (two eyes and a centered smile)
faces = {
    "smile": [
        "0100000010",
        "0100000010",
        "0000000000",
        "0000000000",
        "0000000000",
        "0011111100",
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

# Blinking config
face_blink_on_interval = 5000
face_blink_off_duration = 500
last_face_blink_time = 0
face_blink_state = False
face_is_blinking = False


def draw_scanlines():
    for y in range(0, HEIGHT, 4):
        pygame.draw.line(screen, (10, 30, 10), (0, y), (WIDTH, y), 1)


def draw_face(style="smile", block_size=16):
    global last_face_blink_time, face_blink_state, face_is_blinking
    current_time = pygame.time.get_ticks()

    if not face_is_blinking and current_time - last_face_blink_time > face_blink_on_interval:
        face_blink_state = True
        face_is_blinking = True
        last_face_blink_time = current_time

    if face_is_blinking and current_time - last_face_blink_time > face_blink_off_duration:
        face_blink_state = False
        face_is_blinking = False
        last_face_blink_time = current_time

    pattern = faces["blink"] if face_blink_state else faces.get(style, faces["smile"])
    face_width = len(pattern[0]) * block_size
    x_start = (WIDTH - face_width) // 2
    y_start = 20

    for row_idx, row in enumerate(pattern):
        for col_idx, val in enumerate(row):
            if val == "1":
                rect = pygame.Rect(
                    x_start + col_idx * block_size,
                    y_start + row_idx * block_size,
                    block_size,
                    block_size
                )
                pygame.draw.rect(screen, TEXT_COLOR, rect)


def wrap_text(text, max_chars):
    return textwrap.wrap(text, width=max_chars)


def type_text_lines(lines, x, y_start, line_spacing=32, face=True):
    y = y_start
    for line in lines:
        for i in range(len(line) + 1):
            screen.fill(BG_COLOR)
            draw_scanlines()
            if face:
                draw_face("smile")
            for j in range(len(lines[:lines.index(line)])):
                rendered_prev = font.render(lines[j], True, TEXT_COLOR)
                screen.blit(rendered_prev, (x, y_start + j * line_spacing))

            partial_text = line[:i]
            rendered = font.render(partial_text, True, TEXT_COLOR)
            screen.blit(rendered, (x, y))
            pygame.display.flip()
            keypress_sound.play()
            pygame.time.wait(40)
        y += line_spacing
        pygame.time.wait(200)

    blink = True
    last_blink = pygame.time.get_ticks()

    while True:
        screen.fill(BG_COLOR)
        draw_scanlines()
        if face:
            draw_face("smile")
        for idx, line in enumerate(lines):
            rendered_line = font.render(line, True, TEXT_COLOR)
            screen.blit(rendered_line, (x, y_start + idx * line_spacing))

        if blink:
            last_line = lines[-1]
            text_width = font.size(last_line)[0]
            pygame.draw.rect(screen, TEXT_COLOR, (x + text_width + 5, y_start + (len(lines) - 1) * line_spacing + 5, 10, 20))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        if pygame.time.get_ticks() - last_blink > 500:
            blink = not blink
            last_blink = pygame.time.get_ticks()


def fade_to_black():
    fade = pygame.Surface((WIDTH, HEIGHT))
    fade.fill((0, 0, 0))
    for alpha in range(0, 255, 5):
        fade.set_alpha(alpha)
        screen.blit(fade, (0, 0))
        pygame.display.update()
        pygame.time.delay(30)


def boot_up_sequence():
    screen.fill(BG_COLOR)
    pygame.display.flip()
    startup_sound.play()
    time.sleep(1)

    boot_lines = [
        "Booting Love Machine v1.0...",
        "Initializing core systems...",
        "Loading sentiment engines...",
        "Calibrating empathy modules...",
        "System ready."
    ]
    type_text_lines(boot_lines, 50, 100, face=False)


def wait_for_enter(message="Press ENTER to begin.", show_face=False):
    blink = True
    last_blink = pygame.time.get_ticks()
    while True:
        screen.fill(BG_COLOR)
        draw_scanlines()
        if show_face:
            draw_face("smile")
        rendered = font.render(message, True, TEXT_COLOR)
        screen.blit(rendered, (50, HEIGHT - 80))
        if blink:
            pygame.draw.rect(screen, TEXT_COLOR, (50 + rendered.get_width() + 5, HEIGHT - 75, 10, 20))
        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return

        if pygame.time.get_ticks() - last_blink > 500:
            blink = not blink
            last_blink = pygame.time.get_ticks()


def show_slide(text, face_style="smile"):
    wrapped_lines = wrap_text(text, 40)
    type_text_lines(wrapped_lines, 50, HEIGHT - 160, face=(face_style != None))


def main():
    while True:
        wait_for_enter("Press ENTER to begin.", show_face=False)
        screen.fill(BG_COLOR)
        pygame.display.flip()

        boot_up_sequence()
        pygame.time.wait(1000)

        for slide_text, face in slides:
            show_slide(slide_text, face_style=face)

        fade_to_black()
        wait_for_enter("Press ENTER to begin.", show_face=False)


if __name__ == "__main__":
    main()
p
