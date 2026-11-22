"""Independent geometry checks, portable on-disk format, and a fast greedy baseline."""
import json
from pathlib import Path

import numpy as np

from .geometry import NAMES, ORIENTATIONS, normalize

SHAPES = {o.cells: NAMES[o.kind] for o in ORIENTATIONS}


def greedy(bank, seed, prefix=()):
    """Descending Hamming gain, uniformly shuffled within each gain tier."""
    rng = np.random.default_rng(seed)
    selected = list(prefix)
    used = np.zeros(bank.w * bank.h, dtype=np.uint8)
    if selected:
        used[bank.cells[selected]] = 1
    eligible = np.flatnonzero(~used[bank.cells].any(axis=1)) if selected else np.arange(len(bank.gain))
    order = rng.permutation(eligible)
    order = order[np.argsort(-bank.gain[order], kind="stable")]
    # Scalar indexing avoids a temporary NumPy array for each collision test.
    occupied = bytearray(used.tobytes())
    for pid, cells in zip(order.tolist(), bank.cells[order].tolist()):
        a, b, c, d, e = cells
        if occupied[a] or occupied[b] or occupied[c] or occupied[d] or occupied[e]:
            continue
        occupied[a] = occupied[b] = occupied[c] = occupied[d] = occupied[e] = 1
        selected.append(pid)
    return selected


def as_record(bank, selected, mode):
    pieces = []
    for pid in sorted(selected, key=lambda i: (int(bank.origin[i]), int(bank.orientation[i]))):
        cells = [[int(c % bank.w), int(c // bank.w)] for c in bank.cells[pid]]
        pieces.append({"shape": NAMES[bank.kind[pid]], "cells": cells})
    return {"schema": 1, "width": bank.w, "height": bank.h, "mode": mode,
            "placement": "strict" if bank.strict else "approximate", "pieces": pieces}


def validate(record, black=None):
    """Rebuild the occupancy from explicit coordinates; check connectivity and free shape."""
    w, h, mode = record["width"], record["height"], record["mode"]
    if record.get("schema") != 1 or mode not in ("black", "white") or min(w, h) < 1:
        raise ValueError("Invalid packing header")
    if record["placement"] not in ("strict", "approximate"):
        raise ValueError("Invalid placement rule")
    if black is not None and black.shape != (h, w):
        raise ValueError("Target and packing dimensions differ")
    owner = np.full((h, w), -1, dtype=np.int32)
    kinds = []
    for i, piece in enumerate(record["pieces"]):
        cells = {tuple(c) for c in piece["cells"]}
        if len(piece["cells"]) != 5 or len(cells) != 5:
            raise ValueError(f"Piece {i} must have five distinct cells")
        if any(type(x) is not int or type(y) is not int or
               not (0 <= x < w and 0 <= y < h) for x, y in cells):
            raise ValueError(f"Invalid coordinates on piece {i}")
        visited = {next(iter(cells))}
        for _ in range(4):
            visited |= cells & {(x+dx, y+dy) for x, y in visited
                                for dx, dy in ((1,0), (-1,0), (0,1), (0,-1))}
        if visited != cells or SHAPES.get(normalize(cells)) != piece["shape"]:
            raise ValueError(f"Shape mismatch on piece {i}")
        for x, y in cells:
            if owner[y, x] != -1:
                raise ValueError(f"Overlap at {(x, y)}")
            if black is not None and record["placement"] == "strict" and black[y,x] != (mode == "black"):
                raise ValueError(f"Strict placement crosses the boundary at {(x, y)}")
            owner[y,x] = i
        kinds.append(NAMES.index(piece["shape"]))
    return owner, np.asarray(kinds, dtype=np.int8)


def save(record, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # One line per piece keeps diffs readable without bloating the gallery.
    header = {k: v for k,v in record.items() if k != "pieces"}
    body = ",\n".join("    " + json.dumps(p, separators=(",", ":")) for p in record["pieces"])
    path.write_text(json.dumps(header)[:-1] + ', "pieces": [\n' + body + '\n]}\n')
