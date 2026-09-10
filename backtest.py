"""Repeatable local comparison of the historical and optimized quote policies.

This is not the private HackerRank grader: its complete order stream was not
included in the shared conversation. It is a deterministic stress backtest using
the published market parameters and binary contracts, intended for relative
policy comparison rather than reporting a competition score.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from market_maker import (
    BASELINE_POLICY, OPTIMIZED_POLICY, BinaryOption, MarketMaker, MarketParameters,
    OptionLeg, Underlying,
)

PARAMS = MarketParameters(.001, .01, -.02, 1., .2, .1, .25, .02, .0015, .012, -.015, 1.)
STATE = [Underlying("FED", 1, 3.), Underlying("AJR", 2, 500.), Underlying("THR", 3, 600.)]


@dataclass(frozen=True)
class Result:
    pnl: float
    worst_cash: float
    fills: int


def run(policy, seed: int = 20260910, sessions: int = 400) -> Result:
    """Simulate client limit prices around exact fair value under fixed randomness."""
    rng = random.Random(seed)
    options = [
        BinaryOption((OptionLeg(1, 1),), 1, 1, 3.0),
        BinaryOption((OptionLeg(2, 1),), 2, 1, 500.0),
        BinaryOption((OptionLeg(3, 1),), 3, 2, 620.0),
        BinaryOption((OptionLeg(3, 1), OptionLeg(2, -1)), 4, 2, 0.0),
    ]
    maker = MarketMaker(list(STATE), options, 40.0, policy)
    maker.estimated_params = PARAMS
    initial_cash, worst_cash, fills = maker.cash_balance, maker.cash_balance, 0
    for index in range(sessions):
        option = options[index % len(options)]
        fair = maker.price_option(option)
        quote = maker.quote(option, 1)
        # A client buys or sells only when its limit crosses our displayed quote.
        client_advantage = rng.uniform(0.0, 0.06)
        client_buys = rng.random() < 0.5
        if client_buys and quote.offer_price <= fair + client_advantage:
            quantity = min(quote.offer_quantity, rng.randint(1, 5))
            maker.on_trade(option, quote.offer_price, -quantity, 1)
            fills += quantity
        elif not client_buys and quote.bid_price >= fair - client_advantage:
            quantity = min(quote.bid_quantity, rng.randint(1, 5))
            maker.on_trade(option, quote.bid_price, quantity, 1)
            fills += quantity
        # Expected-value marking isolates quote/inventory policy from luck.
        marked_value = sum(maker.position[contract.option_id] * maker.price_option(contract) for contract in options)
        worst_cash = min(worst_cash, maker.cash_balance + marked_value)
    marked_value = sum(maker.position[contract.option_id] * maker.price_option(contract) for contract in options)
    return Result(round(maker.cash_balance + marked_value - initial_cash, 4), round(worst_cash, 4), fills)


if __name__ == "__main__":
    for name, policy in (("baseline", BASELINE_POLICY), ("optimized", OPTIMIZED_POLICY)):
        result = run(policy)
        print(f"{name:9} pnl={result.pnl:7.4f} worst_marked_cash={result.worst_cash:7.4f} fills={result.fills}")
