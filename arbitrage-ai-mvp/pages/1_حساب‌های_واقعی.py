import os
import pandas as pd
import streamlit as st
from account_readonly import ExchangeAPIError, wallex_balances, nobitex_balances

st.set_page_config(page_title="اتصال امن حساب‌ها | آربیتراژ", page_icon="🔐", layout="wide")
st.markdown("<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>", unsafe_allow_html=True)
st.title("🔐 اتصال واقعی حساب‌های صرافی")
st.caption("اتصال فقط‌خواندنی؛ دریافت موجودی واقعی و بدون امکان ثبت سفارش")
st.warning("این صفحه فقط از درخواست‌های GET برای مشاهده موجودی استفاده می‌کند. هیچ سفارش، خریدوفروش، برداشت، واریز یا انتقالی در کد این صفحه وجود ندارد.")

wallex_ready = bool(os.getenv("WALLEX_API_KEY", "").strip())
nobitex_ready = bool(os.getenv("NOBITEX_API_TOKEN", "").strip())
c1, c2 = st.columns(2)
c1.metric("والکس", "کلید تنظیم شده" if wallex_ready else "در انتظار کلید فقط‌خواندنی")
c2.metric("نوبیتکس", "توکن تنظیم شده" if nobitex_ready else "در انتظار توکن")

if st.button("🔄 دریافت موجودی واقعی", type="primary", use_container_width=True):
    results, errors = [], []
    if wallex_ready:
        try:
            results.extend(wallex_balances())
        except ExchangeAPIError as error:
            errors.append(("والکس", str(error)))
    else:
        errors.append(("والکس", "کلید API هنوز در متغیر امن WALLEX_API_KEY ثبت نشده است."))
    if nobitex_ready:
        try:
            results.extend(nobitex_balances())
        except ExchangeAPIError as error:
            errors.append(("نوبیتکس", str(error)))
    else:
        errors.append(("نوبیتکس", "توکن API هنوز در متغیر امن NOBITEX_API_TOKEN ثبت نشده است."))
    st.session_state["real_account_balances"] = results
    st.session_state["real_account_errors"] = errors
    st.session_state["real_account_checked"] = True

if st.session_state.get("real_account_checked"):
    for exchange, error in st.session_state.get("real_account_errors", []):
        st.error(f"{exchange}: {error}")
    rows = st.session_state.get("real_account_balances", [])
    if rows:
        view = pd.DataFrame([{
            "صرافی": row["exchange"], "دارایی": row["asset"], "نام": row["name"],
            "موجودی کل": str(row["total"]), "موجودی قفل‌شده": str(row["locked"]),
            "موجودی آزاد": str(row["available"]),
        } for row in rows])
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.success(f"موجودی {len(rows)} ردیف دارایی از API صرافی دریافت شد.")
    elif not st.session_state.get("real_account_errors"):
        st.info("در کیف‌پول‌های متصل، موجودی غیرصفر پیدا نشد.")

st.divider()
st.subheader("تنظیم امن کلیدها در Render")
st.markdown("""
در پنل Render، سرویس arbitrage-ai-mvp-1vby را باز کنید:
1. وارد بخش Environment شوید.
2. دو متغیر زیر را اضافه کنید و مقدار واقعی هرکدام را فقط همان‌جا وارد کنید.
3. ذخیره کنید تا سرویس دوباره راه‌اندازی شود.

- WALLEX_API_KEY — کلید والکس با مجوز مشاهده موجودی؛ مجوز معامله و برداشت خاموش
- NOBITEX_API_TOKEN — توکن API نوبیتکس برای دسترسی خواندن کیف‌پول

**کلیدها را در چت، GitHub، کد برنامه یا تصویر صفحه منتشر نکنید.** اگر صرافی امکان محدودکردن مجوز دارد، فقط دسترسی مشاهده را فعال کنید و برداشت/معامله را غیرفعال نگه دارید.
""")
st.info("بازار عمومی والکس و نوبیتکس در صفحه اصلی همچنان بدون کلید خصوصی دریافت می‌شود. تا زمان ثبت کلیدهای امن در Render، بخش موجودی حساب‌ها در انتظار اتصال باقی می‌ماند.")
