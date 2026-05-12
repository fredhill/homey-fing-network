#!/usr/bin/env python3
"""
Generate Fing Network Monitor banner images (small, large, xlarge) for Homey store.

Sizes:
  xlarge: 2000 × 750  (banner ratio)
  large:  1000 × 375
  small:   500 × 188
"""

import math
import os
from PIL import Image, ImageDraw, ImageFont

# ─── Palette ──────────────────────────────────────────────────────────────────
BG_DARK    = (13,  17,  23)      # #0d1117
BG_MID     = (22,  27,  34)      # #161b22
TEAL       = (0, 176, 176)       # #00b0b0
TEAL_DIM   = (0, 176, 176, 60)   # teal at 24% alpha
TEAL_MID   = (0, 176, 176, 120)  # teal at 47%
WHITE      = (255, 255, 255)
TEAL_TEXT  = (0, 208, 208)       # #00d0d0 — tagline / pills

FONT_BOLD   = "/System/Library/Fonts/HelveticaNeue.ttc"
FONT_MEDIUM = "/System/Library/Fonts/HelveticaNeue.ttc"


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def draw_glow_circle(draw, cx, cy, max_r, color, steps=20):
    """Draw a soft radial glow."""
    for i in range(steps, 0, -1):
        r     = int(max_r * i / steps)
        alpha = int(55 * (1 - i / steps) ** 1.5)
        rgba  = color + (alpha,)
        bbox  = (cx - r, cy - r, cx + r, cy + r)
        draw.ellipse(bbox, fill=rgba)


def build_banner(W, H):
    img  = Image.new("RGB", (W, H), BG_DARK)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    gdraw = ImageDraw.Draw(glow)

    # ── Background gradient (vertical, subtle) ─────────────────────────────
    for y in range(H):
        t = y / H
        c = lerp_color(BG_DARK, BG_MID, t * 0.6)
        draw.line([(0, y), (W, y)], fill=c)

    # ── Network topology — left third of canvas ─────────────────────────────
    cx = int(W * 0.155)
    cy = H // 2
    r1 = int(H * 0.30)   # first ring radius
    r2 = int(H * 0.50)   # outer ring radius

    # Spoke angles
    angles_inner = [30, 90, 150, 210, 270, 330]
    angles_outer = [0, 60, 120, 180, 240, 300]

    inner_nodes = [
        (cx + int(r1 * math.cos(math.radians(a))),
         cy + int(r1 * math.sin(math.radians(a))))
        for a in angles_inner
    ]
    outer_nodes = [
        (cx + int(r2 * math.cos(math.radians(a))),
         cy + int(r2 * math.sin(math.radians(a))))
        for a in angles_outer
    ]

    # Outer → inner edges (very faint)
    for (ox, oy), (ix, iy) in zip(outer_nodes, inner_nodes):
        draw.line([(ox, oy), (ix, iy)],
                  fill=(0, 80, 80), width=max(1, W // 1000))

    # Inner → centre edges
    for ix, iy in inner_nodes:
        draw.line([(ix, iy), (cx, cy)],
                  fill=(0, 130, 130), width=max(1, W // 800))

    # Inner ring cross-connects (hexagon outline)
    for i in range(len(inner_nodes)):
        a = inner_nodes[i]
        b = inner_nodes[(i + 1) % len(inner_nodes)]
        draw.line([a, b], fill=(0, 100, 100), width=max(1, W // 1200))

    # Glow behind centre hub
    draw_glow_circle(gdraw, cx, cy, int(H * 0.45), TEAL)
    img.paste(glow, mask=glow)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)

    # Outer nodes
    nr_outer = max(4, W // 200)
    for ox, oy in outer_nodes:
        if 0 <= ox <= W and 0 <= oy <= H:
            draw.ellipse(
                (ox - nr_outer, oy - nr_outer, ox + nr_outer, oy + nr_outer),
                fill=(0, 80, 80)
            )

    # Inner ring nodes
    nr_inner = max(6, W // 130)
    for ix, iy in inner_nodes:
        # Halo
        draw.ellipse(
            (ix - nr_inner*2, iy - nr_inner*2, ix + nr_inner*2, iy + nr_inner*2),
            fill=(0, 50, 50)
        )
        # Core
        draw.ellipse(
            (ix - nr_inner, iy - nr_inner, ix + nr_inner, iy + nr_inner),
            fill=TEAL
        )

    # Centre hub
    hub_r = max(14, W // 80)
    # Outer ring
    draw.ellipse(
        (cx - hub_r*2, cy - hub_r*2, cx + hub_r*2, cy + hub_r*2),
        fill=(0, 60, 60)
    )
    # Ring
    draw.ellipse(
        (cx - hub_r - 3, cy - hub_r - 3, cx + hub_r + 3, cy + hub_r + 3),
        fill=(0, 130, 130)
    )
    # Core
    draw.ellipse(
        (cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r),
        fill=TEAL
    )

    # ── Vertical separator line ─────────────────────────────────────────────
    sep_x  = int(W * 0.32)
    sep_y1 = int(H * 0.15)
    sep_y2 = int(H * 0.85)
    draw.line([(sep_x, sep_y1), (sep_x, sep_y2)],
              fill=(0, 100, 100, 80), width=max(1, W // 1200))

    # ── Text block ──────────────────────────────────────────────────────────
    tx = int(W * 0.35)

    # App title
    title_size = max(20, H // 8)
    try:
        font_title = ImageFont.truetype(FONT_BOLD, title_size, index=1)
    except Exception:
        font_title = ImageFont.load_default()

    draw.text((tx, int(H * 0.20)), "Fing Network Monitor",
              font=font_title, fill=WHITE)

    # Tagline
    tag_size = max(12, H // 18)
    try:
        font_tag = ImageFont.truetype(FONT_MEDIUM, tag_size, index=0)
    except Exception:
        font_tag = ImageFont.load_default()

    draw.text((tx + 2, int(H * 0.47)),
              "Real-time presence detection for every device on your network",
              font=font_tag, fill=TEAL_TEXT)

    # Thin divider under tagline
    div_y = int(H * 0.62)
    draw.line([(tx, div_y), (int(W * 0.93), div_y)],
              fill=(0, 100, 100), width=max(1, W // 1200))

    # Feature pills
    pill_size = max(9, H // 26)
    try:
        font_pill = ImageFont.truetype(FONT_MEDIUM, pill_size, index=0)
    except Exception:
        font_pill = ImageFont.load_default()

    pills = ["Presence Detection", "Unknown Device Alerts", "Powered by Fingbox"]
    pill_x = tx
    pill_y = int(H * 0.67)
    pill_h = max(20, H // 16)
    pill_pad_x = max(10, W // 100)
    pill_gap   = max(8, W // 150)

    for label in pills:
        bbox   = font_pill.getbbox(label)
        pw     = bbox[2] - bbox[0] + pill_pad_x * 2
        rx1, ry1 = pill_x, pill_y
        rx2, ry2 = pill_x + pw, pill_y + pill_h
        radius = pill_h // 2

        # Pill background (semi-transparent teal)
        pill_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pdraw    = ImageDraw.Draw(pill_img)
        pdraw.rounded_rectangle(
            [(rx1, ry1), (rx2, ry2)],
            radius=radius,
            fill=(0, 176, 176, 35),
            outline=(0, 176, 176, 100),
            width=max(1, W // 1200)
        )
        img.paste(pill_img, mask=pill_img)

        # Pill text
        text_y = pill_y + (pill_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((pill_x + pill_pad_x, text_y), label,
                  font=font_pill, fill=TEAL_TEXT)

        pill_x += pw + pill_gap

    return img


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "images")
    os.makedirs(out_dir, exist_ok=True)

    sizes = {
        "xlarge": (2000, 750),
        "large":  (1000, 375),
        "small":  ( 500, 188),
    }

    for name, (W, H) in sizes.items():
        print(f"  Generating {name}.png ({W}×{H})…")
        img = build_banner(W, H)
        path = os.path.join(out_dir, f"{name}.png")
        img.save(path, "PNG", optimize=True)
        print(f"  ✓ Saved {path}")

    print("Done.")


if __name__ == "__main__":
    main()
