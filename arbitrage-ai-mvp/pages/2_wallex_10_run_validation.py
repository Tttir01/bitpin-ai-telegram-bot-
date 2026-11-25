import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from wallex_reconnect_batch import (
    GAP_SCHEDULE,
    clear_runs,
    import_runs_json,
    load_runs,
    next_gap_seconds,
    save_run,
    summarize_runs,
)
from wallex_rest_reconnect_diagnostic import run_rest_reconnect_convergence

st.set_page_config(page_title="آزمون ده‌مرحله‌ای والکس", page_icon="🧭", layout="wide")
st.markdown("<style>html,body,[class*='css']{direction:rtl;text-align:right}</style>", unsafe_allow_html=True)
st.title("🧭 اعتبارسنجی ده‌مرحله‌ای همگرایی والکس")
st.caption("این صفحه مستقل از اسکنر و سبد معاملات کاغذی است و فقط API عمومی REST و Centrifugo را می‌خواند.")

st.warning(
    "هر بار فقط یک آزمایش اجرا می‌شود. سوابق در SQLite محلی ذخیره می‌شوند؛ "
    "در Render رایگان ممکن است پس از راه‌اندازی مجدد یا انتشار نسخه پاک شوند."
)
st.info(
    "برای بازیابی سابقه پس از انتشار نسخه، فایل JSON گزارش قبلی را از گوشی انتخاب و وارد کنید. "
    "می‌توانید چند فایل را یکی‌یکی وارد کنید؛ رکوردهای تکراری نادیده گرفته می‌شوند و رکورد متعارض جایگزین نمی‌شود."
)

try:
    runs = load_runs()
except Exception as exc:
    st.error(f"خواندن پایگاه داده نتایج ناموفق بود: {exc}")
    st.stop()

st.subheader("بازیابی سوابق از فایل JSON")
st.markdown("اگر بارگذاری فایل در گوشی خطای شبکه داد، متن کامل فایل JSON را در کادر زیر بچسبانید.")
pasted_report = st.text_area(
    "متن کامل گزارش JSON",
    height=180,
    key="wallex_history_restore_paste",
    placeholder='{"summary": {}, "runs": [...]}',
)
if st.button(
    "بازیابی از متن چسبانده‌شده",
    disabled=not pasted_report.strip(),
    key="restore_wallex_history_paste",
):
    try:
        restore_result = import_runs_json(pasted_report)
        st.success(
            f"بازیابی انجام شد: {restore_result['imported']} رکورد اضافه شد؛ "
            f"{restore_result['skipped']} رکورد تکراری بود؛ "
            f"{restore_result['conflicts']} مورد تعارض داشت و تغییر داده نشد."
        )
        if restore_result["conflicts"]:
            st.warning("برای شماره‌های متعارض، سابقه موجود حفظ شد. فایل گزارش را نگه دارید تا مورد بررسی شود.")
        st.rerun()
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        st.error(f"متن JSON وارد نشد: {exc}")
    except Exception as exc:
        st.error(f"خطا هنگام بازیابی متن: {exc}")

uploaded_report = st.file_uploader(
    "فایل wallex_reconnect_10_run_report.json را انتخاب کنید",
    type=["json"],
    key="wallex_history_restore_upload",
)
if st.button("بازیابی و ادغام سوابق فایل", disabled=uploaded_report is None, key="restore_wallex_history"):
    try:
        restore_result = import_runs_json(uploaded_report.getvalue())
        st.success(
            f"بازیابی انجام شد: {restore_result['imported']} رکورد اضافه شد؛ "
            f"{restore_result['skipped']} رکورد تکراری بود؛ "
            f"{restore_result['conflicts']} مورد تعارض داشت و تغییر داده نشد."
        )
        if restore_result["conflicts"]:
            st.warning("برای شماره‌های متعارض، سابقه موجود حفظ شد. فایل گزارش را نگه دارید تا مورد بررسی شود.")
        st.rerun()
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        st.error(f"فایل وارد نشد: {exc}")
    except Exception as exc:
        st.error(f"خطا هنگام بازیابی سوابق: {exc}")

summary = summarize_runs(runs)
progress = min(summary["total"], len(GAP_SCHEDULE))
st.progress(progress / len(GAP_SCHEDULE), text=f"پیشرفت مجموعه: {progress} از ۱۰ آزمایش")

m1, m2, m3, m4 = st.columns(4)
m1.metric("تعداد آزمایش", f"{progress}/10")
m2.metric("همگرایی کاندید", summary["candidate"])
m3.metric("ناموفق/ناکافی", summary["failed"])
m4.metric("نرخ کاندید", f"{summary['candidate_rate_pct']:.1f}%")

restored_first_two = {int(item.get("run_number", 0)) for item in runs}.issuperset({1, 2})
if not restored_first_two:
    st.warning(
        "برای جلوگیری از جابه‌جایی شماره‌ها، اجرای آزمایش جدید تا زمان بازیابی آزمایش‌های ۱ و ۲ غیرفعال است. "
        "گزارش‌های قبلی را از گوشی وارد کنید."
    )

if progress < len(GAP_SCHEDULE):
    gap = next_gap_seconds(progress)
    st.info(f"آزمایش بعدی با وقفه عمدی {gap} ثانیه اجرا می‌شود. برنامه وقفه‌ها: ۲، ۵ و ۱۰ ثانیه، در مجموع ۱۰ بار.")
    if st.button(
        f"اجرای آزمایش شماره {progress + 1} (وقفه {gap} ثانیه)",
        type="primary",
        key="run_next_wallex_batch",
        disabled=not restored_first_two,
    ):
        with st.spinner("در حال دریافت REST، قطع کنترل‌شده و اتصال مجدد Centrifugo..."):
            try:
                result = run_rest_reconnect_convergence(gap_seconds=gap, wait_seconds=8)
                result["run_number"] = progress + 1
                result["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
                save_run(result)
                st.success("نتیجه آزمایش در SQLite ذخیره شد.")
                st.rerun()
            except Exception as exc:
                st.error(f"اجرای آزمایش یا ذخیره نتیجه ناموفق بود: {exc}")
else:
    st.success("هر ۱۰ آزمایش تکمیل شده است. نتیجه زیر فقط ارزیابی تشخیصی است و مجوز اتصال به اسکنر نیست.")

if runs:
    table = []
    for item in runs:
        comparison = item.get("post_rest_ws_comparison", {})
        table.append({
            "آزمایش": item.get("run_number"),
            "وقفه (ثانیه)": item.get("gap_seconds"),
            "نتیجه": item.get("status", "failed"),
            "خرید": comparison.get("bid", {}).get("status", "failed"),
            "فروش": comparison.get("ask", {}).get("status", "failed"),
            "تأخیر اتصال مجدد (ms)": item.get("reconnect_delay_ms"),
            "تأخیر پیام خرید (ms)": (item.get("after_reconnect_ws", {}).get("bid") or {}).get("received_after_reconnect_ms"),
            "تأخیر پیام فروش (ms)": (item.get("after_reconnect_ws", {}).get("ask") or {}).get("received_after_reconnect_ms"),
            "خطا": item.get("error", ""),
        })
    st.subheader("نتایج ذخیره‌شده آزمایش‌ها")
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.subheader("جمع‌بندی دو کانال")
    st.write({
        "تطبیق کاندید خرید": f"{summary['bid_candidate']} از {summary['total']}",
        "تطبیق کاندید فروش": f"{summary['ask_candidate']} از {summary['total']}",
        "تعداد کل موفق": summary["candidate"],
        "تعداد ناموفق یا ناکافی": summary["failed"],
    })
    for item in runs:
        label = f"آزمایش {item.get('run_number')} — {item.get('status', 'failed')} — وقفه {item.get('gap_seconds')} ثانیه"
        with st.expander(label):
            st.json(item)

    payload = json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False, indent=2)
    st.download_button(
        "📥 دریافت گزارش کامل JSON و ذخیره در گوشی",
        data=payload,
        file_name="wallex_reconnect_10_run_report.json",
        mime="application/json",
        use_container_width=True,
    )

if st.button("پاک‌کردن نتایج ذخیره‌شده و شروع مجموعه جدید", key="reset_wallex_ten_run"):
    clear_runs()
    st.rerun()

st.divider()
st.caption(
    "معیار کاندید هر آزمایش: اولین پیام معتبر پس از اتصال مجدد با snapshot جدید REST "
    "در آستانه اختلاف قیمت حداکثر ۰٫۱۰٪ و اختلاف حجم حداکثر ۲۰٪ باشد. "
    "نمونه‌های publication دریافتی نیز در تشخیص جدید ثبت می‌شوند، اما این نتیجه replay پیام‌های ازدست‌رفته، "
    "ترتیب کامل رویدادها، timestamp معتبر سمت صرافی یا snapshot بودن publication را اثبات نمی‌کند."
)
st.error(
    "قفل‌های ایمنی ثابت‌اند: scanner_feed_enabled=false، execution_allowed=false، "
    "gap_recovery_verified=false و sequence_order_verified=false. هیچ سفارش واقعی ثبت نمی‌شود."
)
