import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from config import BOT_TOKEN, DEEPSEEK_API_KEY

# تنظیمات لاگ‌گیری
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# تابع دریافت قیمت از صرافی بیت‌پین
def get_bitpin_price(currency_pair):
    url = "https://api.bitpin.ir/v1/mkt/tickers/"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            for item in results:
                if item.get("code") == currency_pair:
                    raw_price = item.get("price") or item.get("last_price")
                    if raw_price:
                        return int(float(raw_price))
    except Exception as e:
        logging.error(f"Error fetching Bitpin price: {e}")
    return None

# تابع تحلیل بازار با DeepSeek AI
def get_ai_analysis(btc, usdt, eth):
    url = "https://api.deepseek.com/v1/chat/completions"
    prompt = (
        f"شما یک تحلیلگر حرفه‌ای ارز دیجیتال هستید. قیمت‌های لحظه‌ای صرافی بیت‌پین:\n"
        f"- بیت‌کوین: {btc} تومان\n"
        f"- تتر: {usdt} تومان\n"
        f"- اتریوم: {eth} تومان\n\n"
        f"لطفاً یک تحلیل کوتاه، حرفه‌ای و پیشنهاد صریح (خرید، فروش یا صبر) به زبان فارسی ارائه دهید."
    )
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        if response.status_code == 200:
            res_data = response.json()
            choices = res_data.get("choices", [])
            if choices:
                return choices[0]["message"]["content"]
        return f"خطا در پاسخ هوش مصنوعی. کد پاسخ: {response.status_code}"
    except Exception as e:
        return f"خطای ارتباط با هوش مصنوعی: {str(e)}"

# دستور /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **سلام! ربات تریدر هوشمند پایتون فعال شد.**\n\n"
        "دستورات موجود:\n"
        "/prices - دریافت قیمت لحظه‌ای از بیت‌پین\n"
        "/analyze - تحلیل هوشمند بازار با DeepSeek"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# دستور /prices
async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc = get_bitpin_price("BTC_IRT")
    usdt = get_bitpin_price("USDT_IRT")
    eth = get_bitpin_price("ETH_IRT")
    
    prices_msg = (
        "📊 **قیمت‌های لحظه‌ای در صرافی بیت‌پین:**\n\n"
        f"₿ **بیت‌کوین:** {f'{btc:,} تومان' if btc else 'خطا'}\n"
        f"💵 **تتر:** {f'{usdt:,} تومان' if usdt else 'خطا'}\n"
        f"Ξ **اتریوم:** {f'{eth:,} تومان' if eth else 'خطا'}"
    )
    await update.message.reply_text(prices_msg, parse_mode="Markdown")

# دستور /analyze
async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 در حال استعلام قیمت‌ها و ارسال به هوش مصنوعی...")
    
    btc_val = get_bitpin_price("BTC_IRT")
    usdt_val = get_bitpin_price("USDT_IRT")
    eth_val = get_bitpin_price("ETH_IRT")
    
    if btc_val and usdt_val and eth_val:
        ai_response = get_ai_analysis(f"{btc_val:,}", f"{usdt_val:,}", f"{eth_val:,}")
        await update.message.reply_text(f"🧠 **تحلیل هوشمند بازار (DeepSeek):**\n\n{ai_response}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ خطا در دریافت اطلاعات قیمت برای انجام تحلیل.")

# اجرای اصلی ربات
if __name__ == "__main__":
    if not BOT_TOKEN or not DEEPSEEK_API_KEY:
        print("خطا: لطفاً توکن تلگرام و کلید DeepSeek را در فایل .env تنظیم کنید.")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("prices", prices_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    
    print("🤖 ربات با موفقیت شروع به کار کرد و در حال گوش دادن به پیام‌هاست...")
    app.run_polling()
