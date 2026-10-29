# QA and rehearsals (RUI-268)

Each rehearsal starts from a **fresh clone of the private origin** into an empty folder, a **new virtual
environment from `requirements.lock.txt`**, and **no keys** (`STEWARD_KEYS` pointed at an empty folder) unless
stated. The click-through is a headless browser script: every page, approve a reply and post it (dry run), approve a
ticket and export it, submit text to *Try it*, and optionally run the agent. Console errors and HTTP status are
recorded.

## Rehearsal 1 - 2026-10-29, commit a65827b

| Check | Result |
|---|---|
| Clone + venv + install | 68 s, no errors |
| `pytest` (no keys) | 42 passed |
| `python scripts/run_demo.py` | demo database built from `demo/*.jsonl`, server up |
| 8 pages (overview, agent, inbox, board, queue, receipts, try, spot check) | all HTTP 200 |
| Approve reply -> Post (dry run) | OK, audit row written, "dry-run" shown |
| Approve ticket -> Export | OK, file written to `data/tickets/` |
| *Try it* with no key and no local student | **FAIL: HTTP 500** (an empty label set was indexed) |

Fixed in dff403d: *Try it* now shows the scrubbed text and says that no triage model is available; a missing key
file raises a clear `MissingKey` error; the spot-check page explains why it is empty on the demo database. A
regression test was added (43 tests).

## Rehearsal 2 - 2026-10-29, commit 2697d29

| Check | Result |
|---|---|
| Clone + venv + install | 30 s, no errors |
| `pytest` (no keys) | 44 passed |
| `python scripts/run_demo.py` (with the Meta key) | server up |
| 8 pages | all HTTP 200, **0 browser console errors, 0 server errors** |
| Approve reply -> Post (dry run) | OK |
| Approve ticket -> Export | OK |
| *Try it* (live, Muse Spark) | OK; the e-mail in the text was replaced by `[EMAIL]` before the call |
| Live agent pass on the demo database | completed; report lists new / quiet issues against the recorded pass |

Spend of this rehearsal (live pass and *Try it*): $0.33, merged into the main receipts ledger.
