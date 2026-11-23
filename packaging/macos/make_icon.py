"""Draw the app icon from code so the build has no binary source assets."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    iconset = Path(sys.argv[1])
    iconset.mkdir(parents=True, exist_ok=True)
    size = 1024
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        draw.line((0, y, size, y), fill=(15, 101 + y // 20, 205 + y // 70, 255))
    draw.rounded_rectangle(
        (38, 38, 986, 986), radius=220, outline=(255, 255, 255, 80), width=6
    )
    draw.rounded_rectangle((225, 226, 498, 800), radius=38, fill="white")
    draw.rounded_rectangle((526, 226, 799, 800), radius=38, fill="white")
    draw.polygon(
        [(498, 262), (512, 280), (526, 262), (526, 802), (512, 824), (498, 802)],
        fill=(206, 226, 251),
    )
    for y in (350, 430, 510, 590, 670):
        draw.rounded_rectangle((280, y, 442, y + 14), radius=7, fill=(101, 155, 221))
        draw.rounded_rectangle((581, y, 744, y + 14), radius=7, fill=(101, 155, 221))
    draw.arc((210, 755, 814, 872), 0, 180, fill=(216, 238, 255), width=22)
    sizes = {16, 32, 128, 256, 512}
    for points in sizes:
        for scale in (1, 2):
            pixels = points * scale
            name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
            image.resize((pixels, pixels), Image.Resampling.LANCZOS).save(
                iconset / name
            )


if __name__ == "__main__":
    main()
