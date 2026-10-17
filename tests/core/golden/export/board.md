| group | n | acc/value ↑ | f1/value ↑ |
|:--|--:|--:|--:|
| svm | 3 | **0.920 ± 0.010** [0.871, 0.954] | 0.890 ± 0.010 |
| rf† | 3 | 0.910 ± 0.005 [0.862, 0.947] | **0.910 ± 0.010** |
| logreg | 3 | 0.880 (◇×3) [0.826, 0.925] | 0.860 ± 0.010 |
| knn¹ | 1 | 0.850 [0.794, 0.894] | 0.800 |
| *baselines* |  |  |  |
| Smith_2024 & co | — | 0.900 ± 0.004 | 0.870 |
| Lee 2023‡ | — | 0.930 | — |

- metric versions: acc@v2, f1@v1
- ¹ single seed · ◇×n identical seeds · † within noise of best · ‡ metric version differs from the paper
- [lo, hi] 95% test-set interval (wilson)
- baselines: Smith_2024 & co — arXiv:2401.01234; Lee 2023 — doi:10.1000/xyz123
