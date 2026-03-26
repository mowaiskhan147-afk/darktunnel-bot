import base64
import json
import logging
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes, ConversationHandler
)

# ---------- Your Token ----------
BOT_TOKEN = "8769439909:AAGIA8qiFuTATk5AguKnU0cKWTA8DhT0eMY"

# Conversation states
WAITING_PASSWORD = 1

# ---------- Decryption Functions ----------
def decrypt_aes_gcm(ciphertext_b64: str, password: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    salt = raw[:16]
    iv = raw[16:28]
    ct = raw[28:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=10000,
        backend=default_backend()
    )
    key = kdf.derive(password.encode())
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return (decryptor.update(ct) + decryptor.finalize()).decode()

def try_decrypt(encrypted_part: str, password: str):
    """Try decryption; if fails, return None."""
    try:
        return json.loads(decrypt_aes_gcm(encrypted_part, password))
    except Exception:
        return None

def process_darktunnel(raw: str, password: str = "") -> dict:
    # Remove darktunnel:// prefix if present
    if raw.startswith("darktunnel://"):
        raw = raw[13:]
    try:
        outer = json.loads(base64.b64decode(raw))
    except Exception as e:
        return {"error": f"Invalid base64: {e}"}
    enc = outer.get("encryptedLockedConfig")
    if not enc:
        return {"error": "No encrypted part found."}

    # First try: decryption with given password
    inner = try_decrypt(enc, password)
    if inner is not None:
        return {"outer": outer, "inner": inner}

    # Second try: maybe it's not encrypted (just base64 of JSON)
    try:
        maybe_json = base64.b64decode(enc).decode()
        inner = json.loads(maybe_json)
        return {"outer": outer, "inner": inner, "note": " (unencrypted, no password needed)"}
    except:
        pass

    return {"error": "Decryption failed. Wrong password or invalid format."}

# ---------- Telegram Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a Dark Tunnel config (darktunnel://...)\n\n"
        "If it's password-protected, I'll ask for the password.\n"
        "If not, it will be decrypted automatically."
    )

async def handle_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("darktunnel://"):
        await update.message.reply_text("Please send a valid darktunnel:// URL.")
        return

    context.user_data["config"] = text

    # Check if we can decrypt without password (by trying empty)
    result = process_darktunnel(text, "")
    if "error" not in result:
        # Success with empty password – show result immediately
        await update.message.reply_text(format_result(result))
        return

    # Need password – ask user
    keyboard = [
        [InlineKeyboardButton("Yes, enter password", callback_data="need_pass"),
         InlineKeyboardButton("No (if it's actually unencrypted)", callback_data="no_pass")]
    ]
    await update.message.reply_text(
        "This config seems to be password-protected. Do you have the password?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_PASSWORD

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    config = context.user_data.get("config")
    if not config:
        await query.edit_message_text("No config found. Send it again.")
        return ConversationHandler.END

    if data == "need_pass":
        await query.edit_message_text("Please send the password (as plain text).")
        return WAITING_PASSWORD
    else:
        # User says no password – try empty password again (maybe they were wrong)
        result = process_darktunnel(config, "")
        await query.edit_message_text(format_result(result))
        return ConversationHandler.END

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    config = context.user_data.get("config")
    result = process_darktunnel(config, password)
    await update.message.reply_text(format_result(result))
    return ConversationHandler.END

def format_result(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    out = "**Outer config:**\n```json\n" + json.dumps(result["outer"], indent=2) + "\n```\n"
    out += "**Decrypted inner config:**\n```json\n" + json.dumps(result["inner"], indent=2) + "\n```"
    if "note" in result:
        out += f"\n*Note:* {result['note']}"
    return out

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# ---------- Main ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_config)],
        states={
            WAITING_PASSWORD: [
                CallbackQueryHandler(button_callback, pattern="^(need_pass|no_pass)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()