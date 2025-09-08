#!/usr/bin/env python3
# Generative art -> preview -> Epson TM-T88 over TCP:9100 (ESC/POS raster)
# Goal: distinctive, varied, layered prints with curated "styles".
# - Random style recipes with different weights + blending.
# - 2–3 layers typical (style-dependent), avoids muddy stacks.
# - Header ("name — trait") above art; consistent-ish height.
# - Socket-based printing (no python-escpos).

import os, socket, uuid, math, time, random, sys, argparse
from datetime import datetime

import numpy as np
from PIL import (
    Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance, ImageStat, ImageChops, ImageFont
)

# ====== CONFIG ======
PRINTER_IP   = "192.168.192.168"   # <-- your printer IP
PRINTER_PORT = 9100
PRINTER_DOTS = 512
PREVIEW_PNG  = "last-art-preview.png"
LOG_FILE     = "printed-art-ids.txt"

# ---- Height guards ----
MIN_BASE_HEIGHT   = int(os.getenv("LM_MIN_BASE_HEIGHT", "900"))
MIN_FINAL_ROWS    = int(os.getenv("LM_MIN_FINAL_ROWS", "900"))

# ---- Header ----
HEADER_FONT_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), "assets", "Px437_IBM_DOS_ISO8.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
]
HEADER_FONT_SIZE = 32
HEADER_LEFT = 12
HEADER_TOP  = 12
HEADER_BOTTOM_GAP = 22

def _load_header_font():
    for p in HEADER_FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, HEADER_FONT_SIZE)
            except Exception:
                pass
    return ImageFont.load_default()

# ====== VARIANTS ======
VARIANTS = ["noise","lines","shapes","strokes","plasma","life","halftone","burst","maze"]

# ====== STYLE RECIPES ======
STYLES = {
    "distinctive": {
        "base": {"plasma":0.18,"lines":0.18,"strokes":0.16,"noise":0.14,"life":0.12,"halftone":0.12,"shapes":0.06,"burst":0.03,"maze":0.01},
        "alt":  {"plasma":0.14,"lines":0.20,"strokes":0.18,"noise":0.14,"life":0.12,"halftone":0.16,"shapes":0.04,"burst":0.02,"maze":0.00},
        "layer_prob": 0.75, "layers": (2,3),
        "mode_probs": {"screen":0.5,"multiply":0.35,"add":0.15},
        "opacity": (0.42, 0.78),
        "plasma_oversample": 3.0
    },
    "graphic": {
        "base": {"plasma":0.10,"lines":0.24,"strokes":0.20,"noise":0.16,"halftone":0.16,"life":0.06,"shapes":0.05,"burst":0.02,"maze":0.01},
        "alt":  {"plasma":0.08,"lines":0.28,"strokes":0.22,"noise":0.16,"halftone":0.18,"life":0.04,"shapes":0.03,"burst":0.01,"maze":0.00},
        "layer_prob": 0.8, "layers": (2,3),
        "mode_probs": {"screen":0.35,"multiply":0.50,"add":0.15},
        "opacity": (0.40, 0.72),
        "plasma_oversample": 2.6
    },
    "cloudy": {
        "base": {"plasma":0.30,"lines":0.10,"strokes":0.10,"noise":0.14,"life":0.12,"halftone":0.12,"shapes":0.04,"burst":0.06,"maze":0.02},
        "alt":  {"plasma":0.20,"lines":0.12,"strokes":0.12,"noise":0.18,"life":0.14,"halftone":0.16,"shapes":0.03,"burst":0.04,"maze":0.01},
        "layer_prob": 0.7, "layers": (2,3),
        "mode_probs": {"screen":0.6,"multiply":0.25,"add":0.15},
        "opacity": (0.38, 0.70),
        "plasma_oversample": 3.4
    },
    "structured": {
        "base": {"plasma":0.12,"lines":0.20,"strokes":0.12,"noise":0.12,"life":0.08,"halftone":0.14,"shapes":0.06,"burst":0.06,"maze":0.10},
        "alt":  {"plasma":0.10,"lines":0.22,"strokes":0.14,"noise":0.12,"life":0.08,"halftone":0.18,"shapes":0.05,"burst":0.06,"maze":0.05},
        "layer_prob": 0.75, "layers": (2,3),
        "mode_probs": {"screen":0.45,"multiply":0.40,"add":0.15},
        "opacity": (0.40, 0.74),
        "plasma_oversample": 2.8
    },
    "minimal": {
        "base": {"plasma":0.12,"lines":0.18,"strokes":0.16,"noise":0.18,"life":0.10,"halftone":0.16,"shapes":0.04,"burst":0.04,"maze":0.02},
        "alt":  {"plasma":0.10,"lines":0.20,"strokes":0.18,"noise":0.18,"life":0.10,"halftone":0.18,"shapes":0.03,"burst":0.02,"maze":0.01},
        "layer_prob": 0.6, "layers": (1,2),
        "mode_probs": {"screen":0.5,"multiply":0.35,"add":0.15},
        "opacity": (0.36, 0.62),
        "plasma_oversample": 2.4
    },
}
STYLE_NAMES = list(STYLES.keys())

def _pick(distr: dict, rng):
    keys = list(distr.keys())
    w = np.array([distr[k] for k in keys], dtype=np.float64)
    w = w / (w.sum() if w.sum() > 0 else 1.0)
    idx = int(rng.choice(len(keys), p=w))
    return keys[idx]

def _pick_variant(rng, weights):
    return _pick(weights, rng)

def _pick_mode(rng, mode_probs):
    return _pick(mode_probs, rng)

def new_run_seed():
    u = uuid.uuid4()
    return u, u.int & 0xFFFFFFFF

# ====== GENERATORS ======
def gen_noise(seed, w, h):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
    img = Image.fromarray(base, "L").filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.6)))
    shift = rng.integers(80, 120); gain  = rng.uniform(1.4, 1.8)
    img = Image.eval(img, lambda p: int(max(0, min(255, (p - shift) * gain))))
    return img

def gen_lines(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255); d = ImageDraw.Draw(img)
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
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.9)))

def gen_shapes(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255); d = ImageDraw.Draw(img)
    count = rng.randint(8, 24)
    for _ in range(count):
        x1, y1 = rng.randrange(w), rng.randrange(h)
        x2 = min(w-1, x1 + rng.randrange(8, max(10, w//4)))
        y2 = min(h-1, y1 + rng.randrange(8, max(10, h//4)))
        fill = rng.randint(50, 200)
        (d.rectangle if rng.random()<0.5 else d.ellipse)([x1, y1, x2, y2], fill=fill)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.5, 1.0)))

def gen_strokes(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 255); d = ImageDraw.Draw(img)
    n = rng.randint(800, 1600)
    for _ in range(n):
        x = rng.randrange(w); y = rng.randrange(h)
        length = rng.randint(4, 22); angle = rng.uniform(0, 2*math.pi)
        dx = int(length * math.cos(angle)); dy = int(length * math.sin(angle))
        grey = rng.randint(10, 160)
        d.line([(x, y), (x+dx, y+dy)], fill=grey, width=rng.randint(1, 2))
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))

def gen_plasma(seed, w, h, oversample=3.0):
    rng = np.random.default_rng(seed)
    W, H = int(w * oversample), int(h * oversample)
    def smooth_rand_grid(width, height, cells_x, cells_y):
        grid = (rng.random((cells_y, cells_x)) * 255).astype(np.uint8)
        return Image.fromarray(grid, "L").resize((width, height), Image.BICUBIC)
    base_cells_x = max(6, int(W / rng.uniform(220, 300)))
    base_cells_y = max(6, int(H / rng.uniform(220, 300)))
    octaves      = int(rng.integers(5, 7))
    lacunarity   = float(rng.uniform(1.8, 2.1))
    persistence  = float(rng.uniform(0.50, 0.62))
    acc = np.zeros((H, W), dtype=np.float32); amp = 1.0
    cells_x, cells_y = base_cells_x, base_cells_y
    for _ in range(octaves):
        layer = np.asarray(smooth_rand_grid(W, H, cells_x, cells_y), dtype=np.float32) / 255.0
        acc += layer * amp
        amp *= persistence
        cells_x = min(max(6, int(cells_x * lacunarity)), max(36, W // 22))
        cells_y = min(max(6, int(cells_y * lacunarity)), max(36, H // 22))
    mn, mx = acc.min(), acc.max()
    field = (acc - mn) / (mx - mn + 1e-9)
    field = np.clip(field, 0.0, 1.0) ** 0.85
    field = 0.6 * field + 0.4 * (field * (1.0 - field) * 4.0)
    cloud = (field * 255.0).astype(np.uint8)
    img = Image.fromarray(cloud, "L").filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.25, 0.55))))
    return img.resize((w, h), Image.LANCZOS)

def gen_life(seed, w, h):
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
    img = Image.fromarray(np.clip(density * 255, 0, 255).astype(np.uint8), "L")
    img = img.resize((w, h), Image.NEAREST)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.7)))

def gen_halftone(seed, w, h):
    rng = np.random.default_rng(seed)
    base = gen_plasma(int(seed), w, h, oversample=2.6) if rng.random() < 0.6 else gen_noise(int(seed), w, h)
    cell = int(rng.integers(6, 12))
    img = Image.new("L", (w, h), 255); d = ImageDraw.Draw(img)
    jitter = rng.uniform(0.0, 0.25)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            crop = base.crop((x, y, min(x+cell, w), min(y+cell, h))).resize((1,1), Image.BILINEAR)
            val = crop.getpixel((0,0))
            darkness = 1.0 - (val / 255.0)
            r = darkness * (cell * 0.5)
            if r <= 0.2: continue
            jx = int((rng.random() - 0.5) * jitter * cell)
            jy = int((rng.random() - 0.5) * jitter * cell)
            cx = x + cell//2 + jx; cy = y + cell//2 + jy
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=int(40 + 160*darkness))
    return img

def gen_radial_burst(seed, w, h):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 245); d = ImageDraw.Draw(img)
    cx = rng.randint(int(w*0.2), int(w*0.8)); cy = rng.randint(int(h*0.2), int(h*0.8))
    rays = rng.randint(50, 160); maxlen = int(max(w, h) * 1.1); base_grey = rng.randint(40, 120)
    for i in range(rays):
        angle = (2*math.pi) * (i / rays) + rng.uniform(-0.03, 0.03)
        length = int(maxlen * rng.uniform(0.6, 1.0))
        x2 = int(cx + length * math.cos(angle)); y2 = int(cy + length * math.sin(angle))
        width = rng.randint(1, 3); g = min(200, max(30, int(base_grey + rng.uniform(-30, 30))))
        d.line([(cx, cy), (x2, y2)], fill=g, width=width)
    return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.8)))

def gen_maze(seed, w, h):
    rng = np.random.default_rng(seed)

    # choose grid density, then ensure odd dimensions
    cols = max(17, w // int(rng.integers(18, 28)))
    rows = max(17, h // int(rng.integers(18, 28)))
    if cols % 2 == 0: cols -= 1
    if rows % 2 == 0: rows -= 1

    grid = np.zeros((rows, cols), dtype=np.uint8)
    visited = np.zeros_like(grid, dtype=bool)

    # cardinal directions (step by 2 in the carving phase)
    dirs = [(1,0), (-1,0), (0,1), (0,-1)]

    def nbs(r, c):
        out = []
        for dr, dc in dirs:
            nr, nc = r + 2*dr, c + 2*dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc]:
                out.append((nr, nc, dr, dc))
        rng.shuffle(out)
        return out

    # start on a guaranteed odd cell strictly inside bounds
    r0 = 2 * int(rng.integers(0, rows // 2)) + 1
    c0 = 2 * int(rng.integers(0, cols // 2)) + 1
    r0 = min(rows - 2, max(1, r0))
    c0 = min(cols - 2, max(1, c0))

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
        grid[r + dr, c + dc] = 1  # carve connector
        grid[nr, nc] = 1         # carve next cell
        visited[nr, nc] = True
        stack.append((nr, nc))

    # render the maze to image
    cell = int(rng.integers(4, 7))
    img = Image.new("L", (cols * cell, rows * cell), 0)
    px = img.load()
    for y in range(rows):
        for x in range(cols):
            if grid[y, x]:
                for yy in range(y * cell, (y + 1) * cell):
                    for xx in range(x * cell, (x + 1) * cell):
                        px[xx, yy] = 220
    img = img.resize((w, h), Image.NEAREST)
    return img.filter(ImageFilter.GaussianBlur(radius=float(rng.uniform(0.4, 0.9))))

# ====== COMPOSITOR / STYLE ENGINE ======
def random_flip_rotate(img, rng):
    if rng.random() < 0.5: img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if rng.random() < 0.5: img = img.transpose(Image.FLIP_TOP_BOTTOM)
    k = int(rng.integers(0, 4))
    if k: img = img.rotate(90 * k, expand=False)
    return img

def _normalize_layer(img_l):
    img_l = ImageOps.autocontrast(img_l, cutoff=(2, 2))
    img_l = ImageEnhance.Contrast(img_l).enhance(1.05)
    return img_l

def blend_layers(a, b, mode, opacity):
    a = a.convert("L"); b = _normalize_layer(b.convert("L"))
    if mode == "multiply": mixed = ImageChops.multiply(a, b)
    elif mode == "add":    mixed = ImageChops.add(a, b)
    else:                  mixed = ImageChops.screen(a, b)
    return Image.blend(a, mixed, opacity) if opacity < 1.0 else mixed

def _make_layer(variant, seed, w, h, style):
    if variant == "noise":     return gen_noise(seed, w, h)
    if variant == "lines":     return gen_lines(int(seed), w, h)
    if variant == "shapes":    return gen_shapes(int(seed), w, h)
    if variant == "strokes":   return gen_strokes(int(seed), w, h)
    if variant == "plasma":    return gen_plasma(int(seed), w, h, oversample=style["plasma_oversample"])
    if variant == "life":      return gen_life(int(seed), w, h)
    if variant == "halftone":  return gen_halftone(int(seed), w, h)
    if variant == "burst":     return gen_radial_burst(int(seed), w, h)
    if variant == "maze":      return gen_maze(int(seed), w, h)
    return gen_noise(seed, w, h)

def generate_image(style_name, seed, target_width):
    rng = np.random.default_rng(seed)
    style = STYLES[style_name]
    base_h = max(MIN_BASE_HEIGHT, int(target_width * rng.uniform(1.7, 2.0)))

    base_variant = _pick_variant(rng, style["base"])
    base = _make_layer(base_variant, seed, target_width, base_h, style)
    base = random_flip_rotate(base, rng)

    if rng.random() < style["layer_prob"]:
        min_l, max_l = style["layers"]
        layer_count = int(rng.integers(min_l, max_l+1))
        used = {base_variant:1}
        img = base
        for _ in range(layer_count):
            alt_variant = _pick_variant(rng, style["alt"])
            if (base_variant == "plasma" and alt_variant == "plasma") or used.get(alt_variant,0) >= 1:
                tries = 0
                while ((alt_variant == base_variant) or (alt_variant == "plasma" and base_variant == "plasma") or used.get(alt_variant,0)>=1) and tries < 5:
                    alt_variant = _pick_variant(rng, style["alt"]); tries += 1
            used[alt_variant] = used.get(alt_variant,0) + 1

            layer_seed = (seed + int(rng.integers(1000, 9999))) & 0xFFFFFFFF
            layer = _make_layer(alt_variant, layer_seed, target_width, base_h, style)
            layer = random_flip_rotate(layer, rng)

            mode = _pick_mode(rng, style["mode_probs"])
            opacity = float(rng.uniform(*style["opacity"]))
            img = blend_layers(img, layer, mode, opacity)
    else:
        img = base

    if rng.random() < 0.65:
        w_, h_ = img.size
        cx, cy = w_//2, h_//2
        maxr = float(math.hypot(cx, cy))
        mask = Image.new("L", (w_, h_), 0); mp = mask.load()
        strength = float(rng.uniform(0.35, 0.60))
        for y in range(h_):
            for x in range(w_):
                r = math.hypot(x - cx, y - cy) / maxr
                mp[x, y] = int(255 * min(1.0, (r*r)))
        if strength < 1.0:
            mask = Image.blend(Image.new("L", (w_, h_), 0), mask, strength)
        img = Image.composite(Image.new("L", (w_, h_), 255), img, mask)

    return img

# ====== PREP / TRIM / DITHER ======
def _auto_levels(img, black_point=0.05, white_point=0.05, contrast_boost=1.15, gamma=0.95):
    img = ImageOps.autocontrast(img, cutoff=(int(black_point*100), int(white_point*100)))
    img = ImageEnhance.Contrast(img).enhance(contrast_boost)
    lut = [min(255, max(0, int((i/255.0) ** gamma * 255))) for i in range(256)]
    return img.point(lut)

def _crop_whitespace_lr(img):
    tmp = img.convert("L")
    w, h = tmp.size
    px = tmp.load()
    left = next((x for x in range(w) if any(px[x,y] < 250 for y in range(h))), 0)
    right = next((x for x in range(w-1, -1, -1) if any(px[x,y] < 250 for y in range(h))), w-1)
    return img.crop((left, 0, right+1, h)) if right > left else img

def _trim_bands_tb(img, black_frac=0.97, white_frac=0.997, max_ratio=0.25):
    g = img.convert("L"); w, h = g.size; max_trim = int(h * max_ratio)
    def row_black_fraction(y): return 1.0 - (ImageStat.Stat(g.crop((0,y,w,y+1))).mean[0]/255.0)
    top, bottom = 0, h
    for y in range(h):
        if y>=max_trim: break
        bf = row_black_fraction(y); wf = 1.0-bf
        if bf>=black_frac or wf>=white_frac: top = y+1
        else: break
    for y in range(h-1,-1,-1):
        if (h-1-y)>=max_trim: break
        bf=row_black_fraction(y); wf=1.0-bf
        if bf>=black_frac or wf>=white_frac: bottom=y
        else: break
    return img.crop((0,top,w,bottom)) if bottom>top else img

def prep_for_printer(img_gray, max_width, target_mean=140, margin_px=8, margin_tb=6):
    if img_gray.mode!="L": img_gray=img_gray.convert("L")
    w,h=img_gray.size
    if w!=max_width:
        img_gray=img_gray.resize((max_width,int(h*(max_width/w))),Image.BILINEAR)
    img_gray=_auto_levels(img_gray)
    m = ImageStat.Stat(img_gray).mean[0]
    if m < target_mean-12: img_gray=_auto_levels(img_gray,0.04,0.06,1.1,0.9)
    elif m > target_mean+12: img_gray=_auto_levels(img_gray,0.06,0.04,1.1,1.1)

    img_1=img_gray.convert("1",dither=Image.FLOYDSTEINBERG)
    img_1=_trim_bands_tb(img_1); img_1=_crop_whitespace_lr(img_1)

    if margin_px>0 or margin_tb>0:
        w,h=img_1.size
        pad=Image.new("1",(w+margin_px*2,h+margin_tb*2),1)
        pad.paste(img_1,(margin_px,margin_tb)); img_1=pad

    w,h=img_1.size; pad=(8-(w%8))%8
    if pad:
        padded=Image.new("1",(w+pad,h),1); padded.paste(img_1,(0,0)); img_1=padded

    if h<MIN_FINAL_ROWS:
        pad_h=MIN_FINAL_ROWS-h
        padded=Image.new("1",(w,h+pad_h),1); padded.paste(img_1,(0,0)); img_1=padded

    return img_1

# ====== ESC/POS SEND ======
def send_image_escpos(ip, port, img_1bit, rows_per_chunk=96, base_sleep=0.015, sock_timeout=25):
    ESC_INIT=b"\x1B\x40"; ESC_2=b"\x1B\x32"; GS_INVERT_OFF=b"\x1D\x42\x00"; GS_FULL_CUT=b"\x1D\x56\x00"
    w,h=img_1bit.size; bpr=(w+7)//8
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(sock_timeout); s.connect((ip,port))
    try:
        s.sendall(ESC_INIT+ESC_2+GS_INVERT_OFF)
        y=0
        while y<h:
            bh=min(rows_per_chunk,h-y)
            band=img_1bit.crop((0,y,w,y+bh)).convert("L")
            band_data=bytearray()
            for yy in range(bh):
                byte=0
                for x in range(w):
                    if band.getpixel((x,yy))<128: byte|=(1<<(7-(x%8)))
                    if (x%8)==7: band_data.append(byte); byte=0
                if (w%8)!=0: band_data.append(byte)
            header=b"\x1D\x76\x30\x00"+bytes([bpr&0xFF,(bpr>>8)&0xFF,bh&0xFF,(bh>>8)&0xFF])
            s.sendall(header+band_data)
            darkness=1.0-(ImageStat.Stat(band).mean[0]/255.0)
            time.sleep(base_sleep+(0.06*darkness))
            y+=bh
        s.sendall(b"\n\n\n"+GS_FULL_CUT)
    finally:
        s.close()

# ====== CLI ======
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="", help="Participant name (printed in header)")
    p.add_argument("--trait", default="", help="Assigned trait (printed in header)")
    p.add_argument("--style", default="", help=f"Force style: one of {', '.join(STYLE_NAMES)}")
    # NEW: archetype support
    p.add_argument("--archetype", default="", help="Quiz archetype (printed in header)")
    return p.parse_args()

# ====== MAIN ======
def main():
    args = parse_args()
    name = (args.name or "Participant").strip().upper()
    trait = (args.trait or "Curious").strip().upper()
    archetype = (getattr(args, "archetype", "") or "").strip().upper()
    force_style = (args.style or "").strip().lower()

    rng=np.random.default_rng()
    style_name = force_style if force_style in STYLES else random.choice(STYLE_NAMES)
    run_uuid,seed=new_run_seed()
    print(f"Style: {style_name} | run id: {run_uuid} | seed: {seed} | name: {name} | trait: {trait}" + (f" | archetype: {archetype}" if archetype else ""))

    # Generate art and compose header
    art = generate_image(style_name, seed, PRINTER_DOTS)
    font = _load_header_font()

    # Build up to 3 header lines: Name / Trait / Archetype (only non-empty shown)
    header_lines = [name] if name else []
    if trait:
        header_lines.append(trait)
    if archetype:
        header_lines.append(archetype)

    # Measure total header height (line by line)
    LINE_GAP = 6
    y = HEADER_TOP
    line_heights = []
    for ln in header_lines:
        bbox = font.getbbox(ln) if ln else None
        lh = (bbox[3] - bbox[1]) if bbox else (HEADER_FONT_SIZE + 6)
        line_heights.append(lh)

    header_h = sum(line_heights) + (LINE_GAP * max(0, len(header_lines) - 1))
    header_total = y + header_h + HEADER_BOTTOM_GAP

    canvas_h = max(MIN_BASE_HEIGHT, art.height + header_total)
    canvas = Image.new("L", (PRINTER_DOTS, canvas_h), 255)
    d = ImageDraw.Draw(canvas)

    # Draw each header line
    y = HEADER_TOP
    for i, ln in enumerate(header_lines):
        d.text((HEADER_LEFT, y), ln, font=font, fill=0)
        y += line_heights[i]
        if i < len(header_lines) - 1:
            y += LINE_GAP

    # Paste art underneath header
    canvas.paste(art, (0, header_total))

    # Prep, save, log, print
    img_1=prep_for_printer(canvas,PRINTER_DOTS)
    img_1.save(PREVIEW_PNG); print(f"Saved preview: {PREVIEW_PNG}")
    with open(LOG_FILE,"a") as f:
        f.write(
            f"{datetime.now().isoformat()}  {run_uuid}  style={style_name}  seed={seed}  "
            f"name={name}  trait={trait}" + (f"  archetype={archetype}" if archetype else "") + "\n"
        )
    send_image_escpos(PRINTER_IP,PRINTER_PORT,img_1); print("Sent to printer.")

if __name__ == "__main__":
    main()
