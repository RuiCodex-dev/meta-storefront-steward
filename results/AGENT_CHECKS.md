# The agent's checkers: how often they stop Muse Spark, and what that taught us

`scripts/eval_agent_checks.py` (seed 20261030) runs in a copy of the database, so the real approval queue is never
touched. Its receipts are merged into the main ledger.

* **Replies:** 120 held-out synthetic actionable reviews, 12 in each of 10 languages (written by Muse Spark Open,
  never used for training), drafted by Muse Spark 1.3 and checked by the deterministic reply verifier.
* **Tickets:** every crash-backed issue of the latest clustering run (10), written by Muse Spark 1.3 and checked by
  the ticket verifier.

| Run | Replies drafted | Pass on the first attempt | Blocked first | Fixed by the one guided revision | Still blocked (kept out of the queue) | Tickets passing first time |
|---|---|---|---|---|---|---|
| v1 | 119 of 120 | **101 (84.9%)** | 18: 17 citation, 1 promise | 18 of 18 | 0 | 10 of 10 |
| v2 (release ids tagged in the prompt) | 119 of 120 | **117 (98.3%)** | 2: both promise | 1 of 2 | 1 | 10 of 10 |

In both runs one review never left the machine: the outbound personal-data scan found a handle-like pattern in its
text and blocked the call before anything was sent. This is the privacy layer working, not a model failure.

Cost: v1 $0.70 and v2 $0.61 for 120 replies (about $0.005 per reply); 10 tickets $0.07.

## What the checkers found

1. **A prompt defect (v1).** In 17 of 18 blocked drafts Spark cited a real release loosely: "2.0.0" for the release
   named "2.0.0 (7)", or "Koi Drift 1.1.1" for "1.1.1". The verifier is strict on purpose (an id either exists
   exactly or it is invented), so the fix went into the prompt, not the checker: releases now carry an explicit
   `[RELEASE id=...]` tag like reviews and clusters. First-attempt pass rate went from 84.9% to 98.3%.
2. **A real catch (v2).** A French draft said "Essayez la dernière version avec ses petites corrections" ("try the
   latest version with its small fixes"), which implies a fix has already shipped. Only a release note may claim
   that. Blocked; the guided revision removed it.
3. **A checker false positive (v2).** "Amazing that you finished all 5 towns in 3 days!" was blocked as a date
   promise, because the rule matched "in 3 days", which is the reviewer's own achievement. The rule now treats
   "in N days/weeks" as a commitment only after words such as *will, fix, update, release, ready*
   (`tests/test_draft_verifier.py`). Re-checking all 121 stored v2 draft texts offline with the new rule: the French
   true positive is still caught and the false positive is gone. The v2 table above is reported as it ran, before
   this fix.

Coverage note: the verifier's language check uses word lists for en, tr, de, fr, nl, es, it and pt, plus the script
for Russian and Chinese. Polish replies are length-, promise-, personal-data- and citation-checked, but not
language-checked.

Raw counts: `agent_checks.json` (v2) and `agent_checks_v1_untagged_releases.json` (v1); no review text is stored.
