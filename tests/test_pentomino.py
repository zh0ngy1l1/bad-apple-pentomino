import copy
import json
import unittest

import numpy as np
from PIL import Image

from pentomino.frame import binary_image, black_target, crop_frame
from pentomino.geometry import Bank, NAMES, ORIENTATIONS, orientations
from pentomino.metrics import boundary_f1, measure, native_costs, pixel_bound
from pentomino.packing import as_record, greedy, validate
from pentomino.render import piece_image
from pentomino.search import Objective, Search


class GeometryTests(unittest.TestCase):
    def test_free_shapes_against_independent_growth(self):
        # Grow all free n-ominoes one square at a time. This catches a missing or duplicate piece.
        free = {((0, 0),)}
        for _ in range(4):
            larger = set()
            for shape in free:
                cells = set(shape)
                border = {(x+dx, y+dy) for x,y in cells
                          for dx,dy in ((0,1),(0,-1),(1,0),(-1,0))} - cells
                for cell in border:
                    larger.add(min(orientations(cells | {cell})))
            free = larger
        known = {min(orientations(o.cells)) for o in ORIENTATIONS}
        self.assertEqual(free, known)
        self.assertEqual(len({o.cells for o in ORIENTATIONS}), 63)
        self.assertEqual([sum(o.kind==i for o in ORIENTATIONS) for i in range(12)],
                         [8,2,8,8,8,4,4,4,4,1,8,4])

    def test_candidate_bank(self):
        target = np.fromfunction(lambda y,x: (x+2*y)%4 != 0, (6,8), dtype=int)
        for strict in (True,False):
            bank = Bank(target,strict)
            for o,shape in enumerate(ORIENTATIONS):
                for y in range(6):
                    for x in range(8):
                        cells = [(x+dx,y+dy) for dx,dy in shape.cells]
                        in_bounds = all(cx<8 and cy<6 for cx,cy in cells)
                        hits = sum(bool(target[cy,cx]) for cx,cy in cells) if in_bounds else 0
                        pid = bank.lookup[o,y,x]
                        self.assertEqual(pid>=0, in_bounds and hits >= (5 if strict else 3))
                        if pid >= 0:
                            self.assertEqual(bank.gain[pid], 2*hits-5)
                            self.assertEqual(set(bank.cells[pid]), {cy*8+cx for cx,cy in cells})

    def test_invalid_packings(self):
        rec = {"schema":1,"width":5,"height":2,"mode":"black","placement":"strict",
               "pieces":[{"shape":"I","cells":[[x,0] for x in range(5)]}]}
        validate(rec)
        changes = (lambda r:r["pieces"].append(copy.deepcopy(r["pieces"][0])),
                   lambda r:r["pieces"][0].update(shape="Y"),
                   lambda r:r["pieces"][0]["cells"].__setitem__(0, [1,0]),
                   lambda r:r["pieces"][0]["cells"].__setitem__(2, [2,1]),
                   lambda r:r["pieces"][0]["cells"].__setitem__(0, [-1,0]))
        for change in changes:
            bad = copy.deepcopy(rec)
            change(bad)
            with self.assertRaises(ValueError):
                validate(bad)
        with self.assertRaises(ValueError):
            validate(rec, np.zeros((2,5),bool))

    def test_boundary_crossing_and_empty_target(self):
        intended = np.array([[1,1,1,1,0]],dtype=bool)
        for strict, expected_error in ((True,4),(False,1)):
            bank = Bank(intended,strict)
            ids = greedy(bank,13)
            for mode in ("black","white"):
                black = intended if mode=="black" else ~intended
                metrics = measure(as_record(bank,ids,mode),black,binary_image(black))
                self.assertEqual(metrics["error_pixels"], expected_error)
                self.assertGreaterEqual(expected_error,pixel_bound(bank))
        bank = Bank(np.zeros((6,8),bool))
        state = Search(bank,5,Objective(.8))
        state.step()
        self.assertEqual(state.error,0)
        self.assertEqual(len(state.active),0)


class SearchTests(unittest.TestCase):
    def setUp(self):
        data = np.fromfunction(lambda y,x: (x*19+y*11)%256,(29,41),dtype=int).astype(np.uint8)
        self.source = crop_frame(Image.fromarray(data))
        self.black = black_target(self.source,12)

    def test_fixed_step_replay_and_incremental_scores(self):
        for mode, strict, obj in (("black",False,Objective(.8, local=.45)),
                                  ("white",True,Objective(28))):
            bank = Bank(self.black if mode=="black" else ~self.black, strict)
            signatures = []
            for _ in range(2):
                state = Search(bank,273,obj)
                last = None
                for _ in range(4):
                    for _ in range(25):
                        state.step()
                    rec = as_record(bank,state.active,mode)
                    stats = measure(rec,self.black,self.source)
                    self.assertEqual(stats["error_pixels"],state.error)
                    self.assertEqual([stats[k] for k in NAMES],state.counts)
                    value = obj.value(state.error,state.counts,bank.area,stats["same_neighbor_pairs"])
                    if last is not None:
                        self.assertLessEqual(value,last)
                    last = value
                signatures.append(json.dumps(rec))
            self.assertEqual(*signatures)

    def test_native_cost_and_lexicographic_cap(self):
        for mode in ("black","white"):
            bank = Bank(self.black if mode=="black" else ~self.black)
            start = Search(bank,14,Objective())
            limits = (Objective(error_cap=start.error+2), Objective(.8,native_tie=True))
            for obj in limits:
                costs = native_costs(bank,self.source,mode)
                state = Search(bank,14,obj,start.active,costs if obj.native_tie else None)
                for _ in range(60):
                    state.step()
                stats = measure(as_record(bank,state.active,mode),self.black,self.source)
                if obj.native_tie:
                    self.assertEqual(state.native_error,stats["native_error_pixels"])
                else:
                    self.assertLessEqual(state.error,obj.error_cap)

    def test_outline_does_not_change_occupancy(self):
        owner = np.array([[0]*5, [1]*5, [-1]*5])
        kinds = np.array([NAMES.index("I")]*2)
        im = np.asarray(piece_image(owner,kinds,"black","mono",6))
        self.assertTrue((im[12:] == 255).all())
        self.assertTrue((im[:12] < 255).all())
        self.assertFalse(np.array_equal(im[5],im[6]))
        self.assertEqual(boundary_f1(self.black,self.black),1.)

if __name__ == "__main__":
    unittest.main()
