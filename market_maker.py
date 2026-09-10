"""Analytical binary-option market maker for the Akuna trading challenge.

The pricing engine mirrors the stated simulator: a finite-state FED process and
lognormal company values driven by FED, sector, and idiosyncratic shocks.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final

AJARAI_NAME: Final = "AJR"
AJARAI_UNDERLYING_ID: Final = 2
FED_FUNDS_RATE_NAME: Final = "FED"
FED_FUNDS_RATE_UNDERLYING_ID: Final = 1
THERIODIC_NAME: Final = "THR"
THERIODIC_UNDERLYING_ID: Final = 3

UNDERLYING_NAME_BY_ID: Final = {
    AJARAI_UNDERLYING_ID: AJARAI_NAME,
    FED_FUNDS_RATE_UNDERLYING_ID: FED_FUNDS_RATE_NAME,
    THERIODIC_UNDERLYING_ID: THERIODIC_NAME,
}


@dataclass(frozen=True)
class OptionLeg:
    underlying_id: int
    weight: float


@dataclass(eq=True, frozen=True, unsafe_hash=True)
class BinaryOption:
    legs: tuple[OptionLeg, ...]
    option_id: int
    steps_until_expiry: int
    strike: float

    def __post_init__(self) -> None:
        if self.steps_until_expiry < 0 or not self.legs:
            raise ValueError("Option requires legs and non-negative expiry")
        if len({leg.underlying_id for leg in self.legs}) != len(self.legs):
            raise ValueError("Option legs must use distinct underlyings")

    def advance_step(self) -> "BinaryOption":
        return self if self.steps_until_expiry == 0 else replace(self, steps_until_expiry=self.steps_until_expiry - 1)

    def expiry_valuation(self, values: dict[int, float]) -> float:
        return float(self.observable_value(values) >= self.strike)

    def observable_value(self, values: dict[int, float]) -> float:
        return sum(leg.weight * values[leg.underlying_id] for leg in self.legs)


class OrderType(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class FokOrder:
    counterparty_id: int
    option_id: int
    order_type: OrderType
    price: float
    quantity: int


@dataclass(frozen=True)
class Quote:
    bid_price: float
    bid_quantity: int
    offer_price: float
    offer_quantity: int

    def __post_init__(self) -> None:
        if not (0 <= self.bid_price < self.offer_price <= 1):
            raise ValueError("Quote prices must be ordered and inside [0, 1]")
        if self.bid_quantity <= 0 or self.offer_quantity <= 0:
            raise ValueError("Quote quantities must be positive")


@dataclass(frozen=True)
class Underlying:
    name: str
    underlying_id: int
    value: float

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Underlying) and self.underlying_id == other.underlying_id


@dataclass(frozen=True)
class MarketHistory:
    values_by_underlying_id: dict[int, tuple[float, ...]]


@dataclass(frozen=True)
class MarketParameters:
    ajarai_drift: float
    ajarai_idio_std_dev: float
    ajarai_rate_beta: float
    ajarai_sector_beta: float
    rate_down_probability: float
    rate_reversion_strength: float
    rate_up_probability: float
    sector_std_dev: float
    theriodic_drift: float
    theriodic_idio_std_dev: float
    theriodic_rate_beta: float
    theriodic_sector_beta: float
    rate_step: float = 0.25
    rate_target: float = 2.0


class MarketMaker:
    """Deterministic pricer with inventory-aware two-sided quotes."""

    MAX_POSITION: Final = 15
    MAX_QUOTE_SIZE: Final = 3

    def __init__(self, underlying_initial_state: list[Underlying], option_initial_state: list[BinaryOption], cash_balance: float) -> None:
        self.underlying_state = underlying_initial_state
        self.active_option_state = option_initial_state
        self.cash_balance = cash_balance
        self.position: defaultdict[int, int] = defaultdict(int)

    @property
    def name(self) -> str:
        return "AnalyticalInventoryMarketMaker"

    def on_step_advance(self, new_underlying_state: list[Underlying], new_option_state: list[BinaryOption]) -> None:
        self.underlying_state, self.active_option_state = new_underlying_state, new_option_state

    def on_trade(self, option: BinaryOption, price: float, quantity: int, counterparty_id: int) -> None:
        """Record signed quantity: positive when our bot buys, negative when it sells."""
        self.position[option.option_id] += quantity
        self.cash_balance -= price * quantity

    def _fed_distribution(self, params: MarketParameters, steps: int) -> dict[float, float]:
        rate = next(u.value for u in self.underlying_state if u.underlying_id == FED_FUNDS_RATE_UNDERLYING_ID)
        state = {rate: 1.0}
        for _ in range(steps):
            next_state: defaultdict[float, float] = defaultdict(float)
            for current, probability in state.items():
                tilt = params.rate_reversion_strength * (params.rate_target - current)
                up = min(max(params.rate_up_probability + tilt, 0.0), 1.0)
                down = min(max(params.rate_down_probability - tilt, 0.0), 1.0 - up)
                next_state[max(round(current + params.rate_step, 2), 0.0)] += probability * up
                next_state[max(round(current - params.rate_step, 2), 0.0)] += probability * down
                next_state[current] += probability * (1 - up - down)
            state = dict(next_state)
        return state

    @staticmethod
    def _normal_cdf(value: float) -> float:
        return (1 + math.erf(value / math.sqrt(2))) / 2

    def price_option_from_parameters(self, params: MarketParameters, option: BinaryOption) -> float:
        values = {u.underlying_id: u.value for u in self.underlying_state}
        steps = option.steps_until_expiry
        if steps == 0:
            return option.expiry_valuation(values)
        fed = self._fed_distribution(params, steps)
        weights = {leg.underlying_id: leg.weight for leg in option.legs}
        if set(weights) == {FED_FUNDS_RATE_UNDERLYING_ID}:
            return sum(p for rate, p in fed.items() if weights[FED_FUNDS_RATE_UNDERLYING_ID] * rate >= option.strike)
        if len(weights) == 1:
            underlying_id, weight = next(iter(weights.items()))
            if underlying_id == AJARAI_UNDERLYING_ID:
                drift, rate_beta, sector_beta, idio = params.ajarai_drift, params.ajarai_rate_beta, params.ajarai_sector_beta, params.ajarai_idio_std_dev
            elif underlying_id == THERIODIC_UNDERLYING_ID:
                drift, rate_beta, sector_beta, idio = params.theriodic_drift, params.theriodic_rate_beta, params.theriodic_sector_beta, params.theriodic_idio_std_dev
            else:
                return 0.0
            target = option.strike / weight
            if target <= 0:
                return float(weight > 0)
            sigma = math.sqrt(steps * ((sector_beta * params.sector_std_dev) ** 2 + idio ** 2))
            initial_rate = values[FED_FUNDS_RATE_UNDERLYING_ID]
            initial_value = max(values.get(underlying_id, 0.0), 1e-9)
            return sum(prob * self._tail_probability(math.log(target), math.log(initial_value) + steps * drift + rate_beta * (rate - initial_rate), sigma, weight > 0) for rate, prob in fed.items())
        if len(weights) == 2 and set(weights) == {AJARAI_UNDERLYING_ID, THERIODIC_UNDERLYING_ID}:
            # Supports the challenge's relative-value contracts, e.g. THR - AJR >= 0.
            positive = THERIODIC_UNDERLYING_ID if weights[THERIODIC_UNDERLYING_ID] > 0 else AJARAI_UNDERLYING_ID
            negative = AJARAI_UNDERLYING_ID if positive == THERIODIC_UNDERLYING_ID else THERIODIC_UNDERLYING_ID
            if option.strike != 0 or abs(weights[positive]) != abs(weights[negative]):
                return 0.0
            p_cfg = self._company_config(params, positive)
            n_cfg = self._company_config(params, negative)
            sigma = math.sqrt(steps * (((p_cfg[2] - n_cfg[2]) * params.sector_std_dev) ** 2 + p_cfg[3] ** 2 + n_cfg[3] ** 2))
            initial_log_ratio = math.log(max(values[positive], 1e-9) / max(values[negative], 1e-9))
            initial_rate = values[FED_FUNDS_RATE_UNDERLYING_ID]
            return sum(prob * self._tail_probability(0, initial_log_ratio + steps * (p_cfg[0] - n_cfg[0]) + (p_cfg[1] - n_cfg[1]) * (rate - initial_rate), sigma, True) for rate, prob in fed.items())
        return 0.0

    @staticmethod
    def _tail_probability(threshold: float, mean: float, sigma: float, positive_weight: bool) -> float:
        if sigma == 0:
            return float((mean >= threshold) if positive_weight else (mean <= threshold))
        tail = 1 - MarketMaker._normal_cdf((threshold - mean) / sigma)
        return tail if positive_weight else 1 - tail

    @staticmethod
    def _company_config(params: MarketParameters, underlying_id: int) -> tuple[float, float, float, float]:
        if underlying_id == AJARAI_UNDERLYING_ID:
            return params.ajarai_drift, params.ajarai_rate_beta, params.ajarai_sector_beta, params.ajarai_idio_std_dev
        return params.theriodic_drift, params.theriodic_rate_beta, params.theriodic_sector_beta, params.theriodic_idio_std_dev

    def price_option(self, option: BinaryOption) -> float:
        return self.price_option_from_parameters(self.estimated_params, option) if hasattr(self, "estimated_params") else 0.5

    def quote(self, option: BinaryOption, counterparty_id: int) -> Quote:
        fair_value = self.price_option(option)
        inventory = self.position[option.option_id]
        skew = inventory * 0.015
        half_spread = 0.03 + abs(inventory) * 0.002
        bid = round(max(0, min(0.98, fair_value - half_spread - skew)), 2)
        ask = round(max(0.01, min(1, fair_value + half_spread - skew)), 2)
        if inventory >= self.MAX_POSITION:
            bid = 0.0
        elif inventory <= -self.MAX_POSITION:
            ask = 1.0
        if bid >= ask:
            bid, ask = max(0, round(ask - 0.01, 2)), ask
            if bid >= ask:
                ask = min(1, round(bid + 0.01, 2))
        allocation = max(self.cash_balance, 0) / max(1, len(self.active_option_state))
        buy_capacity = int(allocation / bid) if bid else self.MAX_QUOTE_SIZE
        sell_capacity = int(allocation / (1 - ask)) if ask < 1 else self.MAX_QUOTE_SIZE
        if buy_capacity < 1:
            bid, buy_capacity = 0.0, 1
        if sell_capacity < 1:
            ask, sell_capacity = 1.0, 1
        return Quote(bid, min(self.MAX_QUOTE_SIZE, buy_capacity), ask, min(self.MAX_QUOTE_SIZE, sell_capacity))

    def respond_to_fok(self, option: BinaryOption, order: FokOrder) -> bool:
        fair_value, inventory = self.price_option(option), self.position[option.option_id]
        selling = order.order_type == OrderType.BUY
        reduces_inventory = (selling and inventory > 0) or (not selling and inventory < 0)
        edge = 0.01 if reduces_inventory else 0.03
        if abs(inventory + (-order.quantity if selling else order.quantity)) > self.MAX_POSITION:
            return False
        if selling:
            return order.price >= fair_value + edge and self.cash_balance >= (1 - order.price) * order.quantity
        return order.price <= fair_value - edge and self.cash_balance >= order.price * order.quantity

    def warm_up(self, history: MarketHistory) -> None:
        fed = history.values_by_underlying_id[FED_FUNDS_RATE_UNDERLYING_ID]
        ajr = history.values_by_underlying_id[AJARAI_UNDERLYING_ID]
        thr = history.values_by_underlying_id[THERIODIC_UNDERLYING_ID]
        changes = [round(fed[i] - fed[i - 1], 2) for i in range(1, len(fed))]
        if not changes:
            return
        ajr_returns = [math.log(ajr[i] / ajr[i - 1]) for i in range(1, len(ajr))]
        thr_returns = [math.log(thr[i] / thr[i - 1]) for i in range(1, len(thr))]
        def regress(x: list[float], y: list[float]) -> tuple[float, float]:
            mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
            variance = sum((v - mean_x) ** 2 for v in x) / len(x)
            slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / len(x) / variance if variance else 0.0
            return slope, mean_y - slope * mean_x
        ajr_beta, ajr_drift = regress(changes, ajr_returns)
        thr_beta, thr_drift = regress(changes, thr_returns)
        ajr_residual = [value - (ajr_drift + ajr_beta * change) for value, change in zip(ajr_returns, changes)]
        thr_residual = [value - (thr_drift + thr_beta * change) for value, change in zip(thr_returns, changes)]
        covariance = sum(a * b for a, b in zip(ajr_residual, thr_residual)) / len(changes)
        variance_a = sum(v * v for v in ajr_residual) / len(changes)
        variance_t = sum(v * v for v in thr_residual) / len(changes)
        up, down = sum(c > 0 for c in changes) / len(changes), sum(c < 0 for c in changes) / len(changes)
        if up + down >= 1:
            up = down = 0.49
        rate_slope, rate_intercept = regress(list(fed[:-1]), changes)
        reversion = min(max(-2 * rate_slope, 0), 1)
        target = max((rate_intercept - 0.25 * (up - down)) / (0.5 * reversion), 0) if reversion > 0.001 else 2.0
        self.estimated_params = MarketParameters(ajr_drift, math.sqrt(max(variance_a - abs(covariance), 1e-4)), ajr_beta, 1.0, max(down, .001), reversion, max(up, .001), math.sqrt(abs(covariance)), thr_drift, math.sqrt(max(variance_t - abs(covariance), 1e-4)), thr_beta, 1.0 if covariance >= 0 else -1.0, rate_target=target)
