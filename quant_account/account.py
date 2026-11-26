"""单标的、只做多的最小现金账户。

内部以整数“分”记账，对外以 Decimal 表示金额，避免二进制浮点误差。
本模块只负责账本，不模拟行情、订单、撮合或特定市场的交易规则。
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Union


MoneyInput = Union[str, int, Decimal]
Side = Literal["BUY", "SELL"]


class InsufficientCashError(ValueError):
    """买入价款和手续费超过可用现金。"""


class InsufficientPositionError(ValueError):
    """卖出数量超过当前持仓。"""


def _to_cents(value: MoneyInput, *, name: str, positive: bool = False) -> int:
    """校验金额并精确转换成整数分；不对小数偷偷四舍五入。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise TypeError(f"{name} 必须是字符串、整数或 Decimal，不能使用 float/bool")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} 不是有效金额") from exc

    if not amount.is_finite():
        raise ValueError(f"{name} 必须是有限金额，不能为 NaN 或 Infinity")
    if amount < 0 or (positive and amount == 0):
        requirement = "大于 0" if positive else "大于或等于 0"
        raise ValueError(f"{name} 必须{requirement}")

    # as_integer_ratio() 返回精确分数，不依赖 Decimal 全局计算精度。
    numerator, denominator = amount.as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise ValueError(f"{name} 必须精确到分，不能包含非零的分以下金额")
    return cents


def _as_money(cents: int) -> Decimal:
    """精确把整数分转换为两位小数金额，不进行可能舍入的除法。"""
    parts = Decimal(cents).as_tuple()
    return Decimal((parts.sign, parts.digits, -2))


def _validate_quantity(quantity: int) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError("quantity 必须是 Python 正整数，不能为 float/bool")
    if quantity <= 0:
        raise ValueError("quantity 必须大于 0")


@dataclass(frozen=True)
class Trade:
    """一笔已经完成的账本交易；不是待执行订单。"""

    trade_id: int
    symbol: str
    side: Side
    quantity: int
    price: Decimal
    notional: Decimal
    fee: Decimal
    cash_after: Decimal
    position_after: int


@dataclass(frozen=True)
class AccountSnapshot:
    """用外部给定价格估值的只读快照；生成快照不会改变账户。"""

    symbol: str
    cash: Decimal
    position: int
    mark_price: Decimal
    market_value: Decimal
    equity: Decimal
    total_fees: Decimal


class CashAccount:
    """只支持一个标的、整数份额、无融资无做空的现金账户。

    金额输入使用 str/int/Decimal，例如 "100.00"，不接受 float。
    买卖时必须显式提供该笔交易的手续费，允许 fee="0.00"。
    手续费是固定金额，不是费率；金额单位由使用者统一指定。
    """

    def __init__(self, initial_cash: MoneyInput, *, symbol: str) -> None:
        if not isinstance(symbol, str):
            raise TypeError("symbol 必须是字符串")
        if not symbol.strip():
            raise ValueError("symbol 不能为空")
        cash_cents = _to_cents(initial_cash, name="initial_cash")
        self._symbol = symbol.strip()
        self._initial_cash_cents = cash_cents
        self._cash_cents = cash_cents
        self._position = 0
        self._total_fee_cents = 0
        self._trades: list[Trade] = []

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def initial_cash(self) -> Decimal:
        return _as_money(self._initial_cash_cents)

    @property
    def cash(self) -> Decimal:
        return _as_money(self._cash_cents)

    @property
    def position(self) -> int:
        return self._position

    @property
    def total_fees(self) -> Decimal:
        return _as_money(self._total_fee_cents)

    @property
    def trades(self) -> tuple[Trade, ...]:
        """返回不可变的历史副本，调用者不能通过它增删账本记录。"""
        return tuple(self._trades)

    def buy(self, *, quantity: int, price: MoneyInput, fee: MoneyInput) -> Trade:
        """立即按给定价格记一笔买入；先校验现金，再修改账户。"""
        return self._execute("BUY", quantity=quantity, price=price, fee=fee)

    def sell(self, *, quantity: int, price: MoneyInput, fee: MoneyInput) -> Trade:
        """立即记一笔卖出；禁止超卖，也禁止费用使现金变为负数。"""
        return self._execute("SELL", quantity=quantity, price=price, fee=fee)

    def _execute(
        self, side: Side, *, quantity: int, price: MoneyInput, fee: MoneyInput
    ) -> Trade:
        _validate_quantity(quantity)
        price_cents = _to_cents(price, name="price", positive=True)
        fee_cents = _to_cents(fee, name="fee")
        notional_cents = quantity * price_cents

        if side == "BUY":
            cash_after = self._cash_cents - notional_cents - fee_cents
            position_after = self._position + quantity
        else:
            if quantity > self._position:
                raise InsufficientPositionError("卖出数量超过当前持仓，最小账户不允许做空")
            cash_after = self._cash_cents + notional_cents - fee_cents
            position_after = self._position - quantity

        if cash_after < 0:
            raise InsufficientCashError("交易后现金不足，无法支付价款或手续费")

        # 所有业务校验和记录构造成功后才提交变更。
        trade = Trade(
            trade_id=len(self._trades) + 1,
            symbol=self._symbol,
            side=side,
            quantity=quantity,
            price=_as_money(price_cents),
            notional=_as_money(notional_cents),
            fee=_as_money(fee_cents),
            cash_after=_as_money(cash_after),
            position_after=position_after,
        )
        self._trades.append(trade)
        self._cash_cents = cash_after
        self._position = position_after
        self._total_fee_cents += fee_cents
        return trade

    def snapshot(self, mark_price: MoneyInput) -> AccountSnapshot:
        """按指定非负价格估值；现金 + 持仓市值 = 账户权益。"""
        mark_cents = _to_cents(mark_price, name="mark_price")
        market_value_cents = self._position * mark_cents
        return AccountSnapshot(
            symbol=self._symbol,
            cash=self.cash,
            position=self._position,
            mark_price=_as_money(mark_cents),
            market_value=_as_money(market_value_cents),
            equity=_as_money(self._cash_cents + market_value_cents),
            total_fees=self.total_fees,
        )
