"""All fidelity metrics use occupancy before color or outlines are applied."""
import math

import numpy as np
from PIL import Image
from scipy import ndimage

from .frame import binary_image
from .geometry import NAMES
from .packing import validate


def ratio(n, d):
    return float(n/d) if d else 1.0


def iou(a, b):
    return ratio(np.count_nonzero(a & b), np.count_nonzero(a | b))


def boundary_f1(a, b):
    # An edge is its orientation and lattice position between opposite-color cells.
    ea = np.r_[(a[1:] != a[:-1]).ravel(), (a[:,1:] != a[:,:-1]).ravel()]
    eb = np.r_[(b[1:] != b[:-1]).ravel(), (b[:,1:] != b[:,:-1]).ravel()]
    return ratio(2*int(np.sum(ea & eb)), int(ea.sum() + eb.sum()))


def pair_counts(owner, kinds):
    n = len(kinds)
    borders = []
    for a,b in ((owner[1:], owner[:-1]), (owner[:,1:], owner[:,:-1])):
        valid = (a != b) & (a >= 0) & (b >= 0)
        lo, hi = np.minimum(a[valid], b[valid]), np.maximum(a[valid], b[valid])
        borders.append(lo.astype(np.int64)*n + hi)
    pairs = np.unique(np.concatenate(borders))
    same = int((kinds[pairs//n] == kinds[pairs%n]).sum()) if n else 0
    return same, len(pairs)


def pixel_bound(bank):
    if not bank.strict:
        r = bank.area % 5
        return min(r, 5-r)
    # Each legal piece lies in one four-connected component of coverable cells.
    can_cover = np.zeros(bank.w * bank.h, dtype=bool)
    can_cover[bank.cells] = True
    labels, _ = ndimage.label(can_cover.reshape(bank.h, bank.w))
    sizes = np.bincount(labels.ravel())[1:]
    return int(bank.area - can_cover.sum() + (sizes % 5).sum())


def native_iou(mask, source):
    enlarged = binary_image(mask).resize(source.size, Image.Resampling.NEAREST)
    return iou(np.asarray(enlarged) < 128, np.asarray(source) < 128)


def native_costs(bank, source, mode):
    """Exact source-pixel Hamming improvement of each legal coarse-grid placement."""
    labels = np.arange(bank.w*bank.h, dtype=np.int32).reshape(bank.h, bank.w)
    cell = np.asarray(Image.fromarray(labels).resize(source.size, Image.Resampling.NEAREST)).ravel()
    intended = np.asarray(source).ravel() < 128
    if mode == "white":
        intended = ~intended
    total = np.bincount(cell, minlength=bank.w*bank.h)
    hits = np.bincount(cell[intended], minlength=bank.w*bank.h)
    return int(intended.sum()), (2*hits-total)[bank.cells].sum(axis=1)


def measure(record, black, source):
    owner, kinds = validate(record, black)
    occupied = owner >= 0
    intended = black if record["mode"] == "black" else ~black
    recon = occupied if record["mode"] == "black" else ~occupied
    tp = int((recon & black).sum())
    black_fp = int((recon & ~black).sum())
    black_fn = int((~recon & black).sum())
    spill = int((occupied & ~intended).sum())
    missed = int((~occupied & intended).sum())
    err, n = spill + missed, len(kinds)
    counts = np.bincount(kinds, minlength=12)
    p = counts[counts > 0] / max(n, 1)
    entropy = float(-(p*np.log(p)).sum())
    same, pairs = pair_counts(owner, kinds)
    native = np.asarray(binary_image(recon).resize(source.size, Image.Resampling.NEAREST)) < 128
    native_black = np.asarray(source) < 128
    return dict(
        intended_cells=int(intended.sum()), pieces=n, **{s:int(k) for s,k in zip(NAMES, counts)},
        correct_pixels=black.size-err, error_pixels=err, error_rate=err/black.size,
        correct_pct=100*(1-err/black.size), missed=missed, spill=spill,
        black_iou=iou(recon, black), black_precision=ratio(tp, tp+black_fp),
        black_recall=ratio(tp, tp+black_fn), occupied_iou=iou(occupied, intended),
        boundary_f1=boundary_f1(recon, black), native_black_iou=iou(native, native_black),
        native_error_pixels=int((native != native_black).sum()),
        target_native_black_iou=native_iou(black, source), types_used=len(p),
        entropy_nats=entropy, entropy_norm=entropy/math.log(12), hhi=float(p@p),
        quadratic_counts=int(counts@counts), sqrt_evenness=float(np.sqrt(p).sum()/math.sqrt(12)),
        same_neighbor_pairs=same, neighbor_pairs=pairs, same_neighbor_rate=same/max(pairs, 1),
        intricate_share=sum(int(counts[NAMES.index(s)]) for s in "FWXZ")/max(n,1))
