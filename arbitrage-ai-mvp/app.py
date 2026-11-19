from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

import pandas as pd
import requests
import streamlit as st
from scanner import scan_markets, read_wallex_balances
from telegram_reports import send_scan_report, send_paper_trade_report, telegram_configured
from risk_gates import (
    is_paper_candidate, profit_change_warning,
    MAX_VWAP_CHANGE_PCT, MAX_MATCHED_VOLUME_CHANGE_PCT,
    MAX_STABILITY_PROFIT_DROP_PCT, PROFIT_DROP_WARNING_PCT,
    PAPER_BLOCK_PROFIT_DROP_PCT,
)

TEHRAN = ZoneInfo("Asia/Tehran")

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 هوش مصنوعی آربیتراژ")
st.caption("نسخه آزمایشی ۰.۹ | گزارش عملکرد معاملات کاغذی و تشخیص فرصت پایدار")
st.warning(
    "این نسخه سفارش واقعی ثبت نمی‌کند. سودها برآورد شبیه‌سازی بر اساس سطوح قابل مشاهده دفتر سفارش هستند؛ "
    "موجودی حساب، امکان انتقال، شبکه انتقال و تغییر قیمت تا زمان اجرای واقعی تأیید نمی‌شوند."
)


# Wallex private account connection is strictly read-only.
st.subheader("🔐 اتصال حساب والکس")
if os.getenv("WALLEX_API_KEY", "").strip():
    try:
        wallex_account = read_wallex_balances()
        if wallex_account.get("configured"):
            st.success("اتصال API والکس برقرار است؛ دسترسی فقط‌خواندنی.")
            if wallex_account.get("balances"):
                st.dataframe(pd.DataFrame(wallex_account["balances"]), hide_index=True, use_container_width=True)
            else:
                st.info("اتصال موفق بود؛ موجودی قابل نمایش دریافت نشد.")
    except requests.RequestException as error:
        st.error(f"دریافت موجودی والکس ناموفق بود (خطای ارتباط/API: {getattr(error.response, 'status_code', 'network')}).")
    except Exception:
        st.error("اتصال موجودی والکس ناموفق بود؛ جزئیات محرمانه نمایش داده نمی‌شود.")
else:
    st.info("برای فعال‌سازی اتصال موجودی، کلید API فقط‌خواندنی والکس را در متغیر WALLEX_API_KEY در Render ثبت کنید.")
st.caption("قفل ایمنی: این برنامه فقط GET موجودی را اجرا می‌کند؛ هیچ مسیر ثبت سفارش، معامله یا برداشت در اتصال والکس استفاده نمی‌شود.")

# Nobitex private account connection is strictly read-only.
from nobitex_private import read_nobitex_balances
st.subheader("🔐 اتصال حساب نوبیتکس")
if os.getenv("NOBITEX_API_PUBLIC_KEY", "").strip() and os.getenv("NOBITEX_API_PRIVATE_KEY", "").strip():
    try:
        nobitex_account = read_nobitex_balances()
        if nobitex_account.get("configured"):
            st.success("اتصال API نوبیتکس برقرار است؛ دسترسی فقط‌خواندنی.")
            if nobitex_account.get("balances"):
                st.dataframe(pd.DataFrame(nobitex_account["balances"]), hide_index=True, use_container_width=True)
            else:
                st.info("اتصال موفق بود؛ پاسخ کیف پول موجودی قابل نمایش نداشت.")
    except requests.RequestException as error:
        status = getattr(getattr(error, "response", None), "status_code", "network")
        st.error(f"دریافت موجودی نوبیتکس ناموفق بود (خطای ارتباط/API: {status}).")
    except Exception:
        st.error("اتصال موجودی نوبیتکس ناموفق بود؛ جزئیات محرمانه نمایش داده نمی‌شود.")
else:
    st.info("برای فعال‌سازی، دو کلید نوبیتکس را با نام‌های NOBITEX_API_PUBLIC_KEY و NOBITEX_API_PRIVATE_KEY در Render ثبت کنید.")
st.caption("قفل ایمنی: فقط POST /users/wallets/list با دسترسی READ اجرا می‌شود؛ هیچ endpoint سفارش، معامله، انتقال یا برداشت فراخوانی نمی‌شود.")

with st.sidebar:
    st.header("تنظیمات")
    capital = st.number_input(
        "سرمایه آزمایشی (تومان)", min_value=100000,
        value=2000000, step=100000
    )
    fee_wallex = st.number_input(
        "کارمزد هر سمت والکس (%)", min_value=0.0,
        max_value=5.0, value=0.25, step=0.05
    ) / 100
    fee_nobitex = st.number_input(
        "کارمزد هر سمت نوبیتکس (%)", min_value=0.0,
        max_value=5.0, value=0.25, step=0.05
    ) / 100
    slippage_pct = st.number_input(
        "لغزش تخمینی هر سمت (%)", min_value=0.0,
        max_value=5.0, value=0.20, step=0.05
    )
    transfer_cost_pct = st.number_input(
        "هزینه انتقال و سایر هزینه‌ها (%)", min_value=0.0,
        max_value=10.0, value=0.30, step=0.05
    )
    min_net = st.number_input(
        "حداقل سود خالص برآوردی (%)", min_value=-10.0,
        max_value=20.0, value=0.25, step=0.05
    )
    min_executable = st.number_input(
        "حداقل سرمایه قابل اجرا (تومان)", min_value=0,
        max_value=capital, value=min(100000, int(capital)), step=50000
    )
    st.caption(
        "کارمزد و لغزش باید با سطح کارمزد حساب و شرایط واقعی شبکه تطبیق داده شوند."
    )
    refresh = st.button("🔄 دریافت دوباره قیمت‌ها", width="stretch")

scan_settings = (
    capital, fee_wallex, fee_nobitex, slippage_pct, transfer_cost_pct,
    min_net, min_executable
)
should_scan = refresh or st.session_state.get("scan_settings") != scan_settings
if should_scan:
    with st.spinner("در حال دریافت دفتر سفارش عمومی والکس و نوبیتکس..."):
        result = scan_markets(
            fee_local=fee_wallex,
            fee_global=fee_nobitex,
            slippage_pct=slippage_pct,
            transfer_cost_pct=transfer_cost_pct,
            capital_toman=capital,
        )
        st.session_state["scan"] = result
        previous_settings = st.session_state.get("stability_settings")
        if previous_settings != scan_settings:
            st.session_state["stability_counts"] = {}
            st.session_state["previous_eligible_keys"] = set()
            st.session_state["previous_market_snapshots"] = {}
            st.session_state["market_stability_checks"] = {}
            st.session_state["stability_scan_number"] = 0
        st.session_state["stability_settings"] = scan_settings

        # Compare consecutive snapshots for each route. A route only earns a
        # stability count when VWAP prices and matched volume remain within limits.
        eligible_items = {
            (item.get("symbol"), item.get("buy_exchange"), item.get("sell_exchange")): item
            for item in result.get("opportunities", [])
            if item.get("net_spread_pct", -999) >= min_net
            and item.get("profit_toman", 0) > 0
            and item.get("used_capital_toman", 0) >= min_executable
        }
        eligible_now = set(eligible_items)
        old_counts = st.session_state.get("stability_counts", {})
        previous_keys = st.session_state.get("previous_eligible_keys", set())
        previous_snapshots = st.session_state.get("previous_market_snapshots", {})
        new_counts = {}
        market_checks = {}
        current_snapshots = {}
        for key, item in eligible_items.items():
            route_id = "|".join(key)
            current = {
                "buy_vwap": float(item.get("buy_vwap") or 0),
                "sell_vwap": float(item.get("sell_vwap") or 0),
                "base_quantity": float(item.get("base_quantity") or 0),
                "profit_toman": float(item.get("profit_toman") or 0),
            }
            prior = previous_snapshots.get(route_id)
            if prior:
                buy_move = abs(current["buy_vwap"] / prior["buy_vwap"] - 1) * 100 if prior.get("buy_vwap") else 999
                sell_move = abs(current["sell_vwap"] / prior["sell_vwap"] - 1) * 100 if prior.get("sell_vwap") else 999
                volume_move = abs(current["base_quantity"] / prior["base_quantity"] - 1) * 100 if prior.get("base_quantity") else 999
                profit_drop = max(0.0, (prior["profit_toman"] - current["profit_toman"]) / prior["profit_toman"] * 100) if prior.get("profit_toman", 0) > 0 else 0
                passed = (
                    buy_move <= MAX_VWAP_CHANGE_PCT
                    and sell_move <= MAX_VWAP_CHANGE_PCT
                    and volume_move <= MAX_MATCHED_VOLUME_CHANGE_PCT
                    and profit_drop <= MAX_STABILITY_PROFIT_DROP_PCT
                )
                profit_change = (
                    (current["profit_toman"] / prior["profit_toman"] - 1) * 100
                    if prior.get("profit_toman", 0) > 0 else None
                )
                market_checks[route_id] = {
                    "passed": passed, "buy_move_pct": buy_move,
                    "sell_move_pct": sell_move, "volume_move_pct": volume_move,
                    "profit_drop_pct": profit_drop, "profit_change_pct": profit_change,
                    "label": "پایدار نسبت به اسکن قبل" if passed else "ناپایدار؛ تغییر محسوس قیمت/حجم/سود",
                }
            else:
                passed = False
                market_checks[route_id] = {
                    "passed": False, "buy_move_pct": None, "sell_move_pct": None,
                    "volume_move_pct": None, "profit_drop_pct": None,
                    "profit_change_pct": None,
                    "label": "در انتظار اسکن مقایسه‌ای",
                }
            if passed and key in previous_keys:
                new_counts[key] = old_counts.get(key, 0) + 1
            else:
                new_counts[key] = 1
            current_snapshots[route_id] = current
        st.session_state["stability_counts"] = new_counts
        st.session_state["previous_eligible_keys"] = eligible_now
        st.session_state["previous_market_snapshots"] = current_snapshots
        st.session_state["market_stability_checks"] = market_checks
        st.session_state["stability_scan_number"] = st.session_state.get("stability_scan_number", 0) + 1
        st.session_state["scan_stability"] = {
            "|".join(key): count for key, count in new_counts.items()
        }

        history = st.session_state.setdefault("history", [])
        history.append({
            "time": datetime.now(TEHRAN),
            "opportunities": len(eligible_now),
            "stable_opportunities": sum(1 for count in new_counts.values() if count >= 5),
            "best_profit": max(
                [x.get("profit_toman", 0) for x in result.get("opportunities", [])
                 if (x.get("symbol"), x.get("buy_exchange"), x.get("sell_exchange")) in eligible_now] or [0]
            ),
            "best_symbol": (
                max(
                    [x for x in result.get("opportunities", [])
                     if (x.get("symbol"), x.get("buy_exchange"), x.get("sell_exchange")) in eligible_now],
                    key=lambda x: x.get("profit_toman", 0)
                ).get("symbol", "—")
                if eligible_now else "—"
            ),
        })
        st.session_state["history"] = history[-300:]

        # Optional Telegram notification; failures never interrupt market scanning.
        if telegram_configured():
            send_scan_report(
                list(eligible_items.values()),
                {"|".join(key): count for key, count in new_counts.items()},
                st.session_state["stability_scan_number"],
                result.get("diagnostics", {}),
                result.get("errors", []),
            )

result = st.session_state.get(
    "scan", {"opportunities": [], "errors": [], "diagnostics": {}}
)
for error in result.get("errors", []):
    st.error(error)

diagnostics = result.get("diagnostics", {})
a, b, c, d = st.columns(4)
a.metric("سرمایه شبیه‌سازی", f"{capital:,.0f} تومان")
b.metric("دفتر سفارش والکس", str(diagnostics.get("wallex_books", "—")))
c.metric("دفتر سفارش نوبیتکس", str(diagnostics.get("nobitex_books", "—")))
d.metric("جفت‌ارز مشترک", str(diagnostics.get("common_symbols", "—")))

df = pd.DataFrame(result.get("opportunities", []))
if not df.empty:
    df = df[
        (df["net_spread_pct"] >= min_net)
        & (df["profit_toman"] > 0)
        & (df["used_capital_toman"] >= min_executable)
    ].copy()
    # Transparent review score: include repeat stability, not execution probability.
    return_score = (df["net_spread_pct"].clip(lower=0, upper=1.5) / 1.5) * 100
    capital_score = (df["used_capital_toman"] / max(float(capital), 1)).clip(upper=1) * 100
    # Wallex's public depth response has no server timestamp, so freshness is penalized.
    freshness_score = 50.0
    stability_score = (df["stable_scans"].clip(lower=0, upper=5) / 5) * 100 if "stable_scans" in df else 0.0
    df["review_score"] = (
        return_score * 0.35 + capital_score * 0.25
        + freshness_score * 0.25 + stability_score * 0.15
    ).round(0).astype(int)
    stability = st.session_state.get("scan_stability", {})
    df["stable_scans"] = df.apply(
        lambda row: stability.get("|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), 0),
        axis=1,
    )
    df["stable_5"] = df["stable_scans"] >= 5
    stability_score = (df["stable_scans"].clip(lower=0, upper=5) / 5) * 100
    df["review_score"] = (
        return_score * 0.35 + capital_score * 0.25
        + freshness_score * 0.25 + stability_score * 0.15
    ).round(0).astype(int)
    market_checks = st.session_state.get("market_stability_checks", {})
    df["market_stability"] = df.apply(
        lambda row: market_checks.get(
            "|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), {}
        ).get("label", "در انتظار اسکن مقایسه‌ای"),
        axis=1,
    )
    df["market_stable_now"] = df.apply(
        lambda row: market_checks.get(
            "|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), {}
        ).get("passed", False),
        axis=1,
    )
    df["profit_change_pct"] = df.apply(
        lambda row: market_checks.get(
            "|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), {}
        ).get("profit_change_pct"),
        axis=1,
    )
    df["stress_025_pass"] = pd.to_numeric(
        df.get("stress_profit_slip_025_toman", pd.Series(index=df.index, dtype=float)),
        errors="coerce",
    ).fillna(-1) > 0
    df["profit_change_warning"] = df["profit_change_pct"].apply(
        profit_change_warning
    )
    df = df.sort_values(
        ["stable_5", "review_score", "profit_toman"], ascending=[False, False, False]
    )

if df.empty:
    st.info(
        "با تنظیمات فعلی فرصت خالصِ دارای حجم کافی پیدا نشد. "
        "ممکن است عمق کافی، جفت‌ارز تومانی مشترک یا داده تازه در دسترس نباشد."
    )
else:
    best = df.iloc[0]
    st.subheader("بهترین فرصت بر اساس امتیاز بررسی")
    x, y, z, w = st.columns(4)
    x.metric("سود خالص تخمینی", f"{best['profit_toman']:,.0f} تومان")
    y.metric("سرمایه درگیر", f"{best['used_capital_toman']:,.0f} تومان")
    z.metric("بازده خالص", f"{best['net_spread_pct']:.2f}%")
    w.metric("امتیاز بررسی", f"{int(best['review_score'])}/100")

    stable_df = df[df["stable_5"]]
    st.subheader("کنترل تغییر قیمت و حجم بین دو اسکن")
    st.caption(
        f"مقایسه با اسکن قبلی همان مسیر: تغییر میانگین قیمت خرید یا فروش حداکثر {MAX_VWAP_CHANGE_PCT:.2f}٪، "
        f"تغییر حجم تطبیق‌یافته حداکثر {MAX_MATCHED_VOLUME_CHANGE_PCT:.0f}٪ و افت سود برای حفظ پایداری حداکثر {MAX_STABILITY_PROFIT_DROP_PCT:.0f}٪ است. "
        f"این حد پایداری با هشدار افت سود {PROFIT_DROP_WARNING_PCT:.0f}٪ و مسدودسازی ثبت کاغذی در افت {PAPER_BLOCK_PROFIT_DROP_PCT:.0f}٪ متفاوت است. "
        "شمارنده پایداری نیز در رتبه‌بندی لحاظ می‌شود."
    )
    # Show the measured changes against the immediately preceding snapshot.
    for metric_key, column_name in (
        ("buy_move_pct", "تغییر میانگین خرید"),
        ("sell_move_pct", "تغییر میانگین فروش"),
        ("volume_move_pct", "تغییر حجم تطبیق‌یافته"),
        ("profit_change_pct", "تغییر سود خالص تخمینی"),
    ):
        df[column_name] = df.apply(
            lambda row: (
                f"{market_checks.get('|'.join((str(row['symbol']), str(row['buy_exchange']), str(row['sell_exchange']))), {}).get(metric_key):+.3f}%"
                if market_checks.get(
                    "|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), {}
                ).get(metric_key) is not None else "—"
            ),
            axis=1,
        )
    market_view = df[[
        "symbol", "buy_exchange", "sell_exchange", "market_stability",
        "تغییر میانگین خرید", "تغییر میانگین فروش",
        "تغییر حجم تطبیق‌یافته", "تغییر سود خالص تخمینی",
        "profit_change_warning", "stable_scans"
    ]].rename(columns={
        "profit_change_warning": "هشدار افت سود",
        "symbol": "جفت‌ارز", "buy_exchange": "صرافی خرید",
        "sell_exchange": "صرافی فروش", "market_stability": "نتیجه مقایسه اسکن",
        "stable_scans": "شمارنده پایداری",
    })
    st.dataframe(market_view, width="stretch", hide_index=True)
    warning_rows = df[df["profit_change_pct"].notna() & (df["profit_change_pct"] <= -3)]
    for _, warning_row in warning_rows.iterrows():
        if warning_row["profit_change_pct"] <= -5:
            st.error(
                f"{warning_row['symbol']}: افت سود {warning_row['profit_change_pct']:.2f}%؛ "
                "ثبت معامله کاغذی تا بهبود شرایط مسدود است."
            )
        else:
            st.warning(
                f"{warning_row['symbol']}: افت سود {warning_row['profit_change_pct']:.2f}%؛ "
                "هشدار کاهش سود، نیازمند بررسی مجدد."
            )
    stress_failed = df[~df["stress_025_pass"]]
    for _, stress_row in stress_failed.iterrows():
        st.warning(
            f"{stress_row['symbol']}: سود در آزمون لغزش اضافه ۰٫۲۵٪ مثبت نیست؛ "
            "برای ثبت کاغذی واجد شرایط نیست."
        )
    st.caption(
        "درصدها نسبت به اسکن بلافاصله قبلی همان مسیر هستند؛ تغییر سود مثبت یعنی افزایش و منفی یعنی کاهش. "
        "در اولین اسکن، داده مقایسه‌ای وجود ندارد و «—» نمایش داده می‌شود."
    )
    st.subheader("تشخیص فرصت پایدار")
    s1, s2 = st.columns(2)
    s1.metric("تعداد فرصت‌های پایدار (۵ اسکن)", len(stable_df))
    s2.metric("تعداد اسکن انجام‌شده", st.session_state.get("stability_scan_number", 0))
    if not stable_df.empty:
        st.success("فرصت‌های زیر در ۵ اسکن متوالی واجد شرایط باقی مانده‌اند؛ این فقط پایداری داده و قیمت است، نه تضمین اجرا یا سود.")
        stable_view = stable_df[["symbol", "buy_exchange", "sell_exchange", "net_spread_pct", "profit_toman", "stable_scans"]].rename(columns={
            "symbol": "جفت‌ارز", "buy_exchange": "صرافی خرید", "sell_exchange": "صرافی فروش",
            "net_spread_pct": "بازده خالص ٪", "profit_toman": "سود تخمینی تومان",
            "stable_scans": "تعداد اسکن متوالی",
        })
        st.dataframe(stable_view, width="stretch", hide_index=True)
    else:
        st.info("هنوز فرصت واجد شرایطی در ۵ اسکن متوالی تکرار نشده است. برای بررسی، هر بار «دریافت دوباره قیمت‌ها» را بزنید.")
    st.subheader("اعتبارسنجی اجرای فرضی")
    st.caption(
        "این بخش فقط کیفیت داده و امکان تطبیق حجم روی دفتر سفارش عمومی را می‌سنجد؛ "
        "موجودی حساب، محدودیت سفارش، وضعیت واریز/برداشت و امکان انتقال شبکه را تأیید نمی‌کند."
    )
    validation_cols = [
        "symbol", "validation_status", "asset_identity_status", "network_status", "deposit_withdraw_status", "buy_vwap", "sell_vwap",
        "buy_levels_used", "sell_levels_used", "depth_coverage_pct",
        "buy_book_age_seconds", "sell_book_age_seconds",
        "snapshot_skew_seconds", "buy_api_latency_ms", "sell_api_latency_ms",
        "net_spread_pct", "profit_toman",
        "stress_profit_slip_010_toman", "stress_profit_slip_025_toman",
        "stress_profit_slip_050_toman", "max_extra_slippage_pct",
    ]
    validation_view = df[validation_cols].rename(columns={
        "symbol": "جفت‌ارز",
        "validation_status": "نتیجه بررسی",
        "buy_vwap": "میانگین قیمت خرید",
        "sell_vwap": "میانگین قیمت فروش",
        "buy_levels_used": "سطوح مصرف‌شده خرید",
        "sell_levels_used": "سطوح مصرف‌شده فروش",
        "depth_coverage_pct": "پوشش حجم فروش ٪",
        "buy_book_age_seconds": "سن داده خرید (ثانیه)",
        "sell_book_age_seconds": "سن داده فروش (ثانیه)",
        "snapshot_skew_seconds": "فاصله دریافت دو دفتر (ثانیه)",
        "buy_api_latency_ms": "تأخیر API خرید (ms)",
        "sell_api_latency_ms": "تأخیر API فروش (ms)",
        "net_spread_pct": "بازده خالص ٪",
        "profit_toman": "سود تخمینی تومان",
        "stress_profit_slip_010_toman": "سود با ۰٫۱۰٪ لغزش اضافه",
        "stress_profit_slip_025_toman": "سود با ۰٫۲۵٪ لغزش اضافه",
        "stress_profit_slip_050_toman": "سود با ۰٫۵۰٪ لغزش اضافه",
        "max_extra_slippage_pct": "حد تحمل لغزش اضافه ٪",
    })
    st.subheader("آزمون فشار لغزش قیمت")
    st.caption(
        "در هر سناریو، لغزش اضافه به‌طور هم‌زمان به خرید و فروش افزوده می‌شود؛ "
        "کارمزد و هزینه انتقال ثابت می‌مانند. این آزمون تخمین تنش است، نه پیش‌بینی اجرای واقعی."
    )
    stress_cols = [
        "جفت‌ارز", "سود با ۰٫۱۰٪ لغزش اضافه", "سود با ۰٫۲۵٪ لغزش اضافه",
        "سود با ۰٫۵۰٪ لغزش اضافه", "حد تحمل لغزش اضافه ٪",
    ]
    st.dataframe(validation_view[stress_cols], width="stretch", hide_index=True)
    st.dataframe(validation_view.drop(columns=[
        "سود با ۰٫۱۰٪ لغزش اضافه", "سود با ۰٫۲۵٪ لغزش اضافه",
        "سود با ۰٫۵۰٪ لغزش اضافه", "حد تحمل لغزش اضافه ٪",
    ]), width="stretch", hide_index=True)
    st.subheader("فرصت‌های قابل بررسی")
    display = df.rename(columns={
        "symbol": "جفت‌ارز",
        "buy_exchange": "صرافی خرید",
        "sell_exchange": "صرافی فروش",
        "buy_ask": "بهترین قیمت خرید",
        "sell_bid": "بهترین قیمت فروش",
        "spread_pct": "اختلاف خام ٪",
        "net_spread_pct": "بازده خالص ٪",
        "profit_toman": "سود خالص تخمینی (تومان)",
        "used_capital_toman": "سرمایه درگیر (تومان)",
        "unused_capital_toman": "سرمایه استفاده‌نشده (تومان)",
        "base_quantity": "حجم قابل تطبیق",
        "buy_vwap": "میانگین قیمت خرید",
        "sell_vwap": "میانگین قیمت فروش",
        "buy_levels_used": "سطوح خرید مصرف‌شده",
        "sell_levels_used": "سطوح فروش مصرف‌شده",
        "depth_coverage_pct": "پوشش حجم فروش ٪",
        "snapshot_skew_seconds": "فاصله زمانی دو دفتر (ثانیه)",
        "validation_status": "نتیجه اعتبارسنجی",
        "depth_note": "تازگی داده",
        "review_score": "امتیاز بررسی از ۱۰۰",
        "stable_scans": "تعداد اسکن متوالی",
    })
    columns = [
        "جفت‌ارز", "صرافی خرید", "صرافی فروش",
        "بهترین قیمت خرید", "بهترین قیمت فروش", "اختلاف خام ٪",
        "بازده خالص ٪", "سود خالص تخمینی (تومان)",
        "سرمایه درگیر (تومان)", "سرمایه استفاده‌نشده (تومان)",
        "حجم قابل تطبیق", "میانگین قیمت خرید", "میانگین قیمت فروش",
        "سطوح خرید مصرف‌شده", "سطوح فروش مصرف‌شده", "پوشش حجم فروش ٪",
        "فاصله زمانی دو دفتر (ثانیه)", "نتیجه اعتبارسنجی",
        "تازگی داده", "امتیاز بررسی از ۱۰۰", "تعداد اسکن متوالی",
    ]
    st.dataframe(display[columns], width="stretch", hide_index=True)
    st.caption(
        "امتیاز بررسی، رتبه‌بندی شفاف بر اساس بازده، میزان سرمایه قابل استفاده و تازگی داده است؛ "
        "احتمال موفقیت یا تضمین سود نیست. به‌دلیل نبود مهر زمانی والکس، امتیاز تازگی محافظه‌کارانه محاسبه می‌شود."
    )
    st.caption(
        "فقط بازارهای دارای مظنه IRT/TMN مشترک در محاسبه سود تومانی وارد می‌شوند. "
        "بازارهای USDT فعلاً برای جلوگیری از فرض نرخ تبدیل جداگانه در سود تومانی لحاظ نشده‌اند."
    )

st.divider()
st.subheader("🧪 سبد معاملات کاغذی")
st.caption(
    "ثبت معامله در این بخش فقط نتیجه یک شبیه‌سازی روی snapshot فعلی دفتر سفارش است؛ "
    "هیچ سفارش یا انتقال واقعی انجام نمی‌شود. سوابق پس از اتصال امن، در دفتر ابری ذخیره می‌شوند؛ معاملات فقط شبیه‌سازی هستند."
)
paper_trades = st.session_state.setdefault("paper_trades", [])
ledger_url = os.getenv("SUPABASE_URL", "").rstrip("/") + "/functions/v1/arbitrage-paper-ledger"
ledger_anon_key = "".join(os.getenv("SUPABASE_ANON_KEY", "").split())
ledger_token = "".join(os.getenv("ARBITRAGE_APP_TOKEN", "").split())
ledger_ready = bool(os.getenv("SUPABASE_URL") and ledger_anon_key and ledger_token)

def ledger_request(method, payload=None):
    if not ledger_ready:
        return None, "تنظیمات اتصال امن به دفتر ابری کامل نیست."
    headers = {
        "Authorization": f"Bearer {ledger_anon_key}",
        "apikey": ledger_anon_key,
        "x-app-token": ledger_token,
        "Content-Type": "application/json",
    }
    try:
        response = requests.request(
            method, ledger_url, headers=headers, json=payload, timeout=15
        )
        if response.status_code == 409:
            return None, "این مسیر در ۳۰ دقیقه اخیر قبلاً ثبت شده است."
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        failed_response = getattr(exc, "response", None)
        if failed_response is not None:
            detail = (failed_response.text or "").replace("\\n", " ").strip()[:180]
            return None, f"خطای دفتر ابری (HTTP {failed_response.status_code}): {detail or 'پاسخ نامعتبر'}"
        return None, f"خطای ارتباط با دفتر ابری: {type(exc).__name__}"

if "paper_trades_loaded" not in st.session_state:
    st.session_state["paper_trades_loaded"] = False
    st.session_state["ledger_load_error"] = "بارگذاری هنوز انجام نشده است."

def load_cloud_ledger():
    if not ledger_ready:
        st.session_state["paper_trades_loaded"] = False
        st.session_state["ledger_load_error"] = "متغیرهای اتصال در Render کامل نیستند."
        return
    cloud_result, cloud_error = ledger_request("GET")
    if cloud_error is None and isinstance(cloud_result, dict):
        st.session_state["paper_trades"] = [
            row.get("trade", {}) for row in cloud_result.get("trades", [])
        ]
        st.session_state["paper_trades_loaded"] = True
        st.session_state["ledger_load_error"] = ""
    else:
        st.session_state["paper_trades_loaded"] = False
        st.session_state["ledger_load_error"] = cloud_error or "پاسخ نامعتبر از دفتر ابری."

if not st.session_state.get("paper_trades_loaded") and not st.session_state.get("ledger_load_attempted"):
    st.session_state["ledger_load_attempted"] = True
    load_cloud_ledger()

if st.button("🔁 تلاش دوباره برای اتصال دفتر ابری", key="retry_cloud_ledger"):
    load_cloud_ledger()
    if st.session_state.get("paper_trades_loaded"):
        st.success("اتصال دفتر ابری با موفقیت برقرار شد؛ سوابق آزمایشی بارگذاری شدند.")
    else:
        st.error(f"اتصال دفتر ابری برقرار نشد: {st.session_state.get('ledger_load_error', 'خطای نامشخص')}")

if not ledger_ready:
    st.warning("اتصال ذخیره دائمی هنوز پیکربندی نشده است؛ معاملات جدید در فضای ابری ثبت نمی‌شوند.")
elif not st.session_state.get("paper_trades_loaded"):
    st.warning("بارگذاری سوابق ابری انجام نشد؛ ثبت معامله کاغذی غیرفعال است.")
    st.error(f"جزئیات تشخیصی: {st.session_state.get('ledger_load_error', 'نامشخص')}")

paper_candidates = pd.DataFrame()
if not df.empty:
    candidate_mask = df.apply(
        lambda row: is_paper_candidate(
            stable_scans=row["stable_scans"],
            market_stable_now=row["market_stable_now"],
            validation_status=row["validation_status"],
            profit_toman=row["profit_toman"],
            used_capital_toman=row["used_capital_toman"],
            capital=capital,
            profit_change_pct=row["profit_change_pct"],
            stress_profit_slip_025_toman=row.get("stress_profit_slip_025_toman"),
        ),
        axis=1,
    )
    paper_candidates = df[candidate_mask].copy()

if paper_candidates.empty:
    st.info("برای ثبت معامله کاغذی، ابتدا باید فرصت مثبت، پایدار در ۵ اسکن و قابل بررسی در شبیه‌سازی وجود داشته باشد.")
else:
    candidate_labels = [
        f"{row['symbol']} | خرید: {row['buy_exchange']} ← فروش: {row['sell_exchange']} | "
        f"سرمایه: {row['used_capital_toman']:,.0f} تومان | سود تخمینی: {row['profit_toman']:,.0f} تومان"
        for _, row in paper_candidates.iterrows()
    ]
    selected_index = st.selectbox(
        "انتخاب فرصت برای ثبت در سبد آزمایشی",
        options=list(range(len(candidate_labels))),
        format_func=lambda index: candidate_labels[index],
        key="paper_candidate_select",
    )
    selected = paper_candidates.iloc[selected_index]
    current_scan = st.session_state.get("stability_scan_number", 0)
    # Prevent repeated paper entries for the same asset and exchange direction.
    # A route becomes eligible again only after its 30-minute expiry window.
    route_key = (
        f"{selected['symbol']}|{selected['buy_exchange']}|{selected['sell_exchange']}"
    )
    now_local = datetime.now(TEHRAN)
    recent_same_route = False
    for existing in paper_trades:
        existing_key = (
            f"{existing.get('جفت‌ارز', '')}|"
            f"{existing.get('صرافی خرید', '')}|{existing.get('صرافی فروش', '')}"
        )
        if existing_key != route_key:
            continue
        try:
            recorded_at = datetime.strptime(existing.get("زمان", ""), "%Y-%m-%d %H:%M:%S")
            if now_local.replace(tzinfo=None) - recorded_at < timedelta(minutes=30):
                recent_same_route = True
                break
        except (TypeError, ValueError):
            # If an old record has an unreadable timestamp, block conservatively.
            recent_same_route = True
            break
    if recent_same_route:
        st.warning("این جفت‌ارز با همین مسیر خرید و فروش در ۳۰ دقیقه اخیر ثبت شده است؛ برای جلوگیری از دوباره‌شماری، ثبت مجدد موقتاً مسدود است.")
    if st.button(
        "ثبت معامله کاغذی و محاسبه نتیجه",
        type="primary",
        disabled=recent_same_route or not ledger_ready or not st.session_state.get("paper_trades_loaded"),
        key="record_paper_trade",
    ):
        trade = {
            "زمان": datetime.now(TEHRAN).strftime("%Y-%m-%d %H:%M:%S"),
            "اسکن": current_scan,
            "جفت‌ارز": str(selected["symbol"]),
            "صرافی خرید": str(selected["buy_exchange"]),
            "صرافی فروش": str(selected["sell_exchange"]),
            "سرمایه مصرفی (تومان)": int(selected["used_capital_toman"]),
            "خرید ناخالص (تومان)": int(selected["buy_gross_toman"]),
            "فروش ناخالص (تومان)": int(selected["sell_gross_toman"]),
            "کارمزد خرید (تومان)": int(selected["buy_fee_toman"]),
            "لغزش خرید (تومان)": int(selected["buy_slippage_toman"]),
            "کارمزد فروش (تومان)": int(selected["sell_fee_toman"]),
            "لغزش فروش (تومان)": int(selected["sell_slippage_toman"]),
            "انتقال و سایر هزینه‌ها (تومان)": int(selected["transfer_cost_toman"]),
            "کل هزینه‌ها (تومان)": int(selected["total_costs_toman"]),
            "سود/زیان خالص (تومان)": int(selected["profit_toman"]),
            "بازده خالص (%)": float(selected["net_spread_pct"]),
            "وضعیت": "تکمیل‌شده در شبیه‌سازی",
        }
        cloud_result, cloud_error = ledger_request("POST", {"route_key": route_key, "trade": trade})
        if cloud_error:
            st.error(f"ثبت در فضای ابری ناموفق بود: {cloud_error}")
        else:
            paper_trades.append(trade)
            st.session_state["paper_trades"] = paper_trades[-500:]
            st.success(
                f"معامله کاغذی در فضای ابری ذخیره شد؛ سود/زیان خالص تخمینی: "
                f"{trade['سود/زیان خالص (تومان)']:,} تومان"
            )
            if telegram_configured():
                telegram_ok, telegram_message = send_paper_trade_report(trade)
                if not telegram_ok:
                    st.warning(f"گزارش تلگرام ارسال نشد: {telegram_message}")

total_paper_pnl = sum(item["سود/زیان خالص (تومان)"] for item in paper_trades)
paper_wins = sum(1 for item in paper_trades if item["سود/زیان خالص (تومان)"] > 0)
paper_losses = sum(1 for item in paper_trades if item["سود/زیان خالص (تومان)"] < 0)
p1, p2, p3, p4 = st.columns(4)
p1.metric("تعداد معاملات کاغذی", len(paper_trades))
p2.metric("سود/زیان خالص تجمعی", f"{total_paper_pnl:,.0f} تومان")
p3.metric("نتیجه مثبت", paper_wins)
p4.metric("نتیجه منفی", paper_losses)

if paper_trades:
    paper_view = pd.DataFrame(paper_trades)
    pnl_col = "سود/زیان خالص (تومان)"
    roi_col = "بازده خالص (%)"
    cost_col = "کل هزینه‌ها (تومان)"
    if pnl_col not in paper_view:
        paper_view[pnl_col] = 0
    paper_view[pnl_col] = pd.to_numeric(paper_view[pnl_col], errors="coerce").fillna(0)
    if roi_col in paper_view:
        paper_view[roi_col] = pd.to_numeric(paper_view[roi_col], errors="coerce").fillna(0)
    else:
        paper_view[roi_col] = 0
    if cost_col in paper_view:
        paper_view[cost_col] = pd.to_numeric(paper_view[cost_col], errors="coerce").fillna(0)
    else:
        paper_view[cost_col] = 0

    total_count = len(paper_view)
    breakeven_count = int((paper_view[pnl_col] == 0).sum())
    positive_count = int((paper_view[pnl_col] > 0).sum())
    negative_count = int((paper_view[pnl_col] < 0).sum())
    win_rate = (positive_count / total_count * 100) if total_count else 0
    average_pnl = float(paper_view[pnl_col].mean()) if total_count else 0
    average_roi = float(paper_view[roi_col].mean()) if total_count else 0
    total_costs = float(paper_view[cost_col].sum()) if total_count else 0

    st.markdown("#### 📊 گزارش عملکرد معاملات")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("درصد معاملات سودده", f"{win_rate:.1f}%")
    a2.metric("میانگین سود یا زیان هر معامله", f"{average_pnl:,.0f} تومان")
    a3.metric("میانگین بازده خالص", f"{average_roi:.2f}%")
    a4.metric("مجموع هزینه‌های محاسبه‌شده", f"{total_costs:,.0f} تومان")
    st.caption(
        f"سودده: {positive_count} معامله | زیان‌ده: {negative_count} معامله | "
        f"بدون سود و زیان: {breakeven_count} معامله | "
        f"بهترین نتیجه: {paper_view[pnl_col].max():,.0f} تومان | "
        f"ضعیف‌ترین نتیجه: {paper_view[pnl_col].min():,.0f} تومان"
    )

    if "زمان" in paper_view:
        paper_view["_زمان_گزارش"] = pd.to_datetime(paper_view["زمان"], errors="coerce")
        dated = paper_view.dropna(subset=["_زمان_گزارش"]).copy()
        if not dated.empty:
            dated["تاریخ"] = dated["_زمان_گزارش"].dt.strftime("%Y-%m-%d")
            daily = dated.groupby("تاریخ", as_index=False).agg(
                تعداد_معامله=(pnl_col, "count"),
                سود_زیان_روزانه=(pnl_col, "sum"),
            ).sort_values("تاریخ")
            daily["سود_زیان_تجمعی"] = daily["سود_زیان_روزانه"].cumsum()
            daily_view = daily.rename(columns={
                "تعداد_معامله": "تعداد معاملات",
                "سود_زیان_روزانه": "سود/زیان روزانه (تومان)",
                "سود_زیان_تجمعی": "سود/زیان تجمعی (تومان)",
            })
            st.markdown("#### 📈 نمودار سود و زیان بر اساس روز")
            st.line_chart(
                daily_view,
                x="تاریخ",
                y=["سود/زیان روزانه (تومان)", "سود/زیان تجمعی (تومان)"],
                x_label="تاریخ",
                y_label="مبلغ به تومان",
            )
            st.markdown("#### خلاصه روزانه")
            st.dataframe(daily_view, width="stretch", hide_index=True)

    st.markdown("#### سوابق معاملات ثبت‌شده")
    st.dataframe(
        paper_view.drop(columns=["_زمان_گزارش"], errors="ignore").iloc[::-1],
        width="stretch",
        hide_index=True,
    )
else:
    st.info("هنوز معامله کاغذی ثبت نشده است. ابتدا یک فرصت واجد شرایط را انتخاب کنید.")

st.divider()
st.subheader("تاریخچه و گزارش روزانه این نشست")
history = st.session_state.get("history", [])
today = datetime.now(TEHRAN).date()
today_history = [row for row in history if row["time"].date() == today]
h1, h2, h3 = st.columns(3)
h1.metric("تعداد اسکن امروز در این نشست", len(today_history))
h2.metric("بهترین سود مشاهده‌شده", f"{max([r['best_profit'] for r in today_history] or [0]):,.0f} تومان")
h3.metric("آخرین اسکن", today_history[-1]["time"].strftime("%H:%M:%S") if today_history else "—")
if today_history:
    history_df = pd.DataFrame([{
        "زمان": row["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "تعداد فرصت واجد شرایط": row["opportunities"],
        "فرصت پایدار (۵ اسکن)": row.get("stable_opportunities", 0),
        "بهترین جفت‌ارز": row["best_symbol"],
        "بهترین سود تخمینی (تومان)": row["best_profit"],
    } for row in today_history])
    st.dataframe(history_df, width="stretch", hide_index=True)
else:
    st.caption("پس از هر بار دریافت قیمت، سابقه اسکن در همین نشست ثبت می‌شود. این تاریخچه با بسته‌شدن نشست پاک می‌شود.")

st.divider()
st.subheader("روش محاسبه")
st.write(
    "برنامه ابتدا حجم قابل فروش در دفتر سفارش مقصد را می‌سنجد، سپس با سرمایه تعیین‌شده "
    "از سطوح فروش دفتر سفارش مبدأ خرید شبیه‌سازی می‌کند. قیمت و حجم هر سطح در محاسبه لحاظ می‌شود؛ "
    "کارمزد خرید و فروش، لغزش تخمینی هر سمت و هزینه انتقال از سود کسر می‌شوند. "
    "سود خالص فقط برای حجمی گزارش می‌شود که در دفتر سفارش مقصد نیز قابل فروش باشد."
)
st.subheader("محدودیت‌های مهم")
st.write(
    "- هیچ سفارش واقعی، برداشت یا انتقالی انجام نمی‌شود.\n"
    "- موجودی قابل برداشت و واریز حساب‌ها بررسی نمی‌شود.\n"
    "- کارمزد شبکه و زمان انتقال به‌صورت زنده از صرافی دریافت نمی‌شود.\n"
    "- سن داده نوبیتکس از مهر زمانی صرافی محاسبه می‌شود؛ برای والکس فقط زمان دریافت محلی در دسترس است و سن واقعی سمت صرافی قابل اثبات نیست.\n"
    "- فاصله زمانی دریافت دو دفتر و تأخیر API گزارش می‌شود؛ این مقادیر جایگزین مهر زمانی معتبر صرافی نیستند.\n"
    "- میانگین قیمت خرید/فروش و تعداد سطوح مصرف‌شده از حجم واقعی قابل مشاهده در همان snapshot محاسبه می‌شوند.\n"
    "- ممکن است دفتر سفارش تا لحظه معامله تغییر کند؛ سود واقعی می‌تواند کمتر یا منفی شود.\n"
    "- بازارهای USDT تا زمان افزودن مسیر تبدیل مستقل USDT/تومان، وارد سود تومانی نمی‌شوند."
)
st.info(
    "داده‌ها از API عمومی والکس و نوبیتکس دریافت می‌شوند و برای این بخش کلید خصوصی لازم نیست. "
    "کلید API، برداشت و ثبت سفارش واقعی در این برنامه فعال نشده‌اند."
)
