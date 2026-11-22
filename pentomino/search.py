"""Greedy mosaic initialization and bounded, overlapping window repacking."""
from dataclasses import dataclass
from functools import cache
import random

import numpy as np

from .geometry import NAMES, ORIENTATIONS, window_geometry
from .packing import greedy

INTRICATE = tuple(NAMES.index(s) for s in "FWXZ")


def bitmap(array):
    return int.from_bytes(np.packbits(array, bitorder="little").tobytes(), "little")


def bits(number):
    while number:
        low = number & -number
        yield low.bit_length() - 1
        number ^= low


class Window:
    def __init__(self, w, h):
        self.os, self.xs, self.ys, self.mask_array = window_geometry(w, h)
        self.masks = self.mask_array.tolist()
        self.kinds = np.array([ORIENTATIONS[o].kind for o in self.os], dtype=np.int8)
        self.at = [0] * (w*h)
        for i, mask in enumerate(self.masks):
            for c in bits(mask):
                self.at[c] |= 1 << i
        self.conflicts = []
        self.neighbors = []
        for mask in self.masks:
            blocked = adjacent = 0
            for c in bits(mask):
                blocked |= self.at[c]
                x, y = c % w, c // w
                for dx, dy in ((1,0), (-1,0), (0,1), (0,-1)):
                    if 0 <= x+dx < w and 0 <= y+dy < h:
                        adjacent |= 1 << (c+dx+dy*w)
            self.conflicts.append(blocked)
            self.neighbors.append(adjacent & ~mask)


window = cache(Window)


@cache
def mosaics():
    """A small, reproducible library of exact five-piece 5 × 5 interiors."""
    tile = window(5, 5)
    rng = random.Random(3341)
    def cover(todo, legal):
        if not todo:
            return ()
        c = min(bits(todo), key=lambda c: (tile.at[c] & legal).bit_count())
        choices = list(bits(tile.at[c] & legal))
        rng.shuffle(choices)
        for k in choices:
            tail = cover(todo & ~tile.masks[k], legal & ~tile.conflicts[k])
            if tail is not None:
                return (k,) + tail
        return None
    return tuple(cover((1 << 25)-1, (1 << len(tile.masks))-1) for _ in range(96))


def mosaic_seed(bank, seed):
    rng = random.Random(seed)
    tile, pool = window(5, 5), mosaics()
    prefix = []
    # Select the grid phase containing the most complete, disjoint interiors.
    best = []
    for dy in range(min(5, bank.h)):
        for dx in range(min(5, bank.w)):
            starts = [(x,y) for y in range(dy, bank.h-4, 5)
                      for x in range(dx, bank.w-4, 5) if bank.target[y:y+5,x:x+5].all()]
            if len(starts) > len(best):
                best = starts
    for x, y in best:
        for k in rng.choice(pool):
            prefix.append(int(bank.lookup[tile.os[k], y+tile.ys[k], x+tile.xs[k]]))
    return greedy(bank, seed, prefix)


@dataclass(frozen=True)
class Objective:
    diversity: float = 0
    local: float = 0
    complexity: float = 0
    error_cap: int | None = None
    native_tie: bool = False

    def value(self, error, counts, area, contacts=0):
        n = sum(counts)
        # Equivalent to sum((n_i - N/12)^2) / (target_area/5).
        dispersion = (sum(x*x for x in counts) - n*n/12) / max(area/5, 1)
        if self.error_cap is not None:
            return (dispersion, error)
        complexity = sum(counts[i] for i in INTRICATE)
        return (error + self.diversity*dispersion + self.local*contacts
                - self.complexity*complexity, error)


def adjacent_cells(cells, w, h):
    for cell in cells:
        y, x = divmod(int(cell), w)
        if x:
            yield cell-1
        if x+1 < w:
            yield cell+1
        if y:
            yield cell-w
        if y+1 < h:
            yield cell+w


PATCH_SIZES = ((5,5), (6,5), (5,6), (6,6), (7,6), (6,7), (8,7), (7,8), (8,8))


class Search:
    def __init__(self, bank, seed, objective, selected=None, native_cost=None):
        self.bank = bank
        self.rng = random.Random(seed)
        self.noise = np.random.default_rng(seed)
        self.objective = objective
        self.active = set(mosaic_seed(bank, seed) if selected is None else selected)
        self.owner = np.full(bank.w*bank.h, -1, dtype=np.int32)
        ids = sorted(self.active)
        self.owner[bank.cells[ids]] = np.asarray(ids, dtype=np.int32)[:, None]
        self.counts = np.bincount(bank.kind[ids], minlength=12).tolist()
        self.error = bank.area - int(bank.gain[ids].sum())
        self.native_cost = native_cost
        if native_cost is not None:
            base, gain = native_cost
            self.native_error = base - int(gain[ids].sum())
        if objective.error_cap is not None and self.error > objective.error_cap:
            raise ValueError("Lexicographic search needs a feasible starting packing")
        self.steps = self.changed = 0
        self.intended = np.flatnonzero(bank.target).tolist()

    def step(self):
        self.steps += 1
        b, rng, obj = self.bank, self.rng, self.objective
        if not self.intended:
            return
        # Alternate boundary repairs with interior moves so diversity can change.
        focus = .70 if obj.diversity == obj.local == obj.complexity == 0 and obj.error_cap is None else .46
        if self.error and rng.random() < focus:
            errors = np.flatnonzero((self.owner >= 0) != b.target.ravel())
            center = int(errors[rng.randrange(len(errors))])
        else:
            center = rng.choice(self.intended)
        w, h = rng.choice(PATCH_SIZES)
        w, h = min(b.w, w), min(b.h, h)
        cy, cx = divmod(center, b.w)
        x = min(max(cx - rng.randrange(w//4, w-w//4), 0), b.w-w)
        y = min(max(cy - rng.randrange(h//4, h-h//4), 0), b.h-h)
        tile = window(w, h)
        labels = self.owner.reshape(b.h, b.w)[y:y+h, x:x+w]
        ids, counts = np.unique(labels[labels >= 0], return_counts=True)
        removed = ids[counts == 5]
        reserved = bitmap(np.isin(labels, ids[counts < 5]))
        todo = bitmap(b.target[y:y+h, x:x+w]) & ~reserved
        if not todo:
            return
        gids = b.lookup[tile.os, y+tile.ys, x+tile.xs]
        legal = bitmap((gids >= 0) & ((tile.mask_array & np.uint64(reserved)) == 0))
        if not legal:
            return
        search = Repair(self, tile, gids, removed, todo, legal)
        replacement = search.run()
        if replacement is None:
            return
        self.owner[b.cells[removed]] = -1
        self.active.difference_update(removed.tolist())
        new = np.asarray(replacement, dtype=np.int32)
        self.owner[b.cells[new]] = new[:, None]
        self.active.update(replacement)
        self.counts = search.best_counts
        self.error = search.best_error
        if obj.native_tie:
            self.native_error = search.best_native
        self.changed += 1


class Repair:
    """Bounded depth-first set packing. A skip branch can leave a target cell empty."""
    def __init__(self, state, tile, gids, removed, todo, legal):
        self.state, self.tile, self.gids = state, tile, gids
        self.todo, self.legal = todo, legal
        b, obj = state.bank, state.objective
        self.removed = set(removed.tolist())
        self.base = [n-int(k) for n,k in zip(state.counts, np.bincount(b.kind[removed], minlength=12))]
        self.base_error = state.error + int(b.gain[removed].sum())
        old_contacts = self.affected_contacts() if obj.local else 0
        self.best_score = obj.value(state.error, state.counts, b.area, old_contacts)
        if obj.native_tie:
            native_gain = state.native_cost[1]
            self.base_native = state.native_error + int(native_gain[removed].sum())
            self.native_gains = native_gain[gids].tolist()
            self.best_native = state.native_error
            self.best_score += (self.best_native,)
        self.best_counts, self.best_error = state.counts, state.error
        self.best = None
        self.nodes = 0
        self.gains = b.gain[gids].tolist()
        self.kinds = tile.kinds.tolist()
        # This linearized objective orders branches only. Acceptance uses the full score.
        strength = obj.diversity if obj.error_cap is None else 18
        deviation = np.asarray(self.base) - sum(self.base)/12
        bias = -2*strength*deviation/max(1, b.area/5)
        bias[list(INTRICATE)] += obj.complexity
        scores = self.gains + bias[tile.kinds] + state.noise.uniform(0, 1.8, len(gids))
        self.priority = scores.tolist()
        self.external = {}
        self.pure = obj.diversity == obj.local == obj.complexity == 0 and obj.error_cap is None
        self.lower_limit = self.base_error - todo.bit_count()
        self.stop = False

    def affected_contacts(self):
        b, owner = self.state.bank, self.state.owner
        pairs = set()
        for pid in self.removed:
            for c in adjacent_cells(b.cells[pid], b.w, b.h):
                neighbor = int(owner[c])
                if neighbor >= 0 and neighbor != pid and b.kind[pid] == b.kind[neighbor]:
                    pairs.add(tuple(sorted((pid, neighbor))))
        return len(pairs)

    def contacts(self, choices):
        count = 0
        b = self.state.bank
        for j, k in enumerate(choices):
            if k not in self.external:
                pid = int(self.gids[k])
                outside = {int(self.state.owner[c]) for c in adjacent_cells(b.cells[pid], b.w, b.h)}
                self.external[k] = sum(p != -1 and p not in self.removed and b.kind[p] == b.kind[pid]
                                       for p in outside)
            count += self.external[k]
            count += sum(self.kinds[k] == self.kinds[l] and bool(self.tile.neighbors[k] & self.tile.masks[l])
                         for l in choices[:j])
        return count

    def consider(self, choices, error):
        obj, state = self.state.objective, self.state
        if obj.error_cap is not None and error > obj.error_cap:
            return
        if self.pure and error > self.best_error:
            return
        counts = self.base.copy()
        for k in choices:
            counts[self.kinds[k]] += 1
        contacts = self.contacts(choices) if obj.local else 0
        score = obj.value(error, counts, state.bank.area, contacts)
        if obj.native_tie:
            native = self.base_native - sum(self.native_gains[k] for k in choices)
            score += (native,)
        if score < self.best_score or (score == self.best_score and self.best is None):
            proposed = [int(self.gids[k]) for k in choices]
            if set(proposed) != self.removed:
                self.best, self.best_counts = proposed, counts
                self.best_error, self.best_score = error, score
                if obj.native_tie:
                    self.best_native = native
        if self.pure and error == self.lower_limit:
            self.stop = True

    def visit(self, todo, legal, error, choices):
        self.nodes += 1
        if self.nodes > 240 or self.stop:
            return
        obj = self.state.objective
        limit = obj.error_cap if obj.error_cap is not None else self.best_error + (0 if self.pure else 6)
        # Each remaining intended cell can eliminate at most one error.
        if error - todo.bit_count() > limit:
            return
        at = self.tile.at
        branch_cell, min_count = 0, 10**6
        for c in bits(todo):
            n = (at[c] & legal).bit_count()
            if n == 0:
                todo ^= 1 << c
            elif n < min_count:
                branch_cell, min_count = c, n
        if error - todo.bit_count() > limit:
            return
        if not todo:
            self.consider(choices, error)
            return
        options = sorted(bits(at[branch_cell] & legal), key=self.priority.__getitem__, reverse=True)
        for k in options:
            choices.append(k)
            self.visit(todo & ~self.tile.masks[k], legal & ~self.tile.conflicts[k],
                       error-self.gains[k], choices)
            choices.pop()
            if self.nodes >= 240 or self.stop:
                return
        self.visit(todo ^ (1 << branch_cell), legal & ~at[branch_cell], error, choices)

    def run(self):
        self.visit(self.todo, self.legal, self.base_error, [])
        return self.best
