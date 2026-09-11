"""为视觉定位截图叠加不改变坐标系的辅助网格。"""

from __future__ import annotations

from PIL import Image, ImageDraw


def add_grid(image: Image.Image, *, rows: int = 8, columns: int = 8) -> Image.Image:
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = base.size

    for column in range(1, columns):
        x = round(width * column / columns)
        draw.line((x, 0, x, height), fill=(0, 110, 255, 100), width=2)
    for row in range(1, rows):
        y = round(height * row / rows)
        draw.line((0, y, width, y), fill=(0, 110, 255, 100), width=2)

    cell_width = width / columns
    cell_height = height / rows
    for row in range(rows):
        for column in range(columns):
            label = f"{_column_name(column)}{row + 1}"
            x = round(column * cell_width) + 4
            y = round(row * cell_height) + 4
            box_width = 10 + len(label) * 8
            draw.rectangle(
                (x, y, x + box_width, y + 20),
                fill=(0, 70, 180, 170),
            )
            draw.text((x + 4, y + 3), label, fill=(255, 255, 255, 255))

    return Image.alpha_composite(base, overlay).convert("RGB")


def _column_name(index: int) -> str:
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result
