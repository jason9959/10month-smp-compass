from datetime import date

import pandas as pd

from core.schedule import build_contribution_schedule


def test_monthly_schedule_keeps_original_anchor_after_holiday_shift():
    trading_dates = pd.to_datetime([
        "2026-07-23",
        "2026-08-21",
        "2026-09-21",
    ])
    schedule = build_contribution_schedule(
        anchor_date=date(2026, 6, 21),
        end_date=date(2026, 9, 30),
        frequency="매월",
        trading_dates=trading_dates,
    )

    assert schedule["scheduled_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-21",
        "2026-08-21",
        "2026-09-21",
    ]
    assert schedule["actual_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-23",
        "2026-08-21",
        "2026-09-21",
    ]


def test_month_end_anchor_returns_to_31_when_possible():
    trading_dates = pd.to_datetime([
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ])
    schedule = build_contribution_schedule(
        anchor_date=date(2026, 1, 31),
        end_date=date(2026, 4, 30),
        frequency="매월",
        trading_dates=trading_dates,
    )

    assert schedule["scheduled_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
    ]
