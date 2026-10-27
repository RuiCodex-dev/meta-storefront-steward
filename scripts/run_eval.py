"""Score every triage system on both frozen test sets against the Claude gold labels.

  python scripts/run_eval.py [--api]     (--api also runs the hosted baselines that are not cached yet)

Systems:
  rules                 keyword floor, local
  spark13_zeroshot      Muse Spark 1.3, category list only
  spark13_guided        Muse Spark 1.3 with the label guide + 12 worked examples (= the teacher)
  sparkopen_guided      Muse Spark Open (open weights, served by Baseten), same prompt as the teacher
  llama3b_base          Llama 3.2 3B-Instruct, no fine-tuning, 4-bit NF4 on one A10G (Modal)
  llama3b_student       Llama 3.2 3B-Instruct + QLoRA distilled from the teacher, 4-bit NF4 on one A10G (Modal)
  glimmer_base          Muse Glimmer 30B, no fine-tuning, 4-bit NF4 on one H100 (Modal)
  glimmer_student       Muse Glimmer 30B + QLoRA distilled from the teacher, 4-bit NF4 on one H100 (Modal)
Writes results/eval.json and results/EVAL.md (aggregates only, no review text).
"""
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from steward import config, db, metrics, triage  # noqa: E402

SPLITS = {"real": "test_real", "synth": "test_synth"}
SYSTEMS = [
    ("rules", "Keyword rules", "local CPU", "floor"),
    ("spark13_zeroshot", "Muse Spark 1.3, zero-shot", "Meta Model API", "category names only"),
    ("spark13_guided", "Muse Spark 1.3, guided (teacher)", "Meta Model API", "label guide + 12 examples"),
    ("sparkopen_guided", "Muse Spark Open, guided", "Baseten (open weights)", "same prompt as the teacher"),
    ("llama3b_base", "Llama 3.2 3B, no tuning", "Modal A10G, 4-bit (open weights)", "student prompt, no training"),
    ("llama3b_student", "Llama 3.2 3B + QLoRA student", "Modal A10G, 4-bit (open weights)", "distilled from the teacher"),
    ("glimmer_base", "Muse Glimmer 30B, no tuning", "Modal H100, 4-bit (open weights)", "student prompt, thinks before answering"),
    ("glimmer_student", "Muse Glimmer 30B + QLoRA student", "Modal H100, 4-bit (open weights)", "distilled from the teacher, answers directly"),
]
API = {"spark13_zeroshot": ("meta", "muse-spark-1.3", "zeroshot"),
       "spark13_guided": ("meta", "muse-spark-1.3", "guided"),
       "sparkopen_guided": ("baseten", "meta-models/muse-spark-open-1026", "guided")}
FILES = {"llama3b_base": "llama3b-base", "llama3b_student": "llama3b-student",
         "glimmer_base": "glimmer-base", "glimmer_student": "glimmer-student"}


def gold(con, split):
    return {r["item_id"]: r for r in con.execute(
        "SELECT l.* FROM labels l JOIN splits s ON s.item_id=l.item_id WHERE s.split=? AND l.source='gold_claude'",
        (split,))}


def items(con, split):
    return [{"id": r["id"], "text": r["text"]} for r in con.execute(
        "SELECT i.id, i.text FROM items i JOIN splits s ON s.item_id=i.id WHERE s.split=? ORDER BY i.id", (split,))]


def cached(con, source, ids):
    return {r["item_id"]: {"category": r["category"], "severity": r["severity"]} for r in con.execute(
        "SELECT * FROM labels WHERE source=? AND item_id IN (%s)" % ",".join("?" * len(ids)), [source, *ids])}


def run_api(con, sysname, split):
    prov, model, mode = API[sysname]
    its = items(con, split)
    have = cached(con, sysname, [i["id"] for i in its])
    todo = [i for i in its if i["id"] not in have]
    if todo:
        out = triage.label_items(prov, model, todo, mode=mode, batch=20, workers=6, purpose=f"eval-{sysname}")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for iid, lab in out.items():
            con.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",
                        (iid, sysname, lab["category"], int(lab["severity"]), lab["language"], lab["gloss_en"],
                         None, now))
        con.commit()


def preds(con, sysname, split):
    ids = list(gold(con, split))
    if sysname == "rules":
        txt = {i["id"]: i["text"] for i in items(con, split)}
        return {i: triage.rule_label(txt[i]) for i in ids}
    if sysname in API:
        return cached(con, sysname, ids)
    f = config.DATA / "students" / f"pred_{FILES[sysname]}_{split}.jsonl"
    if not f.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, f.open(encoding="utf-8")) if r["id"] in set(ids)}


def cost_latency(con, sysname, n_items_total):
    if sysname in API:
        r = con.execute("SELECT SUM(cost_usd), AVG(latency_ms), COUNT(*) FROM receipts WHERE purpose IN (?,?)",
                        (f"eval-{sysname}", f"eval-{sysname}-retry")).fetchone()
        if r[2]:
            # batched 20 per call: per-review latency is the call latency / 20 (amortised throughput, not TTFB)
            return round(1000 * r[0] / n_items_total, 3), round(r[1] / 20, 1)
        return None, None
    if sysname == "rules":
        return 0.0, 0.1
    # GPU-hosted open weights: GPU minutes spent on evaluation x Modal list price (modal.com/pricing, 2026-10-28)
    gpu = {"glimmer": ("glimmer_train_log.json", 0.001097 * 60), "llama3b": ("llama3b_train_log.json", 0.000306 * 60)}
    fam, kind = sysname.split("_")
    logf, usd_per_min = gpu[fam]
    lp = config.DATA / "students" / logf
    if lp.exists():
        lg = json.loads(lp.read_text(encoding="utf-8"))
        mins = lg.get("base_eval_min" if kind == "base" else "student_eval_min")
        if mins:
            usd = round(1000 * mins * usd_per_min / n_items_total, 3)
            ms = round(60000 * mins / n_items_total, 1)    # amortised wall time per review, batched
            return usd, ms
    ms = []
    for split in SPLITS.values():
        f = config.DATA / "students" / f"pred_{FILES[sysname]}_{split}.jsonl"
        if f.exists():
            ms += [json.loads(l).get("ms", 0) for l in f.open(encoding="utf-8")]
    return 0.0, (round(sum(ms) / len(ms), 1) if ms else None)


def main():
    con = db.connect()
    use_api = "--api" in sys.argv
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "systems": []}
    gold_sets = {k: gold(con, v) for k, v in SPLITS.items()}
    out["n_real"], out["n_synth"] = len(gold_sets["real"]), len(gold_sets["synth"])
    # freeze proof: hash of the sorted (id, category, severity) gold rows of each test set
    for k, g in gold_sets.items():
        blob = "\n".join(f"{i}\t{r['category']}\t{r['severity']}" for i, r in sorted(g.items()))
        out[f"gold_sha256_{k}"] = hashlib.sha256(blob.encode()).hexdigest()
    n_total = out["n_real"] + out["n_synth"]
    for sysname, name, where, note in SYSTEMS:
        row = {"id": sysname, "name": name, "where": where, "note": note}
        for k, split in SPLITS.items():
            if use_api and sysname in API:
                run_api(con, sysname, split)
            p = preds(con, sysname, split)
            g = gold_sets[k]
            common = [i for i in g if i in p]
            if not common:
                row[k] = None
                continue
            rep = metrics.report([g[i]["category"] for i in common], [p[i]["category"] for i in common],
                                 [g[i]["severity"] for i in common], [int(p[i]["severity"]) for i in common])
            row[k] = list(rep["macro_f1"])
            row[k + "_detail"] = rep
            row[k + "_coverage"] = f"{len(common)}/{len(g)}"
        row["usd_per_1k"], row["ms"] = cost_latency(con, sysname, n_total)
        out["systems"].append(row)
    res = ROOT / "results"
    res.mkdir(exist_ok=True)
    (res / "eval.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    lines = ["# Triage evaluation", "", f"Generated {out['generated']}. Gold = Claude labels "
             "(owner spot check recorded separately). Macro-F1 over the categories present in each test set, "
             "95% percentile bootstrap (2,000 resamples, seed 20261027).", "",
             f"Test sets: real = all {out['n_real']} written reviews of the included apps; held-out synthetic = "
             f"{out['n_synth']} reviews written by Muse Spark Open (the training pool was written by Muse Spark 1.3).",
             f"Gold hashes: real `{out['gold_sha256_real'][:16]}`, synthetic `{out['gold_sha256_synth'][:16]}`.", "",
             "| System | Runs on | Real: macro-F1 [95% CI] | Real: actionable recall | Synthetic: macro-F1 [95% CI] "
             "| Synthetic: accuracy | Severity within 1 (synth) | $ / 1k reviews | ms / review |",
             "|---|---|---|---|---|---|---|---|---|"]
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]" if t else "-"
    for s in out["systems"]:
        rd, sd = s.get("real_detail"), s.get("synth_detail")
        lines.append(f"| {s['name']} | {s['where']} | {f(s.get('real'))} | {f(rd['actionable_recall']) if rd else '-'} "
                     f"| {f(s.get('synth'))} | {f(sd['accuracy']) if sd else '-'} | "
                     f"{f(sd['severity_within1']) if sd else '-'} | {s['usd_per_1k'] if s['usd_per_1k'] is not None else '-'} "
                     f"| {s['ms'] if s['ms'] is not None else '-'} |")
    (res / "EVAL.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
