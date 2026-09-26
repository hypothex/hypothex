# Hypothex phase 1a — acceptance results

## 1. Toy E2E in CI
Pending: the branch `phase-1a` is not pushed yet. Locally: 204 tests pass; ruff, ruff format, ty, and the Sphinx build are clean.

## 2. Agent-only loop (skill file only)
Sandbox: examples/toy-classifier copy with 3 baseline models x 3 seeds (best: rf, accuracy 0.885 ± 0.006, n=3).
A fresh agent got only skills/hypothex/SKILL.md and the goal "improve the best accuracy on toy-test".

| Criterion | Result |
|---|---|
| ≥ 3 new runs, created_by agent:acceptance, non-empty hypothesis | pass |
| Seed group n ≥ 3 (same config_hash + commit) | pass (svm, n=3) |
| Compared against the previous best (compare / examples) | pass (fixed 9, broke 3 vs rf) |
| Note on an agent run | pass |
| Every run lists repo, run_dir, dataset hash, checkpoint | pass |

Outcome: SVM (RBF, C=10) reached accuracy 0.922 ± 0.000 (n=3) and beat rf.
Friction found: the agent's shell dropped an unquoted `{seed}`, so 3 runs failed.
Fix: `hx run`/`hx launch` now warn when `--seed` is set but the command has no `{seed}`, and the skill and docs quote `'{seed}'`.

## 3. DeepRetro pilot
Pending: the user picks the DeepRetro evaluation to onboard.
