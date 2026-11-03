# Sanma friend frame evidence

The fixture images were captured from CPU-only 300+0 friend matches. Name and portrait regions in full frames were replaced by identical solid rectangles before saving. PNGs are lossless; no threshold or color quantization was applied.

* `119-0-*` and `119-2-*` are pre-click pairs from regression 119, 05:37:54–59 and 05:40:43–47. The first exhibits a 15-pixel left-wall edge change with a stable self lamp; the second also changes the lamp. Both were originally rejected by the production comparator. These two examples cannot establish general safety.
* `41-*` is a previously rejected pair from run 41 at 09:02:57 and 09:03:08, with the self lamp visibly changing and the clock reading 288 then 290. The existing stop test expects rejection. The report was taken from the existing test fixture with slot 2 unresolved, matching that test.
* `116-before`, `116-after`, and `116-late-wall` are actual observations before and after play. They provide real river, center and right-wall changes, composed into an otherwise identical image for independent region checks.
* `left-wall-26` and `left-wall-28` are the same wall's 200×530 crop in the same East 1 hand from run 7e79853, when the center shows 16 and 11 tiles remaining. They contain no portrait or user name. The tests paste each crop onto the same base frame, isolating the actual wall change from unrelated actions.

These images do not establish when a turn began, whether an input occurred, whether the clock is current, or whether a visual candidate is safe to click. They cover a small sample of layouts and lighting and do not authorize gameplay.
