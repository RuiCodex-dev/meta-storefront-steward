# Store screenshots: results

Pipeline: `steward/screens.py`, batch runner `scripts/make_screens.py`. Muse Image 1.0 paints only the scene (a phone
with an empty black screen). SAM 3.1 finds the screen. Our code places the untouched app capture inside it and sets
the caption in a real font. The fidelity guard then compares every interface pixel of the finished image with the
resized capture, and rejects the asset unless the maximum difference is 0.

Captures are real app screens from the studio's own builds (offline emulator / QA build, sample documents only),
not mock-ups. Images are kept in `data/screens/` (not in this repository); per-asset hashes are in the JSON files.

| App | Orientation | Scenes generated | Scenes the shape gate accepted | Assets | Accepted (max pixel difference 0) |
|---|---|---|---|---|---|
| Koi Drift | portrait | 2 | 1 | 3 | 3 |
| Document Reader | portrait | 4 | 1 (3 rejected by the first, too strict gate; see below) | 4 | 4 |
| Stickman Empire | landscape | 6 | 3 (3 phones painted lying flat, correctly rejected) | 4 | 4 |

Cost of all screenshot work so far: 12 Muse Image calls ($0.12) and 31 SAM 3.1 calls ($0.08), from the receipts table.

## What the gate learned (2026-10-30)

* **First gate: the screen box's aspect ratio within 12% of the capture's.** Muse Image paints today's 20:9 phones,
  so a 9:16 or 16:9 capture never matched, and good scenes were thrown away. It was replaced by a rule that matches
  how real phones show such apps: the screen box must be large, in the capture's orientation, phone-shaped
  (long/short between 1.6 and 2.4), and at least as elongated as the capture. The capture is then fitted inside
  unchanged, and the gap is the phone's own black screen, the way a 16:9 game looks on a 20:9 phone.
* **Landscape prompt.** "Lying sideways" made Muse Image lay the phone flat on a table three times out of three. A flat
  phone is a thin sliver to SAM and fails the shape rule, so none of those reached a composite. The prompt now asks
  for a phone standing on its long edge on a stand.
* **Bezel inset.** SAM's "phone screen" box can include part of the bezel. The capture is now placed 3.5% of the
  box's short side inside it, so the interface never covers the frame.

Tests: `tests/test_screens.py` (landscape fit, flat phone rejected, orientation, shape, one changed pixel caught).
