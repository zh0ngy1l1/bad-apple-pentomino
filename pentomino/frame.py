"""All comparisons start from the same 4:3 grayscale crop."""
from PIL import Image
import numpy as np


def crop_frame(image):
    gray = image.convert("L")
    width, height = gray.size
    unit = min(width // 4, height // 3)
    if unit == 0:
        raise ValueError("Input must contain at least 4 × 3 pixels")
    w, h = 4 * unit, 3 * unit
    x, y = (width - w) // 2, (height - h) // 2
    return gray.crop((x, y, x+w, y+h))


def black_target(gray, width, threshold=128, resample="box"):
    if width < 4 or width % 4:
        raise ValueError("Use a width divisible by four for an exact 4:3 grid")
    if not 0 <= threshold <= 255:
        raise ValueError("Threshold must be between 0 and 255")
    size = width, width * 3 // 4
    method = {"box": Image.Resampling.BOX, "nearest": Image.Resampling.NEAREST,
              "lanczos": Image.Resampling.LANCZOS}[resample]
    return np.asarray(gray.resize(size, method)) < threshold


def binary_image(black):
    return Image.fromarray((~np.asarray(black, dtype=bool)).astype(np.uint8)*255)
