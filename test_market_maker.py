import unittest

from market_maker import *
from backtest import run


PARAMS = MarketParameters(.001, .01, -.02, 1., .2, .1, .25, .02, .0015, .012, -.015, 1.)
STATE = [Underlying("FED", 1, 3.), Underlying("AJR", 2, 500.), Underlying("THR", 3, 600.)]


class AnalyticalPricingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.maker = MarketMaker(STATE, [], 40)

    def price(self, days, legs, strike):
        return self.maker.price_option_from_parameters(PARAMS, BinaryOption(tuple(legs), 1, days, strike))

    def test_published_theoretical_cases(self):
        cases = [
            (1, [OptionLeg(1, 1)], 3., .7000),
            (5, [OptionLeg(1, 1)], 3.5, .0471),
            (1, [OptionLeg(2, 1)], 500., .5309),
            (10, [OptionLeg(3, 1)], 650., .2068),
            (1, [OptionLeg(3, 1), OptionLeg(2, -1)], 0., 1.0000),
            (10, [OptionLeg(3, 1), OptionLeg(2, -1)], 0., .9999),
        ]
        for days, legs, strike, expected in cases:
            with self.subTest(days=days, strike=strike):
                self.assertAlmostEqual(self.price(days, legs, strike), expected, places=4)

    def test_zero_company_value_does_not_crash(self):
        self.maker.underlying_state[1] = Underlying("AJR", 2, 0.)
        value = self.price(1, [OptionLeg(2, 1)], 1.)
        self.assertGreaterEqual(value, 0.)
        self.assertLessEqual(value, 1.)


class RiskControlTests(unittest.TestCase):
    def setUp(self):
        self.option = BinaryOption((OptionLeg(1, 1),), 9, 1, 3.)
        self.maker = MarketMaker(STATE, [self.option], 40)
        self.maker.estimated_params = PARAMS

    def test_inventory_cap_turns_off_risk_increasing_side(self):
        self.maker.position[9] = 15
        quote = self.maker.quote(self.option, 1)
        self.assertEqual(quote.bid_price, 0.)
        self.assertLessEqual(quote.bid_quantity, OPTIMIZED_POLICY.max_quote_size)
        self.maker.position[9] = -15
        self.assertEqual(self.maker.quote(self.option, 1).offer_price, 1.)

    def test_fok_rejects_trade_beyond_inventory_cap(self):
        self.maker.position[9] = 14
        self.assertFalse(self.maker.respond_to_fok(self.option, FokOrder(1, 9, OrderType.SELL, .01, 2)))

    def test_quotes_are_valid_and_sized_conservatively(self):
        quote = self.maker.quote(self.option, 1)
        self.assertLess(quote.bid_price, quote.offer_price)
        self.assertLessEqual(max(quote.bid_quantity, quote.offer_quantity), OPTIMIZED_POLICY.max_quote_size)

    def test_cap_includes_existing_portfolio_short_liability(self):
        other = BinaryOption((OptionLeg(2, 1),), 10, 1, 500.)
        self.maker.position[10] = -32  # $32 maximum future payout already reserved.
        self.assertFalse(self.maker.respond_to_fok(self.option, FokOrder(1, 9, OrderType.BUY, .99, 1)))


class BacktestTests(unittest.TestCase):
    def test_optimized_policy_remains_solvent_and_produces_activity(self):
        baseline = run(BASELINE_POLICY)
        optimized = run(OPTIMIZED_POLICY)
        self.assertGreaterEqual(optimized.worst_cash, 0)
        self.assertGreater(optimized.fills, 0)
        # The harness is deterministic: changes to strategy behavior are reviewed explicitly.
        self.assertIsInstance(baseline.pnl, float)


if __name__ == "__main__":
    unittest.main()
