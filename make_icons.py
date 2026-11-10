from PIL import Image, ImageDraw

SRC = "app/static/logo.png"
OUT = "app/static"
TILT = -40  # degrees; negative leans the wrench to the right


def gradient_tile(size):
    g = Image.new("RGBA", (size, size))
    px = g.load()
    c1, c2 = (99, 102, 241), (34, 211, 238)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
    g.putalpha(mask)
    return g


def make(size, name, fill=0.8):
    tile = gradient_tile(size)
    wrench = Image.open(SRC).convert("RGBA")
    wrench = wrench.crop(wrench.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox())
    target = int(size * fill)
    wrench.thumbnail((target, target), Image.LANCZOS)
    pad = Image.new("RGBA", (target + 4, target + 4), (0, 0, 0, 0))
    pad.paste(wrench, ((pad.width - wrench.width) // 2, (pad.height - wrench.height) // 2), wrench)
    rotated = pad.rotate(TILT, resample=Image.BICUBIC, expand=True)
    rotated.thumbnail((int(size * 0.86), int(size * 0.86)), Image.LANCZOS)
    tile.alpha_composite(rotated, ((size - rotated.width) // 2, (size - rotated.height) // 2))
    tile.save(f"{OUT}/{name}")
    print("created", f"{OUT}/{name}")


make(64, "favicon.png")
make(180, "apple-touch-icon.png")