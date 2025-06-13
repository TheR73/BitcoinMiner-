import os, time, logging, smtplib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
from tinydb import TinyDB, Query
from datetime import datetime, timedelta
from email.message import EmailMessage

# — CONFIGURATION —
DB = TinyDB("data.json")
User = Query()
TOKEN = os.getenv("TELEGRAM_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
BTC_USD = 98000
BASE = 0.00000000001
AD = BASE / 2
MIN_WITHDRAW = 0.5
AD_COOLDOWN = 60  # seconds between ads

logging.basicConfig(level=logging.INFO)

def get_user(uid):
    user = DB.get(User.id == uid)
    if not user:
        user = {"id": uid, "balance_btc": 0.0, "referred_by": None,
                "referrals": [], "ref_earn": 0.0,
                "session_end": None, "last_ad": 0}
        DB.insert(user)
    return user

def upd_user(uid, **kwargs):
    DB.update(kwargs, User.id == uid)

def send_email(subject, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, EMAIL_USER, EMAIL_USER
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg)

def credit(uid, btc):
    u = get_user(uid)
    u["balance_btc"] += btc
    DB.update({"balance_btc": u["balance_btc"]}, User.id == uid)

def fmt(btc):
    usd = btc * BTC_USD
    return f"{btc:.12f} BTC (~${usd:.4f})"

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args
    u = get_user(uid)
    if args:
        ref = int(args[0])
        if ref != uid and not u["referred_by"]:
            upd_user(uid, referred_by=ref)
            ref_user = get_user(ref)
            ref_user["referrals"].append(uid)
            DB.write()
    menu = "Commands:\n/help\n/mine\n/ad\n/balance\n/withdraw\n/referral\n/referstats"
    await update.message.reply_text("Welcome! " + menu)

async def help_cmd(update, ctx): await start(update, ctx)

async def mine(update, ctx):
    u = get_user(update.effective_user.id)
    now = datetime.utcnow()
    if u["session_end"] and now < datetime.fromisoformat(u["session_end"]):
        remaining = datetime.fromisoformat(u["session_end"]) - now
        await update.message.reply_text(f"⏳ Mining active: {remaining} left. Use /ad.")
    else:
        end = (now + timedelta(hours=8)).isoformat()
        upd_user(u["id"], session_end=end)
        credit(u["id"], BASE)
        await update.message.reply_text("⛏ Mining started! BASE credited. /ad to boost.")

async def ad(update, ctx):
    u = get_user(update.effective_user.id)
    now_ts = time.time()
    if not u["session_end"] or now_ts > datetime.fromisoformat(u["session_end"]).timestamp():
        return await update.message.reply_text("No active session. Use /mine.")
    if now_ts - u["last_ad"] < AD_COOLDOWN:
        return await update.message.reply_text("⏱ Please wait before next ad.")
    credit(u["id"], AD)
    upd_user(u["id"], last_ad=now_ts)
    await update.message.reply_text("🎥 Ad watched! AD credited.")

async def balance(update, ctx):
    btc = get_user(update.effective_user.id)["balance_btc"]
    await update.message.reply_text("Balance: " + fmt(btc))

async def referral(update, ctx):
    uid = update.effective_user.id
    code = f"{uid}"
    await update.message.reply_text(f"Share this link:\nhttps://t.me/{ctx.bot.username}?start={code}\n10% bonus from referrals.")

async def referstats(update, ctx):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(f"Refs: {len(u['referrals'])}\nBTC from refs: {fmt(u['ref_earn'])}")

async def withdraw(update, ctx):
    await update.message.reply_text("Send amount and BTC address like:\n0.75 1A1zP1...")

async def handle_msg(update, ctx):
    parts = update.message.text.split()
    if len(parts) != 2: return
    try:
        amt = float(parts[0])
    except:
        return await update.message.reply_text("❗ Invalid format.")
    addr = parts[1]
    if amt < MIN_WITHDRAW:
        return await update.message.reply_text("⚠️ Minimum withdrawal is $0.50.")
    btc_amt = amt / BTC_USD
    fee = 0.1 * amt if amt < 20 else 1 + 0.1 * amt
    recv = amt - fee
    uid = update.effective_user.id
    u = get_user(uid)
    if u["balance_btc"] * BTC_USD < amt:
        return await update.message.reply_text("Insufficient balance.")
    u["balance_btc"] -= btc_amt
    DB.update({"balance_btc": u["balance_btc"]}, User.id == uid)
    send_email("Withdrawal", f"user:{uid}\n{amt}$ → {addr}\nFee:{fee}, receives:{recv}")
    await update.message.reply_text(f"✅ Withdrawal submitted!\nFee=${fee:.2f}, you get ${recv:.2f}.")

app = ApplicationBuilder().token(TOKEN).build()
handlers = [
    CommandHandler("start", start),
    CommandHandler("help", help_cmd),
    CommandHandler("mine", mine),
    CommandHandler("ad", ad),
    CommandHandler("balance", balance),
    CommandHandler("referral", referral),
    CommandHandler("referstats", referstats),
    CommandHandler("withdraw", withdraw),
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg),
]
for h in handlers:
    app.add_handler(h)

app.run_polling()
