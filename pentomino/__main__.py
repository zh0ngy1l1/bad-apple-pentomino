"""Command-line entry points for solving, reproducing the experiments and auditing."""
import argparse
import math
import json
from pathlib import Path

from PIL import Image

from .benchmark import Case, SEED, WEIGHTS, benchmark, run_case, write_csv
from .frame import binary_image, black_target, crop_frame
from .gallery import gallery
from .render import PALETTES, enlarged, render_run
from .verify import verify


def solve(args):
    if not math.isfinite(args.seconds) or args.seconds < 0:
        raise ValueError("Search seconds must be finite and nonnegative")
    if args.algorithm=="greedy" and args.objective!="accuracy":
        raise ValueError("Greedy uses the accuracy objective. Set --objective accuracy.")
    out = Path(args.out)
    (out/"targets").mkdir(parents=True,exist_ok=True)
    with Image.open(args.input) as image:
        gray = crop_frame(image)
    gray.save(out/"source-cropped.png")
    black = black_target(gray,args.width)
    h,w = black.shape
    target = binary_image(black)
    target.save(out/"targets"/f"{w}x{h}.png")
    enlarged(target,math.ceil(960/w)).save(out/"targets"/f"{w}x{h}-large.png")
    rows = []
    parent = None
    duration = args.seconds
    if args.objective=="lex":
        duration = args.seconds/2
        first = Case(w,args.mode,args.placement,"accuracy",(("accuracy-stage1",duration),),args.seed)
        row,anchor = run_case(first,gray,out)[0]
        parent = anchor,row["solve_s"]
        rows.append(row)
    obj = "greedy" if args.algorithm=="greedy" else args.objective
    final = Case(w,args.mode,args.placement,obj,(("solution",0 if obj=="greedy" else duration),),
                 args.seed,"accuracy-stage1" if parent else "")
    row,_ = run_case(final,gray,out,parent=parent)[0]
    rows.append(row)
    write_csv(rows,out/"metrics.csv")
    for row in rows:
        key = row["run"]
        record = json.loads((out/"packings"/f"{key}.json").read_text())
        render_run(record,black,out/"images"/key,tuple(dict.fromkeys(("dusk",args.palette))))
    verify(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command",required=True)
    s = commands.add_parser("solve",help="solve one frame and save JSON, images and metrics")
    s.add_argument("input")
    s.add_argument("--out",default="runs/frame")
    s.add_argument("--width",type=int,default=80)
    s.add_argument("--mode",choices=("black","white"),default="black")
    s.add_argument("--placement",choices=("strict","approximate"),default="approximate")
    s.add_argument("--algorithm",choices=("window","greedy"),default="window")
    s.add_argument("--objective",choices=(*WEIGHTS,"lex"),default="lex")
    s.add_argument("--seconds",type=float,default=8)
    s.add_argument("--seed",type=int,default=SEED)
    s.add_argument("--palette",choices=tuple(PALETTES),default="dusk")
    b = commands.add_parser("benchmark",help="run the single-frame experiment matrix and build the gallery")
    b.add_argument("--source",default="data/frame0226.png")
    b.add_argument("--out",default="runs/benchmark")
    b.add_argument("--replay",metavar="METRICS_CSV",help="use the recorded patch counts in place of wall budgets")
    for name,help_text in (("gallery","regenerate the benchmark gallery from saved packings"),
                           ("verify","recompute reported metrics and check piece geometry and masks")):
        c = commands.add_parser(name,help=help_text)
        c.add_argument("folder",nargs="?",default="results")
    args = p.parse_args()
    if args.command=="solve":
        solve(args)
    elif args.command=="benchmark":
        benchmark(args.source,args.out,args.replay)
        gallery(args.out)
        verify(args.out)
    elif args.command=="gallery":
        gallery(args.folder)
    else:
        verify(args.folder)


if __name__ == "__main__":
    main()
