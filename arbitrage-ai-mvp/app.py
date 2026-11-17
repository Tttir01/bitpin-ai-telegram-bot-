import streamlit as st
import pandas as pd
from scanner import scan_markets

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("📈 Arbitrage AI")
st.caption("نسخه آزمایشی ۰.۳ | بیت‌پین ↔ MEXC | فقط تحلیل و شبیه‌سازی")
st.warning(
    "این نسخه سفارش واقعی ثبت نمی‌کند. سود خالص فقط یک برآورد است؛ "
    "عمق کامل سفارش، موجودی حساب‌ها، امکان انتقال و تغییر قیمت هنگام اجرا "
    "هنوز تأیید نمی‌شوند."
)

with st.sidebar:
    st.header("تنظیمات")
    capital = st.number_input(
        "سرمایه آزمایشی (تومان)", min_value=100000,
        value=2000000, step=100000
    )
    fee_local = st.number_input(
        "کارمزد هر سمت بیت‌پین (%)", min_value=0.0,
        max_value=5.0, value=0.25, step=0.05
    ) / 100
    fee_global = st.number_input(
        "کارمزد هر سمت MEXC (%)", min_value=0.0,
        max_value=5.0, value=0.10, step=0.05
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
        "کارمزدها، لغزش و هزینه انتقال تخمینی‌اند؛ "
        "مقادیر واقعی حساب و شبکه را وارد کنید."
    )
    refresh = st.button("🔄 دریافت قیمت‌ها", use_container_width=True)

scan_settings = (fee_local, fee_global, slippage_pct, transfer_cost_pct)
if refresh or st.session_state.get("scan_settings") != scan_settings:
    with st.spinner("در حال دریافت داده‌های عمومی بیت‌پین و MEXC..."):
        st.session_state["scan"] = scan_markets(
            fee_local=fee_local,
            fee_global=fee_global,
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
        "مبلغ تومانی صرفاً محاسبه درصد روی سرمایه فرضی است؛ "
        "به‌دلیل تفاوت ارز مظنه و محدودیت انتقال، سود قابل تحقق یا تضمینی نیست."
    )

st.divider()
st.subheader("روش محاسبه")
st.write(
    "قیمت خرید با کارمزد خرید و لغزش تخمینی افزایش می‌یابد؛ "
    "قیمت فروش پس از کسر کارمزد فروش و لغزش تخمینی محاسبه می‌شود؛ "
    "سپس هزینه انتقال و سایر هزینه‌های واردشده کسر می‌گردد."
)
st.subheader("مواردی که هنوز بررسی نمی‌شوند")
st.write(
    "- عمق کامل دفتر سفارش و حجم قابل معامله در چند سطح قیمت\n"
    "- موجودی قابل برداشت و امکان انتقال بین صرافی‌ها\n"
    "- زمان انتقال، محدودیت شبکه و تغییر قیمت در مسیر\n"
    "- تطبیق دقیق واحد ارز مظنه بین دو بازار\n"
    "- ثبت، پیگیری یا لغو سفارش واقعی"
)
st.info(
    "نسخه ۰.۳ فقط داده عمومی بیت‌پین و MEXC را می‌خواند. "
    "هیچ کلید خصوصی، اطلاعات ورود حساب، برداشت یا سفارش واقعی استفاده نمی‌شود."
)
