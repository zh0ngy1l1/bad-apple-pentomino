"""Paired experiments, single-threaded search and exact step-count replay."""
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import numpy as np
from PIL import Image
import PIL
import scipy

from .frame import binary_image, black_target, crop_frame
from .geometry import Bank, NAMES, window_geometry
from .metrics import measure, native_costs, native_iou, pixel_bound
from .packing import as_record, greedy, save
from .search import Objective, PATCH_SIZES, Search, mosaics, window

SEED = 271828
WEIGHTS = {"accuracy": Objective(), "modest": Objective(.8), "strong": Objective(28),
           "local": Objective(.8, local=.45), "complex": Objective(.8, complexity=.45),
           "light-complex": Objective(.8, complexity=.06)}
WIDTHS = (40, 60, 80, 100, 120)


def write_csv(rows, path):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class Case:
    width: int
    mode: str
    rule: str
    objective: str
    checkpoints: tuple   # (unique run id, cumulative improvement seconds)
    seed: int = SEED
    parent: str = ""


def plan():
    yield Case(80, "black", "approximate", "greedy", (("black-080-greedy",0),))
    yield Case(80, "black", "approximate", "modest",
               (("black-080-seed",0), ("black-080-1p5s",1.5), ("black-080-modest",8),
                ("black-080-30s",30), ("black-080-75s",75)))
    for width in WIDTHS:
        for mode in ("black","white"):
            if (width,mode) != (80,"black"):
                yield Case(width,mode,"approximate","modest",((f"{mode}-{width:03}-modest",8),))
    for mode in ("black","white"):
        yield Case(80,mode,"strict","modest",((f"{mode}-080-strict",8),))
    yield Case(80,"black","approximate","accuracy",(("black-080-accuracy-stage1",4),
                                                     ("black-080-accuracy",8)))
    yield Case(80,"black","approximate","lex",(("black-080-lex",4),),
               parent="black-080-accuracy-stage1")
    for name in ("strong","local","complex"):
        yield Case(80,"black","approximate",name,((f"black-080-{name}",8),))
    # Repeat the main fidelity/diversity comparison with a second independent seed.
    for name in ("accuracy","modest","strong"):
        yield Case(80,"black","approximate",name,((f"black-080-{name}-seed2",8),),seed=314159)


    yield from followup_cases()
    yield Case(80,"black","approximate","contour",(("black-080-contour",10),),parent="black-080-30s")


def followup_cases():
    # Check a small complexity weight and repeat the color/lexicographic comparisons.
    yield Case(80,"black","approximate","light-complex",(("black-080-light-complex",8),))
    yield Case(80,"white","approximate","modest",(("white-080-modest-seed2",8),),seed=314159)
    yield Case(80,"black","approximate","accuracy",(("black-080-lex-anchor-seed2",4),),seed=314159)
    yield Case(80,"black","approximate","lex",(("black-080-lex-seed2",4),),seed=314159,
               parent="black-080-lex-anchor-seed2")


def cold_templates(bank):
    """Charge every standalone trajectory for its patch tables on the current grid."""
    window.cache_clear()
    window_geometry.cache_clear()
    mosaics.cache_clear()
    mosaics()
    for w,h in PATCH_SIZES:
        window(min(w,bank.w),min(h,bank.h))


def run_case(case, gray, out, replay=None, parent=None):
    t = perf_counter()
    black = black_target(gray,case.width)
    p = perf_counter()
    bank = Bank(black if case.mode=="black" else ~black, strict=case.rule=="strict")
    q = perf_counter()
    is_greedy = case.objective=="greedy"
    if not is_greedy:
        cold_templates(bank)
    native_cost = native_costs(bank,gray,case.mode) if case.objective=="contour" else None
    ready = perf_counter()
    parent_time = 0.
    if case.parent:
        anchor, parent_time = parent
        # The bank is deterministic for a given target/rule, so ids can be reused.
        ids, anchor_error = anchor
        obj = (Objective(error_cap=anchor_error + 2) if case.objective=="lex" else
               Objective(.8,native_tie=True))
    else:
        ids = None
        obj = WEIGHTS.get(case.objective, Objective())
    if is_greedy:
        selected = greedy(bank,case.seed)
        state = None
    else:
        state = Search(bank,case.seed,obj,ids,native_cost)
    seeded = perf_counter()
    bound = pixel_bound(bank)
    elapsed = 0.
    result = []
    for key, budget in case.checkpoints:
        start = perf_counter()
        if state is not None:
            if replay is None:
                while elapsed + perf_counter()-start < budget:
                    state.step()
            else:
                while state.steps < replay[key]:
                    state.step()
            selected = state.active
        elapsed += perf_counter()-start
        record = as_record(bank,selected,case.mode)
        scores = measure(record,black,gray)
        if state is not None:
            assert state.error == scores["error_pixels"] and state.counts == [scores[s] for s in NAMES]
        if native_cost is not None:
            assert state.native_error == scores["native_error_pixels"]
        save(record,out/"packings"/f"{key}.json")
        prep = (p-t)+(q-p)+(ready-q)
        seed_time = seeded-ready
        counts = [scores[s] for s in NAMES]
        score = obj.value(scores["error_pixels"], counts, bank.area, scores["same_neighbor_pairs"])[0]
        row = dict(run=key, width=bank.w,height=bank.h,mode=case.mode,placement=case.rule,
                   algorithm="random-tie greedy" if is_greedy else "mosaic + window search",
                   objective="accuracy" if is_greedy else case.objective,
                   diversity_weight=obj.diversity, local_weight=obj.local, complexity_weight=obj.complexity,
                   pixel_cap=obj.error_cap, parent_run=case.parent, seed=case.seed,
                   requested_search_s=budget, preproc_s=p-t,enumeration_s=q-p,templates_s=ready-q,
                   seed_s=seed_time,search_s=elapsed,prior_stage_s=parent_time,
                   solve_s=prep+seed_time+elapsed+parent_time,
                   steps=state.steps if state is not None else 0, changes=state.changed if state else 0,
                   geometric_placements=bank.geometric_count,eligible_placements=len(bank.gain),
                   objective_value=score,**scores,pixel_lower_bound=bound,
                   pixel_gap=scores["error_pixels"]-bound,solver_status="heuristic feasible",
                   solver_objective_bound=None)
        print(f'{key:28} {row["error_pixels"]:4} errors  {row["entropy_norm"]:.4f} entropy  '
              f'{row["steps"]:6} patches  {row["solve_s"]:.3f} s',flush=True)
        result.append((row, (sorted(selected), scores["error_pixels"])))
    return result


def benchmark(source, out, replay_path=None):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    (out/"targets").mkdir(exist_ok=True)
    with Image.open(source) as image:
        gray = crop_frame(image)
    gray.save(out/"source-cropped.png")
    pre = []
    for w in WIDTHS:
        black = black_target(gray,w)
        binary_image(black).save(out/"targets"/f"{w}x{w*3//4}.png")
        # Native-resolution comparison measures what the sampling choice already loses.
        if w == 80:
            for method in ("box","nearest","lanczos"):
                for thresh in (96,128,160):
                    mask = black_target(gray,w,thresh,method)
                    pre.append(dict(width=w,filter=method,threshold=thresh,black_cells=int(mask.sum()),
                                    differs_from_box128=int((mask!=black).sum()),
                                    native_black_iou=native_iou(mask,gray)))
    write_csv(pre,out/"preprocessing.csv")
    replay = None
    if replay_path:
        with Path(replay_path).open() as handle:
            replay = {row["run"]:int(row["steps"]) for row in csv.DictReader(handle)}
    parents, rows = {}, []
    cases = list(plan())
    anchors = {c.parent for c in cases if c.parent}
    for case in cases:
        for row, anchor in run_case(case,gray,out,replay,parents.get(case.parent)):
            rows.append(row)
            if row["run"] in anchors:
                parents[row["run"]] = anchor, row["solve_s"]
        write_csv(rows,out/"metrics.csv")
    env = {"python":sys.version.split()[0],"numpy":np.__version__,"pillow":PIL.__version__,
           "scipy":scipy.__version__, "platform":platform.platform(), "machine":platform.machine(),
           "search_workers":1,"timing":"perf_counter wall seconds, image I/O and scoring excluded"}
    (out/"environment.json").write_text(json.dumps(env,indent=2)+"\n")
