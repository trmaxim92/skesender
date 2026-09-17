from PIL import Image
from pathlib import Path

src = Path(__file__).resolve().parents[1] / "public" / "brand-icon.png"
out = Path(__file__).resolve().parents[1] / "public"
base = Image.open(src).convert("RGBA")


def resize(size: int) -> Image.Image:
    return base.resize((size, size), Image.Resampling.LANCZOS)


for size, name in [
    (64, "favicon.png"),
    (180, "apple-touch-icon.png"),
    (192, "pwa-192.png"),
    (512, "pwa-512.png"),
]:
    resize(size).save(out / name, "PNG", optimize=True)
    print("wrote", name)


def maskable(size: int, pad_ratio: float = 0.12) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (13, 71, 161, 255))
    inner = int(size * (1 - 2 * pad_ratio))
    icon = resize(inner)
    x = (size - inner) // 2
    y = (size - inner) // 2
    canvas.paste(icon, (x, y), icon)
    return canvas


for size, name in [(192, "pwa-maskable-192.png"), (512, "pwa-maskable-512.png")]:
    maskable(size).save(out / name, "PNG", optimize=True)
    print("wrote", name)

print("done")
