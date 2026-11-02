# Meta Model API usage log (RUI-268)

Hard rule: total spend never above **$150** (owner, 2026-10-26). The client refuses calls above a **$140** ledger.
The Billing alert ($150/month, e-mail only) is a second line, not a cap. One line per day, read from the
dev.meta.ai Usage and Billing pages plus our own receipts table.

| Date (CET) | Credits shown on Billing | Spend today | Spend to date | Calls | Note |
|---|---|---|---|---|---|
| 2026-10-26 | **$150.00 free credits in use** (seen 16:45 UTC) | $0.00 | $0.00 | 0 | claim filed 16:22 UTC; card added by the owner; balance EUR 0.00; no API call made |
| 2026-10-27 (to 09:45 CET) | $150 in use | $5.81 | $5.81 | 557 | Baseten $8.23 of $90 cap (416 calls); synthetic data, teacher labels, baselines, clustering, drafts, agent, Muse Image + SAM |
| 2026-10-29 (03:20 CET) | Usage page: **EUR 0.00 spend** (credits applied, card not charged); 817.7k input tokens, 1.2M output, cache hit 15.5%, 2 images, 5 images segmented. Billing page did not finish loading | $0.22 | $6.04 | 589 | receipts agree with the Usage page: 814.0k input / 1.20M output / 15.4% cached tokens; 2 agent passes (memory, tickets) $0.21. Baseten $8.23 of $90 (unchanged). Modal (Meta jobs) ~$2.24 of the workspace credit |
| 2026-10-29 (18:30 CET) | not re-read today | $0.00 | $8.87 | - | Independent label review (owner asked it to be done for him; NOT a human check): Claude Opus 5.5 via Rui Codex's own Anthropic API credit, 2 runs x 50 cards + 1 smoke call = $0.52, own cap $5, in the receipts table as provider 'anthropic' |
| 2026-11-02 (11:45 CET) | Usage page (Oct 27-Nov 2): **EUR 0.00 spend** (credits applied); 1.4M input / 1.8M output tokens, cache hit 20.4%, 1.1k requests | ~$0.4-0.9 | **~$9.3-9.8** | ~60 | Video footage: 2 live agent passes and 3 Try-it calls on the synthetic demo DB. Their receipts were written to the demo DB, which is rebuilt from source on every demo start, so they are **not** in the main ledger; the figure is the Usage page's token delta over the main receipts (1.284M in / 1.730M out) priced at the Spark rates, a range because the page rounds to 0.1M. Baseten $8.23 of $90 (unchanged). Open fix: demo-mode receipts should also go to the main ledger. |
