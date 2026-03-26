import os
import json
import base64
from flask import Flask, request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import requests

BOT_TOKEN = "8769439909:AAGIA8qiFuTATk5AguKnU0cKWTA8DhT0eMY"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# In-memory store for pending configs (while waiting for password)
pending = {}

def decrypt_aes_gcm(ciphertext_b64, password):
    raw = base64.b64decode(ciphertext_b64)
    if len(raw) < 28:
        raise ValueError("Invalid ciphertext")
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

def try_unencrypted(enc):
    """Attempt to decode enc as base64 of JSON (no encryption)."""
    try:
        decoded = base64.b64decode(enc).decode()
        return json.loads(decoded)
    except:
        return None

def process_darktunnel(raw, password=""):
    # Remove darktunnel:// prefix
    if raw.startswith("darktunnel://"):
        raw = raw[13:]

    # Outer base64 decode
    try:
        outer = json.loads(base64.b64decode(raw))
    except Exception as e:
        return {"error": f"Invalid outer base64: {e}"}

    enc = outer.get("encryptedLockedConfig")
    if not enc:
        return {"error": "No encryptedLockedConfig field found."}

    # Try decryption with given password
    if password:
        try:
            inner = json.loads(decrypt_aes_gcm(enc, password))
            return {"outer": outer, "inner": inner, "method": "decrypted"}
        except Exception as e:
            # Decryption failed – maybe wrong password
            pass

    # Try with empty password (if no password given)
    if not password:
        try:
            inner = json.loads(decrypt_aes_gcm(enc, ""))
            return {"outer": outer, "inner": inner, "method": "decrypted (empty password)"}
        except:
            pass

    # Try unencrypted (base64 of JSON)
    inner = try_unencrypted(enc)
    if inner is not None:
        return {"outer": outer, "inner": inner, "method": "unencrypted"}

    # If still nothing, return error
    return {"error": "Could not decrypt. Maybe it's password protected. Send the password."}

def format_result(result):
    if "error" in result:
        return f"❌ {result['error']}"
    out = f"**Outer config:**\n```json\n{json.dumps(result['outer'], indent=2)}\n```\n"
    out += f"**Decrypted inner config:**\n```json\n{json.dumps(result['inner'], indent=2)}\n```\n"
    out += f"\n*Method:* {result.get('method', 'unknown')}"
    return out

def send_message(chat_id, text):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(f"{TELEGRAM_API}/sendMessage", json=data)

@app.route("/", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return "OK", 200
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/start"):
            send_message(chat_id, "Send me a darktunnel:// URL, I'll decrypt it automatically (no password needed if unencrypted).")
        elif text.startswith("darktunnel://"):
            # First try with empty password (will also attempt unencrypted)
            result = process_darktunnel(text, "")
            if "error" in result:
                # Could not decrypt – ask for password
                pending[chat_id] = text
                send_message(chat_id, "I couldn't decrypt it automatically. Please send the password (if any).")
            else:
                send_message(chat_id, format_result(result))
        else:
            # If we are waiting for a password for this chat
            if chat_id in pending:
                config = pending.pop(chat_id)
                result = process_darktunnel(config, text)
                send_message(chat_id, format_result(result))
            else:
                send_message(chat_id, "I don't understand. Send /start for help.")
    return "OK", 200

@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    url = request.args.get("url")
    if not url:
        return "Missing url parameter", 400
    resp = requests.get(f"{TELEGRAM_API}/setWebhook?url={url}")
    return resp.text

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))