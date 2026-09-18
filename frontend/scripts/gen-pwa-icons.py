"""Generate favicon / PWA icons from sidebar brand mark."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "public"
SRC_ANY = ROOT / "brand-icon.png"
SRC_MASK = ROOT / "brand-icon-maskable.png"
BRAND = (161, 13, 33, 255)  # #a10d21


def load(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def resize(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.Resampling.LANCZOS)


any_base = load(SRC_ANY)
mask_base = load(SRC_MASK) if SRC_MASK.exists() else any_base

for size, name in [
    (64, "favicon.png"),
    (180, "apple-touch-icon.png"),
    (192, "pwa-192.png"),
    (512, "pwa-512.png"),
]:
    resize(any_base, size).save(ROOT / name, "PNG", optimize=True)
    print("wrote", name)


def maskable(size: int) -> Image.Image:
    # Prefer dedicated full-bleed mark; fall back to padded any-icon on brand.
    if SRC_MASK.exists():
        return resize(mask_base, size)
    canvas = Image.new("RGBA", (size, size), BRAND)
    pad = int(size * 0.12)
    inner = size - pad * 2
    icon = resize(any_base, inner)
    canvas.paste(icon, (pad, pad), icon)
    return canvas


for size, name in [(192, "pwa-maskable-192.png"), (512, "pwa-maskable-512.png")]:
    maskable(size).save(ROOT / name, "PNG", optimize=True)
    print("wrote", name)

print("done")
