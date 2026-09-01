"""Generates the InstaCore Sync application icon (.ico + .png).

This is a build-time asset-generation script, not part of the shipped
app — Pillow is a generation-time-only tool (not a runtime dependency).
Run it once to (re)produce:
    src/instacore_sync/ui/resources/icons/app_icon.ico   (multi-resolution, for Windows/PyInstaller)
    src/instacore_sync/ui/resources/icons/app_icon.png   (1024x1024, for docs/tray/Linux dev)

Design: a rounded-square badge in the app's own dark-navy/violet-cyan
accent gradient (see src/instacore_sync/ui/theme/dark_theme.qss) with a
simple upload-arrow-into-cloud glyph — legible down to 16x16, consistent
with the app's own visual identity rather than a generic placeholder.

Usage:
    pip install pillow   # build-time only, not in requirements.txt
    python packaging/generate_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "instacore_sync" / "ui" / "resources" / "icons"

# Matches dark_theme.qss's own palette.
NAVY_DARK = (14, 16, 32, 255)  # #0E1020
NAVY_MID = (19, 21, 41, 255)  # #131529
VIOLET = (124, 131, 253, 255)  # #7C83FD
CYAN = (93, 224, 230, 255)  # #5DE0E6
WHITE = (255, 255, 255, 255)


def _lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))


def _rounded_rect_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def build_icon() -> Image.Image:
    # Background: top-to-bottom navy gradient inside a rounded square.
    gradient = Image.new("RGBA", (SIZE, SIZE))
    for y in range(SIZE):
        row_color = _lerp(NAVY_DARK, NAVY_MID, y / SIZE)
        gradient.paste(row_color, (0, y, SIZE, y + 1))
    # Accent glow: a soft diagonal violet->cyan sweep across the lower-right,
    # composited on top of the navy base for depth without needing per-pixel loops.
    accent = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    accent_draw = ImageDraw.Draw(accent)
    steps = 48
    for i in range(steps):
        t = i / (steps - 1)
        color = _lerp(VIOLET, CYAN, t)
        x0 = int(SIZE * 0.15 + (SIZE * 0.85) * t)
        accent_draw.ellipse(
            [x0 - SIZE * 0.55, SIZE * 0.15, x0 + SIZE * 0.55, SIZE * 1.1],
            fill=(*color[:3], 46),
        )
    gradient = Image.alpha_composite(gradient, accent)

    mask = _rounded_rect_mask(SIZE, radius=int(SIZE * 0.22))
    badge = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    badge.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(badge)

    # Glyph: an upward arrow merging into a rounded "cloud/sync" base —
    # reads as "upload" at a glance, simple enough to survive 16x16.
    cx = SIZE // 2
    arrow_w = SIZE * 0.30
    stem_w = SIZE * 0.10
    tip_y = SIZE * 0.20
    base_y = SIZE * 0.58

    # Arrow stem.
    draw.rounded_rectangle(
        [cx - stem_w / 2, tip_y + SIZE * 0.10, cx + stem_w / 2, base_y],
        radius=int(stem_w / 2),
        fill=WHITE,
    )
    # Arrow head (triangle).
    draw.polygon(
        [
            (cx, tip_y),
            (cx - arrow_w / 2, tip_y + SIZE * 0.18),
            (cx + arrow_w / 2, tip_y + SIZE * 0.18),
        ],
        fill=WHITE,
    )
    # Cloud base: three overlapping circles + a rounded rectangle underline.
    cloud_y = SIZE * 0.66
    cloud_r = SIZE * 0.135
    for dx, r_scale in ((-0.19, 0.85), (0.0, 1.0), (0.20, 0.85)):
        r = cloud_r * r_scale
        x = cx + SIZE * dx
        draw.ellipse([x - r, cloud_y - r, x + r, cloud_y + r], fill=WHITE)
    draw.rounded_rectangle(
        [cx - SIZE * 0.30, cloud_y, cx + SIZE * 0.30, cloud_y + SIZE * 0.14],
        radius=int(SIZE * 0.07),
        fill=WHITE,
    )

    return badge


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = build_icon()

    png_path = OUT_DIR / "app_icon.png"
    icon.save(png_path, format="PNG")

    ico_path = OUT_DIR / "app_icon.ico"
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(ico_path, format="ICO", sizes=ico_sizes)

    print(f"Wrote {png_path} ({icon.size[0]}x{icon.size[1]})")
    print(f"Wrote {ico_path} (sizes: {ico_sizes})")


if __name__ == "__main__":
    main()
