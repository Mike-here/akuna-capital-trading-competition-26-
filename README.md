# Akuna Capital Trading Competition 2026

This repository contains a small **market-making bot** for a simulated trading
competition. It is written to be readable for people who have never worked with
options or algorithmic trading.

## What problem is the bot solving?

The market contains **binary options**. A binary option pays either `$1` or `$0`
at expiry:

- `1d FED >= 3.00` pays `$1` if the FED value is at least `3.00` in one day.
- `1d AJR >= 500.00` pays `$1` if AjarAI is at least `500.00` in one day.
- `THR - AJR >= 0` pays `$1` if Theriodic finishes above AjarAI.

The fair value of a binary option is therefore its probability of paying `$1`.
For example, an option with a 53% chance of paying has a fair value near `$0.53`.

A market maker posts both a **bid** (the price it will pay to buy) and an
**offer** (the price it will accept to sell). If the bot believes fair value is
`$0.53`, it might quote `$0.50 / $0.56`: buy below fair value, sell above it,
and aim to earn the difference while keeping its inventory under control.

## Strategy overview

The bot separates the problem into two layers:

1. **Price each contract accurately.** The pricing layer estimates the chance
   that the contract settles at `$1`.
2. **Decide how much risk to take.** The quoting layer chooses prices and sizes
   that try to earn spread without allowing one-sided inventory to threaten the
   account.

This distinction matters. Accurate prices alone do not prevent losses if a bot
keeps buying the same contract or repeatedly sells a contract that later pays
`$1`.

## Pricing model

### FED contracts: exact dynamic programming

The FED value moves on a discrete grid. At every step it can go up, down, or
stay unchanged; the probabilities tilt toward a long-run target rate. Rather
than sampling random paths, the bot carries forward the probability of every
possible FED state. This is dynamic programming.

For a contract such as `5d FED >= 3.50`, the bot sums the probabilities of all
final FED states at or above `3.50`. This is exact for the simulator's discrete
rate model and has no Monte Carlo noise.

### Company contracts: analytical probability

AJR and THR are modeled as lognormal values influenced by:

- a drift term;
- the total FED move;
- a shared sector shock; and
- a company-specific shock.

Conditional on a final FED state, the logarithm of a company's final value is
normally distributed. The bot uses the normal cumulative distribution function
(`math.erf`) to calculate the chance of clearing a strike, then averages that
answer across the exact FED distribution.

The same idea prices a relative-value contract such as `THR - AJR >= 0`, using
the distribution of the log ratio `THR / AJR`. Company values are clamped to a
very small positive number before taking logarithms, preventing a zero-value
edge case from crashing the strategy.

## Risk and quoting controls

The current `OPTIMIZED_POLICY` is deliberately more selective than the original
high-volume version.

- **Confidence-aware spread:** contracts near 50/50 have the most jump risk, so
  their spread is wider. High-confidence contracts can be quoted more tightly.
- **Inventory skew:** if the bot is already long a contract, it moves both quote
  prices lower to encourage selling and discourage further purchases. The
  reverse happens when it is short.
- **Inventory cap:** a single option cannot exceed 12 long or 12 short
  contracts. Quotes automatically shut off the side that would add more risk.
- **Portfolio short-liability reserve:** being short one binary can cost up to
  `$1` at settlement. Before selling another contract, the bot reserves capital
  for every existing short position across the whole portfolio, not just the
  option currently being quoted.
- **Cash-aware sizes:** the bot limits quote size to the remaining capital and
  inventory room, with a maximum displayed size of five contracts.
- **Inventory-aware FOKs:** a fill-or-kill order that reduces an existing
  position can be accepted with a smaller edge; an order that adds risk needs a
  larger edge and must fit the same capital reserve.

These controls are meant to avoid the near-bankruptcy outcomes visible in the
competition logs. They do not guarantee profit: a market maker can still lose
when prices are wrong, counterparties are better informed, or outcomes are
unfavorable.

## Tests and local backtest

Run the regression suite:

```sh
python3 -m unittest -v
```

The tests include all six published theoretical cases from the competition
conversation, plus regressions for zero company values, portfolio liability,
inventory limits, FOK limits, and valid quotes.

Run the deterministic local policy comparison:

```sh
python3 backtest.py
```

This compares the historical high-volume policy with the current policy under a
fixed, synthetic order-flow simulation. Its P&L is useful for comparing local
policy changes, not as an official competition score. The private grader's
complete RFQ/FOK sequence and underlying paths were not available in the shared
conversation, so its exact cumulative P&L cannot be reproduced here.

## Repository layout

- `market_maker.py` — contracts, pricing model, risk controls, and the bot.
- `test_market_maker.py` — deterministic regression tests.
- `backtest.py` — repeatable local policy comparison.
