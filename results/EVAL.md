# Triage evaluation

Generated 2026-10-27T23:48:17+00:00. Gold = Claude labels (AI labels; independent second-model review, not human: results/spotcheck.json). Macro-F1 over the categories present in each test set, 95% percentile bootstrap (2,000 resamples, seed 20261027).

Test sets: real = all 49 written reviews of the included apps; held-out synthetic = 591 reviews written by Muse Spark Open (the training pool was written by Muse Spark 1.3).
Gold hashes: real `540c0d4a48c05a2b`, synthetic `6d5b5d9fe929ee91`.

| System | Runs on | Real: macro-F1 [95% CI] | Real: actionable recall | Synthetic: macro-F1 [95% CI] | Synthetic: accuracy | Severity within 1 (synth) | $ / 1k reviews | ms / review |
|---|---|---|---|---|---|---|---|---|
| Keyword rules | local CPU | 0.402 [0.153, 0.463] | 0.833 [0.500, 1.000] | 0.574 [0.540, 0.605] | 0.574 [0.533, 0.614] | 0.860 [0.832, 0.885] | 0.0 | 0.1 |
| Muse Spark 1.3, zero-shot | Meta Model API | 0.776 [0.331, 0.833] | 1.000 [1.000, 1.000] | 0.984 [0.973, 0.993] | 0.985 [0.973, 0.993] | 1.000 [1.000, 1.000] | 0.677 | 591.9 |
| Muse Spark 1.3, guided (teacher) | Meta Model API | 0.776 [0.331, 0.833] | 1.000 [1.000, 1.000] | 0.991 [0.982, 0.998] | 0.992 [0.983, 0.998] | 0.998 [0.995, 1.000] | 0.656 | 544.1 |
| Muse Spark Open, guided | Baseten (open weights) | 0.787 [0.428, 1.000] | 1.000 [1.000, 1.000] | 0.995 [0.988, 1.000] | 0.995 [0.988, 1.000] | 0.998 [0.995, 1.000] | 1.188 | 645.1 |
| Llama 3.2 3B, no tuning | Modal A10G, 4-bit (open weights) | 0.331 [0.152, 0.400] | 1.000 [1.000, 1.000] | 0.694 [0.656, 0.729] | 0.697 [0.660, 0.734] | 0.871 [0.844, 0.897] | 0.02 | 65.6 |
| Llama 3.2 3B + QLoRA student | Modal A10G, 4-bit (open weights) | 0.714 [0.325, 0.774] | 1.000 [1.000, 1.000] | 0.987 [0.976, 0.995] | 0.986 [0.976, 0.995] | 0.998 [0.995, 1.000] | 0.026 | 84.4 |
| Muse Glimmer 30B, no tuning | Modal H100, 4-bit (open weights) | 0.718 [0.329, 0.833] | 1.000 [1.000, 1.000] | 0.956 [0.939, 0.972] | 0.959 [0.942, 0.975] | 0.995 [0.988, 1.000] | 0.802 | 731.2 |
| Muse Glimmer 30B + QLoRA student | Modal H100, 4-bit (open weights) | 0.913 [0.394, 1.000] | 1.000 [1.000, 1.000] | 0.993 [0.986, 0.998] | 0.993 [0.986, 0.998] | 0.998 [0.995, 1.000] | 0.134 | 121.9 |
