# Meta Model API usage log (RUI-268)

Hard rule: total spend never above **$150** (owner, 2026-10-26). The client refuses calls above a **$140** ledger.
The Billing alert ($150/month, e-mail only) is a second line, not a cap. One line per day, read from the
dev.meta.ai Usage and Billing pages plus our own receipts table.

| Date (CET) | Credits shown on Billing | Spend today | Spend to date | Calls | Note |
|---|---|---|---|---|---|
| 2026-10-26 | **$150.00 free credits in use** (seen 16:45 UTC) | $0.00 | $0.00 | 0 | claim filed 16:22 UTC; card added by the owner; balance EUR 0.00; no API call made |
| 2026-10-27 (to 09:45 CET) | $150 in use | $5.81 | $5.81 | 557 | Baseten $8.23 of $90 cap (416 calls); synthetic data, teacher labels, baselines, clustering, drafts, agent, Muse Image + SAM |
| 2026-10-29 (03:20 CET) | Usage page: **EUR 0.00 spend** (credits applied, card not charged); 817.7k input tokens, 1.2M output, cache hit 15.5%, 2 images, 5 images segmented. Billing page did not finish loading | $0.22 | $6.04 | 589 | receipts agree with the Usage page: 814.0k input / 1.20M output / 15.4% cached tokens; 2 agent passes (memory, tickets) $0.21. Baseten $8.23 of $90 (unchanged). Modal (Meta jobs) ~$2.24 of the workspace credit |
