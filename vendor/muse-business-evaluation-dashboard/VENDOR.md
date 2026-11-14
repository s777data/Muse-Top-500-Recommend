# Vendored dashboard engine — DO NOT EDIT

Byte copy of `src/evaluator/` + `config/` from the LOCAL working copy
`~/workspace/muse-business-evaluation-dashboard/` (Muse Business
Evaluation Dashboard engine **V5.5 + GAV-Code**, V5.4 missing-leg policy),
copied 2026-11-14 for the Mag-500 build. `__pycache__` and `output/`
excluded. The engine's runtime cache/output land in
`vendor/muse-business-evaluation-dashboard/output/` (gitignored).
Parallel valuation workers use per-worker copies of this tree (see
`scripts/valuation_adapter.py`) so each worker has its own
`output/cache/` directory.

Per-file SHA-256 (of the vendored copy, verified identical to the source
working copy at copy time):

| File | Bytes | SHA-256 |
|---|---|---|
| `config/dcf.yaml` | 2082 | `4f4834f3aa0dc121f16e10c18cd1832b8f099a1613d71f33070aa08e45bf673d` |
| `config/peers.yaml` | 21488 | `aa2176e8d9df14bf5a2c8b4b7eb19806efa2d9c05b50344568c4ff92c9881428` |
| `config/scoring.yaml` | 11928 | `7245de3f5282cda4c04dbc04586942b53ed8850b1f7e00827a2319d6d43d9616` |
| `config/sources.yaml` | 10871 | `7c6c416c4717a74910c20d5fd4967c2bf16d4cfcdded92bab5fa361cf260202f` |
| `config/tickers.yaml` | 13189 | `b33e5f6853a354cc4e376fe15cf5e59af73e542deac1ca72eff410819bf12265` |
| `src/__init__.py` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `src/evaluator/__init__.py` | 79 | `acc8bbb39faebf9c3cc7a12954b33fd736950f7f6fe48b2f6c472f8e957f662b` |
| `src/evaluator/buybacks.py` | 66573 | `730c9ab0bee00ae97bd290ab23bcd1df79eb6a46a6c9faa4598b38a13124d55e` |
| `src/evaluator/class_shares.py` | 13415 | `fb5951d4bf710dbb00b22c30cac871b78c11338c61c00e23b8dfeaee10db7fee` |
| `src/evaluator/config.py` | 536 | `6351d8c681fec359ff69e1d24f330358fe491e5b26fae45ce98454e2f8c96bfd` |
| `src/evaluator/dcf.py` | 6741 | `f6a206144fc3fd1c7a9c72fa77fa17abc94ea273f3a80d24cbebb437e90c52e5` |
| `src/evaluator/edgar.py` | 29742 | `23639b06a4fb3a02a0a0f2f5ecfb5fde2737972db7c50c39a995d7463c8b21de` |
| `src/evaluator/explanations.py` | 6636 | `71195d44d682128b09058e87aa13a0ed012de2f4752ec33c2eaa3ad0f17a88e9` |
| `src/evaluator/filings.py` | 7501 | `91d6e679f09882abc09f803c34b2870224fb6f0e2e4631e0376326501f6d5923` |
| `src/evaluator/metrics.py` | 46454 | `5c98a9446021da530b3e30512d2364789a27378a1ab464cb290799422c1ed078` |
| `src/evaluator/prices.py` | 6934 | `656911d56a28cb9dac6c6d574223397d17b37e5de7adb44361cae6028119773d` |
| `src/evaluator/run.py` | 32734 | `130e7543031b1293f24a088d7ba30a74e9c560bfa1a6f2bdfeebf56ee279cffc` |
| `src/evaluator/scoring.py` | 13586 | `1e0dd7dee2a1d5b109874587e9906badfa444d140f7e84def910e4c9478da151` |
| `src/evaluator/util.py` | 1488 | `aad3815548f5a3690b86bfa0338e75f7373b02315c029d2bcf41f81abe7af245` |
