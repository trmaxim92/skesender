from PIL import Image
from pathlib import Path

src = Path(r"c:\order-elite\frontend\public\oe-notify-icon.png")
out = Path(r"c:\order-elite\frontend\public")
base = Image.open(src).convert("RGBA")


def resize(size: int) -> Image.Image:
    return base.resize((size, size), Image.Resampling.LANCZOS)


for size, name in [(192, "pwa-192.png"), (512, "pwa-512.png"), (180, "apple-touch-icon.png")]:
    resize(size).save(out / name, "PNG")
    print("wrote", name)


def maskable(size: int, pad_ratio: float = 0.18) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (26, 109, 255, 255))
    inner = int(size * (1 - 2 * pad_ratio))
    icon = resize(inner)
    x = (size - inner) // 2
    y = (size - inner) // 2
    canvas.paste(icon, (x, y), icon)
    return canvas


for size, name in [(192, "pwa-maskable-192.png"), (512, "pwa-maskable-512.png")]:
    maskable(size).save(out / name, "PNG")
    print("wrote", name)

print("done")
