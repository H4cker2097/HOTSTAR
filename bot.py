import os
import re
import logging
from datetime import datetime, timezone
import telebot
from telebot import types
from database import init_db, create_order, get_order, list_orders, update_order_status, save_screenshot
from payment_provider import verify_payment_for_order, ProviderNotConfigured

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("hotstar_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HOTSTAR_CHECKOUT_URL = os.getenv("HOTSTAR_CHECKOUT_URL", "https://www.hotstar.com/in/")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Set it in your deployment environment.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
init_db()

# Minimal in-memory conversation state. Orders themselves are persisted in the database.
pending_mobile = {}


def is_admin(user_id):
    return user_id in ADMIN_IDS


def mask_mobile(value):
    digits = re.sub(r"\D", "", value or "")
    return ("*" * max(0, len(digits) - 4)) + digits[-4:]


def order_keyboard(order_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Open official Hotstar", url=HOTSTAR_CHECKOUT_URL))
    kb.add(types.InlineKeyboardButton("Submit payment screenshot", callback_data=f"shot:{order_id}"))
    kb.add(types.InlineKeyboardButton("Check payment status", callback_data=f"status:{order_id}"))
    kb.add(types.InlineKeyboardButton("Cancel order", callback_data=f"cancel:{order_id}"))
    return kb


@bot.message_handler(commands=["start", "help"])
def start(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Activate JioHotstar", callback_data="new_order"))
    bot.send_message(
        message.chat.id,
        "Welcome! This bot assists with the official Hotstar checkout.\\n\\n"
        "You will enter your login OTP directly on the official Hotstar website. "
        "Never send your OTP, password, or session cookies to this bot.\\n\\n"
        "Payment screenshots are for review only; payment is confirmed only by an authorized provider.",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: c.data == "new_order")
def new_order_callback(call):
    pending_mobile[call.from_user.id] = True
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Enter your mobile number (including country code if needed).")


@bot.message_handler(func=lambda m: bool(m.from_user and pending_mobile.get(m.from_user.id)))
def receive_mobile(message):
    mobile = re.sub(r"\s+", "", message.text or "")
    if not re.fullmatch(r"\+?[0-9]{8,15}", mobile):
        bot.reply_to(message, "That number format doesn't look valid. Please enter 8–15 digits, optionally starting with +.")
        return
    pending_mobile.pop(message.from_user.id, None)
    order_id = create_order(message.from_user.id, mobile)
    bot.send_message(
        message.chat.id,
        f"Order created: <code>{order_id}</code>\\n"
        "1. Open the official checkout below.\\n"
        "2. Complete login and OTP verification on Hotstar itself.\\n"
        "3. Complete payment only if you agree to the displayed terms and amount.\\n"
        "4. Return here to submit a payment screenshot if needed.\\n\\n"
        "A screenshot does not prove payment; the payment provider must confirm it.",
        reply_markup=order_keyboard(order_id),
    )
    notify_admins(f"New order <code>{order_id}</code>; mobile {mask_mobile(mobile)}; Telegram user {message.from_user.id}.")


@bot.callback_query_handler(func=lambda c: c.data.startswith(("shot:", "status:", "cancel:")))
def order_action(call):
    action, order_id = call.data.split(":", 1)
    order = get_order(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
        return
    if order["telegram_user_id"] != call.from_user.id and not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "This order does not belong to you.", show_alert=True)
        return

    if action == "shot":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"Send a screenshot/photo for order <code>{order_id}</code> now.")
    elif action == "status":
        bot.answer_callback_query(call.id)
        try:
            result = verify_payment_for_order(order)
            if result["verified"]:
                update_order_status(order_id, "PAYMENT_VERIFIED", provider_txn_id=result.get("transaction_id"))
                bot.send_message(call.message.chat.id, f"Payment verified for order <code>{order_id}</code>. Activation still requires separate confirmation.")
            else:
                bot.send_message(call.message.chat.id, f"Payment status: <b>{result['status']}</b>. {result.get('message', '')}")
        except ProviderNotConfigured:
            bot.send_message(call.message.chat.id, "Automatic payment verification is not configured yet. Your order remains pending; an admin can review it.")
    elif action == "cancel":
        if order["status"] in ("PAYMENT_VERIFIED", "ACTIVATION_CONFIRMED"):
            bot.answer_callback_query(call.id, "A verified order cannot be cancelled here.", show_alert=True)
            return
        update_order_status(order_id, "CANCELLED")
        bot.answer_callback_query(call.id, "Order cancelled.")
        bot.send_message(call.message.chat.id, f"Order <code>{order_id}</code> was cancelled.")


@bot.message_handler(content_types=["photo", "document"])
def receive_screenshot(message):
    order_id = None
    # User must reply to the bot's screenshot request and include the order ID, or send /upload ORDER_ID first.
    if message.reply_to_message and message.reply_to_message.text:
        match = re.search(r"([A-Z0-9]{8,})", message.reply_to_message.text)
        if match:
            order_id = match.group(1)
    if not order_id:
        bot.reply_to(message, "Please identify the order first using /upload ORDER_ID, then send the screenshot.")
        return
    order = get_order(order_id)
    if not order or (order["telegram_user_id"] != message.from_user.id and not is_admin(message.from_user.id)):
        bot.reply_to(message, "Order not found or not yours.")
        return
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    save_screenshot(order_id, message.from_user.id, file_id)
    update_order_status(order_id, "PAYMENT_PENDING")
    bot.reply_to(message, f"Screenshot received for <code>{order_id}</code>. It is evidence for review, not payment confirmation.")
    notify_admins(
        f"Screenshot submitted for <code>{order_id}</code> by user {message.from_user.id}. "
        f"Use /order {order_id} and verify against the payment provider."
    )


@bot.message_handler(commands=["upload"])
def upload_command(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /upload ORDER_ID")
        return
    order_id = parts[1].strip()
    order = get_order(order_id)
    if not order or (order["telegram_user_id"] != message.from_user.id and not is_admin(message.from_user.id)):
        bot.reply_to(message, "Order not found or not yours.")
        return
    bot.reply_to(message, f"Now send the screenshot for order <code>{order_id}</code>.")


@bot.message_handler(commands=["admin"])
def admin_home(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    bot.reply_to(message, "Admin commands: /orders, /order ORDER_ID, /verify ORDER_ID, /paid ORDER_ID, /activation ORDER_ID confirmed|failed")


@bot.message_handler(commands=["orders"])
def admin_orders(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    rows = list_orders(20)
    if not rows:
        bot.reply_to(message, "No orders yet.")
        return
    lines = [f"<code>{o['order_id']}</code> — {o['status']} — user {o['telegram_user_id']} — {mask_mobile(o['mobile'])}" for o in rows]
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["order"])
def admin_order(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /order ORDER_ID")
        return
    order = get_order(parts[1].strip())
    if not order:
        bot.reply_to(message, "Order not found.")
        return
    bot.reply_to(message, f"Order <code>{order['order_id']}</code>\nStatus: {order['status']}\nMobile: {mask_mobile(order['mobile'])}\nUser: {order['telegram_user_id']}\nProvider transaction: {order.get('provider_txn_id') or 'not recorded'}")


@bot.message_handler(commands=["verify"])
def admin_verify(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /verify ORDER_ID")
        return
    order = get_order(parts[1].strip())
    if not order:
        bot.reply_to(message, "Order not found.")
        return
    try:
        result = verify_payment_for_order(order)
    except ProviderNotConfigured:
        bot.reply_to(message, "Payment provider is not configured. No payment has been marked verified.")
        return
    if result["verified"]:
        update_order_status(order["order_id"], "PAYMENT_VERIFIED", provider_txn_id=result.get("transaction_id"))
        bot.reply_to(message, f"Provider verified payment for {order['order_id']}. Activation remains separate.")
        safe_send(order["telegram_user_id"], f"Payment verified for order <code>{order['order_id']}</code>. Activation is not yet confirmed.")
    else:
        bot.reply_to(message, f"Not verified: {result['status']} — {result.get('message', '')}")


@bot.message_handler(commands=["paid"])
def admin_paid(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    bot.reply_to(message, "Use /verify ORDER_ID for provider verification. This bot does not allow manual screenshot-only payment confirmation.")


@bot.message_handler(commands=["activation"])
def admin_activation(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Unauthorized.")
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or parts[2] not in ("confirmed", "failed"):
        bot.reply_to(message, "Usage: /activation ORDER_ID confirmed|failed")
        return
    order = get_order(parts[1])
    if not order or order["status"] != "PAYMENT_VERIFIED":
        bot.reply_to(message, "Order must have provider-verified payment before activation status can be updated.")
        return
    new_status = "ACTIVATION_CONFIRMED" if parts[2] == "confirmed" else "ACTIVATION_FAILED"
    update_order_status(order["order_id"], new_status)
    safe_send(order["telegram_user_id"], f"Activation status for order <code>{order['order_id']}</code>: <b>{new_status}</b>.")


def safe_send(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception:
        log.exception("Failed to notify chat %s", chat_id)


def notify_admins(text):
    for admin_id in ADMIN_IDS:
        safe_send(admin_id, text)


if __name__ == "__main__":
    log.info("Starting Telegram bot polling")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
