# Storefront Steward

**An approval-gated agent that runs a small studio's app-store feedback loop: it reads every review, crash and
release across all the studio's apps, groups the problems across apps and languages, drafts replies that cannot
overclaim, and makes store screenshots whose app interface is provably the real one. Nothing reaches a store
without a human click.**

Built by Rui Codex for the Meta Global AI Developer Hackathon (Indie track, theme *Build for Your World*).
Everything in this repository was written during the building period (27 Oct - 4 Nov 2026); the design notes in
`docs/` predate it and contain no code.

## The problem

Rui Codex is a small studio with 40 apps and games on Google Play and the App Store. Its real feedback is not a
flood, it is a trickle scattered everywhere: over the full history the 34 apps in scope have **49 written reviews**
(43 of them 5-star), **40 crash/ANR issues** in the last 90 days and **68 releases**, in 9 languages. The cost is not
volume; it is that the one signal that matters (a 1-star "ads after every button", a native crash that three
different games share) sits in a different console, app and language from the next one, and gets missed.

## What it does

| Page | What happens |
|---|---|
| **Agent** | Muse Spark 1.3 runs the developer's "morning pass" with tool calling: studio overview -> sync -> triage -> group issues -> draft replies -> report. Posting is not one of its tools. Every step and its cost is logged. |
| **Issue board** | The whole studio (every review, crash issue and release) goes into **one** Muse Spark context, no retrieval. Spark returns issue clusters as strict JSON; a verifier checks that every cited id exists and every quote is a verbatim substring before anything is shown. Review-to-crash links are accepted only when app and version line up. |
| **Approval queue** | Muse Spark drafts each reply in the reviewer's language. A deterministic verifier blocks drafts that exceed the store limit (Play 350 characters), are in the wrong language, promise dates/refunds/compensation or imply a fix already shipped, contain personal data, or cite something that does not exist. Approve -> post; the writer is dry-run unless `STEWARD_LIVE=1`. |
| **Inbox** | Every real review, pseudonymised and scrubbed, sorted by severity. |
| **Receipts** | Every model call with model, mode (Standard only), tokens, cost, latency and a prompt hash. |
| **Screenshots** (`steward/screens.py`) | Muse Image paints only the scene (a phone with a blank screen); SAM 3.1 finds the screen; our code pastes the untouched app capture; a fidelity guard proves every interface pixel is identical (max difference 0) or rejects the asset. Captions are set in a real font by our code. |

A first real finding: the issue board grouped five crash issues from **three different games** (Ant Empire,
Grandma's Kitchen, Merge Kingdom) into one cluster, the same `SoLoud::DiskFile::pos()` native crash. One fix ships
to three apps; no single-app console shows that.

## Meta models and their jobs

| Model | Where | Job |
|---|---|---|
| Muse Spark 1.3 | Meta Model API (Standard mode) | agent planner (tool calling), teacher labels, whole-studio clustering, reply drafts, synthetic training reviews |
| Muse Spark Open (open weights) | Baseten | held-out test-set generator (a different model than the training-data writer), guided baseline |
| Muse Image 1.0 | Meta Model API | store-screenshot scenes, never the interface |
| SAM 3.1 | Meta Model API | finds the phone screen in the generated scene |
| Muse Glimmer 30B (open weights, Apache-2.0) | this PC, llama.cpp, official Q4_K_M GGUF | private, local triage tier |
| Llama 3.2 3B-Instruct (open weights) | this PC, QLoRA on an 8 GB RTX 4070 laptop GPU | student distilled from the Spark teacher |

Contributor mode is never used; the budget guard refuses `-contributor` model ids.

## Evaluation

See [`results/EVAL.md`](results/EVAL.md) (regenerate with `python scripts/run_eval.py --api`). Two test sets, never mixed:

* **Real:** all 49 written reviews of the in-scope apps. With n=49 and a heavy praise majority the intervals are wide,
  and that is reported, not hidden. The number that matters here is **actionable recall**: did the system flag every
  review that needs action?
* **Held-out synthetic:** 591 reviews in 10 languages written by **Muse Spark Open**, while the training pool (3,060
  reviews) was written by **Muse Spark 1.3**. Exact duplicates, empty items and any text also present in training were
  removed before labelling. This set is clear-cut by construction (frontier models score about 0.99 on it), so it
  mainly separates the small students; it is not a claim about real-world difficulty.

Gold labels are Claude labels, assigned **blind** (without the generator's intended label), spot-checked by the
developer; the agreement of the blind labels with the generator's intended labels was 99.2%. Gold hashes are written
into `results/eval.json`. Every score has n and a 95% bootstrap interval (2,000 resamples, fixed seed). Costs and
latencies come from the receipts table.

## Privacy

* Data: only Rui Codex's own apps, read with Rui Codex's own developer credentials. Health-related apps and apps not
  written by Rui Codex are excluded in code (`steward/apps.py`), and unknown packages are refused by default.
* Before any model sees a record: reviewer ids become keyed HMAC pseudonyms; e-mails, phone numbers, order ids, IBANs,
  card-like numbers, links, handles and names are replaced by typed placeholders (`steward/privacy/scrub.py`, tested on
  40 synthetic reviews in 8 languages with planted personal data).
* Every outbound text is scanned again; a hit blocks the call.
* The only link back to a store review id lives in a separate file read by exactly one function, the approved-reply
  writer (enforced by a test).
* No review data, labels on real reviews, keys or the re-identification map are in this repository (`data/` is
  git-ignored). The video and this README show pseudonyms and paraphrases only.
* The Meta free credits carry a note that content may be used for product improvement; the studio owner decided to
  allow pseudonymised, scrubbed review text under that condition.

## Running it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
# keys are read at run time from ~/.ruicodex-keys (never from the repo): storefront-steward/meta.json, baseten.json
python -c "from steward.connectors import ingest; print(ingest.run_all())"   # read-only store export
python -c "from steward import agent; print(agent.run()['report'])"         # one morning pass
python -m uvicorn steward.web.app:app --port 8765                            # UI, dry-run by default
python -m pytest -q tests
```

Spend is capped in code before every call (Meta Model API USD 140, Baseten USD 90) and logged in `ops/USAGE_LOG.md`.

## Data statement

Real data: written reviews (Google Play monthly exports and API, App Store Connect), Play vitals crash/ANR issues,
release tracks and store listings of Rui Codex's own apps. Synthetic data: reviews generated by Meta models from each
app's own store listing, crash signatures and release notes, labelled `synthetic=1`, used for training and the
held-out synthetic test only. No third-party or scraped datasets are used.

## AI assistance

Code, documentation and labels were produced with AI assistance (Claude by Anthropic) under the developer's direction;
synthetic data and scenes were produced by Meta models as described above. The demo video uses a synthetic voice,
disclosed in the video.

## Licence

Apache-2.0 for the code in this repository. Model weights are not redistributed; each model keeps its own licence.
