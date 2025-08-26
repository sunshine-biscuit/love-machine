#!/usr/bin/env python3
# Generative art -> preview -> Epson TM-T88 over TCP:9100 (ESC/POS raster)
# Includes: halftone / radial burst / maze, safe levels, side+top/bottom trimming,
# light edge softener (no dark rings), adaptive chunked send, and
# weighted variant selection + frequent multi-style layering.

import os, socket, uuid, math, time, random
from datetime import datetime

import numpy as np
from PIL import (
    Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance, ImageStat, ImageChops
)

# ====== CONFIG ======
PRINTER_IP   = "192.168.192.168"   # <-- set this to your printer's IP
PRINTER_PORT = 9100
PRINTER_DOTS = 512                 # safe width; try 576 later if supported
PREVIEW_PNG  = "last-art-preview.png"
LOG_FILE     = "printed-art-ids.txt"

# ---- Height guards (override via env if you like) ----
MIN_BASE_HEIGHT   = int(os.getenv("LM_MIN_BASE_HEIGHT", "900"))   # before dither/trim
MIN_FINAL_ROWS    = int(os.getenv("LM_MIN_FINAL_ROWS", "900"))    # after dither/trim


# ====== VARIANT WEIGHTING ======
VARIANTS = ["noise","lines","shapes","strokes","plasma","life","halftone","burst","maze"]

# Heavier base weight for PLASMA (you can tweak these later)
WEIGHTS_BASE = {
    "plasma": 0.36,
    "lines": 0.10, "shapes": 0.10, "strokes": 0.10, "noise": 0.10,
    "life": 0.10, "halftone": 0.06, "burst": 0.05, "maze": 0.03,
}

# When adding extra layers, still favor plasma a bit, but keep variety
WEIGHTS_ALT = {
    "plasma": 0.28,
    "lines": 0.14, "shapes": 0.14, "strokes": 0.12, "noise": 0.10,
    "life": 0.08, "halftone": 0.07, "burst": 0.05, "maze": 0.02,
}

def weighted_pick(rng, items, weights):
    w = np.array([weights.get(i, 1.0) for i in items], dtype=np.float64)
    w_sum = w.sum()
    if w_sum <= 0:
        return random.choice(items)
    p = w / w_sum
    idx = int(rng.choice(len(items), p=p))
    return items[idx]

# ====== UTIL ======
def new_run_seed():
    u = uuid.uuid4()
    return u, u.int & 0xFFFFFFFF

# ====== ART GENERATORS ======
def gen_noise(seed, w, h):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
    img = Image.fromarray(base, mode="L").filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.6)))
    shift = rng.integers(80, 120)
    gain  = rng.uniform(1.4, 1.8)
    img = Image.eval(img, lambda p: int(max(0, min(255, (p - shift) * gain))))
    return img

def gen_lines(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    bands = rng.randint(3, 7)
    for _ in range(bands):
        amp  = rng.uniform(h*0.04, h*0.28)
        freq = rng.uniform(0.002, 0.028)
        phase= rng.uniform(0, 2*math.pi)
        thickness = rng.randint(1, 3)
        grey = rng.randint(35, 150)
        for x in range(w):
            y = int(h/2 + amp * math.sin(x*freq + phase))
            d.line([(x, y - thickness), (x, y + thickness)], fill=grey)
        for _ in range(w//rng.randint(6, 12)):
            x = rng.randrange(w); y = rng.randrange(h)
            img.putpixel((x, y), rng.randint(0, 110))
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.9)))

def gen_shapes(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    count = rng.randint(30, 80)
    for _ in range(count):
        x1, y1 = rng.randrange(w), rng.randrange(h)
        x2 = min(w-1, x1 + rng.randrange(10, max(12, w//3)))
        y2 = min(h-1, y1 + rng.randrange(10, max(12, h//3)))
        fill = rng.randint(30, 210)
        if rng.random() < 0.5:
            d.rectangle([x1, y1, x2, y2], fill=fill, outline=None)
        else:
            d.ellipse([x1, y1, x2, y2], fill=fill, outline=None)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.6, 1.2)))

def gen_strokes(seed, w, h):
    """Sumi-ink style short strokes for texture."""
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    n = rng.randint(800, 1800)
    for _ in range(n):
        x = rng.randrange(w); y = rng.randrange(h)
        length = rng.randint(4, 22)
        angle  = rng.uniform(0, 2*math.pi)
        dx = int(length * math.cos(angle))
        dy = int(length * math.sin(angle))
        grey = rng.randint(10, 160)
        d.line([(x, y), (x+dx, y+dy)], fill=grey, width=rng.randint(1, 2))
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))

def gen_plasma(seed, w, h):
    """
    Cloud‑like fBM: sums a few *very smooth* low‑frequency noise octaves.
    Uses tiny random grids upscaled with bicubic interpolation (value‑noise style),
    so features are big and fluffy instead of speckly/static.
    """
    rng = np.random.default_rng(seed)

    # Render a bit oversized, then downsample for extra smoothness
    upscale = 1.35
    W, H = int(w * upscale), int(h * upscale)

    def smooth_rand_grid(width, height, cells_x, cells_y):
        """Make a small random grid and bicubic-upscale to (width,height)."""
        grid = (rng.random((cells_y, cells_x)) * 255).astype(np.uint8)
        img_small = Image.fromarray(grid, mode="L")
        # Bicubic gives nice smooth interpolation with gentle roll-off
        return img_small.resize((width, height), Image.BICUBIC)

    # --- octave setup: bigger cells (low frequency) → smaller cells (higher frequency)
    # Start with large features; lacunarity ~ 1.9 keeps it cloud-like
    # Tune here if you want even puffier clouds (decrease cells_* or octaves).
    base_cells_x = max(6, int(W / rng.uniform(180, 260)))
    base_cells_y = max(6, int(H / rng.uniform(180, 260)))
    octaves      = int(rng.integers(4, 6))         # 4–5 octaves is plenty for clouds
    lacunarity   = float(rng.uniform(1.8, 2.1))     # how quickly detail increases
    persistence  = float(rng.uniform(0.50, 0.62))   # amplitude drop per octave

    acc = np.zeros((H, W), dtype=np.float32)
    amp = 1.0
    cells_x, cells_y = base_cells_x, base_cells_y

    for _ in range(octaves):
        layer = np.asarray(smooth_rand_grid(W, H, cells_x, cells_y), dtype=np.float32) / 255.0
        # optional gentle blur per octave to avoid banding from tiny grids
        if cells_x < 10 or cells_y < 10:
            layer = np.asarray(Image.fromarray((layer * 255).astype(np.uint8), "L")
                               .filter(ImageFilter.GaussianBlur(radius=0.4)), dtype=np.uint8) / 255.0
        acc += layer * amp
        amp *= persistence
        cells_x = min(max(6, int(cells_x * lacunarity)), max(32, W // 24))
        cells_y = min(max(6, int(cells_y * lacunarity)), max(32, H // 24))

    # Normalize to 0..1
    mn, mx = float(acc.min()), float(acc.max())
    field = (acc - mn) / (mx - mn + 1e-9)

    # Tone curve for clouds: brighten mids, keep soft contrast
    # (Think "gamma 0.85" into a gentle S-curve)
    field = np.clip(field, 0.0, 1.0) ** 0.85
    field = 0.6 * field + 0.4 * (field * (1.0 - field) * 4.0)  # mild S-curve

    # Map to 0..255 and add tiny blur to remove any residual stepping
    cloud = (field * 255.0).astype(np.uint8)
    img = Image.fromarray(cloud, mode="L")
    img = img.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.3, 0.7))))

    # Downsample to target with LANCZOS (keeps the puffiness)
    return img.resize((w, h), Image.LANCZOS)



def gen_life(seed, w, h):
    """Conway's Game of Life evolved from noise, then rendered."""
    rng = np.random.default_rng(seed)
    gw, gh = max(64, w//8), max(64, h//8)
    grid = (rng.random((gh, gw)) > rng.uniform(0.6, 0.7)).astype(np.uint8)
    def step_life(g):
        n = (
            np.roll(np.roll(g,  1, 0),  1, 1) + np.roll(g,  1, 0) + np.roll(np.roll(g,  1, 0), -1, 1) +
            np.roll(g,  1, 1) + np.roll(g, -1, 1) +
            np.roll(np.roll(g, -1, 0),  1, 1) + np.roll(g, -1, 0) + np.roll(np.roll(g, -1, 0), -1, 1)
        )
        born = (n == 3) & (g == 0)
        survive = ((n == 2) | (n == 3)) & (g == 1)
        return (born | survive).astype(np.uint8)
    for _ in range(int(rng.integers(30, 90))):
        grid = step_life(grid)
    density = grid.astype(np.float32)
    density = (density + np.roll(density, 1, 0) + np.roll(density, -1, 0) +
               np.roll(density, 1, 1) + np.roll(density, -1, 1)) / 5.0
    img = Image.fromarray(np.clip(density * 255, 0, 255).astype(np.uint8), mode="L")
    img = img.resize((w, h), Image.NEAREST)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.7)))

# ----- NEW: Retro halftone -----
def gen_halftone(seed, w, h):
    """Dot halftone: circles sized by cell darkness."""
    rng = np.random.default_rng(seed)
    base = gen_plasma(int(seed), w, h) if rng.random() < 0.6 else gen_noise(int(seed), w, h)
    cell = int(rng.integers(6, 12))
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    jitter = rng.uniform(0.0, 0.25)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            crop = base.crop((x, y, min(x+cell, w), min(y+cell, h))).resize((1,1), Image.BILINEAR)
            val = crop.getpixel((0,0))
            darkness = 1.0 - (val / 255.0)
            r = darkness * (cell * 0.5)
            if r <= 0.2:
                continue
            jx = int((rng.random() - 0.5) * jitter * cell)
            jy = int((rng.random() - 0.5) * jitter * cell)
            cx = x + cell//2 + jx
            cy = y + cell//2 + jy
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=int(40 + 160*darkness))
    return img

# ----- NEW: Radial burst -----
def gen_radial_burst(seed, w, h):
    """Rays from a random centre; softened to avoid dark blobs."""
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 245)
    d = ImageDraw.Draw(img)
    cx = rng.randint(int(w*0.2), int(w*0.8))
    cy = rng.randint(int(h*0.2), int(h*0.8))
    rays = rng.randint(50, 160)
    maxlen = int(max(w, h) * 1.1)
    base_grey = rng.randint(40, 120)
    for i in range(rays):
        angle = (2*math.pi) * (i / rays) + rng.uniform(-0.03, 0.03)
        length = int(maxlen * rng.uniform(0.6, 1.0))
        x2 = int(cx + length * math.cos(angle))
        y2 = int(cy + length * math.sin(angle))
        width = rng.randint(1, 3)
        g = min(200, max(30, int(base_grey + rng.uniform(-30, 30))))
        d.line([(cx, cy), (x2, y2)], fill=g, width=width)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.8)))

# ----- NEW: Maze grids -----
def gen_maze(seed, w, h):
    """Depth-first search maze on a coarse grid, then upscaled and thickened."""
    rng = np.random.default_rng(seed)
    cols = max(16, w // rng.integers(18, 28))
    rows = max(16, h // rng.integers(18, 28))
    grid = np.zeros((rows, cols), dtype=np.uint8)  # 0 walls, 1 path
    visited = np.zeros_like(grid, dtype=bool)
    dirs = [(1,0), (-1,0), (0,1), (0,-1)]

    def nbs(r, c):
        out = []
        for dr, dc in dirs:
            nr, nc = r + 2*dr, c + 2*dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc]:
                out.append((nr, nc, dr, dc))
        rng.shuffle(out)
        return out

    r0 = int(rng.integers(0, rows) | 1)
    c0 = int(rng.integers(0, cols) | 1)
    stack = [(r0, c0)]
    visited[r0, c0] = True
    grid[r0, c0] = 1

    while stack:
        r, c = stack[-1]
        neigh = nbs(r, c)
        if not neigh:
            stack.pop()
            continue
        nr, nc, dr, dc = neigh[0]
        grid[r + dr, c + dc] = 1
        grid[nr, nc] = 1
        visited[nr, nc] = True
        stack.append((nr, nc))

    cell = int(rng.integers(4, 7))
    img = Image.new("L", (cols*cell, rows*cell), 0)
    px = img.load()
    for y in range(rows):
        for x in range(cols):
            if grid[y, x]:
                for yy in range(y*cell, (y+1)*cell):
                    for xx in range(x*cell, (x+1)*cell):
                        px[xx, yy] = 220
    img = img.resize((w, h), Image.NEAREST)
    return img.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.4, 0.9))))

# ---- compositor helpers ----
def random_flip_rotate(img, rng):
    if rng.random() < 0.5: img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if rng.random() < 0.5: img = img.transpose(Image.FLIP_TOP_BOTTOM)
    k = rng.integers(0, 4)
    if k: img = img.rotate(90 * int(k), expand=False)
    return img

def blend_layers(a, b, mode, opacity):
    a = a.convert("L"); b = b.convert("L")
    if mode == "multiply":
        mixed = ImageChops.multiply(a, b)
    elif mode == "add":
        mixed = ImageChops.add(a, b, scale=1.0, offset=0)
    else:
        mixed = ImageChops.screen(a, b)
    if opacity < 1.0:
        mixed = Image.blend(a, mixed, opacity)
    return mixed

def generate_image(variant, seed, target_width):
    """
    Returns an 8-bit grayscale PIL Image (not yet dithered).
    Uses weighted picking (plasma favored) and frequent multi-layering.
    """
    rng = np.random.default_rng(seed)
        # base height now respects a minimum
    base_h = max(MIN_BASE_HEIGHT, int(target_width * rng.uniform(1.7, 2.3)))
    base_w = target_width

    # ---- base layer: favor plasma via weights ----
    if variant in VARIANTS:
        use_variant = variant
    else:
        use_variant = weighted_pick(rng, VARIANTS, WEIGHTS_BASE)

    def make_layer(v, s):
        if v == "noise":     return gen_noise(s, base_w, base_h)
        if v == "lines":     return gen_lines(int(s), base_w, base_h)
        if v == "shapes":    return gen_shapes(int(s), base_w, base_h)
        if v == "strokes":   return gen_strokes(int(s), base_w, base_h)
        if v == "plasma":    return gen_plasma(int(s), base_w, base_h)
        if v == "life":      return gen_life(int(s), base_w, base_h)
        if v == "halftone":  return gen_halftone(int(s), base_w, base_h)
        if v == "burst":     return gen_radial_burst(int(s), base_w, base_h)
        if v == "maze":      return gen_maze(int(s), base_w, base_h)

    img = make_layer(use_variant, seed)
    img = random_flip_rotate(img, rng)

        # ---- Layering: less frequent, fewer double-layers ----
    if rng.random() < 0.60:  # was 0.90
        num_layers = 1 + (1 if rng.random() < 0.25 else 0)  # was 40%
        for _ in range(num_layers):
            alt_choices = [v for v in VARIANTS if v != use_variant]
            # slightly reduce plasma as a *layer* so base can shine
            alt = weighted_pick(rng, alt_choices, {**WEIGHTS_ALT, "plasma": 0.22})
            img2 = make_layer(alt, (seed + rng.integers(1000, 9999)) & 0xFFFFFFFF)
            img2 = random_flip_rotate(img2, rng)

            r = rng.random()
            if r < 0.22:
                mode = "multiply"; opacity = float(rng.uniform(0.32, 0.50))  # a touch lighter
            elif r < 0.70:
                mode = "screen";   opacity = float(rng.uniform(0.45, 0.80))
            else:
                mode = "add";      opacity = float(rng.uniform(0.38, 0.70))
            img = blend_layers(img, img2, mode, opacity)


            # Blend: multiply present but balanced; screen/add more common
            r = rng.random()
            if r < 0.25:
                mode = "multiply"; opacity = float(rng.uniform(0.33, 0.55))
            elif r < 0.70:
                mode = "screen";   opacity = float(rng.uniform(0.45, 0.85))
            else:
                mode = "add";      opacity = float(rng.uniform(0.40, 0.75))

            img = blend_layers(img, img2, mode, opacity)

    # ---- lighter edge softener (no dark edge rings) ----
    if rng.random() < 0.7:
        w_, h_ = img.size
        cx, cy = w_//2, h_//2
        maxr = float(math.hypot(cx, cy))
        mask = Image.new("L", (w_, h_), 0)
        mp = mask.load()
        strength = float(rng.uniform(0.35, 0.65))
        for y in range(h_):
            for x in range(w_):
                r = math.hypot(x - cx, y - cy) / maxr
                mp[x, y] = int(255 * min(1.0, (r*r)))
        if strength < 1.0:
            mask = Image.blend(Image.new("L", (w_, h_), 0), mask, strength)
        img = Image.composite(Image.new("L", (w_, h_), 255), img, mask)  # edges lighten

    return img

# ====== LEVELING / TRIMMING / DITHER ======
def _auto_levels(img, black_point=0.05, white_point=0.05, contrast_boost=1.15, gamma=0.95):
    img = ImageOps.autocontrast(img, cutoff=(int(black_point*100), int(white_point*100)))
    img = ImageEnhance.Contrast(img).enhance(contrast_boost)
    lut = [min(255, max(0, int((i/255.0) ** gamma * 255))) for i in range(256)]
    img = img.point(lut)
    return img

def _crop_whitespace_lr(img_l_or_1):
    """Crop pure-white columns from LEFT/RIGHT only; keep top/bottom."""
    tmp = img_l_or_1.convert("L")
    w, h = tmp.size
    px = tmp.load()
    left = 0
    for x in range(w):
        if any(px[x, y] < 250 for y in range(h)):
            left = x; break
    right = w - 1
    for x in range(w - 1, -1, -1):
        if any(px[x, y] < 250 for y in range(h)):
            right = x; break
    if right <= left:
        return img_l_or_1
    return img_l_or_1.crop((left, 0, right + 1, h))

def _trim_bands_tb(img_1, black_frac=0.97, white_frac=0.997, max_ratio=0.25):
    """
    Trim uniform bands from TOP/BOTTOM that are almost all black or almost all white.
    Limits to max_ratio of height per side. Works on '1' or 'L'.
    """
    g = img_1.convert("L")
    w, h = g.size
    max_trim = int(h * max_ratio)

    def row_black_fraction(y):
        row = g.crop((0, y, w, y+1))
        m = ImageStat.Stat(row).mean[0]  # 0..255
        return 1.0 - (m / 255.0)

    top = 0
    for y in range(h):
        if y >= max_trim: break
        bf = row_black_fraction(y); wf = 1.0 - bf
        if bf >= black_frac or wf >= white_frac:
            top = y + 1
        else:
            break

    bottom = h
    for y in range(h-1, -1, -1):
        if (h - 1 - y) >= max_trim: break
        bf = row_black_fraction(y); wf = 1.0 - bf
        if bf >= black_frac or wf >= white_frac:
            bottom = y
        else:
            break

    if bottom <= top:
        return img_1
    return img_1.crop((0, top, w, bottom))

def prep_for_printer(img_gray, max_width, target_mean=140, margin_px=8, margin_tb=6):
    """
    - Scale to width, stabilise levels, nudge midtones.
    - Dither to 1-bit.
    - Trim top/bottom dense/empty bands; crop side whitespace.
    - Add white margins; pad width to multiple of 8.
    """
    if img_gray.mode != "L":
        img_gray = img_gray.convert("L")

    # scale to width
    w, h = img_gray.size
    if w != max_width:
        new_h = int(h * (max_width / w))
        img_gray = img_gray.resize((max_width, new_h), Image.BILINEAR)

    # levels + midtone target
    img_gray = _auto_levels(img_gray)
    mean = ImageStat.Stat(img_gray).mean[0]
    for _ in range(2):
        if mean < target_mean - 12:
            img_gray = _auto_levels(img_gray, black_point=0.04, white_point=0.06, contrast_boost=1.1, gamma=0.9)
        elif mean > target_mean + 12:
            img_gray = _auto_levels(img_gray, black_point=0.06, white_point=0.04, contrast_boost=1.1, gamma=1.1)
        else:
            break
        mean = ImageStat.Stat(img_gray).mean[0]

    # dither to 1-bit
    img_1 = img_gray.convert("1", dither=Image.FLOYDSTEINBERG)

    # trim top/bottom bands and side whitespace
    img_1 = _trim_bands_tb(img_1, black_frac=0.97, white_frac=0.997, max_ratio=0.25)
    img_1 = _crop_whitespace_lr(img_1)

    # add margins (L/R and T/B)
    if margin_px > 0 or margin_tb > 0:
        w, h = img_1.size
        padded = Image.new("1", (w + margin_px*2, h + margin_tb*2), 1)  # white
        padded.paste(img_1, (margin_px, margin_tb))
        img_1 = padded

    # ensure width multiple of 8 (pad with white so it won't print)
    w, h = img_1.size
    pad = (8 - (w % 8)) % 8
    if pad:
        padded = Image.new("1", (w + pad, h), 1)
        padded.paste(img_1, (0, 0))
        img_1 = padded

    # sanity fallback if almost uniform
    white_fraction = ImageStat.Stat(img_1.convert("L")).mean[0] / 255.0
    if white_fraction > 0.98 or white_fraction < 0.02:
        img_gray2 = _auto_levels(img_gray, black_point=0.08, white_point=0.08, contrast_boost=1.25, gamma=1.0)
        img_1 = img_gray2.convert("1", dither=Image.FLOYDSTEINBERG)
        img_1 = _trim_bands_tb(img_1)
        img_1 = _crop_whitespace_lr(img_1)
        
    # ---- enforce minimum final height (pad white at bottom if needed) ----
    w, h = img_1.size
    if h < MIN_FINAL_ROWS:
        pad_h = MIN_FINAL_ROWS - h
        padded = Image.new("1", (w, h + pad_h), 1)  # white
        padded.paste(img_1, (0, 0))
        img_1 = padded


    return img_1

# ====== ESC/POS SEND (adaptive chunking) ======
def send_image_escpos(ip, port, img_1bit, rows_per_chunk=96, base_sleep=0.015, sock_timeout=25):
    """
    Chunked send with adaptive sleep:
    - rows_per_chunk: 64–128 is safe. 96 default.
    - base_sleep: base pause (sec) between chunks; increases for darker bands.
    """
    ESC_INIT       = b"\x1B\x40"     # init
    ESC_2          = b"\x1B\x32"     # default line spacing
    GS_INVERT_OFF  = b"\x1D\x42\x00" # ensure normal (not inverted)
    GS_FULL_CUT    = b"\x1D\x56\x00" # full cut

    w, h = img_1bit.size
    bytes_per_row = (w + 7) // 8

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(sock_timeout)
    s.connect((ip, port))

    try:
        s.sendall(ESC_INIT + ESC_2 + GS_INVERT_OFF)

        y = 0
        while y < h:
            band_h = min(rows_per_chunk, h - y)
            band = img_1bit.crop((0, y, w, y + band_h)).convert("L")

            # measure darkness of this band (0..255)
            mean = ImageStat.Stat(band).mean[0]
            darkness = 1.0 - (mean / 255.0)  # 0=white, 1=black

            # pack bits
            band_data = bytearray()
            for yy in range(band_h):
                byte = 0
                for x in range(w):
                    if band.getpixel((x, yy)) < 128:  # black
                        byte |= (1 << (7 - (x % 8)))
                    if (x % 8) == 7:
                        band_data.append(byte)
                        byte = 0
                if (w % 8) != 0:
                    band_data.append(byte)

            # GS v 0 header for this band (m=0)
            xL = bytes_per_row & 0xFF
            xH = (bytes_per_row >> 8) & 0xFF
            yL = band_h & 0xFF
            yH = (band_h >> 8) & 0xFF
            header = b"\x1D\x76\x30\x00" + bytes([xL, xH, yL, yH])

            # send band
            s.sendall(header + band_data)

            # adaptive sleep: darker bands rest a bit longer (helps stalls/heat)
            pause = base_sleep + (0.06 * darkness)   # up to ~75ms on very dark bands
            time.sleep(pause)

            y += band_h

        # feed a little + cut
        s.sendall(b"\n\n\n" + GS_FULL_CUT)
    finally:
        s.close()

# ====== MAIN ======
def main():
    # Weighted base pick (plasma more common)
    rng_main = np.random.default_rng()
    variant = weighted_pick(rng_main, VARIANTS, WEIGHTS_BASE)

    run_uuid, seed = new_run_seed()
    print(f"Variant: {variant}  |  run id: {run_uuid}  |  seed: {seed}")

    img_gray = generate_image(variant, seed, PRINTER_DOTS)
    img_1bit = prep_for_printer(img_gray, PRINTER_DOTS)

    # Preview + log
    img_1bit.save(PREVIEW_PNG)
    print(f"Saved preview: {PREVIEW_PNG}")
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now().isoformat()}  {run_uuid}  {variant}  {seed}\n")

    # Print
    send_image_escpos(PRINTER_IP, PRINTER_PORT, img_1bit, rows_per_chunk=96, base_sleep=0.015, sock_timeout=25)
    print("Sent to printer.")

if __name__ == "__main__":
    main()
