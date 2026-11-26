"""运行方式：在项目目录执行 python -m quant_account。"""

from .account import CashAccount, InsufficientCashError


def show(label: str, account: CashAccount, mark_price: str) -> None:
    state = account.snapshot(mark_price)
    print(
        f"{label} | 现金={state.cash:.2f} | 持仓={state.position} "
        f"| 市值={state.market_value:.2f} | 权益={state.equity:.2f} "
        f"| 累计手续费={state.total_fees:.2f}"
    )


def main() -> None:
    account = CashAccount("10000.00", symbol="DEMO")
    show("初始账户", account, "100.00")

    account.buy(quantity=10, price="100.00", fee="1.00")
    show("买入10份，每份100元，手续费1元", account, "100.00")
    show("估值价涨到110元，未卖出", account, "110.00")

    account.sell(quantity=10, price="110.00", fee="1.00")
    show("全部卖出，手续费1元", account, "110.00")

    print("\n成交记录：")
    for trade in account.trades:
        print(
            f"#{trade.trade_id} {trade.side} {trade.quantity}份 "
            f"@ {trade.price:.2f} | 价款={trade.notional:.2f} "
            f"| 手续费={trade.fee:.2f} | 交易后现金={trade.cash_after:.2f}"
        )

    print("\n异常示例：")
    before = account.snapshot("110.00")
    try:
        account.buy(quantity=1000, price="110.00", fee="1.00")
    except InsufficientCashError as exc:
        print(f"已拒绝买入：{exc}")
    print(f"拒绝后账户是否保持不变：{account.snapshot('110.00') == before}")


if __name__ == "__main__":
    main()
