import streamlit as st
import pandas as pd
from scanner import scan_markets

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 هوش مصنوعی آربیتراژ")
st.caption("نسخه آزمایشی ۰.۶ | والکس ↔ نوبیتکس | شبیه‌سازی عمق‌محور")
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
    st.caption(
        "کارمزد و لغزش باید با سطح کارمزد حساب و شرایط واقعی شبکه تطبیق داده شوند."
    )
    refresh = st.button("🔄 دریافت دوباره قیمت‌ها", use_container_width=True)

scan_settings = (
    capital, fee_wallex, fee_nobitex, slippage_pct, transfer_cost_pct
)
if refresh or st.session_state.get("scan_settings") != scan_settings:
    with st.spinner("در حال دریافت دفتر سفارش عمومی والکس و نوبیتکس..."):
        st.session_state["scan"] = scan_markets(
            fee_local=fee_wallex,
            fee_global=fee_nobitex,
            slippage_pct=slippage_pct,
            transfer_cost_pct=transfer_cost_pct,
            capital_toman=capital,
        )
        st.session_state["scan_settings"] = scan_settings

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
    df = df[df["net_spread_pct"] >= min_net].copy()
    df = df.sort_values("profit_toman", ascending=False)

if df.empty:
    st.info(
        "با تنظیمات فعلی فرصت خالص بالاتر از حداقل انتخاب‌شده پیدا نشد. "
        "ممکن است عمق کافی، جفت‌ارز تومانی مشترک یا داده تازه در دسترس نباشد."
    )
else:
    best = df.iloc[0]
    st.subheader("بهترین فرصت بر اساس سود خالص برآوردی")
    x, y, z = st.columns(3)
    x.metric("سود خالص تخمینی", f"{best['profit_toman']:,.0f} تومان")
    y.metric("سرمایه درگیر", f"{best['used_capital_toman']:,.0f} تومان")
    z.metric("بازده خالص", f"{best['net_spread_pct']:.2f}%")

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
    })
    columns = [
        "جفت‌ارز", "صرافی خرید", "صرافی فروش",
        "بهترین قیمت خرید", "بهترین قیمت فروش", "اختلاف خام ٪",
        "بازده خالص ٪", "سود خالص تخمینی (تومان)",
        "سرمایه درگیر (تومان)", "سرمایه استفاده‌نشده (تومان)",
        "حجم قابل تطبیق", "تازگی داده",
    ]
    st.dataframe(
        display[columns], use_container_width=True, hide_index=True
    )
    st.caption(
        "فقط بازارهای دارای مظنه IRT/TMN مشترک در محاسبه سود تومانی وارد می‌شوند. "
        "بازارهای USDT فعلاً برای جلوگیری از فرض نرخ تبدیل جداگانه در سود تومانی لحاظ نشده‌اند."
    )

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
