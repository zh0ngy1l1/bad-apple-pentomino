"""Audit serialized packings, published numeric metrics, and enlarged masks."""
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .frame import black_target
from .geometry import NAMES
from .metrics import measure
from .packing import validate
from .search import Objective


def verify(folder):
    folder = Path(folder)
    with (folder/"metrics.csv").open() as f:
        rows = list(csv.DictReader(f))
    if not rows or len({r["run"] for r in rows}) != len(rows):
        raise ValueError("Missing or duplicate run")
    gray = Image.open(folder/"source-cropped.png").convert("L")
    pieces = 0
    for row in rows:
        key = row["run"]
        record = json.loads((folder/"packings"/f"{key}.json").read_text())
        w,h = int(row["width"]),int(row["height"])
        black = black_target(gray,w)
        published = np.asarray(Image.open(folder/"targets"/f"{w}x{h}.png"))
        if not np.array_equal(published,np.where(black,0,255)):
            raise ValueError(f"Saved target differs from the source crop in {key}")
        if (record["width"],record["height"],record["mode"],record["placement"]) != (w,h,row["mode"],row["placement"]):
            raise ValueError(f"Settings mismatch in {key}")
        scores = measure(record,black,gray)
        for k,v in scores.items():
            if not math.isclose(float(row[k]),v,rel_tol=1e-10,abs_tol=1e-10):
                raise ValueError(f"Metric {k} differs in {key}")
        cap = int(row["pixel_cap"]) if row["pixel_cap"] else None
        obj = Objective(*(float(row[k]) for k in ("diversity_weight","local_weight","complexity_weight")), cap)
        score = obj.value(scores["error_pixels"],[scores[s] for s in NAMES],
                          scores["intended_cells"], scores["same_neighbor_pairs"])[0]
        if not math.isclose(score,float(row["objective_value"]),abs_tol=1e-10):
            raise ValueError(f"Objective mismatch in {key}")
        if cap is not None and scores["error_pixels"] > cap:
            raise ValueError(f"Lexicographic cap exceeded in {key}")
        if int(row["pixel_lower_bound"]) > scores["error_pixels"]:
            raise ValueError(f"Invalid pixel lower bound in {key}")
        owner,_ = validate(record,black)
        recon = (owner>=0) if record["mode"]=="black" else (owner<0)
        path = folder/"images"/key
        mask = np.asarray(Image.open(path/"mask.png"))
        large = Image.open(path/"binary.png")
        if not np.array_equal(mask,np.where(recon,0,255)) or not np.array_equal(
                np.asarray(large), np.asarray(Image.fromarray(mask).resize(large.size,Image.Resampling.NEAREST))):
            raise ValueError(f"Rendered mask mismatch in {key}")
        pieces += scores["pieces"]
    print(f"Verified {len(rows)} packings and their metrics and binary images ({pieces:,} piece instances).")
