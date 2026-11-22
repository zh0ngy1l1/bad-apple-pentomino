"""Build contact sheets and inspectable pixel-perfect images from saved JSON."""
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .benchmark import WIDTHS
from .frame import binary_image
from .render import enlarged, make_sheet, overview, palette_sheet, render_run

SHOWCASE = "black-080-lex"
BEST = "black-080-30s"
HERO = "black-080-contour"


def gallery(out):
    out = Path(out)
    gallery_dir = out/"gallery"
    gallery_dir.mkdir(exist_ok=True)
    with (out/"metrics.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    gray = Image.open(out/"source-cropped.png").convert("L")
    entries = {}
    for row in rows:
        key = row["run"]
        with (out/"packings"/f"{key}.json").open() as stream:
            record = json.load(stream)
        w,h = record["width"],record["height"]
        target_path = out/"targets"/f"{w}x{h}.png"
        black = np.asarray(Image.open(target_path).convert("L")) < 128
        palettes = ("puzzle","dusk","mono") if key in (SHOWCASE,BEST,HERO,"white-080-modest") else ("dusk",)
        owner,kinds,recon = render_run(record,black,out/"images"/key,palettes)
        entries[key] = (row,owner,kinds,black,recon)
        big_target = target_path.with_name(f"{w}x{h}-large.png")
        if not big_target.exists():
            enlarged(binary_image(black),math.ceil(960/w)).save(big_target)

    def items(pairs):
        return [(label,*entries[key]) for label,key in pairs]

    overview(gallery_dir/"overview.png",("",*entries[HERO]),gray)
    palette_sheet(gallery_dir/"palettes.png",("",*entries[SHOWCASE]))
    for mode in ("black","white"):
        make_sheet(gallery_dir/f"resolution-{mode}.png",f"Resolution with {mode} pieces",
                   "Eight seconds of search per grid. Compare the face profile, apple stem and tips of the hair.",
                   items([(f"{w} × {3*w//4}", f"{mode}-{w:03}-modest") for w in WIDTHS]),"resolution")
    make_sheet(gallery_dir/"modes.png","Which color should the pieces occupy?",
               "Same 80 × 60 target, diversity weight and eight-second budget. The black silhouette is scored in both rows.",
               items([("Black pieces","black-080-modest"),("White pieces","white-080-modest")]))
    make_sheet(gallery_dir/"rules.png","Strict and approximate placement",
               "A strict piece covers five intended cells. Approximate placement permits crossing the target boundary.",
               items([("Black · strict","black-080-strict"),("Black · approximate","black-080-modest"),
                      ("White · strict","white-080-strict"),("White · approximate","white-080-modest")]))
    make_sheet(gallery_dir/"diversity.png","Fidelity and shape diversity",
               "Same 80 × 60 black target and eight-second search allowance. Hue identifies the pentomino type.",
               items([("Accuracy only","black-080-accuracy"),("Modest preference","black-080-modest"),
                      ("Strong preference","black-080-strong"),("Two-stage search",SHOWCASE)]),palette="puzzle")
    make_sheet(gallery_dir/"effort.png","What extra search time buys",
               "The four timed rows sample one continuous 80 × 60 run. Greedy and mosaic initialization are shown for context.",
               items([("Greedy","black-080-greedy"),("Mosaic seed","black-080-seed"),
                      ("1.5 seconds","black-080-1p5s"),("8 seconds","black-080-modest"),
                      ("30 seconds",BEST),("75 seconds","black-080-75s")]))
    make_sheet(gallery_dir/"neighborhoods.png","Neighbor repeats and intricate pieces",
               "Compare a global shape preference with an extra reward for F, W, X and Z or a cost for like-shaped neighbors.",
               items([("Global diversity","black-080-modest"),("Neighbor penalty","black-080-local"),
                      ("Light reward","black-080-light-complex"),("Larger reward","black-080-complex")]),palette="puzzle")
    make_sheet(gallery_dir/"contour.png","Where the last two errors fall",
               "Both packings reach the pixel lower bound. A ten-second tie-break uses the original 480 × 360 silhouette.",
               items([("30 s packing",BEST),("Contour tie-break",HERO)]))
    index = [
        "# Single-frame gallery", "",
        "![Original, reconstruction and individual pieces](gallery/overview.png)", "",
        "The overview uses the contour-refined packing. The palette comparison uses the two-stage packing. "
        "Each binary PNG comes directly from the occupied cells in its JSON file. The figures below use integer cell sizes.", "",
        "| Comparison | Images |", "|---|---|",
        "| Resolution | [Black pieces](gallery/resolution-black.png) · [White pieces](gallery/resolution-white.png) |",
        "| Target and placement rule | [Black vs. white](gallery/modes.png) · [Strict vs. approximate](gallery/rules.png) |",
        "| Shape mixture | [Diversity objectives](gallery/diversity.png) · [Local repeats and complexity](gallery/neighborhoods.png) |",
        "| Search and presentation | [Effort checkpoints](gallery/effort.png) · [Three palettes](gallery/palettes.png) · [Contour refinement](gallery/contour.png) |",
        "", "[Original RGB still](../data/frame0226.png) · [Grayscale crop](source-cropped.png) · "
        "[Native and enlarged targets](targets/) · [Full metrics](metrics.csv) · [Evaluation](../REPORT.md)", "",
        "## Individual packings", "",
        "| Run | Pieces | Wrong pixels | Binary | Piece colors | Coordinates |",
        "|---|---:|---:|---|---|---|"]
    for row in rows:
        key = row["run"]
        extra = (f" · [Puzzle](images/{key}/puzzle.png) · [Graphite](images/{key}/mono.png)"
                 if key in (SHOWCASE,BEST,HERO,"white-080-modest") else "")
        index.append(f'| {key} | {row["pieces"]} | {row["error_pixels"]} | '
                     f'[Mask](images/{key}/mask.png) · [Enlarged](images/{key}/binary.png) | '
                     f'[Dusk](images/{key}/dusk.png){extra} | [JSON](packings/{key}.json) |')
    (out/"README.md").write_text("\n".join(index)+"\n")
