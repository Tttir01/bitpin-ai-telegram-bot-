import hmac
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

try:
    from scanner import scan_markets
except Exception:
    scan_markets = None

TEHRAN = ZoneInfo("Asia/Tehran")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

st.set_page_config(page_title="دستیار Gemini", page_icon="🤖", layout="wide")
st.markdown(
    "<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>",
    unsafe_allow_html=True,
)
st.title("🤖 دستیار هوشمند Gemini")
st.caption("دستیار فارسی تحلیل آربیتراژ، مدیریت ریسک و بررسی گزارش ربات‌ها")

assistant_password = os.getenv("GEMINI_ASSISTANT_PASSWORD", "")
api_key = os.getenv("GEMINI_API_KEY", "")
if not assistant_password:
    st.error("برای فعال‌سازی امن دستیار، ابتدا متغیر GEMINI_ASSISTANT_PASSWORD را در تنظیمات محیطی Render تعریف کنید.")
    st.stop()

if not st.session_state.get("gemini_authenticated"):
    entered = st.text_input("رمز ورود دستیار", type="password")
    if st.button("ورود", type="primary"):
        if hmac.compare_digest(entered, assistant_password):
            st.session_state["gemini_authenticated"] = True
            st.rerun()
        else:
            st.error("رمز ورود صحیح نیست.")
    st.stop()

if not api_key:
    st.error("کلید Gemini تنظیم نشده است. متغیر GEMINI_API_KEY را در Render اضافه کنید؛ کلید را در کد یا چت قرار ندهید.")
    st.stop()

SYSTEM_INSTRUCTION = """
تو دستیار فارسی تحلیل آربیتراژ و ربات‌های معاملاتی هستی.
پاسخ‌ها را فارسی، روشن، مرحله‌ای و بدون ادعای قطعی بنویس.
قیمت، موجودی، سود، کارمزد یا وضعیت سفارش را حدس نزن. اگر داده‌ای در زمینه پیام وجود ندارد، صریح بگو نامشخص است.
اگر snapshot بازار ارائه شده، فقط همان snapshot را مبنای تحلیل عددی قرار بده و زمان دریافت آن را یادآوری کن.
داده عمومی دفتر سفارش به معنی موجودی قابل برداشت، امکان انتقال، تطبیق شبکه یا امکان اجرای معامله نیست.
این برنامه فقط تحلیل و شبیه‌سازی می‌کند: هیچ سفارش واقعی، برداشت، انتقال یا تغییر حسابی انجام نده.
هرگز از کاربر کلید خصوصی صرافی، رمز عبور، seed phrase یا توکن محرمانه نخواه.
برای MT5 و سایر ربات‌ها فقط گزارش، کد یا لاگ ارائه‌شده در گفتگو را بررسی کن؛ ادعای اتصال مستقیم به MT5 نکن.
در تحلیل ریسک، کارمزد هر دو سمت، لغزش، عمق دفتر سفارش، نقدشوندگی، تازگی داده و ریسک انتقال را جداگانه بررسی کن.
اگر اطلاعات کافی نیست، به‌جای نتیجه‌گیری قطعی، موارد ناقص را فهرست کن.
"""

def get_market_snapshot():
    if scan_markets is None:
        return None, "ماژول scanner در دسترس نیست."
    try:
        result = scan_markets(
            fee_local=0.0025,
            fee_global=0.0025,
            slippage_pct=0.20,
            transfer_cost_pct=0.30,
            capital_toman=2_000_000,
        )
        rows = []
        for item in result.get("opportunities", [])[:8]:
            rows.append({
                "نماد": item.get("symbol"),
                "خرید": item.get("buy_exchange"),
                "فروش": item.get("sell_exchange"),
                "سود_خالص_تخمینی_تومان": item.get("profit_toman"),
                "بازده_خالص_درصد": item.get("net_spread_pct"),
                "سرمایه_درگیر_تومان": item.get("used_capital_toman"),
                "وضعیت_اعتبارسنجی": item.get("validation_status"),
                "آماده_اجرای_واقعی": False,
            })
        snapshot = {
            "زمان_دریافت_تهران": datetime.now(TEHRAN).isoformat(),
            "منابع": ["دفتر سفارش عمومی والکس", "دفتر سفارش عمومی نوبیتکس"],
            "سرمایه_فرضی_تومان": 2_000_000,
            "تعداد_فرصت_های_بازگشتی": len(result.get("opportunities", [])),
            "فرصت_های_برتر": rows,
            "خطاهای_منبع": result.get("errors", []),
            "محدودیت": "فقط snapshot و شبیه‌سازی؛ موجودی، شبکه انتقال و اجرای واقعی بررسی نمی‌شود.",
        }
        return snapshot, None
    except Exception as exc:
        return None, f"دریافت داده ناموفق بود: {type(exc).__name__}: {exc}"

def ask_gemini(history, user_text, snapshot):
    contents = []
    for item in history[-12:]:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})

    context = ""
    if snapshot:
        context = "\n\nداده بازار عمومی (JSON؛ فقط برای همین گفتگو):\n" + json.dumps(
            snapshot, ensure_ascii=False
        )
    contents.append({"role": "user", "parts": [{"text": user_text + context}]})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 1800,
        },
    }
    response = requests.post(
        API_URL,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=(10, 60),
    )
    if response.status_code != 200:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Gemini API ({response.status_code}): {detail[:700]}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("پاسخ متنی از Gemini دریافت نشد؛ ممکن است درخواست توسط فیلتر ایمنی متوقف شده باشد.")
    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "\n".join(p.get("text", "") for p in parts if p.get("text"))
    if not answer.strip():
        raise RuntimeError("پاسخ Gemini خالی بود.")
    return answer.strip()

with st.sidebar:
    st.subheader("وضعیت دستیار")
    st.success("ورود محافظت‌شده فعال است")
    st.caption(f"مدل انتخاب‌شده: {MODEL}")
    st.caption("داده بازار فقط با فشردن دکمه دریافت می‌شود.")
    if st.button("خروج از دستیار"):
        st.session_state["gemini_authenticated"] = False
        st.rerun()
    st.divider()
    if st.button("🧹 پاک‌کردن گفتگوی فعلی"):
        st.session_state["gemini_messages"] = []
        st.session_state["gemini_snapshot"] = None
        st.rerun()

left, right = st.columns([1, 1])
with left:
    if st.button("📊 دریافت snapshot تازه از والکس و نوبیتکس", use_container_width=True):
        with st.spinner("در حال دریافت داده عمومی بازار..."):
            snapshot, error = get_market_snapshot()
            st.session_state["gemini_snapshot"] = snapshot
            st.session_state["gemini_snapshot_error"] = error
    if st.session_state.get("gemini_snapshot"):
        snap = st.session_state["gemini_snapshot"]
        st.success(f"آخرین snapshot: {snap['زمان_دریافت_تهران']}")
        st.caption(f"فرصت‌های خام بازگشتی: {snap['تعداد_فرصت_های_بازگشتی']}")
    elif st.session_state.get("gemini_snapshot_error"):
        st.warning(st.session_state["gemini_snapshot_error"])
    else:
        st.info("هنوز snapshot تازه‌ای دریافت نشده است.")
with right:
    st.info("برای بررسی ربات MT5، گزارش خطا یا کد را در پیام خود قرار بده. اتصال مستقیم به MT5 در این نسخه وجود ندارد.")

st.divider()
messages = st.session_state.setdefault("gemini_messages", [])
for message in messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("سؤالت را فارسی بنویس؛ مثلاً فرصت‌های امروز را از نظر ریسک بررسی کن...")
if prompt:
    messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Gemini در حال بررسی است..."):
            try:
                answer = ask_gemini(
                    [m for m in messages[:-1]],
                    prompt,
                    st.session_state.get("gemini_snapshot"),
                )
                st.markdown(answer)
                messages.append({"role": "assistant", "content": answer})
            except Exception as exc:
                error_text = f"خطا در ارتباط با Gemini: {exc}"
                st.error(error_text)
                messages.append({"role": "assistant", "content": error_text})
    st.session_state["gemini_messages"] = messages[-24:]
