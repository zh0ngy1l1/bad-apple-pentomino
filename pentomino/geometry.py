"""Free pentomino geometry and target-dependent set-packing candidates."""
from dataclasses import dataclass
from functools import cache

import numpy as np

NAMES = "FILPNTUVWXYZ"
PATTERNS = {
    "F": (".##", "##.", ".#."), "I": ("#####",),
    "L": ("#.", "#.", "#.", "##"), "P": ("##", "##", "#."),
    "N": ("##..", ".###"), "T": ("###", ".#.", ".#."),
    "U": ("#.#", "###"), "V": ("#..", "#..", "###"),
    "W": ("#..", "##.", ".##"), "X": (".#.", "###", ".#."),
    "Y": ("####", ".#.."), "Z": ("##.", ".#.", ".##"),
}


def normalize(cells):
    left = min(x for x, y in cells)
    top = min(y for x, y in cells)
    return tuple(sorted((x - left, y - top) for x, y in cells))


def orientations(cells):
    variants = set()
    for sign in (-1, 1):
        points = [(sign * x, y) for x, y in cells]
        for _ in range(4):
            variants.add(normalize(points))
            points = [(-y, x) for x, y in points]
    return sorted(variants)


@dataclass(frozen=True)
class Orientation:
    kind: int
    cells: tuple
    width: int
    height: int


def make_orientations():
    result = []
    for i, name in enumerate(NAMES):
        cells = [(x, y) for y, row in enumerate(PATTERNS[name])
                 for x, char in enumerate(row) if char == "#"]
        for variant in orientations(cells):
            result.append(Orientation(i, variant, 1 + max(x for x, y in variant),
                                      1 + max(y for x, y in variant)))
    return tuple(result)


ORIENTATIONS = make_orientations()


class Bank:
    """Dense coordinate lookup, with compact arrays only for eligible placements."""

    def __init__(self, intended, strict=False):
        self.target = np.asarray(intended, dtype=bool)
        self.h, self.w = self.target.shape
        self.strict = strict
        self.lookup = np.full((len(ORIENTATIONS), self.h, self.w), -1, np.int32)
        cell_parts, gains, kinds, origins, orientation_ids = [], [], [], [], []
        count = 0
        self.geometric_count = 0
        for o, shape in enumerate(ORIENTATIONS):
            ny, nx = self.h - shape.height + 1, self.w - shape.width + 1
            if min(ny, nx) < 1:
                continue
            ys, xs = np.indices((ny, nx), dtype=np.int32)
            starts = (ys * self.w + xs).ravel()
            offsets = np.array([y * self.w + x for x, y in shape.cells], np.int32)
            cells = starts[:, None] + offsets
            self.geometric_count += len(cells)
            hits = self.target.ravel()[cells].sum(axis=1, dtype=np.int8)
            keep = hits >= (5 if strict else 3)
            n = int(keep.sum())
            self.lookup[o].ravel()[starts[keep]] = np.arange(count, count+n, dtype=np.int32)
            cell_parts.append(cells[keep])
            gains.append(2 * hits[keep] - 5)
            kinds.append(np.full(n, shape.kind, dtype=np.int8))
            origins.append(starts[keep])
            orientation_ids.append(np.full(n, o, dtype=np.int8))
            count += n
        self.cells = np.concatenate(cell_parts) if cell_parts else np.empty((0, 5), np.int32)
        self.gain = np.concatenate(gains) if gains else np.empty(0, np.int8)
        self.kind = np.concatenate(kinds) if kinds else np.empty(0, np.int8)
        self.origin = np.concatenate(origins) if origins else np.empty(0, np.int32)
        self.orientation = np.concatenate(orientation_ids) if orientation_ids else np.empty(0, np.int8)
        self.area = int(self.target.sum())


@cache
def window_geometry(w, h):
    """Enumerate in-window placements once per window size, independently of the image."""
    os, xs, ys, masks = [], [], [], []
    for o, shape in enumerate(ORIENTATIONS):
        start = sum(1 << (dy*w+dx) for dx, dy in shape.cells)
        for y in range(h-shape.height+1):
            for x in range(w-shape.width+1):
                os.append(o)
                xs.append(x)
                ys.append(y)
                masks.append(start << (y*w+x))
    return tuple(np.asarray(a, dtype=t) for a, t in
                 zip((os, xs, ys, masks), (np.intp, np.intp, np.intp, np.uint64)))
