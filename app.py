import os
import json
import base64
from flask import Flask, request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import requests

# ---------- YOUR BOT TOKEN (hardcoded) ----------
BOT_TOKEN = "8769439909:AAGIA8qiFuTATk5AguKnU0cKWTA8DhT0eMY"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# In-memory store for pending configs (simple, fine for demo)
pending = {}

def decrypt_aes_gcm(ciphertext_b64, password):
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

def try_decrypt(enc, password):
    try:
        return json.loads(decrypt_aes_gcm(enc, password))
    except Exception:
        return None

def process_darktunnel(raw, password=""):
    if raw.startswith("darktunnel://"):
        raw = raw[13:]
    try:
        outer = json.loads(base64.b64decode(raw))
    except Exception as e:
        return {"error": f"Invalid base64: {e}"}
    enc = outer.get("encryptedLockedConfig")
    if not enc:
        return {"error": "No encrypted part found."}
    inner = try_decrypt(enc, password)
    if inner is not None:
        return {"outer": outer, "inner": inner}
    # maybe unencrypted base64 of JSON
    try:
        maybe_json = base64.b64decode(enc).decode()
        inner = json.loads(maybe_json)
        return {"outer": outer, "inner": inner, "note": " (unencrypted)"}
    except:
        pass
    return {"error": "Decryption failed. Wrong password or invalid format."}

def format_result(result):
    if "error" in result:
        return f"❌ {result['error']}"
    out = "**Outer config:**\n```json\n" + json.dumps(result["outer"], indent=2) + "\n```\n"
    out += "**Decrypted inner config:**\n```json\n" + json.dumps(result["inner"], indent=2) + "\n```"
    if "note" in result:
        out += f"\n*Note:* {result['note']}"
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
            send_message(chat_id, "Send me a darktunnel:// URL, I'll decrypt it.\n\nIf it's password-protected, send the password in a second message.")
        elif text.startswith("darktunnel://"):
            result = process_darktunnel(text, "")
            if "error" not in result:
                send_message(chat_id, format_result(result))
            else:
                pending[chat_id] = text
                send_message(chat_id, "This config seems password-protected. Please send the password.")
        else:
            if chat_id in pending:
                config = pending.pop(chat_id)
                result = process_darktunnel(config, text)
                send_message(chat_id, format_result(result))
            else:
                send_message(chat_id, "I don't understand. Send /start for help.")
    return "OK", 200

# Optional: endpoint to set webhook (run once)
@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    url = request.args.get("url")
    if not url:
        return "Missing url parameter", 400
    resp = requests.get(f"{TELEGRAM_API}/setWebhook?url={url}")
    return resp.text

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))