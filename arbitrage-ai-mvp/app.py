import streamlit as st
import pandas as pd
from scanner import scan_markets

st.set_page_config(page_title="Arbitrage AI", page_icon="📈", layout="wide")
st.markdown("<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>", unsafe_allow_html=True)
st.title("📈 Arbitrage AI")
st.caption("نسخه آزمایشی ۰.۱ | ایران + بازار جهانی | فقط تحلیل و شبیه‌سازی")
st.warning("این نسخه سفارش واقعی ثبت نمی‌کند. اختلاف قیمت به‌تنهایی سود قطعی نیست؛ عمق سفارش، کارمزد، هزینه انتقال، نرخ تبدیل و موجودی باید بررسی شوند.")

with st.sidebar:
    st.header("تنظیمات")
    capital = st.number_input("سرمایه آزمایشی (تومان)", min_value=100000, value=2000000, step=100000)
    fee_local = st.number_input("کارمزد هر سمت بیت‌پین (%)", min_value=0.0, max_value=5.0, value=0.25, step=0.05) / 100
    fee_global = st.number_input("کارمزد هر سمت صرافی جهانی (%)", min_value=0.0, max_value=5.0, value=0.10, step=0.05) / 100
    min_spread = st.number_input("حداقل اختلاف خام (%)", min_value=0.0, max_value=20.0, value=1.0, step=0.25)
    st.caption("کارمزدها نمونه‌اند؛ با کارمزد واقعی حساب خود جایگزین کنید.")
    refresh = st.button("🔄 دریافت قیمت‌ها", use_container_width=True)

st.subheader("وضعیت")
a,b,c = st.columns(3)
a.metric("سرمایه شبیه‌سازی", f"{capital:,.0f} تومان")
b.metric("حالت اجرا", "شبیه‌سازی")
c.metric("سفارش واقعی", "غیرفعال")

if refresh or "scan" not in st.session_state:
    with st.spinner("در حال دریافت داده‌های عمومی..."):
        st.session_state["scan"] = scan_markets(fee_local, fee_global)

result = st.session_state["scan"]
for err in result.get("errors", []):
    st.error(err)

df = pd.DataFrame(result.get("opportunities", []))
if not df.empty:
    df = df[df["spread_pct"] >= min_spread].sort_values("net_spread_pct", ascending=False)
if df.empty:
    st.info("فرصت قابل مقایسه‌ای با آستانه انتخاب‌شده پیدا نشد؛ یا API در دسترس نیست.")
else:
    st.subheader("اختلاف‌های قابل بررسی")
    st.dataframe(df.rename(columns={
        "symbol":"جفت‌ارز", "buy_exchange":"صرافی خرید", "sell_exchange":"صرافی فروش",
        "buy_ask":"قیمت خرید", "sell_bid":"قیمت فروش",
        "spread_pct":"اختلاف خام ٪", "net_spread_pct":"اختلاف پس از کارمزد ٪",
        "note":"توضیح"
    }), use_container_width=True, hide_index=True)
    st.caption("این ارقام سیگنال معامله نیستند؛ هزینه انتقال، لغزش قیمت و عمق واقعی سفارش هنوز لحاظ نشده‌اند.")

st.divider()
st.subheader("امنیت")
st.write("نسخه اول فقط داده عمومی می‌خواند و هیچ کلید خصوصی، موجودی حساب، برداشت یا سفارش واقعی ندارد.")
