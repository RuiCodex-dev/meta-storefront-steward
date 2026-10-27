# Triage evaluation

Generated 2026-10-27T08:19:35+00:00. Gold = Claude labels (owner spot check recorded separately). Macro-F1 over the categories present in each test set, 95% percentile bootstrap (2,000 resamples, seed 20261027).

Test sets: real = all 49 written reviews of the included apps; held-out synthetic = 591 reviews written by Muse Spark Open (the training pool was written by Muse Spark 1.3).
Gold hashes: real `540c0d4a48c05a2b`, synthetic `6d5b5d9fe929ee91`.

| System | Runs on | Real: macro-F1 [95% CI] | Real: actionable recall | Synthetic: macro-F1 [95% CI] | Synthetic: accuracy | Severity within 1 (synth) | $ / 1k reviews | ms / review |
|---|---|---|---|---|---|---|---|---|
| Keyword rules | local CPU | 0.402 [0.153, 0.463] | 0.833 [0.500, 1.000] | 0.574 [0.540, 0.605] | 0.574 [0.533, 0.614] | 0.860 [0.832, 0.885] | 0.0 | 0.1 |
| Muse Spark 1.3, zero-shot | Meta Model API | 0.776 [0.331, 0.833] | 1.000 [1.000, 1.000] | 0.984 [0.973, 0.993] | 0.985 [0.973, 0.993] | 1.000 [1.000, 1.000] | 0.677 | 591.9 |
| Muse Spark 1.3, guided (teacher) | Meta Model API | 0.776 [0.331, 0.833] | 1.000 [1.000, 1.000] | 0.991 [0.982, 0.998] | 0.992 [0.983, 0.998] | 0.998 [0.995, 1.000] | 0.656 | 544.1 |
| Muse Spark Open, guided | Baseten (open weights) | 0.787 [0.428, 1.000] | 1.000 [1.000, 1.000] | 0.995 [0.988, 1.000] | 0.995 [0.988, 1.000] | 0.998 [0.995, 1.000] | 1.188 | 645.1 |
| Llama 3.2 3B, no tuning | local RTX 4070 8 GB | - | - | - | - | - | 0.0 | - |
| Llama 3.2 3B + QLoRA student | local RTX 4070 8 GB | - | - | - | - | - | 0.0 | - |
| Muse Glimmer 30B, no tuning | local, llama.cpp Q4_K_M | - | - | - | - | - | 0.0 | - |
| Muse Glimmer 30B + LoRA student | local, llama.cpp Q4_K_M | - | - | - | - | - | 0.0 | - |
