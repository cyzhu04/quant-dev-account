"""只使用标准库 unittest 的账户测试；不依赖行情或网络。"""

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import random
import unittest

from quant_account import (
    CashAccount,
    InsufficientCashError,
    InsufficientPositionError,
)


D = Decimal


class CashAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account = CashAccount("10000.00", symbol="DEMO")

    def assert_rejected_without_change(self, error, operation) -> None:
        before = (self.account.snapshot("110.00"), self.account.trades)
        with self.assertRaises(error):
            operation()
        after = (self.account.snapshot("110.00"), self.account.trades)
        self.assertEqual(after, before)

    def test_initial_state(self) -> None:
        state = self.account.snapshot("100.00")
        self.assertEqual(self.account.symbol, "DEMO")
        self.assertEqual(self.account.initial_cash, D("10000.00"))
        self.assertEqual(state.cash, D("10000.00"))
        self.assertEqual(state.position, 0)
        self.assertEqual(state.market_value, D("0.00"))
        self.assertEqual(state.equity, D("10000.00"))
        self.assertEqual(state.total_fees, D("0.00"))
        self.assertEqual(self.account.trades, ())

    def test_manual_buy_revalue_sell_example(self) -> None:
        buy = self.account.buy(quantity=10, price="100.00", fee="1.00")
        self.assertEqual(buy.trade_id, 1)
        self.assertEqual(buy.side, "BUY")
        self.assertEqual(buy.notional, D("1000.00"))
        self.assertEqual(self.account.cash, D("8999.00"))
        self.assertEqual(self.account.position, 10)
        self.assertEqual(self.account.snapshot("100.00").equity, D("9999.00"))
        self.assertEqual(self.account.snapshot("110.00").equity, D("10099.00"))

        sell = self.account.sell(quantity=10, price="110.00", fee="1.00")
        self.assertEqual(sell.trade_id, 2)
        self.assertEqual(sell.side, "SELL")
        self.assertEqual(self.account.cash, D("10098.00"))
        self.assertEqual(self.account.position, 0)
        self.assertEqual(self.account.total_fees, D("2.00"))
        self.assertEqual(self.account.snapshot("110.00").equity, D("10098.00"))

    def test_partial_sell_preserves_remaining_position(self) -> None:
        self.account.buy(quantity=10, price="100.00", fee="1.00")
        trade = self.account.sell(quantity=4, price="110.00", fee="1.00")
        self.assertEqual(trade.cash_after, D("9438.00"))
        self.assertEqual(trade.position_after, 6)
        self.assertEqual(self.account.snapshot("110.00").equity, D("10098.00"))

    def test_multiple_buys_accumulate_position_and_fees(self) -> None:
        self.account.buy(quantity=3, price="100.00", fee="1.00")
        self.account.buy(quantity=2, price="90.00", fee="2.00")
        self.assertEqual(self.account.cash, D("9517.00"))
        self.assertEqual(self.account.position, 5)
        self.assertEqual(self.account.total_fees, D("3.00"))

    def test_exact_cash_including_fee_is_allowed(self) -> None:
        account = CashAccount("1001.00", symbol="DEMO")
        account.buy(quantity=10, price="100.00", fee="1.00")
        self.assertEqual(account.cash, D("0.00"))

    def test_zero_fee_is_allowed(self) -> None:
        self.account.buy(quantity=1, price="100.00", fee="0.00")
        self.account.sell(quantity=1, price="100.00", fee="0.00")
        self.assertEqual(self.account.cash, D("10000.00"))
        self.assertEqual(self.account.total_fees, D("0.00"))

    def test_zero_initial_cash_is_allowed(self) -> None:
        account = CashAccount(0, symbol="DEMO")
        self.assertEqual(account.snapshot(0).equity, D("0.00"))
        with self.assertRaises(InsufficientCashError):
            account.buy(quantity=1, price="0.01", fee="0.00")

    def test_decimal_cents_are_exact(self) -> None:
        account = CashAccount("1.00", symbol="DEMO")
        account.buy(quantity=3, price="0.10", fee="0.01")
        self.assertEqual(account.cash, D("0.69"))
        account.sell(quantity=3, price="0.20", fee="0.01")
        self.assertEqual(account.cash, D("1.28"))
        self.assertEqual(account.total_fees, D("0.02"))

    def test_integer_decimal_and_trailing_zero_inputs(self) -> None:
        account = CashAccount(1000, symbol=" DEMO ")
        account.buy(quantity=1, price=D("100.000"), fee="1.0000")
        self.assertEqual(account.symbol, "DEMO")
        self.assertEqual(account.cash, D("899.00"))

    def test_money_does_not_depend_on_decimal_context_precision(self) -> None:
        with localcontext() as context:
            context.prec = 3
            account = CashAccount("123456789012345678901234567890.12", symbol="DEMO")
            account.buy(quantity=2, price="100.01", fee="0.01")
            self.assertEqual(account.cash, D("123456789012345678901234567690.09"))
            self.assertEqual(
                account.snapshot("110.00").equity,
                D("123456789012345678901234567910.09"),
            )

    def test_insufficient_cash_does_not_change_account(self) -> None:
        self.assert_rejected_without_change(
            InsufficientCashError,
            lambda: self.account.buy(quantity=100, price="100.00", fee="1.00"),
        )

    def test_oversell_does_not_change_account(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="1.00")
        self.assert_rejected_without_change(
            InsufficientPositionError,
            lambda: self.account.sell(quantity=3, price="100.00", fee="1.00"),
        )

    def test_sell_without_position_is_rejected(self) -> None:
        self.assert_rejected_without_change(
            InsufficientPositionError,
            lambda: self.account.sell(quantity=1, price="100.00", fee="1.00"),
        )

    def test_sell_fee_cannot_make_cash_negative(self) -> None:
        self.account.buy(quantity=100, price="100.00", fee="0.00")
        self.assert_rejected_without_change(
            InsufficientCashError,
            lambda: self.account.sell(quantity=1, price="1.00", fee="2.00"),
        )

    def test_sell_fee_can_use_existing_cash(self) -> None:
        self.account.buy(quantity=1, price="100.00", fee="0.00")
        self.account.sell(quantity=1, price="1.00", fee="2.00")
        self.assertEqual(self.account.cash, D("9899.00"))
        self.assertEqual(self.account.position, 0)

    def test_invalid_quantities_on_both_sides_are_atomic(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="0.00")
        for method in (self.account.buy, self.account.sell):
            for quantity, error in (
                (0, ValueError), (-1, ValueError), (1.0, TypeError),
                (True, TypeError), ("1", TypeError), (None, TypeError),
            ):
                with self.subTest(method=method.__name__, quantity=quantity):
                    self.assert_rejected_without_change(
                        error,
                        lambda m=method, q=quantity: m(quantity=q, price="1.00", fee="0.00"),
                    )

    def test_invalid_prices_on_both_sides_are_atomic(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="0.00")
        for method in (self.account.buy, self.account.sell):
            for price in ("0", "-1", "0.001", "NaN", "sNaN", "Infinity", "bad", ""):
                with self.subTest(method=method.__name__, price=price):
                    self.assert_rejected_without_change(
                        ValueError,
                        lambda m=method, p=price: m(quantity=1, price=p, fee="0.00"),
                    )

    def test_invalid_fees_on_both_sides_are_atomic(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="0.00")
        for method in (self.account.buy, self.account.sell):
            for fee in ("-1", "0.001", "NaN", "Infinity", "bad"):
                with self.subTest(method=method.__name__, fee=fee):
                    self.assert_rejected_without_change(
                        ValueError,
                        lambda m=method, f=fee: m(quantity=1, price="1.00", fee=f),
                    )

    def test_float_bool_and_other_money_types_are_rejected(self) -> None:
        for value in (1.0, True, None, [], object()):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    CashAccount(value, symbol="DEMO")
                self.assert_rejected_without_change(
                    TypeError,
                    lambda v=value: self.account.buy(quantity=1, price=v, fee="0.00"),
                )
                self.assert_rejected_without_change(
                    TypeError,
                    lambda v=value: self.account.buy(quantity=1, price="1.00", fee=v),
                )
                self.assert_rejected_without_change(
                    TypeError, lambda v=value: self.account.snapshot(v),
                )

    def test_invalid_initial_cash(self) -> None:
        for value in ("-1", "0.001", "NaN", "-Infinity", "bad"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    CashAccount(value, symbol="DEMO")

    def test_invalid_symbol(self) -> None:
        for symbol, error in (("", ValueError), ("  ", ValueError), (None, TypeError)):
            with self.subTest(symbol=symbol):
                with self.assertRaises(error):
                    CashAccount("100", symbol=symbol)

    def test_snapshot_is_read_only_and_does_not_update_state(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="1.00")
        before = (self.account.cash, self.account.position, self.account.total_fees, self.account.trades)
        snapshot = self.account.snapshot("120.00")
        self.assertEqual(snapshot.market_value, D("240.00"))
        self.assertEqual(snapshot.equity, snapshot.cash + snapshot.market_value)
        self.assertEqual(
            (self.account.cash, self.account.position, self.account.total_fees, self.account.trades),
            before,
        )
        with self.assertRaises(FrozenInstanceError):
            snapshot.cash = D("0.00")
        with self.assertRaises(AttributeError):
            self.account.cash = D("0.00")

    def test_zero_valuation_is_allowed_but_negative_or_subcent_is_not(self) -> None:
        self.account.buy(quantity=2, price="100.00", fee="1.00")
        self.assertEqual(self.account.snapshot("0.00").equity, self.account.cash)
        for price in ("-0.01", "0.001", "NaN", "bad"):
            with self.subTest(price=price):
                self.assert_rejected_without_change(
                    ValueError, lambda p=price: self.account.snapshot(p),
                )

    def test_trade_history_is_immutable_and_detached(self) -> None:
        trade = self.account.buy(quantity=1, price="100.00", fee="1.00")
        old_history = self.account.trades
        with self.assertRaises(FrozenInstanceError):
            trade.fee = D("0.00")
        with self.assertRaises(TypeError):
            old_history[0] = trade
        self.account.sell(quantity=1, price="101.00", fee="1.00")
        self.assertEqual(len(old_history), 1)
        self.assertEqual(len(self.account.trades), 2)

    def test_rejection_does_not_consume_trade_id(self) -> None:
        with self.assertRaises(InsufficientCashError):
            self.account.buy(quantity=1000, price="100.00", fee="1.00")
        first = self.account.buy(quantity=1, price="100.00", fee="1.00")
        with self.assertRaises(InsufficientPositionError):
            self.account.sell(quantity=2, price="100.00", fee="1.00")
        second = self.account.sell(quantity=1, price="100.00", fee="1.00")
        self.assertEqual((first.trade_id, second.trade_id), (1, 2))

    def test_fee_must_be_explicit(self) -> None:
        self.assert_rejected_without_change(
            TypeError, lambda: self.account.buy(quantity=1, price="100.00"),
        )
        self.assert_rejected_without_change(
            TypeError, lambda: self.account.sell(quantity=1, price="100.00"),
        )

    def test_seeded_sequence_matches_reference_ledger_and_is_repeatable(self) -> None:
        rng = random.Random(20261125)
        actions = [
            (rng.choice(("BUY", "SELL")), rng.randint(1, 20), rng.randint(1, 20000), rng.randint(0, 100))
            for _ in range(200)
        ]
        histories = []
        for _ in range(2):
            account = CashAccount("10000.00", symbol="DEMO")
            expected_cash = D("10000.00")
            expected_position = 0
            expected_fees = D("0.00")
            accepted = 0
            for side, quantity, price_cents, fee_cents in actions:
                price = D(f"{price_cents // 100}.{price_cents % 100:02d}")
                fee = D(f"{fee_cents // 100}.{fee_cents % 100:02d}")
                before = (account.snapshot(price), account.trades)
                if side == "SELL" and quantity > expected_position:
                    error = InsufficientPositionError
                elif side == "BUY" and quantity * price + fee > expected_cash:
                    error = InsufficientCashError
                else:
                    error = None
                method = account.buy if side == "BUY" else account.sell
                if error is not None:
                    with self.assertRaises(error):
                        method(quantity=quantity, price=price, fee=fee)
                    self.assertEqual((account.snapshot(price), account.trades), before)
                else:
                    trade = method(quantity=quantity, price=price, fee=fee)
                    direction = 1 if side == "BUY" else -1
                    expected_cash -= direction * quantity * price + fee
                    expected_position += direction * quantity
                    expected_fees += fee
                    accepted += 1
                    self.assertEqual(trade.trade_id, accepted)
                state = account.snapshot(price)
                self.assertEqual(state.cash, expected_cash)
                self.assertEqual(state.position, expected_position)
                self.assertEqual(state.total_fees, expected_fees)
                self.assertEqual(state.equity, expected_cash + expected_position * price)
                self.assertGreaterEqual(state.cash, 0)
                self.assertGreaterEqual(state.position, 0)
            histories.append(account.trades)
        self.assertEqual(histories[0], histories[1])


if __name__ == "__main__":
    unittest.main()
