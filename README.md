# Akuna Capital Trading Competition 2026

Deterministic binary-option market maker based on the shared challenge review.

It uses dynamic programming for FED outcomes and closed-form normal probabilities
for company and relative-value binary options. The quoting layer applies dynamic
spreads, inventory skew, a ±15-contract cap, cash-aware quote sizing, and
inventory-aware FOK acceptance.

Run the regression suite:

```sh
python3 -m unittest -v
```

The tests include all six published theoretical test cases (the exact values
shown in the grader conversation) plus the zero-value, inventory-limit, FOK,
and quote-validity regressions derived from the visible live-session failures.
