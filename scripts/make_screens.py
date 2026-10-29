"""Build one app's store-screenshot set: one Muse Image scene for the whole set, every capture composited into it.

    python scripts/make_screens.py <set.json>

set.json: {"slug": "...", "mood": "...", "scene": "<optional existing scene.png>", "items": [{"capture": "<path to a real app capture>", "headline": "..."}]}
A scene is regenerated (at most MAX_SCENES times) only when SAM 3.1 finds no screen matching the capture's shape.
Every asset must pass the fidelity guard (UI pixels identical, max difference 0) or it is rejected and reported.
Writes images to data/screens/<slug>/ (git-ignored) and a counts-only summary to results/screens_<slug>.json.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward import config, db, screens  # noqa: E402

MAX_SCENES = 3


def main(spec_path: str) -> dict:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    slug, mood, items = spec["slug"], spec["mood"], spec["items"]
    con = db.connect()
    base = config.DATA / "screens" / slug
    scene_png, tries, results = None, 0, []
    first = items[0]
    if spec.get("scene"):          # reuse a scene generated earlier (no new image call)
        scene_png = Path(spec["scene"]).read_bytes()
    while scene_png is None and tries < MAX_SCENES:
        tries += 1
        out = base / f"scene_try{tries}"
        r = screens.compose(first["capture"], first["headline"], app_slug=slug, mood=mood, out_dir=out, con=con)
        if not r["status"].startswith("rejected: no front-facing"):
            scene_png = (out / "scene.png").read_bytes()
            break
    if scene_png is None:
        summary = {"slug": slug, "scenes_tried": tries, "status": "no usable scene"}
    else:
        for i, it in enumerate(items):
            name = Path(it["capture"]).stem
            out = base / name
            if out.exists():
                shutil.rmtree(out)
            r = screens.compose(it["capture"], it["headline"], app_slug=slug, mood=mood, out_dir=out,
                                scene_png=scene_png, con=con)
            results.append({"capture": name, "status": r["status"],
                            "max_abs_diff": (r.get("fidelity") or {}).get("max_abs_diff"),
                            "pixels_checked": (r.get("fidelity") or {}).get("pixels_checked"),
                            "ui_sha256": (r.get("fidelity") or {}).get("ui_sha256"),
                            "out_sha256": (r.get("fidelity") or {}).get("out_sha256")})
        summary = {"slug": slug, "scenes_tried": tries, "assets": len(results),
                   "accepted": sum(1 for x in results if x["status"] == "accepted"), "items": results}
    (ROOT / "results" / f"screens_{slug}.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8",
                                                          newline="\n")
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    main(sys.argv[1])
