from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

import pandas as pd
import requests
import streamlit as st
from scanner import scan_markets

TEHRAN = ZoneInfo("Asia/Tehran")

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 هوش مصنوعی آربیتراژ")
st.caption("نسخه آزمایشی ۰.۸ | تشخیص فرصت پایدار در ۳ اسکن متوالی")
st.warning(
    "این نسخه سفارش واقعی ثبت نمی‌کند. سودها برآورد شبیه‌سازی بر اساس سطوح قابل مشاهده دفتر سفارش هستند؛ "
    "موجودی حساب، امکان انتقال، شبکه انتقال و تغییر قیمت تا زمان اجرای واقعی تأیید نمی‌شوند."
)

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
            st.session_state["stability_scan_number"] = 0
        st.session_state["stability_settings"] = scan_settings

        # Count only opportunities that pass the user's net-return and executable-depth filters.
        eligible_now = {
            (item.get("symbol"), item.get("buy_exchange"), item.get("sell_exchange"))
            for item in result.get("opportunities", [])
            if item.get("net_spread_pct", -999) >= min_net
            and item.get("profit_toman", 0) > 0
            and item.get("used_capital_toman", 0) >= min_executable
        }
        old_counts = st.session_state.get("stability_counts", {})
        previous_keys = st.session_state.get("previous_eligible_keys", set())
        new_counts = {
            key: (old_counts.get(key, 0) + 1 if key in previous_keys else 1)
            for key in eligible_now
        }
        st.session_state["stability_counts"] = new_counts
        st.session_state["previous_eligible_keys"] = eligible_now
        st.session_state["stability_scan_number"] = st.session_state.get("stability_scan_number", 0) + 1
        st.session_state["scan_stability"] = {
            "|".join(key): count for key, count in new_counts.items()
        }

        history = st.session_state.setdefault("history", [])
        history.append({
            "time": datetime.now(TEHRAN),
            "opportunities": len(eligible_now),
            "stable_opportunities": sum(1 for count in new_counts.values() if count >= 3),
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
    # A transparent review score, not a probability or guarantee of execution.
    return_score = (df["net_spread_pct"].clip(lower=0, upper=1.5) / 1.5) * 100
    capital_score = (df["used_capital_toman"] / max(float(capital), 1)).clip(upper=1) * 100
    # Wallex's public depth response has no server timestamp, so freshness is penalized.
    freshness_score = 50.0
    df["review_score"] = (return_score * 0.40 + capital_score * 0.30 + freshness_score * 0.30).round(0).astype(int)
    stability = st.session_state.get("scan_stability", {})
    df["stable_scans"] = df.apply(
        lambda row: stability.get("|".join((str(row["symbol"]), str(row["buy_exchange"]), str(row["sell_exchange"]))), 0),
        axis=1,
    )
    df["stable_3"] = df["stable_scans"] >= 3
    df = df.sort_values(
        ["stable_3", "review_score", "profit_toman"], ascending=[False, False, False]
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

    stable_df = df[df["stable_3"]]
    st.subheader("تشخیص فرصت پایدار")
    s1, s2 = st.columns(2)
    s1.metric("تعداد فرصت‌های پایدار (۳ اسکن)", len(stable_df))
    s2.metric("تعداد اسکن انجام‌شده", st.session_state.get("stability_scan_number", 0))
    if not stable_df.empty:
        st.success("فرصت‌های زیر در ۳ اسکن متوالی واجد شرایط باقی مانده‌اند؛ این فقط پایداری داده و قیمت است، نه تضمین اجرا یا سود.")
        stable_view = stable_df[["symbol", "buy_exchange", "sell_exchange", "net_spread_pct", "profit_toman", "stable_scans"]].rename(columns={
            "symbol": "جفت‌ارز", "buy_exchange": "صرافی خرید", "sell_exchange": "صرافی فروش",
            "net_spread_pct": "بازده خالص ٪", "profit_toman": "سود تخمینی تومان",
            "stable_scans": "تعداد اسکن متوالی",
        })
        st.dataframe(stable_view, width="stretch", hide_index=True)
    else:
        st.info("هنوز فرصت واجد شرایطی در ۳ اسکن متوالی تکرار نشده است. برای بررسی، هر بار «دریافت دوباره قیمت‌ها» را بزنید.")
    st.subheader("اعتبارسنجی اجرای فرضی")
    st.caption(
        "این بخش فقط کیفیت داده و امکان تطبیق حجم روی دفتر سفارش عمومی را می‌سنجد؛ "
        "موجودی حساب، محدودیت سفارش، وضعیت واریز/برداشت و امکان انتقال شبکه را تأیید نمی‌کند."
    )
    validation_cols = [
        "symbol", "validation_status", "buy_vwap", "sell_vwap",
        "buy_levels_used", "sell_levels_used", "depth_coverage_pct",
        "buy_book_age_seconds", "sell_book_age_seconds",
        "snapshot_skew_seconds", "buy_api_latency_ms", "sell_api_latency_ms",
        "net_spread_pct", "profit_toman",
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
    })
    st.dataframe(validation_view, width="stretch", hide_index=True)
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
ledger_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
ledger_token = os.getenv("ARBITRAGE_APP_TOKEN", "")
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
    except requests.RequestException:
        return None, "ارتباط با دفتر ابری برقرار نشد؛ سابقه فقط در نشست ذخیره نشد."

if "paper_trades_loaded" not in st.session_state:
    if ledger_ready:
        cloud_result, cloud_error = ledger_request("GET")
        if cloud_error is None:
            st.session_state["paper_trades"] = [
                row.get("trade", {}) for row in cloud_result.get("trades", [])
            ]
            st.session_state["paper_trades_loaded"] = True
        else:
            st.session_state["paper_trades_loaded"] = False
    else:
        st.session_state["paper_trades_loaded"] = False

if not ledger_ready:
    st.warning("اتصال ذخیره دائمی هنوز پیکربندی نشده است؛ معاملات جدید در فضای ابری ثبت نمی‌شوند.")
elif not st.session_state.get("paper_trades_loaded"):
    st.warning("بارگذاری سوابق ابری انجام نشد؛ برای جلوگیری از ثبت نادرست، ثبت معامله کاغذی تا اتصال موفق غیرفعال است.")

paper_candidates = pd.DataFrame()
if not df.empty:
    paper_candidates = df[
        (df["stable_scans"] >= 3)
        & (df["validation_status"] == "قابل بررسی در شبیه‌سازی")
        & (df["profit_toman"] > 0)
        & (df["used_capital_toman"] <= capital)
    ].copy()

if paper_candidates.empty:
    st.info("برای ثبت معامله کاغذی، ابتدا باید فرصت مثبت، پایدار در ۳ اسکن و قابل بررسی در شبیه‌سازی وجود داشته باشد.")
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
    st.dataframe(paper_view.iloc[::-1], width="stretch", hide_index=True)
else:
    st.caption("هنوز معامله کاغذی ثبت نشده است. ابتدا فرصت واجد شرایط را از فهرست بالا انتخاب کنید.")

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
        "فرصت پایدار (۳ اسکن)": row.get("stable_opportunities", 0),
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
