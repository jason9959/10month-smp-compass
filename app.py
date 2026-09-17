from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core.backtest import run_backtest
from core.charts import portfolio_chart, price_chart
from core.data_loader import load_price_data
from core.reporting import create_result_png


st.set_page_config(
    page_title="이동평균 투자전략 백테스트",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


DEFAULTS = {
    "ticker": "QQQ",
    "start_date": date(2010, 1, 1),
    "end_date": date.today(),
    "ma_months": 10,
    "initial_amount": 10_000_000.0,
    "use_contribution": False,
    "contribution_amount": 1_000_000.0,
    "contribution_frequency": "매월",
}

INPUT_KEYS = list(DEFAULTS.keys())


def initialize_state() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "input"
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_inputs() -> None:
    for key, value in DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.pop("backtest_output", None)
    st.session_state.pop("backtest_context", None)
    st.session_state.page = "input"


def go_back() -> None:
    # Input values intentionally remain untouched.
    st.session_state.page = "input"


@st.cache_data(ttl=3600, show_spinner=False)
def cached_load_price_data(ticker: str, start_date: date, end_date: date, ma_months: int):
    return load_price_data(ticker, start_date, end_date, ma_months)


def money(value: float) -> str:
    return f"{value:,.0f}"


def show_input_page() -> None:
    st.title("📈 이동평균 투자전략 백테스트")
    st.write(
        "종가가 이동평균 위에 있으면 주식을 보유하고, 아래에 있으면 현금을 보유하는 전략을 테스트합니다."
    )
    st.caption("v1 기준: N개월 = N × 21거래일 단순이동평균(SMA), 당일 종가 체결, 수수료·세금·환율 미반영")

    st.divider()

    st.subheader("조건 입력")

    ticker_col, ma_col = st.columns([2, 1])
    with ticker_col:
        st.text_input(
            "종목 티커",
            key="ticker",
            help="예: QQQ, SPY, AAPL, 005930.KS",
        )
    with ma_col:
        st.number_input(
            "이동평균 기간 (개월)",
            min_value=1,
            max_value=60,
            step=1,
            key="ma_months",
        )

    start_col, end_col = st.columns(2)
    with start_col:
        st.date_input("시작일", key="start_date")
    with end_col:
        st.date_input("종료일", key="end_date")

    st.number_input(
        "초기 투자금",
        min_value=1.0,
        step=100_000.0,
        format="%.0f",
        key="initial_amount",
        help="종목 가격과 같은 통화 단위로 계산합니다. 예: 미국 종목이면 USD, 한국 종목이면 KRW 기준으로 해석합니다.",
    )

    st.divider()
    st.subheader("적립식 투자")

    st.checkbox("적립식 투자 사용", key="use_contribution")

    if st.session_state.use_contribution:
        amount_col, frequency_col = st.columns(2)
        with amount_col:
            st.number_input(
                "적립 금액",
                min_value=1.0,
                step=100_000.0,
                format="%.0f",
                key="contribution_amount",
            )
        with frequency_col:
            st.selectbox(
                "적립 주기",
                options=["매주", "매월", "매분기", "매반기", "매년"],
                key="contribution_frequency",
            )

        st.caption(
            "첫 적립일은 시작일에서 선택 주기만큼 지난 날입니다. 해당 날짜가 휴장일이면 이후 가장 가까운 거래일에 적립하며, 다음 예정일은 원래 시작일 기준을 유지합니다."
        )

    st.divider()

    action_col, reset_col = st.columns([3, 1])
    with action_col:
        run_clicked = st.button(
            "백테스트 실행 →",
            type="primary",
            use_container_width=True,
        )
    with reset_col:
        st.button(
            "입력값 초기화",
            use_container_width=True,
            on_click=reset_inputs,
        )

    if run_clicked:
        if st.session_state.start_date >= st.session_state.end_date:
            st.error("종료일은 시작일보다 뒤여야 합니다.")
            return

        with st.spinner("가격 데이터를 불러오고 백테스트를 계산하고 있습니다..."):
            try:
                data = cached_load_price_data(
                    st.session_state.ticker.strip().upper(),
                    st.session_state.start_date,
                    st.session_state.end_date,
                    int(st.session_state.ma_months),
                )
                output = run_backtest(
                    price_data=data,
                    requested_start_date=st.session_state.start_date,
                    requested_end_date=st.session_state.end_date,
                    initial_amount=float(st.session_state.initial_amount),
                    use_contribution=bool(st.session_state.use_contribution),
                    contribution_amount=float(st.session_state.contribution_amount),
                    contribution_frequency=st.session_state.contribution_frequency,
                )
            except Exception as exc:
                st.error(str(exc))
                return

        st.session_state.backtest_output = output
        st.session_state.backtest_context = {
            key: st.session_state[key] for key in INPUT_KEYS
        }
        st.session_state.page = "result"
        st.rerun()


def show_result_page() -> None:
    if "backtest_output" not in st.session_state or "backtest_context" not in st.session_state:
        st.session_state.page = "input"
        st.rerun()
        return

    output = st.session_state.backtest_output
    context = st.session_state.backtest_context
    daily = output.daily
    events = output.events
    metrics = output.metrics
    ticker = context["ticker"].strip().upper()

    png_bytes = create_result_png(
        ticker=ticker,
        ma_months=int(context["ma_months"]),
        requested_start=context["start_date"],
        requested_end=context["end_date"],
        initial_amount=float(context["initial_amount"]),
        use_contribution=bool(context["use_contribution"]),
        contribution_amount=float(context["contribution_amount"]),
        contribution_frequency=context["contribution_frequency"],
        daily=daily,
        metrics=metrics,
    )

    top_left, top_spacer, top_right = st.columns([1.2, 4, 1.5])
    with top_left:
        st.button(
            "← 조건으로 돌아가기",
            use_container_width=True,
            on_click=go_back,
        )
    with top_right:
        st.download_button(
            "결과 이미지 저장",
            data=png_bytes,
            file_name=f"{ticker}_MA{int(context['ma_months'])}_backtest.png",
            mime="image/png",
            use_container_width=True,
        )

    st.title(f"{ticker} 백테스트 결과")
    st.caption(
        f"{context['start_date']} ~ {context['end_date']} · {int(context['ma_months'])}개월 이동평균 · 당일 종가 체결"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 납입금", money(metrics["total_contributions"]))
    c2.metric("최종 자산", money(metrics["final_value"]))
    c3.metric("투자 수익", money(metrics["profit"]))
    c4.metric("수익률", f"{metrics['return_pct']:.2f}%")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("MDD", f"{metrics['mdd_pct']:.2f}%")
    c6.metric("Buy & Hold 최종", money(metrics["buy_hold_final_value"]))
    c7.metric("매수 실행", f"{metrics['buy_count']}회")
    c8.metric("매도 실행", f"{metrics['sell_count']}회")

    st.caption(
        f"실제 첫 거래일: {metrics['effective_start_date']} · 종료 포지션: {metrics['ending_position']} · "
        f"현금 {money(metrics['ending_cash'])} · 보유수량 {metrics['ending_shares']:,.6f}"
    )

    st.divider()
    st.plotly_chart(
        price_chart(daily, events, ticker, int(context["ma_months"])),
        use_container_width=True,
    )

    st.plotly_chart(
        portfolio_chart(daily, float(context["initial_amount"])),
        use_container_width=True,
    )

    st.divider()
    st.subheader("거래 및 적립 내역")

    if events.empty:
        st.info("표시할 거래/적립 이벤트가 없습니다.")
    else:
        event_labels = {
            "BUY": "매수 전환",
            "SELL": "매도 전환",
            "ADD_BUY": "적립 매수",
            "CONTRIBUTION_CASH": "현금 적립",
        }
        display_events = events.copy()
        display_events["구분"] = display_events["event"].map(event_labels).fillna(display_events["event"])
        display_events["날짜"] = pd.to_datetime(display_events["date"]).dt.strftime("%Y-%m-%d")
        display_events["가격"] = display_events["price"].map(lambda x: f"{x:,.4f}")
        display_events["금액"] = display_events["amount"].map(lambda x: f"{x:,.0f}")
        display_events["적립금"] = display_events["contribution"].map(lambda x: f"{x:,.0f}")
        display_events["설명"] = display_events["note"]
        st.dataframe(
            display_events[["날짜", "구분", "가격", "금액", "적립금", "설명"]],
            use_container_width=True,
            hide_index=True,
        )

    if context["use_contribution"] and not output.schedule.empty:
        with st.expander("적립 예정일 / 실제 적립일 확인"):
            schedule_view = output.schedule.copy()
            schedule_view["예정 적립일"] = schedule_view["scheduled_date"].dt.strftime("%Y-%m-%d")
            schedule_view["실제 적립일"] = schedule_view["actual_date"].dt.strftime("%Y-%m-%d")
            st.dataframe(
                schedule_view[["예정 적립일", "실제 적립일"]],
                use_container_width=True,
                hide_index=True,
            )

    st.caption(
        "가정: 수정 종가(Adjusted Close), 소수점 매수 허용, 수수료·세금·환율·현금이자 미반영. "
        "이 결과는 전략 테스트용이며 실제 체결 결과와 다를 수 있습니다."
    )


initialize_state()

if st.session_state.page == "result":
    show_result_page()
else:
    show_input_page()
