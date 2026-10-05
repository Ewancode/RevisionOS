"""Draw the app icons (the same design as public/icon.svg) as PNGs.

Run from the backend's environment, which has Pillow:
    cd backend && uv run python ../frontend/scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

PUBLIC = Path(__file__).resolve().parents[1] / "public"
ACCENT = (79, 70, 229)
WHITE = (255, 255, 255)
PALE = (224, 231, 255)


def cubic(p0, p1, p2, p3, n=16):  # type: ignore[no-untyped-def]
    """Points along a cubic Bezier curve, as in the SVG path."""
    return [
        tuple(
            (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t**2 * c + t**3 * d
            for a, b, c, d in zip(p0, p1, p2, p3, strict=True)
        )
        for t in (i / n for i in range(n + 1))
    ]


def page(side: int) -> list[tuple[float, float]]:
    """One page of the open book, in icon.svg's 512-unit coordinates.
    side=-1 is the left page; +1 mirrors it about the spine (x=256)."""

    def x(v: float) -> float:
        return 256 + side * (256 - v)

    top = cubic((256, 160), (218, 136), (170, 128), (122, 132))
    bottom = cubic((122, 352), (170, 348), (218, 356), (256, 380))
    return [(x(a), b) for a, b in top + bottom]


def draw(size: int, *, padding: float = 0.0, rounded: bool = True) -> Image.Image:
    """`padding`: keep the book inside the maskable safe zone."""
    img = Image.new("RGB", (size, size), ACCENT)
    if rounded:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 112 / 512, fill=ACCENT)
    d = ImageDraw.Draw(img)
    inner = size * (1 - 2 * padding)
    s = inner / 512
    off = size * padding
    for side, colour in ((-1, WHITE), (1, PALE)):
        pts = [(off + x * s, off + y * s) for x, y in page(side)]
        d.polygon(pts, fill=colour)
    d.line([(off + 256 * s, off + 160 * s), (off + 256 * s, off + 380 * s)], fill=ACCENT, width=max(2, round(8 * s)))
    return img


def main() -> None:
    draw(192).save(PUBLIC / "icon-192.png")
    draw(512).save(PUBLIC / "icon-512.png")
    # Maskable: full-bleed background, artwork inside the central 80%.
    draw(512, padding=0.1, rounded=False).save(PUBLIC / "icon-maskable-512.png")
    draw(180, rounded=False).save(PUBLIC / "apple-touch-icon.png")
    print("icons written to", PUBLIC)


if __name__ == "__main__":
    main()
