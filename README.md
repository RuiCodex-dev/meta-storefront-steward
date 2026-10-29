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
| **Agent** | Muse Spark 1.3 runs the developer's "morning pass" with tool calling: studio overview -> read-only store sync -> triage -> group issues -> reply drafts -> engineering tickets -> report. Posting is not one of its tools. The page shows the run live, one line per tool call, with Spark's own plan notes and the cost of every step. |
| **Issue board** | The whole studio (every review, crash issue and release) goes into **one** Muse Spark context, no retrieval. Spark returns issue clusters as strict JSON; a verifier checks that every cited id exists and every quote is a verbatim substring before anything is shown. Review-to-crash links are accepted only when app and version line up. Each issue is matched to the previous pass by evidence overlap (never by title): *new*, *ongoing (+n new signals)*, or *quiet* - quiet is not claimed as fixed. |
| **Approval queue** | Two kinds of work. **Replies**: Muse Spark drafts each one in the reviewer's language; a deterministic verifier blocks drafts that exceed the store limit (Play 350 characters), are in the wrong language, promise dates/refunds/compensation or imply a fix already shipped, contain personal data, or cite something that does not exist. A blocked draft goes back to Spark once with the verifier's findings; the verifier, not the model, still decides. **Engineering tickets**: written from one issue's evidence; the verifier rejects any app, version or id that is not in that evidence. Approve -> post (Play; dry-run unless `STEWARD_LIVE=1`) or export the ticket for the tracker. App Store replies are disabled: App Store Connect is used read-only. |
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
| Muse Glimmer 30B (open weights, Apache-2.0) | one H100 on Modal (4-bit NF4, QLoRA); runs locally from the official GGUF with llama.cpp | the distilled triage student: teacher quality at a fifth of the cost |
| Llama 3.2 3B-Instruct (open weights) | one A10G on Modal (4-bit NF4, QLoRA) | the smallest student, for the cheapest always-on triage |

Contributor mode is never used; the budget guard refuses `-contributor` model ids.

## Evaluation

**Distillation result.** Muse Spark 1.3 labelled 2,754 synthetic training reviews; QLoRA (rank 16, 2 epochs, 345 steps)
distilled that into two open-weight students. Macro-F1 with 95% bootstrap intervals:

| System | Held-out synthetic (n=591) | Real reviews (n=49) | Actionable recall (real) | $ per 1k reviews | ms per review |
|---|---|---|---|---|---|
| Keyword rules (floor) | 0.574 [0.540, 0.605] | 0.402 [0.153, 0.463] | 0.83 | 0 | 0.1 |
| Muse Spark 1.3, guided (the teacher) | 0.991 [0.982, 0.998] | 0.776 [0.331, 0.833] | 1.00 | 0.656 | 544 |
| Muse Spark Open, guided (Baseten) | 0.995 [0.988, 1.000] | 0.787 [0.428, 1.000] | 1.00 | 1.188 | 645 |
| Muse Glimmer 30B, no tuning | 0.956 [0.939, 0.972] | 0.718 [0.329, 0.833] | 1.00 | 0.802 | 731 |
| **Muse Glimmer 30B + QLoRA student** | **0.993 [0.986, 0.998]** | 0.913 [0.394, 1.000] | 1.00 | **0.134** | **122** |
| Llama 3.2 3B, no tuning | 0.694 [0.656, 0.729] | 0.331 [0.152, 0.400] | 1.00 | 0.020 | 66 |
| **Llama 3.2 3B + QLoRA student** | **0.987 [0.976, 0.995]** | 0.714 [0.325, 0.774] | 1.00 | **0.026** | 84 |

The Glimmer student matches its teacher on the held-out set at about a fifth of the cost and 4.5x the speed, and fine-tuning
lifts the 3B model from 0.69 to 0.99. On the real reviews every system that is not the keyword floor flags every
review that needs action; the real-set F1 intervals overlap heavily (n=49, mostly praise), so no ranking is claimed
there. Hosted costs come from the receipts table; GPU costs are evaluation GPU-minutes x Modal list price (H100
$3.95/h, A10G $1.10/h), batched. Latency is amortised batch time per review, not time to first token.

**On our own hardware.** The Glimmer student's LoRA is converted to a llama.cpp adapter (`students/lora_to_gguf.py`) and
applied at run time to Meta's official `Muse-Glimmer-30B` Q4_K_M GGUF. On this studio's laptop (CPU only, no network)
it agreed with the H100 student on **47 of 49** real reviews, parsed 49 of 49, and took 14 s per review (median),
which is enough for a studio that receives a few reviews a week ([`results/local_student_check.json`](results/local_student_check.json)).
The agent's triage tool and the *Try it* page use this local student first and fall back to the hosted teacher.

**The agent's checkers.** On 120 held-out synthetic reviews in 10 languages, 117 of 119 Spark reply drafts passed the
deterministic verifier on the first attempt. The evaluation first showed 101 of 119: it caught a prompt defect
(releases cited loosely), one real implied-fix claim, and one false positive in the checker itself. All three are
described, with the fixes, in [`results/AGENT_CHECKS.md`](results/AGENT_CHECKS.md). Engineering tickets: 10 of 10
passed first time. Store screenshots: 11 of 11 assets kept every interface pixel identical
([`results/SCREENS.md`](results/SCREENS.md)).

Full table: [`results/EVAL.md`](results/EVAL.md) (regenerate with `python scripts/run_eval.py --api`). Two test sets, never mixed:

* **Real:** all 49 written reviews of the in-scope apps. With n=49 and a heavy praise majority the intervals are wide,
  and that is reported, not hidden. The number that matters here is **actionable recall**: did the system flag every
  review that needs action?
* **Held-out synthetic:** 591 reviews in 10 languages written by **Muse Spark Open**, while the training pool (3,060
  reviews) was written by **Muse Spark 1.3**. Exact duplicates, empty items and any text also present in training were
  removed before labelling. This set is clear-cut by construction (frontier models score about 0.99 on it), so it
  mainly separates the small students; it is not a claim about real-world difficulty.

Gold labels are AI labels (Claude), assigned **blind** (without the generator's intended label); the agreement of the
blind labels with the generator's intended labels was 99.2%. **AI-labelled; an independent second-model review agreed
on 50 of 50** spot-check cards (every actionable real review, 14 real praise reviews, 30 held-out synthetic). The
reviewer was Claude Opus 5.5 with its own prompt: it relabelled each card blind and agreement was computed in code
(same category, severity within one level; exact severity 47 of 50). **No human checked these labels.** Because the
gold labeller and the reviewer are both Claude models, the Meta models' own labels on the same cards are a
cross-family control: Muse Spark 1.3 agrees on 49 of 50, Muse Spark Open on 46 of 46. The one disagreement is a
review mixing lost data with a paid-feature complaint (billing or bug). Details:
[`results/spotcheck.json`](results/spotcheck.json). Gold hashes are written
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

**Try it without keys (demo database).** `demo/` holds, as plain JSON lines, 200 synthetic reviews in 10 languages
(written by Muse Spark Open), the studio's own Play crash/ANR issues and releases (no user data), and the outputs of
one recorded agent pass over exactly that data: triage, 13 issues, 38 reply drafts, 3 engineering tickets, every step
and receipt ($0.48). Store sync and posting are off in demo mode, and a banner says so on every page.

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.lock.txt   # .venv/bin/pip on macOS/Linux
python scripts/run_demo.py          # builds data/demo/steward_demo.db and serves http://127.0.0.1:8765
```

**On a studio's own data** (keys and store credentials needed):

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
# keys are read at run time from ~/.ruicodex-keys (never from the repo): storefront-steward/meta.json, baseten.json
python -c "from steward.connectors import ingest; print(ingest.run_all())"   # read-only store export
python -c "from steward import agent; print(agent.run()['report'])"         # one morning pass
python -m uvicorn steward.web.app:app --port 8765                            # UI, dry-run by default
python -m pytest -q tests
# students (Modal, paid from the hackathon credit): weights are downloaded from the official repos at run time
python students/modal_glimmer.py --stage all
python students/modal_llama.py
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
