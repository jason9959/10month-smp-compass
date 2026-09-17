from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .schedule import build_contribution_schedule


@dataclass
class BacktestOutput:
    daily: pd.DataFrame
    events: pd.DataFrame
    schedule: pd.DataFrame
    metrics: dict


def _build_contribution_map(schedule: pd.DataFrame, amount: float) -> dict[pd.Timestamp, float]:
    if schedule.empty:
        return {}
    counts = schedule.groupby("actual_date").size()
    return {pd.Timestamp(day): float(count * amount) for day, count in counts.items()}


def _max_drawdown(values: pd.Series) -> float:
    running_max = values.cummax()
    drawdown = values / running_max - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0


def run_backtest(
    price_data: pd.DataFrame,
    requested_start_date: date,
    requested_end_date: date,
    initial_amount: float,
    use_contribution: bool,
    contribution_amount: float,
    contribution_frequency: str,
) -> BacktestOutput:
    if initial_amount <= 0:
        raise ValueError("초기 투자금은 0보다 커야 합니다.")
    if use_contribution and contribution_amount <= 0:
        raise ValueError("적립 금액은 0보다 커야 합니다.")

    data = price_data.copy().sort_index()
    if data.empty:
        raise ValueError("백테스트할 가격 데이터가 없습니다.")

    schedule = pd.DataFrame(columns=["scheduled_date", "actual_date"])
    if use_contribution:
        schedule = build_contribution_schedule(
            anchor_date=requested_start_date,
            end_date=requested_end_date,
            frequency=contribution_frequency,
            trading_dates=data.index,
        )

    contribution_map = _build_contribution_map(
        schedule,
        contribution_amount if use_contribution else 0.0,
    )

    cash = float(initial_amount)
    shares = 0.0
    position = "CASH"

    bh_cash = float(initial_amount)
    bh_shares = 0.0

    daily_rows: list[dict] = []
    event_rows: list[dict] = []

    first_date = pd.Timestamp(data.index[0])

    for i, (dt, row) in enumerate(data.iterrows()):
        dt = pd.Timestamp(dt)
        price = float(row["Close"])
        sma = float(row["SMA"])
        contribution = float(contribution_map.get(dt, 0.0))

        # Benchmark: invest initial cash on the first trading day and every
        # contribution immediately, regardless of the moving average.
        if i == 0:
            bh_shares = bh_cash / price
            bh_cash = 0.0
        if contribution > 0:
            bh_shares += contribution / price

        previous_position = position
        if price > sma:
            desired_position = "STOCK"
        elif price < sma:
            desired_position = "CASH"
        else:
            desired_position = position

        # On the first day, the initial capital follows the same signal rule.
        # Contribution dates start after requested_start_date, so there is no
        # special first-day contribution case unless the actual test data began later.
        if position == "CASH" and desired_position == "STOCK":
            cash += contribution
            contribution_consumed = contribution
            invested = cash
            shares = cash / price
            cash = 0.0
            position = "STOCK"
            event_rows.append(
                {
                    "date": dt,
                    "event": "BUY",
                    "price": price,
                    "amount": invested,
                    "contribution": contribution_consumed,
                    "note": "현금 전액 매수" + (" (적립금 포함)" if contribution_consumed else ""),
                }
            )

        elif position == "STOCK" and desired_position == "CASH":
            proceeds = shares * price
            shares = 0.0
            cash += proceeds
            position = "CASH"
            event_rows.append(
                {
                    "date": dt,
                    "event": "SELL",
                    "price": price,
                    "amount": proceeds,
                    "contribution": 0.0,
                    "note": "보유 주식 전량 매도",
                }
            )
            if contribution > 0:
                cash += contribution
                event_rows.append(
                    {
                        "date": dt,
                        "event": "CONTRIBUTION_CASH",
                        "price": price,
                        "amount": contribution,
                        "contribution": contribution,
                        "note": "매도 후 현금 적립",
                    }
                )

        elif position == "STOCK":
            if contribution > 0:
                bought = contribution / price
                shares += bought
                event_rows.append(
                    {
                        "date": dt,
                        "event": "ADD_BUY",
                        "price": price,
                        "amount": contribution,
                        "contribution": contribution,
                        "note": "적립금으로 추가 매수",
                    }
                )

        else:  # CASH stays CASH
            if contribution > 0:
                cash += contribution
                event_rows.append(
                    {
                        "date": dt,
                        "event": "CONTRIBUTION_CASH",
                        "price": price,
                        "amount": contribution,
                        "contribution": contribution,
                        "note": "현금 적립",
                    }
                )

        portfolio_value = cash + shares * price
        buy_hold_value = bh_cash + bh_shares * price

        daily_rows.append(
            {
                "date": dt,
                "Close": price,
                "SMA": sma,
                "position": position,
                "previous_position": previous_position,
                "cash": cash,
                "shares": shares,
                "contribution": contribution,
                "portfolio_value": portfolio_value,
                "buy_hold_value": buy_hold_value,
            }
        )

    daily = pd.DataFrame(daily_rows).set_index("date")
    events = pd.DataFrame(
        event_rows,
        columns=["date", "event", "price", "amount", "contribution", "note"],
    )

    total_contributions = initial_amount + float(daily["contribution"].sum())
    final_value = float(daily["portfolio_value"].iloc[-1])
    final_bh_value = float(daily["buy_hold_value"].iloc[-1])
    profit = final_value - total_contributions

    metrics = {
        "effective_start_date": first_date.date(),
        "effective_end_date": pd.Timestamp(daily.index[-1]).date(),
        "initial_amount": float(initial_amount),
        "additional_contributions": float(daily["contribution"].sum()),
        "total_contributions": float(total_contributions),
        "final_value": final_value,
        "profit": profit,
        "return_pct": (profit / total_contributions * 100.0) if total_contributions else np.nan,
        "mdd_pct": _max_drawdown(daily["portfolio_value"]) * 100.0,
        "buy_hold_final_value": final_bh_value,
        "buy_hold_return_pct": (
            (final_bh_value - total_contributions) / total_contributions * 100.0
            if total_contributions
            else np.nan
        ),
        "buy_count": int(events["event"].isin(["BUY", "ADD_BUY"]).sum()) if not events.empty else 0,
        "sell_count": int((events["event"] == "SELL").sum()) if not events.empty else 0,
        "position_changes": int(events["event"].isin(["BUY", "SELL"]).sum()) if not events.empty else 0,
        "ending_position": str(daily["position"].iloc[-1]),
        "ending_cash": float(daily["cash"].iloc[-1]),
        "ending_shares": float(daily["shares"].iloc[-1]),
    }

    return BacktestOutput(daily=daily, events=events, schedule=schedule, metrics=metrics)
