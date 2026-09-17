from datetime import date

import pandas as pd
import pytest

from core.backtest import run_backtest


def _run(
    data,
    *,
    initial=1_000.0,
    contribution=False,
    amount=100.0,
    frequency="매월",
    confirm=1,
    limit=5,
    start=None,
    end=None,
):
    start = start or data.index[0].date()
    end = end or data.index[-1].date()
    return run_backtest(
        price_data=data,
        requested_start_date=start,
        requested_end_date=end,
        initial_amount=initial,
        use_contribution=contribution,
        contribution_amount=amount,
        contribution_frequency=frequency,
        confirmation_count=confirm,
        signal_limit_days=limit,
    )


def test_confirmation_one_matches_original_immediate_transition():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    data = pd.DataFrame(
        {"Close": [110.0, 90.0], "SMA": [100.0, 100.0]},
        index=dates,
    )

    out = _run(data, confirm=1, limit=5)

    transitions = out.events[out.events["event"].isin(["BUY", "SELL"])]
    assert transitions["event"].tolist() == ["BUY", "SELL"]
    assert transitions["date"].tolist() == list(dates)


def test_three_matching_signals_execute_immediately():
    dates = pd.date_range("2026-01-01", periods=7, freq="D")
    data = pd.DataFrame(
        {
            "Close": [110.0, 111.0, 112.0, 110.0, 90.0, 89.0, 88.0],
            "SMA": [100.0] * 7,
        },
        index=dates,
    )

    out = _run(data, confirm=3, limit=5)
    transitions = out.events[out.events["event"].isin(["BUY", "SELL"])]

    assert transitions["event"].tolist() == ["BUY", "SELL"]
    assert transitions["date"].tolist() == [dates[2], dates[6]]
    assert out.daily.loc[dates[2], "decision_reason"] == "COUNT"
    assert out.daily.loc[dates[6], "decision_reason"] == "COUNT"


def test_neutral_gap_keeps_count_and_next_matching_signal_restarts_limit():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    data = pd.DataFrame(
        {
            # BUY, NEUTRAL, BUY, NEUTRAL, NEUTRAL, BUY
            "Close": [110.0, 100.0, 111.0, 100.0, 100.0, 112.0],
            "SMA": [100.0] * 6,
        },
        index=dates,
    )

    out = _run(data, confirm=3, limit=3)
    buys = out.events[out.events["event"] == "BUY"]

    assert len(buys) == 1
    assert buys.iloc[0]["date"] == dates[5]
    assert out.daily.loc[dates[1], "confirmation_progress"] == 1
    assert out.daily.loc[dates[2], "confirmation_progress"] == 2
    # The BUY on day 3 restarts the LIMIT, so two following NEUTRAL days do not force execution.
    assert out.daily.loc[dates[4], "position"] == "CASH"


def test_limit_forces_buy_after_partial_confirmation():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    data = pd.DataFrame(
        {
            # BUY 1/3, then three NEUTRAL days. LIMIT=3 forces BUY on day 4.
            "Close": [110.0, 100.0, 100.0, 100.0, 100.0],
            "SMA": [100.0] * 5,
        },
        index=dates,
    )

    out = _run(data, confirm=3, limit=3)
    buy = out.events[out.events["event"] == "BUY"].iloc[0]

    assert buy["date"] == dates[3]
    assert "LIMIT 3거래일" in buy["note"]
    assert out.daily.loc[dates[3], "decision_reason"] == "LIMIT"
    assert out.daily.loc[dates[3], "position"] == "STOCK"


def test_opposite_signal_clears_pending_state_and_prevents_limit_execution():
    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    data = pd.DataFrame(
        {
            # BUY pending -> NEUTRAL -> SELL clears -> then NEUTRAL days.
            "Close": [110.0, 100.0, 90.0, 100.0, 100.0, 100.0],
            "SMA": [100.0] * 6,
        },
        index=dates,
    )

    out = _run(data, confirm=3, limit=2)

    assert out.events[out.events["event"] == "BUY"].empty
    assert out.metrics["ending_position"] == "CASH"
    assert out.daily.loc[dates[2], "confirmation_progress"] == 0


def test_limit_forces_sell_after_partial_confirmation():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    data = pd.DataFrame(
        {
            # BUY x3 -> STOCK; SELL x2 -> then NEUTRAL x2, LIMIT=2 forces SELL.
            "Close": [110.0, 111.0, 112.0, 90.0, 89.0, 100.0, 100.0, 100.0],
            "SMA": [100.0] * 8,
        },
        index=dates,
    )

    out = _run(data, confirm=3, limit=2)
    sells = out.events[out.events["event"] == "SELL"]

    assert len(sells) == 1
    # Last SELL confirmation was day 5 (index 4); two trading days later is index 6.
    assert sells.iloc[0]["date"] == dates[6]
    assert "SELL 2/3회" in sells.iloc[0]["note"]
    assert out.daily.loc[dates[6], "decision_reason"] == "LIMIT"


def test_contribution_on_count_confirmed_cash_to_stock_is_included_in_buy():
    # 2/1 scheduled contribution maps to 2/2, which is also BUY 3/3.
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-02-02"])
    data = pd.DataFrame(
        {"Close": [110.0, 111.0, 112.0], "SMA": [100.0, 100.0, 100.0]},
        index=dates,
    )

    out = _run(
        data,
        initial=1_000.0,
        contribution=True,
        amount=100.0,
        frequency="매월",
        confirm=3,
        limit=5,
        start=date(2026, 1, 1),
        end=date(2026, 2, 28),
    )

    buy = out.events[out.events["event"] == "BUY"].iloc[0]
    assert buy["date"] == pd.Timestamp("2026-02-02")
    assert buy["contribution"] == 100.0
    assert buy["amount"] == 1_100.0


def test_contribution_while_sell_pending_uses_actual_stock_position():
    # Establish STOCK with 3 BUY signals. First SELL is pending. Weekly contribution
    # maps to 1/08 while position is still STOCK, so it must buy more stock.
    dates = pd.to_datetime([
        "2026-01-01", "2026-01-02", "2026-01-03",
        "2026-01-04", "2026-01-08", "2026-01-09",
    ])
    data = pd.DataFrame(
        {
            "Close": [110.0, 111.0, 112.0, 90.0, 100.0, 100.0],
            "SMA": [100.0] * 6,
        },
        index=dates,
    )

    out = _run(
        data,
        initial=1_120.0,
        contribution=True,
        amount=100.0,
        frequency="매주",
        confirm=3,
        limit=10,
        start=date(2026, 1, 1),
        end=date(2026, 1, 9),
    )

    add_buy = out.events[
        (out.events["event"] == "ADD_BUY")
        & (out.events["date"] == pd.Timestamp("2026-01-08"))
    ]
    assert len(add_buy) == 1
    assert add_buy.iloc[0]["contribution"] == 100.0


def test_contribution_on_limit_forced_stock_to_cash_is_added_after_sell():
    # BUY x3 establishes STOCK. One SELL starts pending. LIMIT=2 then expires on
    # 2/2, which is also the mapped monthly contribution day: sell first, then cash contribution.
    dates = pd.to_datetime([
        "2026-01-01", "2026-01-02", "2026-01-03",
        "2026-01-04", "2026-01-05", "2026-02-02",
    ])
    data = pd.DataFrame(
        {
            "Close": [110.0, 111.0, 112.0, 90.0, 100.0, 100.0],
            "SMA": [100.0] * 6,
        },
        index=dates,
    )

    out = _run(
        data,
        initial=1_120.0,
        contribution=True,
        amount=100.0,
        frequency="매월",
        confirm=3,
        limit=2,
        start=date(2026, 1, 1),
        end=date(2026, 2, 28),
    )

    sell = out.events[out.events["event"] == "SELL"].iloc[0]
    cash_contrib = out.events[
        (out.events["event"] == "CONTRIBUTION_CASH")
        & (out.events["date"] == pd.Timestamp("2026-02-02"))
    ].iloc[0]

    assert sell["date"] == pd.Timestamp("2026-02-02")
    assert "LIMIT 2거래일" in sell["note"]
    assert cash_contrib["contribution"] == 100.0
