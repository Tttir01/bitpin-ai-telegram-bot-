import streamlit as st
import pandas as pd
from scanner import scan_markets

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 Arbitrage AI")
st.caption("نسخه آزمایشی ۰.۵ | والکس ↔ نوبیتکس | فقط تحلیل و شبیه‌سازی")
st.warning(
    "این نسخه سفارش واقعی ثبت نمی‌کند. سود خالص فقط یک برآورد است؛ "
    "موجودی حساب‌ها، امکان انتقال، حجم قابل معامله پس از اثرگذاری بر عمق بازار "
    "و تغییر قیمت هنگام اجرا تأیید نمی‌شوند."
)

with st.sidebar:
    st.header("تنظیمات")
    capital = st.number_input(
        "سرمایه آزمایشی (تومان)", min_value=100000,
        value=2000000, step=100000
    )
    fee_local = st.number_input(
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
        "کارمزد، لغزش و هزینه انتقال تخمینی‌اند؛ مقادیر واقعی ممکن است متفاوت باشند."
    )
    refresh = st.button("🔄 دریافت قیمت‌ها", use_container_width=True)

scan_settings = (fee_local, fee_nobitex, slippage_pct, transfer_cost_pct)
if refresh or st.session_state.get("scan_settings") != scan_settings:
    with st.spinner("در حال دریافت داده‌های عمومی والکس و نوبیتکس..."):
        st.session_state["scan"] = scan_markets(
            fee_local=fee_local,
            fee_global=fee_nobitex,
            slippage_pct=slippage_pct,
            transfer_cost_pct=transfer_cost_pct,
        )
        st.session_state["scan_settings"] = scan_settings

result = st.session_state.get("scan", {"opportunities": [], "errors": []})
for error in result.get("errors", []):
    st.error(error)

a, b, c = st.columns(3)
a.metric("سرمایه شبیه‌سازی", f"{capital:,.0f} تومان")
b.metric("حالت اجرا", "شبیه‌سازی")
c.metric("سفارش واقعی", "غیرفعال")

df = pd.DataFrame(result.get("opportunities", []))
if not df.empty:
    df = df[df["net_spread_pct"] >= min_net].copy()
    df["سود/زیان تخمینی (تومان)"] = (
        capital * df["net_spread_pct"] / 100
    ).round(0).astype("int64")
    df = df.sort_values("net_spread_pct", ascending=False)

if df.empty:
    st.info(
        "با هزینه‌ها و حداقل سود انتخاب‌شده، فرصت مثبت و قابل بررسی پیدا نشد؛ "
        "یا API در دسترس نیست یا جفت‌ارز مشترک وجود ندارد."
    )
else:
    st.subheader("فرصت‌های قابل بررسی")
    display = df.rename(columns={
        "symbol": "جفت‌ارز",
        "buy_exchange": "صرافی خرید",
        "sell_exchange": "صرافی فروش",
        "buy_ask": "قیمت خرید",
        "sell_bid": "قیمت فروش",
        "spread_pct": "اختلاف خام ٪",
        "net_spread_pct": "سود خالص برآوردی ٪",
        "estimated_cost_pct": "هزینه‌های برآوردی ٪",
        "note": "محدودیت داده",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(
        "قیمت‌های بازار والکس با مظنه TMN (تومان) و بازار IRT نوبیتکس "
        "پس از تبدیل ریال به تومان مقایسه می‌شوند. سود قابل تحقق یا تضمینی نیست."
    )

st.divider()
st.subheader("روش محاسبه")
st.write(
    "قیمت خرید با کارمزد خرید و لغزش تخمینی افزایش می‌یابد؛ "
    "قیمت فروش پس از کسر کارمزد فروش و لغزش تخمینی محاسبه می‌شود؛ "
    "سپس هزینه انتقال و سایر هزینه‌های واردشده کسر می‌گردد."
)
st.subheader("محدودیت‌های نسخه فعلی")
st.write(
    "- سفارش واقعی، پیگیری یا لغو سفارش انجام نمی‌شود\n"
    "- موجودی حساب‌ها و امکان واریز/برداشت بررسی نمی‌شود\n"
    "- هزینه، شبکه و زمان انتقال به‌صورت زنده بررسی نمی‌شود\n"
    "- قیمت‌های بهترین bid/ask بازار والکس و دفتر سفارش نوبیتکس استفاده می‌شوند\n"
    "- سود نمایش‌داده‌شده برآوردی است و اثر حجم معامله بر قیمت را تضمین نمی‌کند"
)
st.info(
    "داده‌های عمومی بازار والکس و دفتر سفارش عمومی نوبیتکس استفاده می‌شوند. "
    "برای دریافت این داده‌ها کلید API یا توکن خصوصی لازم نیست؛ "
    "هیچ برداشت یا سفارش واقعی فعال نشده است."
)
