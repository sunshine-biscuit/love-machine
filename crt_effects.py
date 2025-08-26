"""
crt_effects.py
----------------
Pi‑5‑friendly CRT/post‑processing effects for Love Machine (Pygame).

Drop this file into your project (same folder as your main script or in a
`visuals/` package) and import CRTEffects. Call `crt.apply(screen, dt)` once per
frame *after* you finish drawing your scene.

Effects implemented:
- Scanlines (subtle, resolution‑aware)
- Bloom/glow (fast downsample/upsample + additive)
- Vignette (precomputed radial falloff)
- Rolling flicker band (animated, low amplitude)
- Chromatic aberration (RGB sub‑pixel offsets)

All effects are tuned to be tasteful and efficient on Pi 5 @ 800×480.
You can tweak params at the top of the class.
"""

import math
import pygame

class CRTEffects:
    def __init__(self, size, *, enable_scanlines=True, enable_bloom=True,
                 enable_vignette=True, enable_flicker=True, enable_rgb_shift=True):
        self.w, self.h = size
        self.enable_scanlines = enable_scanlines
        self.enable_bloom = enable_bloom
        self.enable_vignette = enable_vignette
        self.enable_flicker = enable_flicker
        self.enable_rgb_shift = enable_rgb_shift

        # ---- Tunables ----
        # Scanlines: intensity 0..1 (1 = dark lines fully black)
        self.scanline_strength = 0.14
        # Bloom: 0..1 additive strength, and internal blur passes
        self.bloom_strength = 0.28
        self.bloom_downscale = 2  # 2 = half res
        self.bloom_passes = 2     # up/down smoothscale passes (2 is usually enough)
        # Vignette: 0..1 strength (darkening towards edges)
        self.vignette_strength = 0.25
        # Flicker: overall brightness modulation + rolling band
        self.flicker_global_amp = 0.03  # small global brightness wobble
        self.flicker_band_amp   = 0.10  # extra brightness inside the moving band
        self.flicker_band_height_px = max(8, self.h // 14)
        self.flicker_band_speed_px  = max(24, self.h // 3)
        # RGB shift: pixel offsets for R/G/B channels (in pixels)
        self.rgb_shift = (-1, 0, 1)  # R, G, B x‑offsets

        # ---- Precompute reusable layers ----
        self._scan_surface = self._make_scanlines() if enable_scanlines else None
        self._vignette_surface = self._make_vignette() if enable_vignette else None
        # Reusable temp surfaces
        self._temp_black = pygame.Surface((self.w, self.h)).convert()
        self._temp_black.set_colorkey(None)
        self._temp_black.fill((0, 0, 0))
        self._band_surface = pygame.Surface((self.w, self.flicker_band_height_px), pygame.SRCALPHA).convert_alpha()
        self._band_surface.fill((255, 255, 255, int(255 * self.flicker_band_amp)))

    # ---------- Public API ----------
    def apply(self, target_surface: pygame.Surface, dt: float) -> pygame.Surface:
        """Apply CRT effects in place. Returns the processed surface.
        Draw your scene to `target_surface` first, then call this.
        `dt` is seconds since last frame (for animations).
        """
        # Chromatic aberration (fast channel offsets via multiply+add)
        if self.enable_rgb_shift:
            self._apply_rgb_shift(target_surface)

        # Bloom/glow (cheap separable blur by downsample/upsample and additive blend)
        if self.enable_bloom:
            self._apply_bloom(target_surface)

        # Vignette darkening
        if self.enable_vignette:
            target_surface.blit(self._vignette_surface, (0, 0), special_flags=pygame.BLEND_MULT)

        # Scanlines on top
        if self.enable_scanlines:
            target_surface.blit(self._scan_surface, (0, 0), special_flags=pygame.BLEND_MULT)

        # Flicker (subtle global + rolling band)
        if self.enable_flicker:
            self._apply_flicker(target_surface, dt)

        return target_surface

    # ---------- Builders ----------
    def _make_scanlines(self) -> pygame.Surface:
        surf = pygame.Surface((self.w, self.h)).convert()
        surf.fill((255, 255, 255))
        dark = max(0, 255 - int(255 * self.scanline_strength))
        # Darken every other row (or every 2 rows for very tall screens)
        step = 2 if self.h >= 480 else 1
        for y in range(0, self.h, step):
            if (y // step) % 2 == 1:
                pygame.draw.line(surf, (dark, dark, dark), (0, y), (self.w, y))
        return surf

    def _make_vignette(self) -> pygame.Surface:
        vignette = pygame.Surface((self.w, self.h), pygame.SRCALPHA).convert_alpha()
        cx, cy = self.w * 0.5, self.h * 0.5
        max_r = math.hypot(cx, cy)
        # Draw concentric translucent rings (cheap radial falloff)
        rings = 80
        for i in range(rings):
            t = i / (rings - 1)
            # Ease curve for smoother edges
            strength = (t ** 2) * self.vignette_strength
            alpha = int(255 * strength)
            r = int(max_r * t)
            pygame.draw.circle(vignette, (0, 0, 0, alpha), (int(cx), int(cy)), r)
        # Convert to MULT surface by flattening to RGB (premultiply not needed for BLEND_MULT)
        v_rgb = pygame.Surface((self.w, self.h)).convert()
        v_rgb.fill((255, 255, 255))
        v_rgb.blit(vignette, (0, 0), special_flags=pygame.BLEND_SUB)
        return v_rgb

    # ---------- Passes ----------
    def _apply_bloom(self, target_surface: pygame.Surface):
        dw, dh = max(1, self.w // self.bloom_downscale), max(1, self.h // self.bloom_downscale)
        # Downsample
        small = pygame.transform.smoothscale(target_surface, (dw, dh))
        # Blur by ping‑pong smoothscale (cheap Gaussian approximation)
        for _ in range(self.bloom_passes):
            small = pygame.transform.smoothscale(small, (max(1, dw // 2), max(1, dh // 2)))
            small = pygame.transform.smoothscale(small, (dw, dh))
        # Upscale back and additively blend
        blurred = pygame.transform.smoothscale(small, (self.w, self.h))
        # Reduce intensity by modulating alpha via a multiplicative fill
        if self.bloom_strength < 1.0:
            # Multiply the blurred image by a gray to attenuate
            atten = int(255 * self.bloom_strength)
            blurred_mod = blurred.copy()
            blurred_mod.fill((atten, atten, atten), special_flags=pygame.BLEND_MULT)
            target_surface.blit(blurred_mod, (0, 0), special_flags=pygame.BLEND_ADD)
        else:
            target_surface.blit(blurred, (0, 0), special_flags=pygame.BLEND_ADD)

    def _apply_rgb_shift(self, target_surface: pygame.Surface):
        # Build additive composite from R, G, B tinted copies with tiny offsets
        r_off, g_off, b_off = self.rgb_shift
        base = target_surface.copy()
        out = self._temp_black
        out.fill((0, 0, 0))

        r = base.copy(); r.fill((255, 0, 0), special_flags=pygame.BLEND_MULT)
        g = base.copy(); g.fill((0, 255, 0), special_flags=pygame.BLEND_MULT)
        b = base.copy(); b.fill((0, 0, 255), special_flags=pygame.BLEND_MULT)

        out.blit(r, (r_off, 0), special_flags=pygame.BLEND_ADD)
        out.blit(g, (g_off, 0), special_flags=pygame.BLEND_ADD)
        out.blit(b, (b_off, 0), special_flags=pygame.BLEND_ADD)

        target_surface.blit(out, (0, 0))

    def _apply_flicker(self, target_surface: pygame.Surface, dt: float):
    # Global tiny brightness wobble
        t = pygame.time.get_ticks() * 0.001  # seconds
        wobble = (math.sin(t * 13.0) + math.sin(t * 7.1)) * 0.5
        wobble = (wobble * self.flicker_global_amp) + 1.0

    # Clamp to valid 0..255 range for pygame.Surface.fill()
        val = int(255 * wobble)
        if val < 0: val = 0
        if val > 255: val = 255

    # Apply wobble by multiplicative gray overlay
        overlay = self._temp_black
        overlay.fill((val, val, val))
        target_surface.blit(overlay, (0, 0), special_flags=pygame.BLEND_MULT)

    # Rolling horizontal bright band
        y = int((t * self.flicker_band_speed_px) % (self.h + self.flicker_band_height_px)) - self.flicker_band_height_px
        target_surface.blit(self._band_surface, (0, y), special_flags=pygame.BLEND_ADD)

# ---------------- Example integration ----------------
if __name__ == "__main__":
    pygame.init()
    size = (800, 480)
    screen = pygame.display.set_mode(size)
    clock = pygame.time.Clock()

    crt = CRTEffects(size)

    # Demo scene: moving text & gradients
    font = pygame.font.SysFont("Courier New", 28)
    t0 = pygame.time.get_ticks()

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False

        # Draw your UI first
        screen.fill((0, 2, 0))
        # simple moving bars
        for i in range(16):
            y = (i * 30 + (pygame.time.get_ticks() // 6)) % size[1]
            pygame.draw.rect(screen, (0, 40 + i * 7, 0), (0, y, size[0], 12))
        # title
        elapsed = (pygame.time.get_ticks() - t0) / 1000.0
        msg = f"Love Machine • Pi 5 CRT Demo • {elapsed:4.1f}s"
        text = font.render(msg, True, (0, 255, 0))
        screen.blit(text, (20, 20))

        # Apply CRT polish last
        crt.apply(screen, dt)

        pygame.display.flip()

    pygame.quit()
