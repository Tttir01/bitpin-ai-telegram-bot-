from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from scanner import scan_markets

TEHRAN = ZoneInfo("Asia/Tehran")

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 هوش مصنوعی آربیتراژ")
st.caption("نسخه آزمایشی ۰.۷ | والکس ↔ نوبیتکس | رتبه‌بندی و گزارش شبیه‌سازی")
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
        st.session_state["scan_settings"] = scan_settings
        history = st.session_state.setdefault("history", [])
        history.append({
            "time": datetime.now(TEHRAN),
            "opportunities": len(result.get("opportunities", [])),
            "best_profit": max(
                [x.get("profit_toman", 0) for x in result.get("opportunities", [])] or [0]
            ),
            "best_symbol": (
                max(result.get("opportunities", []), key=lambda x: x.get("profit_toman", 0)).get("symbol", "—")
                if result.get("opportunities") else "—"
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
    df = df.sort_values(
        ["review_score", "profit_toman"], ascending=[False, False]
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
        "depth_note": "تازگی داده",
        "review_score": "امتیاز بررسی از ۱۰۰",
    })
    columns = [
        "جفت‌ارز", "صرافی خرید", "صرافی فروش",
        "بهترین قیمت خرید", "بهترین قیمت فروش", "اختلاف خام ٪",
        "بازده خالص ٪", "سود خالص تخمینی (تومان)",
        "سرمایه درگیر (تومان)", "سرمایه استفاده‌نشده (تومان)",
        "حجم قابل تطبیق", "تازگی داده", "امتیاز بررسی از ۱۰۰",
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
        "تعداد فرصت خام": row["opportunities"],
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
    "- نوبیتکس زمان آخرین به‌روزرسانی دفتر سفارش را اعلام می‌کند؛ پاسخ عمق والکس در این API زمان سرور ندارد.\n"
    "- ممکن است دفتر سفارش تا لحظه معامله تغییر کند؛ سود واقعی می‌تواند کمتر یا منفی شود.\n"
    "- بازارهای USDT تا زمان افزودن مسیر تبدیل مستقل USDT/تومان، وارد سود تومانی نمی‌شوند."
)
st.info(
    "داده‌ها از API عمومی والکس و نوبیتکس دریافت می‌شوند و برای این بخش کلید خصوصی لازم نیست. "
    "کلید API، برداشت و ثبت سفارش واقعی در این برنامه فعال نشده‌اند."
)
