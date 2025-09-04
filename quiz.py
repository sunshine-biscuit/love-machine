# quiz.py
import os, json, pygame
from collections import defaultdict

from quiz_data import QUESTIONS, CATEGORY_BLURBS

# Resolve project root based on this file’s location
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATS_PATH = os.path.join(DATA_DIR, "stats_quiz.json")

def _ensure_stats_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STATS_PATH):
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump({"total": 0, "categories": {}}, f, indent=2)

def _load_stats():
    _ensure_stats_file()
    with open(STATS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_stats(stats):
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

def _render_block(surface, lines, font, color, start_y, line_gap=8, x=40):
    y = start_y
    for line in lines:
        if not line:
            y += line_gap
            continue
        img = font.render(line, True, color)
        surface.blit(img, (x, y))
        y += img.get_height() + line_gap

def _score_from_answers(answers):
    scores = defaultdict(int)
    for weights in answers:
        for k, v in weights.items():
            scores[k] += v
    if not scores:
        return "REALIST"
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return top

def _a_or_an(word):
    # cheap+cheerful article helper for display text
    if not word: return "a"
    return "an" if word[0].upper() in ("A","E","I","O","U") else "a"

def run_quiz(
    screen,
    clock,
    participant_name=None,
    base_font=None,
    title_font=None,
    overlay_draw_fn=None,
    lights_fade_down_fn=None,
    lights_fade_up_fn=None,
):
    """
    Returns: (category, percent, counts_snapshot, blurb)
    """
    WIDTH, HEIGHT = screen.get_size()

    if base_font is None:
        base_font  = pygame.font.SysFont("Courier New", 24)
    if title_font is None:
        title_font = pygame.font.SysFont("Courier New", 28, bold=True)

    # Optional lighting cue at quiz start
    if callable(lights_fade_down_fn):
        try: lights_fade_down_fn()
        except Exception: pass

    question_index = 0
    selected_index = 0
    chosen_weights = []

    WHITE = (230, 230, 230)
    DIM   = (180, 180, 180)
    HL    = (255, 255, 255)
    BG    = (12, 12, 16)

    def draw_question():
        screen.fill(BG)
        if overlay_draw_fn:
            try: overlay_draw_fn(screen)
            except Exception: pass

        title_lines = [
            "LOVE MACHINE — Quick Feelings Check",
            f"Participant: {participant_name}" if participant_name else ""
        ]
        _render_block(screen, [t for t in title_lines if t], title_font, DIM, start_y=28)

        q = QUESTIONS[question_index]
        _render_block(screen, [q["prompt"]], title_font, WHITE, start_y=96, line_gap=12)

        # Vertical options (A, B, C)
        y = 164
        for i, (text, _weights) in enumerate(q["options"]):
            prefix = ["A)", "B)", "C)"][i]
            color = HL if i == selected_index else DIM
            label = f"{prefix} {text}"
            img = base_font.render(label, True, color)
            screen.blit(img, (72, y))
            y += img.get_height() + 14

        hint = base_font.render("Use ↑/↓ to choose, ENTER to confirm", True, DIM)
        screen.blit(hint, (40, HEIGHT - 64))

        pygame.display.flip()

    def draw_result(category, pct, counts):
        screen.fill(BG)
        if overlay_draw_fn:
            try: overlay_draw_fn(screen)
            except Exception: pass

        header = "I have read your inputs."
        sub    = f"So… you’re {_a_or_an(category)} {category} then?"
        _render_block(screen, [header, sub], title_font, WHITE, start_y=40, line_gap=12)

        blurb = CATEGORY_BLURBS.get(category, "")
        if blurb:
            _render_block(screen, [blurb], base_font, DIM, start_y=140, line_gap=10)

        total = sum(counts.values()) if counts else 0
        stat_line = f"{pct}% of people are also {category}s." if total else "You are the first."
        _render_block(
            screen,
            [stat_line, "", "Press ENTER to continue"],
            base_font, WHITE, start_y=HEIGHT - 140, line_gap=10
        )
        pygame.display.flip()

    # ---- Question loop ----
    running = True
    while running:
        draw_question()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None, 0, {}, ""
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_w):
                    selected_index = (selected_index - 1) % 3
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    selected_index = (selected_index + 1) % 3
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    weights = QUESTIONS[question_index]["options"][selected_index][1]
                    chosen_weights.append(weights)
                    question_index += 1
                    selected_index = 0
                    if question_index >= len(QUESTIONS):
                        running = False
        clock.tick(60)

    # Compute + record result
    category = _score_from_answers(chosen_weights)
    pct, counts_snapshot, _total = _tally_category_count(category)

    # Result screen
    waiting = True
    while waiting:
        draw_result(category, pct, counts_snapshot)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                waiting = False
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                waiting = False
        clock.tick(60)

    # Optional lighting cue at quiz end
    if callable(lights_fade_up_fn):
        try: lights_fade_up_fn()
        except Exception: pass

    blurb = CATEGORY_BLURBS.get(category, "")
    return category, pct, counts_snapshot, blurb
