from datetime import date

import pandas as pd

from core.backtest import run_backtest


def test_contribution_on_cash_to_stock_is_included_in_buy():
    dates = pd.to_datetime(["2026-01-01", "2026-02-02"])
    data = pd.DataFrame(
        {
            "Close": [90.0, 110.0],
            "SMA": [100.0, 100.0],
        },
        index=dates,
    )

    out = run_backtest(
        price_data=data,
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 2, 28),
        initial_amount=1_000.0,
        use_contribution=True,
        contribution_amount=100.0,
        contribution_frequency="매월",
    )

    # Scheduled 2/1 moves to 2/2, which is also the BUY transition day.
    buy = out.events[out.events["event"] == "BUY"].iloc[0]
    assert buy["contribution"] == 100.0
    assert buy["amount"] == 1_100.0


def test_sell_then_contribute_cash_on_same_day():
    dates = pd.to_datetime(["2026-01-01", "2026-02-02"])
    data = pd.DataFrame(
        {
            "Close": [110.0, 90.0],
            "SMA": [100.0, 100.0],
        },
        index=dates,
    )

    out = run_backtest(
        price_data=data,
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 2, 28),
        initial_amount=1_100.0,
        use_contribution=True,
        contribution_amount=100.0,
        contribution_frequency="매월",
    )

    assert out.metrics["ending_position"] == "CASH"
    # 1,100 buys 10 shares at 110; sell at 90 -> 900, then add 100 contribution.
    assert out.metrics["ending_cash"] == 1_000.0
