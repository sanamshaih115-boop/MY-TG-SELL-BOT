# tgid_sell_bot.py — CHEAPEST TG STORE  (PRO UI)
# ✦ Colored inline buttons (blue / green / red)      ✦ Colored owner reply-keyboard
# ✦ Start video (spoiler/blur) + SET VIDEO button    ✦ Video stays on top while navigating
# ✦ Tree-style blockquote font UI                    ✦ Finished messages auto-delete
#
# NOTE: colored buttons need Bot API 9.4+  ->  pip install -U pyTelegramBotAPI
#       If you ever want plain grey buttons again, set COLOR_BUTTONS = False

import os
import json
import time
import asyncio
import re
import html
import threading
import traceback
import hashlib
import functools
import logging
import requests
import qrcode
from io import BytesIO
from types import SimpleNamespace
from datetime import datetime
import telebot
from telebot import types
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# ═══════════════════════════════════════════════
#  CONFIG   (secrets ab env se aate hain — code me mat likho)
# ═══════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "9276909665:AAH1jssA38VqIu-BaQKUm7mbGzdwdx8qhwQ")
OWNER_ID  = int(os.getenv("OWNER_ID", "8688528943"))
API_ID    = int(os.getenv("API_ID", "37156808"))
API_HASH  = os.getenv("API_HASH", "fdeb8f4bd514c6c461f1390eb5187467")
DEFAULT_2FA = "7777"
BRAND = "ZX Telegram Store 🏪"
PER_PAGE = 20
COLOR_BUTTONS = True
# ═══════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")])
log = logging.getLogger("tgidstore")

DB_FILE = "tgid_data.json"
SESSIONS_DIR = "tgid_sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True, num_threads=8)
db_lock = threading.RLock()
PENDING_ADMIN = {}
PENDING_DEPOSIT = {}
PROMPTS = {}        # chat_id -> [prompt message ids]  (flow ke baad delete honge)
KB_MSG = {}        # chat_id -> keyboard wale msg ka id
LAST_UI = {}        # chat_id -> current main UI message id
MEDIA_MSGS = set()  # (chat_id, message_id) jo video/animation caption wale hain

API_CACHE = {
    "phishing": {}, "good": {}, "scam": {},
    "phishing_countries": {}, "good_countries": {}, "scam_countries": {},
    "last_sync": 0, "last_error": "", "raw_response": None
}

# ═══════════════════════════════════════════════
#  DEFAULT DATA
# ═══════════════════════════════════════════════
DEFAULT_DATA = {
    "users": {}, "orders": {}, "payments": {},
    "next_oid": 1001, "next_pid": 1,
    "manual": {"scam_fake": {}, "channels": {}},
    "categories": {},
    "settings": {
        "upi_id": "nazra.bano@fam",
        "upi_name": "NAZRA BANO",
        "support": "@FREECOSTOFSERCH",
        "channel": "https://t.me/+gsRocKN1f7o2NGI1",
        "min_deposit": 20,
        "start_video": "true",
        "start_video_type": "video",
        "api_mode": {"enabled": False, "api_url": "", "api_key": "", "sync_interval": 60}
    }
}

# ═══════════════════════════════════════════════
#  STORAGE
# ═══════════════════════════════════════════════
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return json.loads(json.dumps(DEFAULT_DATA))
                for k, v in DEFAULT_DATA.items():
                    if k not in data: data[k] = v
                for sk, sv in DEFAULT_DATA["settings"].items():
                    if sk not in data.get("settings", {}):
                        data.setdefault("settings", {})[sk] = sv
                for ak, av in DEFAULT_DATA["settings"]["api_mode"].items():
                    if ak not in data["settings"].get("api_mode", {}):
                        data["settings"].setdefault("api_mode", {})[ak] = av
                for mk, mv in DEFAULT_DATA["manual"].items():
                    if mk not in data.get("manual", {}):
                        data.setdefault("manual", {})[mk] = mv
                return data
        except Exception as e:
            print(f"[DB] {e}")
    return json.loads(json.dumps(DEFAULT_DATA))

def save_db(d):
    with db_lock:
        try:
            tmp = DB_FILE + ".tmp"
            with open(tmp, "w") as f: json.dump(d, f, indent=2)
            os.replace(tmp, DB_FILE)
        except Exception as e: print(f"[DB save] {e}")

def get_user(db, uid):
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = {"name": "", "balance": 0, "total_spent": 0, "purchases": [],
                            "banned": False, "joined": datetime.now().isoformat()}
        save_db(db)
    return db["users"][uid]

def is_owner(uid):
    try: return int(uid) == int(OWNER_ID)
    except: return False

def session_path(phone):
    return os.path.join(SESSIONS_DIR, phone.replace("+", "").replace(" ", ""))

def safe_str(v):
    try: return str(v)
    except: return ""
def safe_int(v, default=0):
    try: return int(v)
    except:
        try: return int(float(v))
        except: return default
def safe_float(v, default=0.0):
    try: return float(v)
    except: return default

def esc(v):
    return html.escape(safe_str(v))

def money(x):
    try: return f"{float(x):.2f}".rstrip("0").rstrip(".")
    except: return "0"

# ─── ꜱᴍᴀʟʟ-ᴄᴀᴘꜱ font (ᴍɪꜱꜱ ᴄʜᴜᴛᴋɪ style) — poore bot me ───
_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))
_SC_SKIP = re.compile(r"(<code>.*?</code>|<[^>]+>|&[#\w]+;)", re.S)

def sc(text):
    """Text ko small-caps me badlo. HTML tags, <code> (OTP/number/UPI) aur &entities ko nahi chhedta."""
    parts = _SC_SKIP.split(str(text))
    return "".join(p if i % 2 else "".join(_SC.get(ch.lower(), ch) for ch in p)
                   for i, p in enumerate(parts))

# ═══════════════════════════════════════════════
#  🎨 UI KIT — colored buttons + tree font panels
# ═══════════════════════════════════════════════
def _auto_style(text, cb=None):
    """Har button colored. Back/Main Menu = red, nav/page = blue, baaki text se."""
    t = (text or "").upper()
    if cb == "noop": return "primary"
    if "BACK" in t or "MAIN MENU" in t: return "danger"
    if any(w in t for w in ("PREV", "NEXT", "⬅️", "➡️")): return "primary"
    if any(w in t for w in ("CANCEL", "REJECT", "LOGOUT", "DELETE", "REMOVE", "🗑", "❌", "BROADCAST", "SCAM")):
        return "danger"
    if any(w in t for w in ("CONFIRM", "APPROVE", "PAID", "ADD", "SET", "BUY", "JOIN", "OPEN", "OTP", "SYNC", "✅")):
        return "success"
    return "primary"

class IB(types.InlineKeyboardButton):
    """Colored inline button. style: primary(blue) | success(green) | danger(red) | auto/None = text se auto."""
    def __init__(self, text, callback_data=None, url=None, style="auto", **kw):
        super().__init__(text=sc(text), callback_data=callback_data, url=url, **kw)
        self.style = _auto_style(text, callback_data) if style in ("auto", None) else style
    def to_dict(self):
        d = super().to_dict()
        if COLOR_BUTTONS and self.style: d["style"] = self.style
        return d

class RB(types.KeyboardButton):
    """Colored reply-keyboard button."""
    def __init__(self, text, style="auto", **kw):
        super().__init__(sc(text), **kw)
        self.style = _auto_style(text) if style in ("auto", None) else style
    def to_dict(self):
        d = super().to_dict()
        if COLOR_BUTTONS and self.style: d["style"] = self.style
        return d

def spaced(t):
    return "  ".join(" ".join(w) for w in str(t).upper().split())

def panel(title, rows, emoji="💎", expandable=False):
    """
    ┌──[💎 ᴛɪᴛʟᴇ]
    │
    ├──⇒ 🔒 ʀᴏᴡ
    └──⇒ 👇 ʟᴀꜱᴛ ʀᴏᴡ
    rows: str | (emoji, text) | None (blank line)
    """
    lines = [f"┌──[{emoji} {title}]", "│"]
    last = max((i for i, r in enumerate(rows) if r is not None), default=-1)
    for i, r in enumerate(rows):
        if r is None:
            lines.append("│"); continue
        txt = f"{r[0]} {r[1]}" if isinstance(r, tuple) else str(r)
        lines.append(("└" if i == last else "├") + "──⇒ " + txt)
    body = sc("\n".join(lines))
    tag = "<blockquote expandable>" if expandable else "<blockquote>"
    return f"{tag}{body}</blockquote>"

def back_kb(cb="back_main", label="⬅️ Back"):
    kb = types.InlineKeyboardMarkup()
    kb.row(IB(label, callback_data=cb, style=None))
    return kb

def ans(call, text=None, alert=False):
    if str(call.id) == "0":   # bottom keyboard se aaya (asli callback nahi)
        if text and alert: toast(call.message.chat.id, f"⚠️ {esc(text)}", 3)
        return
    try: bot.answer_callback_query(call.id, text, show_alert=alert)
    except Exception: pass

# ─── short ids (Telegram callback_data max 64 bytes) ───
def hid(k):
    """Kisi bhi lambe key ka chhota stable id (callback_data limit se bachne ke liye)."""
    return hashlib.md5(str(k).encode("utf-8")).hexdigest()[:10]

def unhid(keys, h):
    for k in keys:
        if hid(k) == h: return k
    return None

def fix_url(u, default="https://t.me"):
    """Galat link se button poora fail na ho."""
    u = (u or "").strip()
    if not u: return default
    if u.startswith("@"): return "https://t.me/" + u[1:]
    if re.match(r"^(t|telegram)\.me/", u): return "https://" + u
    if not re.match(r"^(https?|tg)://", u): return "https://" + u
    return u

def is_banned(uid):
    try: return bool(load_db()["users"].get(str(uid), {}).get("banned"))
    except Exception: return False

def notify_owner(text):
    try: bot.send_message(OWNER_ID, text)
    except Exception as e: log.warning(f"notify_owner: {e}")

# ─── callback handler wrapper: ban check + double-tap lock + error safety ───
LOCKED_PREFIXES = ("buyacc_", "scambuy_", "chanbuy_", "rs_buy_", "pay_ap_", "pay_rj_", "logoutyes_")
USER_LOCKS = {}

def cbh(**kw):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(call):
            uid = call.from_user.id
            if not is_owner(uid) and is_banned(uid):
                ans(call, "🚫 You are banned", True); return
            lock = None
            if str(call.data or "").startswith(LOCKED_PREFIXES):
                lock = USER_LOCKS.setdefault(uid, threading.Lock())
                if not lock.acquire(blocking=False):
                    ans(call, "⏳ Please wait"); return
            try:
                return fn(call)
            except Exception as e:
                log.exception(f"callback {call.data}: {e}")
                ans(call, "⚠️ Error, try again", True)
            finally:
                if lock: lock.release()
        return bot.callback_query_handler(**kw)(wrapper)
    return deco

# ─── safe money / order helpers (db lock ke andar) ───
def reserve_balance(uid, price):
    with db_lock:
        db = load_db(); u = get_user(db, uid)
        if u["balance"] < price: return False, u["balance"]
        u["balance"] -= price; save_db(db)
        return True, u["balance"]

def refund_balance(uid, price):
    with db_lock:
        db = load_db(); get_user(db, uid)["balance"] += price; save_db(db)

def record_order(uid, price, phone, label, source, twofa=None):
    """Balance pehle se kat chuka hota hai. Order + user stats save karta hai."""
    uid = str(uid)
    with db_lock:
        db = load_db(); u = get_user(db, uid)
        u["total_spent"] = u.get("total_spent", 0) + price
        u.setdefault("purchases", []).append(phone)
        oid = str(db["next_oid"]); db["next_oid"] += 1
        db["orders"][oid] = {"oid": oid, "uid": uid, "country": label, "phone": phone, "price": price,
                             "2fa": twofa or DEFAULT_2FA, "time": datetime.now().isoformat(), "source": source}
        save_db(db)
        bal = u["balance"]
    notify_owner(panel("NEW ORDER", [("🆔", f"<code>{oid}</code>"), ("👤", f"<code>{uid}</code>"),
                                     ("📱", esc(label)), ("💰", f"₹{money(price)}")], emoji="🛒"))
    return oid, bal

def stock_phone(entry):
    return safe_str(entry.get("phone")) if isinstance(entry, dict) else safe_str(entry)

def stock_2fa(entry):
    return (entry.get("twofa") if isinstance(entry, dict) else None) or DEFAULT_2FA

# ─── message cleaning helpers ───
def safe_delete(chat_id, mid):
    try: bot.delete_message(chat_id, mid)
    except Exception: pass

def toast(chat_id, text, ttl=4, kb=None):
    """Chhota status msg — kuch sec baad khud delete."""
    try:
        m = bot.send_message(chat_id, sc(text), reply_markup=kb)
        threading.Timer(ttl, safe_delete, (chat_id, m.message_id)).start()
        return m
    except Exception: return None

def ask(chat_id, text, handler, kb=None):
    """Prompt bhejo + next step register. Flow khatam hote hi clean() se delete."""
    msg = bot.send_message(chat_id, text, reply_markup=kb)
    PROMPTS.setdefault(chat_id, []).append(msg.message_id)
    bot.register_next_step_handler(msg, handler)
    return msg

def clean(message):
    """Saare prompts + user ka reply delete."""
    cid = message.chat.id
    for mid in PROMPTS.pop(cid, []): safe_delete(cid, mid)
    safe_delete(cid, message.message_id)

def abort_admin(uid):
    data = PENDING_ADMIN.pop(uid, None)
    if data and data.get("client"):
        try: data["loop"].run_until_complete(data["client"].disconnect())
        except Exception: pass

def step_guard(message):
    """True => flow stop (cancel ya owner keyboard ka button dabaya)."""
    txt = (message.text or "").strip()
    if txt.lower() == "cancel" or txt == sc("cancel") or txt in ALL_BTNS:
        clean(message)
        uid = message.from_user.id
        abort_admin(uid); PENDING_DEPOSIT.pop(uid, None)
        if txt in ALL_BTNS: kb_router(message)
        else: toast(message.chat.id, panel("CANCELLED", [("❌", "ACTION STOPPED")]), 3)
        return True
    return False

def retry(message, handler, text):
    clean(message)
    ask(message.chat.id, text, handler)

# ─── main UI send / edit (video upar rehta hai) ───
def send_ui(chat_id, text, kb=None):
    """Naya UI msg: start video (spoiler) + caption. Purana UI msg delete."""
    prev = LAST_UI.pop(chat_id, None)
    if prev: safe_delete(chat_id, prev)
    s = load_db()["settings"]
    vid, vtype = s.get("start_video"), s.get("start_video_type", "video")
    msg = None
    if vid:
        try:
            if vtype == "animation":
                msg = bot.send_animation(chat_id, vid, caption=text, reply_markup=kb, has_spoiler=True)
            else:
                msg = bot.send_video(chat_id, vid, caption=text, reply_markup=kb, has_spoiler=True)
            MEDIA_MSGS.add((chat_id, msg.message_id))
        except TypeError:
            try:
                msg = (bot.send_animation if vtype == "animation" else bot.send_video)(
                    chat_id, vid, caption=text, reply_markup=kb)
                MEDIA_MSGS.add((chat_id, msg.message_id))
            except Exception as e: print(f"[video] {e}"); msg = None
        except Exception as e:
            print(f"[video] {e}"); msg = None
    if msg is None:
        msg = bot.send_message(chat_id, text, reply_markup=kb)
    LAST_UI[chat_id] = msg.message_id
    return msg

def drop_ui(chat_id):
    """Jis UI msg ka kaam ho gaya use delete karo."""
    mid = LAST_UI.pop(chat_id, None)
    if mid: safe_delete(chat_id, mid)

def edit_ui(text, chat_id, message_id, reply_markup=None):
    """bot.edit_message_text jaisa, par video/photo wale msg me caption edit karta hai (video hat'ta nahi)."""
    key = (chat_id, message_id)
    order = ["caption", "text"] if key in MEDIA_MSGS else ["text", "caption"]
    for mode in order:
        try:
            if mode == "text":
                r = bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
                MEDIA_MSGS.discard(key)
            else:
                r = bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id,
                                             reply_markup=reply_markup)
                MEDIA_MSGS.add(key)
            return r
        except Exception as e:
            if "not modified" in str(e).lower(): return None
    # dono fail (msg purana/deleted) -> naya UI bhej do
    return send_ui(chat_id, text, reply_markup)

# ═══════════════════════════════════════════════
#  QR
# ═══════════════════════════════════════════════
def make_upi_qr(upi_id, name, amount=None):
    try:
        if amount:
            upi_uri = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
        else:
            upi_uri = f"upi://pay?pa={upi_id}&pn={name}&cu=INR"
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(upi_uri); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return buf
    except: return None

# ═══════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════
def api_request(url, headers, method="GET", payload=None, timeout=10):
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=timeout)
        else:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        return r.status_code, r.text
    except Exception as e: return None, str(e)

def api_get_stock():
    db = load_db()
    api = db["settings"].get("api_mode", {})
    if not api.get("enabled") or not api.get("api_url") or not api.get("api_key"):
        return None
    base = api["api_url"].rstrip("/")
    if base.endswith("/api"): base = base[:-4]
    key = api["api_key"]
    endpoints = [f"{base}/api/stock", f"{base}/api/categories", f"{base}/stock"]
    auth_variants = [
        {"X-API-Key": key, "Accept": "application/json"},
        {"Authorization": f"Bearer {key}", "Accept": "application/json"},
    ]
    for url in endpoints:
        for headers in auth_variants:
            status, text = api_request(url, headers, "GET")
            if status == 200:
                try:
                    data = json.loads(text)
                    if data and isinstance(data, (list, dict)):
                        API_CACHE["raw_response"] = data
                        return data
                except: continue
    return None

def categorize_key(key):
    """fake/scam -> scam | no_spam/no_limit -> good | spam/limit -> phishing | baaki good"""
    k = key.lower()
    if "fake" in k or "scam" in k:
        return "scam"
    if "no_spam" in k or "nospam" in k or "no_limit" in k or "nolimit" in k:
        return "good"
    if "spam" in k or "limit" in k:
        return "phishing"
    return "good"

def sync_api_stock():
    global API_CACHE
    try:
        data = api_get_stock()
        if not data: return False

        items = None
        if isinstance(data, list): items = data
        elif isinstance(data, dict):
            for k in ["stock", "categories", "items"]:
                if k in data and isinstance(data[k], list):
                    items = data[k]; break

        if not items: return False

        phishing, good, scam = {}, {}, {}
        phishing_countries, good_countries, scam_countries = {}, {}, {}

        for item in items:
            if not isinstance(item, dict): continue

            key = safe_str(item.get("key") or item.get("id")).lower()
            if not key: continue

            country_code = safe_str(item.get("country", "unk")).lower()
            country_name = safe_str(item.get("country_name") or item.get("label", key))
            flag = safe_str(item.get("flag", ""))
            quantity = safe_int(item.get("quantity") or item.get("stock") or 0)

            price = safe_float(item.get("your_inr") or 0)
            if price <= 0:
                usd = safe_float(item.get("your_price") or 0)
                if usd > 0: price = usd * 100
            if price <= 0:
                price = safe_float(item.get("base_inr") or 0)

            display_name = f"{flag} {country_name}".strip()

            entry = {
                "key": key, "country": country_code, "country_name": country_name,
                "flag": flag, "name": display_name, "price": price, "stock": quantity
            }

            cat = categorize_key(key)
            if cat == "scam": bucket, cbucket = scam, scam_countries
            elif cat == "good": bucket, cbucket = good, good_countries
            else: bucket, cbucket = phishing, phishing_countries

            bucket[key] = entry
            if country_code not in cbucket:
                cbucket[country_code] = {"name": display_name, "flag": flag, "keys": [], "total_stock": 0}
            cbucket[country_code]["keys"].append(key)
            cbucket[country_code]["total_stock"] += quantity

        API_CACHE["phishing"] = phishing
        API_CACHE["good"] = good
        API_CACHE["scam"] = scam
        API_CACHE["phishing_countries"] = phishing_countries
        API_CACHE["good_countries"] = good_countries
        API_CACHE["scam_countries"] = scam_countries
        API_CACHE["last_sync"] = time.time()
        API_CACHE["last_error"] = ""
        print(f"[API] Phishing={len(phishing)}, Good={len(good)}, Scam={len(scam)}")
        return True
    except Exception as e:
        print(f"[API] {e}"); traceback.print_exc()
        API_CACHE["last_error"] = str(e)[:150]
        return False

def api_sync_loop():
    while True:
        try:
            db = load_db()
            if db["settings"].get("api_mode", {}).get("enabled"):
                sync_api_stock()
        except Exception as e: print(f"[sync] {e}")
        try:
            interval = int(db["settings"].get("api_mode", {}).get("sync_interval", 60))
        except: interval = 60
        time.sleep(max(30, interval))

def api_buy_account(key):
    db = load_db()
    api = db["settings"].get("api_mode", {})
    if not api.get("enabled"): return None, "API off"
    base = api["api_url"].rstrip("/")
    if base.endswith("/api"): base = base[:-4]
    api_key = api["api_key"]
    endpoints = [f"{base}/api/buy", f"{base}/api/purchase", f"{base}/api/order", f"{base}/buy"]
    auth_variants = [
        {"X-API-Key": api_key, "Content-Type": "application/json"},
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    ]
    payloads = [{"key": key, "quantity": 1}, {"key": key}, {"category": key, "quantity": 1}]
    for url in endpoints:
        for headers in auth_variants:
            for payload in payloads:
                status, text = api_request(url, headers, "POST", payload, timeout=15)
                if status == 200:
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            acc = (data.get("account") or data.get("phone") or
                                   data.get("number") or data.get("data"))
                            if acc:
                                if isinstance(acc, dict):
                                    return safe_str(acc.get("phone") or acc.get("number")), None
                                return safe_str(acc), None
                    except: pass
    return None, "Buy failed"

# ═══════════════════════════════════════════════
#  OTP
# ═══════════════════════════════════════════════
def fetch_otp_sync(phone, timeout=10, retries=3):
    path = session_path(phone)
    if not os.path.exists(path + ".session"):
        return None, "Session missing"
    async def _f():
        client = TelegramClient(path, API_ID, API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout)
            if not await client.is_user_authorized(): return None, "Expired"
            msgs = await asyncio.wait_for(client.get_messages(777000, limit=10), timeout=timeout)
            if not msgs: return None, "No messages"
            for pat in (r'code[:\s]+(\d{4,7})', r'login[:\s]+(\d{4,7})', r'\b(\d{5,6})\b'):
                for m in msgs:                      # msgs newest -> oldest
                    if not m.text: continue
                    match = re.search(pat, m.text, re.IGNORECASE)
                    if match: return match.group(1), None
            return None, "No OTP"
        except asyncio.TimeoutError: return None, "Timeout"
        except Exception as e: return None, str(e)[:80]
        finally:
            try: await client.disconnect()
            except: pass
    last_error = None
    for attempt in range(retries):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try: otp, error = loop.run_until_complete(_f())
            finally: loop.close()
            if otp: return otp, None
            last_error = error
            if attempt < retries - 1: time.sleep(1)
        except Exception as e:
            last_error = str(e)[:80]; time.sleep(1)
    return None, last_error or "Failed"

def logout_session(phone):
    path = session_path(phone)
    if not os.path.exists(path + ".session"): return False, "Session missing"
    async def _l():
        client = TelegramClient(path, API_ID, API_HASH)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
            return True, None
        except Exception as e: return False, str(e)[:100]
        finally:
            try: await client.disconnect()
            except: pass
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: success, error = loop.run_until_complete(_l())
        finally: loop.close()
        try:
            for ext in [".session", ".session-journal"]:
                f = path + ext
                if os.path.exists(f): os.remove(f)
        except: pass
        return success, error
    except Exception as e: return False, str(e)[:100]

# ═══════════════════════════════════════════════
#  KEYBOARDS + SCREEN TEXTS
# ═══════════════════════════════════════════════
# Owner buttons (sirf bottom keyboard me)
BTN_ADMIN  = sc("👑 Admin Panel")
BTN_HOME   = sc("🏠 Home")
BTN_SETVID = sc("🎬 Set Video")
BTN_DELVID = sc("🗑 Del Video")
BTN_ADD    = sc("➕ Add Acc")
BTN_APPR   = sc("✅ Approve")
BTN_STATS  = sc("📊 Stats")
BTN_BCAST  = sc("📢 Broadcast")
# extra admin keyboard buttons (nested keyboard UI)
BTN_BACK = sc("⬅️ Back")
A_STOCK = sc("📋 Stock");      A_SCAM = sc("⚠️ Scam/Fake");  A_CHAN = sc("📢 Channels")
A_ORD   = sc("📦 Orders");     A_SALES = sc("📈 Sales");     A_API  = sc("🔌 API")
A_CATS  = sc("📁 Cats");       A_SET = sc("⚙️ Settings")
A_ADDX  = sc("➕ Add");        A_DELX = sc("🗑 Delete")
S_TOG   = sc("🔛 Toggle");     S_SYNC = sc("🔄 Sync");       S_URL = sc("🌐 URL");  S_KEY = sc("🔑 Key")
F_UPI   = sc("📱 UPI");        F_NAME = sc("👤 Name");       F_MIN = sc("💵 Min")
F_SUP   = sc("📞 Support");    F_CHAN = sc("📢 Channel")
A_USERS = sc("👥 Users");      A_PRICE = sc("💰 Price")
U_FIND  = sc("🔍 Find");       U_BALP = sc("➕ Balance");    U_BALM = sc("➖ Balance")
U_BAN   = sc("🚫 Ban");        U_UNBAN = sc("✅ Unban")
OWNER_BTNS = {BTN_ADMIN, BTN_HOME, BTN_SETVID, BTN_DELVID, BTN_ADD, BTN_APPR, BTN_STATS, BTN_BCAST,
              BTN_BACK, A_STOCK, A_SCAM, A_CHAN, A_ORD, A_SALES, A_API, A_CATS, A_SET, A_ADDX, A_DELX,
              S_TOG, S_SYNC, S_URL, S_KEY, F_UPI, F_NAME, F_MIN, F_SUP, F_CHAN,
              A_USERS, A_PRICE, U_FIND, U_BALP, U_BALM, U_BAN, U_UNBAN}

# User buttons
U_BROWSE  = sc("🌐 Browse Accounts")
U_ADD     = sc("💳 Add Balance")
U_ORDERS  = sc("📦 My Orders")
U_PROFILE = sc("👤 My Profile")
U_SUPPORT = sc("🎧 Support")
U_CHANNEL = sc("📢 Official Channel")
U_TERMS   = sc("🧾 Terms")
USER_BTNS = {U_BROWSE, U_ADD, U_ORDERS, U_PROFILE, U_SUPPORT, U_CHANNEL, U_TERMS}
ALL_BTNS = OWNER_BTNS | USER_BTNS

# Keyboard color: "mix" = alag alag | "danger" = sab red | "primary" = sab blue | "success" = sab green
KB_COLOR = "mix"
def _kc(mix):
    return mix if KB_COLOR == "mix" else KB_COLOR

# Ek hi layout -> inline menu aur bottom keyboard dono me SAME (label + color + order)
MENU_ROWS = [
    [(U_BROWSE, "browse", "primary")],
    [(U_ADD, "add_balance", "success"), (U_ORDERS, "my_orders", "primary")],
    [(U_PROFILE, "my_profile", "primary"), (U_SUPPORT, "support", "danger")],
    [(U_CHANNEL, "official_channel", "success"), (U_TERMS, "terms", "danger")],
]

# ─── Nested bottom-keyboard menus (har menu me Back button) ───
KB_MENU = {}   # uid -> abhi kaunsa keyboard menu khula hai
BACK_TO = {"admin": "main", "scam": "admin", "chan": "admin", "cats": "admin", "api": "admin", "settings": "admin", "users": "admin"}
KB_TITLES = {"main": "MENU", "admin": "ADMIN PANEL", "scam": "SCAM / FAKE", "chan": "CHANNELS",
             "cats": "CATEGORIES", "api": "API MODE", "settings": "SETTINGS", "users": "USERS"}
KB_LAYOUTS = {
    "admin": [
        [(BTN_STATS, "primary"), (BTN_APPR, "success"), (BTN_ADD, "success")],
        [(A_STOCK, "primary"),   (BTN_SETVID, "primary"), (BTN_DELVID, "danger")],
        [(A_SCAM, "danger"),     (A_CHAN, "primary"), (A_ORD, "primary")],
        [(A_SALES, "success"),   (A_API, "primary"),  (BTN_BCAST, "danger")],
        [(A_CATS, "success"),    (A_USERS, "primary"), (A_SET, "primary")],
        [(BTN_BACK, "danger")],
    ],
    "scam":  [[(A_ADDX, "success"), (A_DELX, "danger"), (BTN_BACK, "danger")]],
    "chan":  [[(A_ADDX, "success"), (A_DELX, "danger"), (BTN_BACK, "danger")]],
    "cats":  [[(A_ADDX, "success"), (A_PRICE, "primary"), (A_DELX, "danger")], [(BTN_BACK, "danger")]],
    "users": [[(U_FIND, "primary"), (U_BALP, "success"), (U_BALM, "danger")],
              [(U_BAN, "danger"), (U_UNBAN, "success"), (BTN_BACK, "danger")]],
    "api":   [[(S_TOG, "primary"), (S_SYNC, "success"), (S_URL, "primary")],
              [(S_KEY, "primary"), (BTN_BACK, "danger")]],
    "settings": [[(F_UPI, "primary"), (F_NAME, "primary"), (F_MIN, "primary")],
                 [(F_SUP, "primary"), (F_CHAN, "primary"), (BTN_BACK, "danger")]],
}

def main_kb(uid, menu="main"):
    """Chat ke neeche colored keyboard. Owner ko Admin Panel button milta hai, usme sab kuch (Back ke sath)."""
    try: kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3, is_persistent=True)
    except TypeError: kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    if menu != "main" and is_owner(uid) and menu in KB_LAYOUTS:
        for row in KB_LAYOUTS[menu]:
            kb.row(*[RB(label, style=color) for label, color in row])
        return kb
    for row in MENU_ROWS:
        kb.row(*[RB(label, style=_kc(color)) for label, _cb, color in row])
    if is_owner(uid):
        kb.row(RB(BTN_ADMIN, style=_kc("danger")))
    return kb

def set_kb(cid, uid, menu):
    """Bottom keyboard badlo (ek chhota msg usko attach karta hai, purana msg delete)."""
    KB_MENU[uid] = menu
    old = KB_MSG.get(cid)
    km = bot.send_message(cid, panel(KB_TITLES.get(menu, "MENU"), [("⌨️", "NEECHE KE BUTTONS SE USE KARO")], emoji="⌨️"),
                          reply_markup=main_kb(uid, menu))
    KB_MSG[cid] = km.message_id
    if old: safe_delete(cid, old)

def main_menu(uid):
    """Home ke neeche inline menu — keyboard jaisa hi. Owner options isme nahi (keyboard me hain)."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    for row in MENU_ROWS:
        kb.row(*[IB(label, callback_data=cb, style=_kc(color)) for label, cb, color in row])
    return kb

def admin_menu():
    """Inline admin buttons hata diye — sab kuch bottom keyboard me hai."""
    return None

def home_text(uid):
    db = load_db()
    u = get_user(db, uid)
    return panel("CHEAPEST TG STORE", [
        ("🔐", "VERIFIED ACCOUNTS + SESSION"),
        ("⚡", "INSTANT AUTO DELIVERY"),
        ("🎧", "24/7 SUPPORT"),
        None,
        ("💰", f"BALANCE : ₹{money(u.get('balance', 0))}"),
        ("👇", "SELECT OPTION BELOW"),
    ])

def admin_text():
    db = load_db()
    api = db["settings"].get("api_mode", {})
    pending = len([p for p in db["payments"].values() if p["status"] == "pending"])
    return panel("ADMIN PANEL", [
        ("👥", f"USERS : {len(db['users'])}"),
        ("📦", f"ORDERS : {len(db['orders'])}"),
        ("💰", f"PENDING : {pending}"),
        ("🔌", f"API : {'ON ✅' if api.get('enabled') else 'OFF ❌'}"),
        ("🎬", f"START VIDEO : {'SET ✅' if db['settings'].get('start_video') else 'NOT SET ❌'}"),
        None,
        ("🔴", f"PHISHING : {len(API_CACHE['phishing'])}"),
        ("🟢", f"GOOD : {len(API_CACHE['good'])}"),
        ("⚠️", f"SCAM : {len(API_CACHE['scam'])} + {len(db['manual'].get('scam_fake', {}))}"),
        ("📢", f"CHANNELS : {len(db['manual'].get('channels', {}))}"),
    ], emoji="👑")

def stats_text():
    db = load_db()
    orders = list(db["orders"].values())
    today = datetime.now().strftime("%Y-%m-%d")
    t_orders = [o for o in orders if o.get("time", "").startswith(today)]
    total = sum(o.get("price", 0) for o in orders)
    bal = sum(u.get("balance", 0) for u in db["users"].values())
    pending = len([p for p in db["payments"].values() if p["status"] == "pending"])
    rs = sum(len(c.get("stock", [])) for c in db.get("categories", {}).values())
    banned = len([u for u in db["users"].values() if u.get("banned")])
    return panel("STATS", [
        ("👥", f"USERS : {len(db['users'])}  (🚫 {banned})"),
        ("📦", f"ORDERS : {len(orders)}  (TODAY {len(t_orders)})"),
        ("💰", f"SALES : ₹{money(total)}  (TODAY ₹{money(sum(o.get('price', 0) for o in t_orders))})"),
        ("💵", f"SYSTEM BALANCE : ₹{money(bal)}"),
        ("⏳", f"PENDING DEPOSITS : {pending}"),
        ("📁", f"READY STOCK : {rs}"),
    ], emoji="📊")

def pager_row(kb, prefix, page, total_pages):
    if total_pages > 1:
        nav = []
        if page > 0: nav.append(IB("⬅️ Prev", callback_data=f"{prefix}_pg_{page-1}", style=None))
        nav.append(IB(f"📄 {page+1}/{total_pages}", callback_data="noop", style=None))
        if page < total_pages - 1: nav.append(IB("Next ➡️", callback_data=f"{prefix}_pg_{page+1}", style=None))
        kb.row(*nav)

def build_country_grid(countries_dict, prefix, page=0, back_to="browse", style="primary"):
    """Country list, pagination, 2 columns. callback me country ka hid (short id)."""
    items = sorted(countries_dict.items(), key=lambda x: x[1].get("name", ""))
    items = [(k, v) for k, v in items if v.get("total_stock", 0) > 0]
    total = len(items)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * PER_PAGE:(page + 1) * PER_PAGE]

    kb = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for code, data in chunk:
        row.append(IB(f"{data['name']} • {data.get('total_stock', 0)}"[:40],
                      callback_data=f"{prefix}_c_{hid(code)}", style=style))
        if len(row) == 2: kb.row(*row); row = []
    if row: kb.row(*row)
    pager_row(kb, prefix, page, total_pages)
    kb.row(IB("⬅️ Back", callback_data=back_to, style=None))
    return kb, total, total_pages

def build_item_grid(items_dict, item_keys, prefix, country_code, page=0, style="success"):
    valid_keys = [k for k in item_keys if items_dict.get(k, {}).get("stock", 0) > 0]
    total = len(valid_keys)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = valid_keys[page * PER_PAGE:(page + 1) * PER_PAGE]

    kb = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for k in chunk:
        item = items_dict[k]
        label = f"{item['name']} • ₹{money(item['price'])}"
        if len(label) > 40: label = label[:37] + "..."
        row.append(IB(label, callback_data=f"{prefix}_i_{hid(k)}", style=style))
        if len(row) == 2: kb.row(*row); row = []
    if row: kb.row(*row)

    if total_pages > 1:
        nav = []
        ch = hid(country_code)
        if page > 0: nav.append(IB("⬅️", callback_data=f"{prefix}_ipg_{ch}_{page-1}", style=None))
        nav.append(IB(f"📄 {page+1}/{total_pages}", callback_data="noop", style=None))
        if page < total_pages - 1: nav.append(IB("➡️", callback_data=f"{prefix}_ipg_{ch}_{page+1}", style=None))
        kb.row(*nav)

    kb.row(IB("⬅️ Back", callback_data=f"{prefix}_pg_0", style=None))
    return kb, total_pages

def purchase_done(call, oid, phone, price, balance, source_title="PURCHASE SUCCESSFUL", twofa=None):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.row(IB("🔑 GET OTP", callback_data=f"otp_{oid}", style="success"))
    kb.row(IB("⬅️ Main Menu", callback_data="back_main", style=None))
    edit_ui(panel(source_title, [
        ("🆔", f"ORDER : <code>{oid}</code>"),
        ("📞", f"NUMBER : <code>{esc(phone)}</code>"),
        ("🔑", f"2FA : <code>{esc(twofa or DEFAULT_2FA)}</code>"),
        None,
        ("💰", f"PRICE : ₹{money(price)}"),
        ("💼", f"BALANCE : ₹{money(balance)}"),
    ], emoji="✅"), call.message.chat.id, call.message.message_id, kb)

# ═══════════════════════════════════════════════
#  START / HOME
# ═══════════════════════════════════════════════
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    try:
        cid, uid = message.chat.id, message.from_user.id
        safe_delete(cid, message.message_id)
        if not is_owner(uid) and is_banned(uid):
            toast(cid, panel("BANNED", [("🚫", "AAPKO BLOCK KIYA GAYA HAI")], emoji="🚫"), 6); return
        db = load_db()
        u = get_user(db, uid)
        u["name"] = message.from_user.first_name or ""
        save_db(db)
        # bottom keyboard: ek chhota msg chahiye jo keyboard attach kare (ise delete NAHI karte)
        KB_MENU[uid] = "main"
        old_kb = KB_MSG.get(cid)
        km = bot.send_message(cid, panel("MENU READY", [("⌨️", "NEECHE KE BUTTONS SE USE KARO")], emoji="⌨️"),
                              reply_markup=main_kb(uid))
        KB_MSG[cid] = km.message_id
        if old_kb: safe_delete(cid, old_kb)
        send_ui(cid, home_text(uid), main_menu(uid))
    except Exception as e: log.exception(f"[start] {e}")

@cbh(func=lambda c: c.data == "back_main")
def cb_back_main(call):
    try:
        cid, mid = call.message.chat.id, call.message.message_id
        want_media = bool(load_db()["settings"].get("start_video"))
        is_media = call.message.content_type in ("video", "animation")
        if want_media == is_media:
            edit_ui(home_text(call.from_user.id), cid, mid, main_menu(call.from_user.id))
        else:  # QR photo / purana text msg -> delete karke video wala home
            safe_delete(cid, mid)
            send_ui(cid, home_text(call.from_user.id), main_menu(call.from_user.id))
        ans(call)
    except Exception as e:
        print(f"[back_main] {e}"); ans(call)

# ═══════════════════════════════════════════════
#  BROWSE
# ═══════════════════════════════════════════════
def ready_stock_cats():
    """Admin ne jo categories (price + stock) banayi hain — jo bik sakti hain."""
    cats = load_db().get("categories", {})
    return {k: v for k, v in cats.items() if v.get("stock") and safe_float(v.get("price")) > 0}

@cbh(func=lambda c: c.data == "browse")
def cb_browse(call):
    cnt = lambda d: len([c for c in d.values() if c.get("total_stock", 0) > 0])
    p_count, g_count = cnt(API_CACHE["phishing_countries"]), cnt(API_CACHE["good_countries"])
    s_count = cnt(API_CACHE["scam_countries"])
    db = load_db()
    m_scam = len(db["manual"].get("scam_fake", {}))
    m_chan = len(db["manual"].get("channels", {}))
    rs = len(ready_stock_cats())

    kb = types.InlineKeyboardMarkup(row_width=1)
    if rs: kb.row(IB(f"⚡ READY STOCK ({rs})", callback_data="browse_rs", style="success"))
    kb.row(IB(f"🔴 PHISHING ({p_count})", callback_data="browse_phishing", style="danger"))
    kb.row(IB(f"🟢 GOOD QUALITY ({g_count})", callback_data="browse_good", style="success"))
    kb.row(IB(f"⚠️ SCAM/FAKE ({s_count + m_scam})", callback_data="browse_scam", style="danger"))
    kb.row(IB(f"📢 CHANNELS & GROUPS ({m_chan})", callback_data="browse_channels", style="primary"))
    kb.row(IB("⬅️ Back", callback_data="back_main", style=None))

    rows = []
    if rs: rows.append(("⚡", "READY STOCK — INSTANT"))
    rows += [("🔴", "PHISHING — SPAM / LIMIT"), ("🟢", "GOOD — NO SPAM / NO LIMIT"),
             ("⚠️", "SCAM / FAKE TAG"), ("📢", "CHANNELS & GROUPS"), None, ("👇", "SELECT A SECTION")]
    edit_ui(panel("BROWSE ACCOUNTS", rows, emoji="🌐"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

# ─── READY STOCK (admin ka add kiya hua stock) ───
@cbh(func=lambda c: c.data == "browse_rs" or re.match(r"^rs_pg_\d+$", c.data))
def cb_ready_stock(call):
    page = int(call.data.split("_")[2]) if call.data.startswith("rs_pg_") else 0
    cats = ready_stock_cats()
    if not cats:
        ans(call, "No stock available", True); return
    per = 10
    items = sorted(cats.items(), key=lambda x: x[1].get("name", "").lower())
    total_pages = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    kb = types.InlineKeyboardMarkup(row_width=1)
    for k, c in items[page * per:(page + 1) * per]:
        kb.row(IB(f"{c['name']} • ₹{money(c['price'])} • {len(c['stock'])}"[:45], callback_data=f"rs_i_{hid(k)}", style="success"))
    pager_row(kb, "rs", page, total_pages)
    kb.row(IB("⬅️ Back", callback_data="browse", style=None))
    edit_ui(panel("READY STOCK", [("📁", f"{len(items)} CATEGORIES"), ("⚡", "INSTANT DELIVERY"),
                                  ("📄", f"PAGE {page+1}/{total_pages}")], emoji="⚡"),
            call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("rs_i_"))
def cb_rs_select(call):
    db = load_db()
    key = unhid(db.get("categories", {}).keys(), call.data.replace("rs_i_", ""))
    cat = db.get("categories", {}).get(key) if key else None
    if not cat or not cat.get("stock"):
        ans(call, "❌ Out of stock", True); return
    price = safe_float(cat.get("price"))
    u = get_user(db, call.from_user.id)
    if u["balance"] < price:
        ans(call, f"❌ Insufficient\nNeed: ₹{money(price)}\nYour: ₹{money(u['balance'])}", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(IB("✅ Confirm", callback_data=f"rs_buy_{hid(key)}", style="success"),
           IB("❌ Cancel", callback_data="rs_pg_0", style="danger"))
    edit_ui(panel("CONFIRM PURCHASE", [
        ("📁", esc(cat["name"])), ("💰", f"PRICE : <b>₹{money(price)}</b>"),
        ("💼", f"BALANCE : ₹{money(u['balance'])}"), ("📦", f"STOCK : {len(cat['stock'])}"),
        None, ("❓", "CONFIRM KARO?")], emoji="🛒"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("rs_buy_"))
def cb_rs_buy(call):
    uid = str(call.from_user.id)
    with db_lock:
        db = load_db()
        key = unhid(db.get("categories", {}).keys(), call.data.replace("rs_buy_", ""))
        cat = db.get("categories", {}).get(key) if key else None
        if not cat or not cat.get("stock"):
            ans(call, "❌ Out of stock", True); return
        price = safe_float(cat.get("price"))
        u = get_user(db, uid)
        if u["balance"] < price:
            ans(call, "❌ Insufficient", True); return
        entry = cat["stock"].pop(0)
        u["balance"] -= price
        save_db(db)
        name = cat["name"]
    phone, twofa = stock_phone(entry), stock_2fa(entry)
    oid, bal = record_order(uid, price, phone, name, "stock", twofa)
    purchase_done(call, oid, phone, price, bal, twofa=twofa)
    ans(call, "✅ Done")
    if len(load_db().get("categories", {}).get(key, {}).get("stock", [])) == 0:
        notify_owner(panel("STOCK EMPTY", [("📁", esc(name))], emoji="⚠️"))

# ─── PHISHING + GOOD (ek hi generic code) ───
CATS = {
    "phish": {"cache": "phishing", "ccache": "phishing_countries", "emoji": "🔴",
              "name": "PHISHING", "sub": "SPAM / LIMIT TAG ACCOUNTS", "c_style": "danger"},
    "good":  {"cache": "good", "ccache": "good_countries", "emoji": "🟢",
              "name": "GOOD QUALITY", "sub": "NO SPAM / NO LIMIT ACCOUNTS", "c_style": "success"},
}

def show_country_list(call, prefix, page=0):
    cat = CATS[prefix]
    kb, total, total_pages = build_country_grid(API_CACHE[cat["ccache"]], prefix, page, "browse", cat["c_style"])
    if total == 0:
        edit_ui(panel(cat["name"], [("ℹ️", "ABHI STOCK NAHI HAI"), ("🔌", "ADMIN API SYNC KARE")], emoji=cat["emoji"]),
                call.message.chat.id, call.message.message_id, back_kb("browse")); return
    text = panel(cat["name"], [
        ("🏷", cat["sub"]), None,
        ("🌍", f"{total} COUNTRIES"),
        ("📄", f"PAGE {page+1}/{total_pages}"),
    ], emoji=cat["emoji"])
    edit_ui(text, call.message.chat.id, call.message.message_id, kb)

def show_item_list(call, prefix, cc, page=0):
    cat = CATS[prefix]
    cdata = API_CACHE[cat["ccache"]].get(cc) if cc else None
    if not cdata:
        ans(call, "Not found / refresh", True); return False
    kb, total_pages = build_item_grid(API_CACHE[cat["cache"]], cdata["keys"], prefix, cc, page)
    text = panel(cdata["name"], [
        ("📊", f"{len(cdata['keys'])} TYPES"),
        ("📦", f"TOTAL STOCK : {cdata.get('total_stock', 0)}"),
        ("📄", f"PAGE {page+1}/{total_pages}"),
    ], emoji=cat["emoji"])
    edit_ui(text, call.message.chat.id, call.message.message_id, kb)
    return True

@cbh(func=lambda c: c.data in ("browse_phishing", "browse_good") or re.match(r"^(phish|good)_pg_\d+$", c.data))
def cb_country_list(call):
    if call.data == "browse_phishing": prefix, page = "phish", 0
    elif call.data == "browse_good": prefix, page = "good", 0
    else:
        prefix, _, p = call.data.split("_"); page = int(p)
    show_country_list(call, prefix, page); ans(call)

@cbh(func=lambda c: re.match(r"^(phish|good)_c_.+$", c.data))
def cb_country_pick(call):
    prefix, _, h = call.data.split("_", 2)
    cc = unhid(API_CACHE[CATS[prefix]["ccache"]].keys(), h)
    if show_item_list(call, prefix, cc, 0): ans(call)

@cbh(func=lambda c: re.match(r"^(phish|good)_ipg_.+_\d+$", c.data))
def cb_item_page(call):
    prefix, _, rest = call.data.split("_", 2)
    h, page = rest.rsplit("_", 1)
    cc = unhid(API_CACHE[CATS[prefix]["ccache"]].keys(), h)
    if show_item_list(call, prefix, cc, int(page)): ans(call)

# ─── SELECT & BUY (API accounts) ───
@cbh(func=lambda c: re.match(r"^(phish|good)_i_.+$", c.data))
def cb_select_account(call):
    prefix, _, h = call.data.split("_", 2)
    cache = API_CACHE[CATS[prefix]["cache"]]
    key = unhid(cache.keys(), h)
    item = cache.get(key) if key else None
    if not item:
        ans(call, "Not found / refresh", True); return
    u = get_user(load_db(), call.from_user.id)
    if item["stock"] <= 0:
        ans(call, "❌ Out of stock", True); return
    if u["balance"] < item["price"]:
        ans(call, f"❌ Insufficient\nNeed: ₹{money(item['price'])}\nYour: ₹{money(u['balance'])}", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(IB("✅ Confirm", callback_data=f"buyacc_{prefix}_{h}", style="success"),
           IB("❌ Cancel", callback_data=f"{prefix}_pg_0", style="danger"))
    edit_ui(panel("CONFIRM PURCHASE", [
        ("📱", esc(item["name"])), ("💰", f"PRICE : <b>₹{money(item['price'])}</b>"),
        ("💼", f"BALANCE : ₹{money(u['balance'])}"), ("📦", f"STOCK : {item['stock']}"),
        None, ("❓", "CONFIRM KARO?")], emoji="🛒"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

def buy_from_api(call, key, cache_names, back_cb, title="PURCHASE SUCCESSFUL"):
    """Common API purchase: balance reserve -> API buy -> fail pe refund."""
    uid = str(call.from_user.id)
    item = next((API_CACHE[c].get(key) for c in cache_names if API_CACHE[c].get(key)), None)
    if not item:
        ans(call, "Not found / refresh", True); return
    price = item["price"]
    ok, bal = reserve_balance(uid, price)
    if not ok:
        ans(call, "❌ Insufficient", True); return
    edit_ui(panel("PROCESSING", [("⏳", "ACCOUNT NIKAL RAHE HAIN...")], emoji="⏳"),
            call.message.chat.id, call.message.message_id)
    phone, error = api_buy_account(key)
    if not phone:
        refund_balance(uid, price)
        edit_ui(panel("PURCHASE FAILED", [("❌", esc((error or "Failed")[:60])), ("💰", "BALANCE WAPAS (REFUND)")], emoji="❌"),
                call.message.chat.id, call.message.message_id, back_kb(back_cb))
        ans(call); return
    for c in cache_names:
        if key in API_CACHE[c]:
            API_CACHE[c][key]["stock"] = max(0, API_CACHE[c][key]["stock"] - 1)
    oid, bal = record_order(uid, price, phone, item["name"], "api")
    purchase_done(call, oid, phone, price, bal, title)
    ans(call, "✅ Done")

@cbh(func=lambda c: c.data.startswith("buyacc_"))
def cb_buyapi(call):
    prefix, _, h = call.data.replace("buyacc_", "", 1).partition("_")
    cache_name = CATS.get(prefix, CATS["good"])["cache"]
    key = unhid(API_CACHE[cache_name].keys(), h)
    if not key:
        ans(call, "Not found / refresh", True); return
    buy_from_api(call, key, [cache_name], "browse")

# ─── SCAM ───
def scam_countries_merged():
    db = load_db()
    countries = {}
    for k, v in API_CACHE["scam"].items():
        cc = v.get("country", "unk")
        countries.setdefault(cc, {"name": v.get("name", cc), "flag": v.get("flag", ""), "total_stock": 0})
        countries[cc]["total_stock"] += v.get("stock", 0)
    for k, v in db["manual"].get("scam_fake", {}).items():
        cc = v.get("country", "unk")
        countries.setdefault(cc, {"name": v.get("country_name", cc), "flag": v.get("flag", ""), "total_stock": 0})
        countries[cc]["total_stock"] += 1
    return countries

@cbh(func=lambda c: c.data == "browse_scam" or re.match(r"^scam_pg_\d+$", c.data))
def cb_browse_scam(call):
    page = int(call.data.split("_")[2]) if call.data.startswith("scam_pg_") else 0
    countries = scam_countries_merged()
    if not any(v["total_stock"] > 0 for v in countries.values()):
        ans(call, "No items", True); return
    kb, total, total_pages = build_country_grid(countries, "scam", page, "browse", "danger")
    edit_ui(panel("SCAM / FAKE TAG", [
        ("🌍", f"{total} COUNTRIES"), ("📄", f"PAGE {page+1}/{total_pages}"),
        None, ("👇", "SELECT COUNTRY")], emoji="⚠️"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("scam_c_"))
def cb_scam_country(call):
    cc = unhid(scam_countries_merged().keys(), call.data.replace("scam_c_", ""))
    db = load_db()
    items = [("api", k, v) for k, v in API_CACHE["scam"].items() if v.get("country") == cc and v.get("stock", 0) > 0]
    items += [("manual", k, v) for k, v in db["manual"].get("scam_fake", {}).items() if v.get("country") == cc]
    if not cc or not items:
        ans(call, "Not found / refresh", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for src, k, v in items[:40]:
        if src == "api": label = f"{v.get('name', k)[:25]} • ₹{money(v.get('price', 0))}"
        else: label = f"⚠️ {safe_str(v.get('phone', 'N/A'))[:20]} • ₹{money(v.get('price', 0))}"
        row.append(IB(label, callback_data=f"scamsel_{src}_{hid(k)}", style="danger"))
        if len(row) == 2: kb.row(*row); row = []
    if row: kb.row(*row)
    kb.row(IB("⬅️ Back", callback_data="scam_pg_0", style=None))
    country_name = items[0][2].get("country_name") or items[0][2].get("name", cc)
    edit_ui(panel(country_name, [("📊", f"{len(items)} ITEMS")], emoji="⚠️"),
            call.message.chat.id, call.message.message_id, kb)
    ans(call)

def resolve_scam(src, h):
    if src == "api":
        key = unhid(API_CACHE["scam"].keys(), h)
        return key, (API_CACHE["scam"].get(key) if key else None)
    items = load_db()["manual"].get("scam_fake", {})
    key = unhid(items.keys(), h)
    return key, (items.get(key) if key else None)

@cbh(func=lambda c: c.data.startswith("scamsel_"))
def cb_scamsel(call):
    src, _, h = call.data.replace("scamsel_", "", 1).partition("_")
    key, item = resolve_scam(src, h)
    if not item:
        ans(call, "Not found / sold", True); return
    if src == "api": price, name, phone = item["price"], item["name"], None
    else: price, phone, name = safe_float(item.get("price", 0)), item.get("phone", ""), item.get("country_name", "")
    u = get_user(load_db(), call.from_user.id)
    if u["balance"] < price:
        ans(call, f"❌ Need ₹{money(price)}", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(IB("✅ Confirm", callback_data=f"scambuy_{src}_{h}", style="success"),
           IB("❌ Cancel", callback_data="scam_pg_0", style="danger"))
    rows = [("📱", esc(name))]
    if phone: rows.append(("📞", f"<code>{esc(phone)}</code>"))
    rows += [("💰", f"PRICE : ₹{money(price)}"), ("💼", f"BALANCE : ₹{money(u['balance'])}"), None, ("❓", "CONFIRM KARO?")]
    edit_ui(panel("CONFIRM", rows, emoji="🛒"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("scambuy_"))
def cb_scambuy(call):
    src, _, h = call.data.replace("scambuy_", "", 1).partition("_")
    uid = str(call.from_user.id)
    if src == "api":
        key, item = resolve_scam(src, h)
        if not key or not item:
            ans(call, "Not found / sold", True); return
        buy_from_api(call, key, ["scam"], "browse"); return
    with db_lock:
        db = load_db()
        items = db["manual"].get("scam_fake", {})
        key = unhid(items.keys(), h)
        item = items.get(key) if key else None
        if not item:
            ans(call, "Not found / sold", True); return
        price, phone, name = safe_float(item.get("price", 0)), item.get("phone", ""), item.get("country_name", "")
        u = get_user(db, uid)
        if u["balance"] < price:
            ans(call, "❌ Insufficient", True); return
        del items[key]; u["balance"] -= price; save_db(db)
    oid, bal = record_order(uid, price, phone, name, "manual")
    purchase_done(call, oid, phone, price, bal)
    ans(call, "✅ Done")

# ─── CHANNELS ───
def channel_countries():
    countries = {}
    for k, v in load_db()["manual"].get("channels", {}).items():
        cc = v.get("country", "unk")
        countries.setdefault(cc, {"name": v.get("country_name", cc), "flag": v.get("flag", ""), "total_stock": 0})
        countries[cc]["total_stock"] += 1
    return countries

@cbh(func=lambda c: c.data == "browse_channels" or re.match(r"^chan_pg_\d+$", c.data))
def cb_browse_channels(call):
    page = int(call.data.split("_")[2]) if call.data.startswith("chan_pg_") else 0
    countries = channel_countries()
    if not countries:
        ans(call, "No channels", True); return
    kb, total, total_pages = build_country_grid(countries, "chan", page, "browse", "primary")
    edit_ui(panel("CHANNELS & GROUPS", [("🌍", f"{total} COUNTRIES"), None, ("👇", "SELECT COUNTRY")], emoji="📢"),
            call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("chan_c_"))
def cb_chan_country(call):
    cc = unhid(channel_countries().keys(), call.data.replace("chan_c_", ""))
    items = load_db()["manual"].get("channels", {})
    filtered = [(k, v) for k, v in items.items() if v.get("country") == cc]
    if not cc or not filtered:
        ans(call, "Not found / refresh", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for k, v in filtered[:40]:
        title = safe_str(v.get("title", "Channel"))[:25]
        row.append(IB(f"{v.get('flag','')} {title} • ₹{money(v.get('price', 0))}", callback_data=f"chansel_{hid(k)}", style="success"))
        if len(row) == 2: kb.row(*row); row = []
    if row: kb.row(*row)
    kb.row(IB("⬅️ Back", callback_data="chan_pg_0", style=None))
    edit_ui(panel(filtered[0][1].get("country_name", cc), [("📊", f"{len(filtered)} ITEMS")], emoji="📢"),
            call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("chansel_"))
def cb_chansel(call):
    db = load_db()
    items = db["manual"].get("channels", {})
    key = unhid(items.keys(), call.data.replace("chansel_", ""))
    item = items.get(key) if key else None
    if not item:
        ans(call, "Not found / sold", True); return
    u = get_user(db, call.from_user.id)
    price = safe_float(item.get("price", 0))
    if u["balance"] < price:
        ans(call, f"❌ Need ₹{money(price)}", True); return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(IB("✅ Confirm", callback_data=f"chanbuy_{hid(key)}", style="success"),
           IB("❌ Cancel", callback_data="chan_pg_0", style="danger"))
    edit_ui(panel("CONFIRM", [("📢", esc(item.get("title", ""))), ("💰", f"PRICE : ₹{money(price)}"),
                              ("💼", f"BALANCE : ₹{money(u['balance'])}"), None, ("❓", "CONFIRM KARO?")], emoji="🛒"),
            call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("chanbuy_"))
def cb_chanbuy(call):
    uid = str(call.from_user.id)
    with db_lock:
        db = load_db()
        items = db["manual"].get("channels", {})
        key = unhid(items.keys(), call.data.replace("chanbuy_", ""))
        item = items.get(key) if key else None
        if not item:
            ans(call, "Not found / sold", True); return
        price = safe_float(item.get("price", 0))
        u = get_user(db, uid)
        if u["balance"] < price:
            ans(call, "❌ Insufficient", True); return
        del items[key]; u["balance"] -= price; save_db(db)
    link = item.get("link", "")
    oid, bal = record_order(uid, price, link, item.get("country_name", "") or item.get("title", ""), "channel", "-")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.row(IB("📢 OPEN LINK", url=fix_url(link), style="success"))
    kb.row(IB("⬅️ Main Menu", callback_data="back_main", style=None))
    edit_ui(panel("PURCHASE SUCCESSFUL", [
        ("🆔", f"ORDER : <code>{oid}</code>"), ("📢", esc(item.get("title", ""))),
        ("🔗", f"<code>{esc(link)}</code>"), None,
        ("💰", f"PRICE : ₹{money(price)}"), ("💼", f"BALANCE : ₹{money(bal)}")], emoji="✅"),
        call.message.chat.id, call.message.message_id, kb)
    ans(call, "✅ Done")

# ═══════════════════════════════════════════════
#  OTHER USER SCREENS
# ═══════════════════════════════════════════════
@cbh(func=lambda c: c.data == "add_balance")
def cb_add_balance(call):
    try:
        s = load_db()["settings"]
        text = panel("ADD BALANCE", [
            ("📱", f"UPI : <code>{esc(s['upi_id'])}</code>"),
            ("👤", f"NAME : {esc(s.get('upi_name', ''))}"),
            ("💵", f"MIN : ₹{s['min_deposit']}"),
            None,
            ("1️⃣", "UPI PE PAY KARO"),
            ("2️⃣", "'I HAVE PAID' DABAO"),
            ("3️⃣", "UTR + SCREENSHOT BHEJO"),
        ], emoji="💳")
        qr = make_upi_qr(s["upi_id"], s.get("upi_name", "Merchant"))
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.row(IB("✅ I HAVE PAID", callback_data="paid_start", style="success"))
        kb.row(IB("⬅️ Back", callback_data="back_main", style=None))
        cid = call.message.chat.id
        safe_delete(cid, call.message.message_id)
        LAST_UI.pop(cid, None)
        sent = None
        if qr:
            try: sent = bot.send_photo(cid, qr, caption=text, reply_markup=kb)
            except Exception: sent = None
        if sent is None: sent = bot.send_message(cid, text, reply_markup=kb)
        LAST_UI[cid] = sent.message_id
        MEDIA_MSGS.add((cid, sent.message_id)) if sent.content_type == "photo" else None
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "my_orders")
def cb_my_orders(call):
    try:
        uid = str(call.from_user.id)
        orders = [o for o in load_db()["orders"].values() if o["uid"] == uid]
        if not orders:
            ans(call, "No orders", True); return
        kb = types.InlineKeyboardMarkup(row_width=2)
        row = []
        for o in reversed(orders[-20:]):   # newest pehle
            label = o["phone"][:18] if safe_str(o["phone"]).startswith("+") else safe_str(o["country"])[:18]
            row.append(IB(label or f"#{o['oid']}", callback_data=f"myorder_{o['oid']}", style="primary"))
            if len(row) == 2: kb.row(*row); row = []
        if row: kb.row(*row)
        kb.row(IB("⬅️ Back", callback_data="back_main", style=None))
        edit_ui(panel("MY ORDERS", [("📦", f"TOTAL : {len(orders)}"), None, ("👇", "TAP ANY ORDER")], emoji="📦"),
                call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "my_profile")
def cb_my_profile(call):
    try:
        u = get_user(load_db(), call.from_user.id)
        text = panel("MY PROFILE", [
            ("🆔", f"ID : <code>{call.from_user.id}</code>"),
            ("👤", f"NAME : {esc(call.from_user.first_name)}"),
            None,
            ("💰", f"BALANCE : ₹{money(u.get('balance', 0))}"),
            ("📊", f"SPENT : ₹{money(u.get('total_spent', 0))}"),
            ("📦", f"PURCHASES : {len(u.get('purchases', []))}"),
        ], emoji="👤")
        edit_ui(text, call.message.chat.id, call.message.message_id, back_kb())
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "support")
def cb_support(call):
    try:
        s = load_db()["settings"]
        text = panel("SUPPORT", [("📞", esc(s["support"])), ("📢", esc(s["channel"])), None, ("🕐", "24/7 ACTIVE")], emoji="🎧")
        edit_ui(text, call.message.chat.id, call.message.message_id, back_kb())
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "official_channel")
def cb_official_channel(call):
    try:
        link = load_db()["settings"].get("channel", "https://t.me/ZXPRIMEPROOFS")
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.row(IB("📢 JOIN CHANNEL", url=fix_url(link), style="success"))
        kb.row(IB("⬅️ Back", callback_data="back_main", style=None))
        edit_ui(panel("OFFICIAL CHANNEL", [("📢", "JOIN FOR UPDATES & STOCK ALERTS")], emoji="📢"),
                call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "terms")
def cb_terms(call):
    text = panel("TERMS OF SERVICE", [
        ("1️⃣", "SOLD AS-IS"), ("2️⃣", "NO REFUND"), ("3️⃣", "REPLACEMENT 1 HR"),
        ("4️⃣", "NO ILLEGAL USE"), ("5️⃣", "NOT RESPONSIBLE FOR MISUSE"), ("6️⃣", "DEPOSIT NON-REFUNDABLE"),
    ], emoji="🧾", expandable=True)
    edit_ui(text, call.message.chat.id, call.message.message_id, back_kb())
    ans(call)

@cbh(func=lambda c: c.data == "noop")
def cb_noop(call): ans(call)

def order_kb(oid, is_phone=True):
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_phone:
        kb.row(IB("🔑 OTP", callback_data=f"otp_{oid}", style="success"))
        kb.row(IB("🔓 Logout", callback_data=f"logout_{oid}", style="danger"))
    kb.row(IB("⬅️ Back", callback_data="my_orders", style=None))
    return kb

@cbh(func=lambda c: c.data.startswith("myorder_"))
def cb_myorder(call):
    try:
        oid = call.data.replace("myorder_", "")
        order = load_db()["orders"].get(oid)
        if not order:
            ans(call, "Not found", True); return
        if order["uid"] != str(call.from_user.id) and not is_owner(call.from_user.id):
            ans(call, "❌", True); return
        is_phone = safe_str(order["phone"]).startswith("+")
        rows = [("📞" if is_phone else "🔗", f"<code>{esc(order['phone'])}</code>"), ("📱", esc(order["country"]))]
        if is_phone: rows.append(("🔒", f"2FA : <code>{esc(order.get('2fa', DEFAULT_2FA))}</code>"))
        rows += [("💰", f"₹{money(order['price'])}"), ("📅", order["time"][:16].replace("T", " "))]
        edit_ui(panel("ORDER DETAILS", rows, emoji="📦"), call.message.chat.id, call.message.message_id, order_kb(oid, is_phone))
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

# ═══════════════════════════════════════════════
#  DEPOSIT   (prompts + replies auto-delete)
# ═══════════════════════════════════════════════
@cbh(func=lambda c: c.data == "paid_start")
def cb_paid_start(call):
    uid = call.from_user.id
    with db_lock:
        db = load_db()
        pid = str(db["next_pid"]); db["next_pid"] += 1; save_db(db)
    PENDING_DEPOSIT[uid] = {"pid": pid, "qr_mid": call.message.message_id}
    ans(call)
    ask(call.message.chat.id, panel("DEPOSIT • STEP 1/2", [
        ("🧾", "APNA UTR NUMBER BHEJO"), ("❌", "STOP KARNE KE LIYE: cancel")], emoji="💳"),
        process_deposit_utr)

def process_deposit_utr(message):
    try:
        if step_guard(message): return
        uid = message.from_user.id
        utr = (message.text or "").strip()
        if len(utr) < 8:
            retry(message, process_deposit_utr, panel("INVALID UTR", [("❌", "MIN 8 DIGITS — DOBARA BHEJO")], emoji="💳")); return
        data = PENDING_DEPOSIT.get(uid)
        if not data:
            clean(message); toast(message.chat.id, "❌ Expired"); return
        if any(p.get("utr") == utr and p.get("status") != "rejected" for p in load_db()["payments"].values()):
            retry(message, process_deposit_utr, panel("UTR ALREADY USED", [("❌", "YE UTR PEHLE USE HO CHUKA HAI")], emoji="💳")); return
        data["utr"] = utr
        clean(message)
        ask(message.chat.id, panel("DEPOSIT • STEP 2/2", [
            ("📸", "PAYMENT SCREENSHOT BHEJO"), ("❌", "STOP KARNE KE LIYE: cancel")], emoji="💳"),
            process_deposit_screenshot)
    except Exception as e: print(f"[utr] {e}")

def process_deposit_screenshot(message):
    try:
        if step_guard(message): return
        uid, cid = message.from_user.id, message.chat.id
        if not message.photo:
            retry(message, process_deposit_screenshot, panel("PHOTO CHAHIYE", [("📸", "SCREENSHOT PHOTO BHEJO")], emoji="💳")); return
        data = PENDING_DEPOSIT.get(uid)
        if not data:
            clean(message); toast(cid, "❌ Expired"); return
        db = load_db()
        pid, utr = data["pid"], data["utr"]
        file_id = message.photo[-1].file_id
        db["payments"][pid] = {"uid": uid, "utr": utr, "file_id": file_id,
                               "status": "pending", "time": datetime.now().isoformat()}
        save_db(db)
        PENDING_DEPOSIT.pop(uid, None)
        clean(message)
        if data.get("qr_mid"): safe_delete(cid, data["qr_mid"])
        send_ui(cid, panel("DEPOSIT SUBMITTED", [
            ("🆔", f"ID : <code>{pid}</code>"), ("🧾", f"UTR : <code>{esc(utr)}</code>"),
            None, ("⏳", "ADMIN APPROVAL KA WAIT KARO")], emoji="✅"), main_menu(uid))
        try:
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.row(IB("✅ Approve", callback_data=f"pay_ap_{pid}", style="success"),
                   IB("❌ Reject", callback_data=f"pay_rj_{pid}", style="danger"))
            bot.send_photo(OWNER_ID, file_id, caption=panel("NEW DEPOSIT", [
                ("👤", f"<code>{uid}</code>"), ("🆔", f"<code>{pid}</code>"), ("🧾", f"<code>{esc(utr)}</code>")], emoji="💰"),
                reply_markup=kb)
        except Exception: pass
    except Exception as e: print(f"[ss] {e}")

@cbh(func=lambda c: c.data.startswith("pay_ap_"))
def cb_pay_ap(call):
    if not is_owner(call.from_user.id): return
    pid = call.data.replace("pay_ap_", "")
    db = load_db()
    if pid not in db["payments"] or db["payments"][pid]["status"] != "pending":
        ans(call, "Not found / done", True); return
    ans(call)
    src_mid = call.message.message_id
    ask(call.message.chat.id, panel("APPROVE", [("💰", "AMOUNT BHEJO (₹)"), ("❌", "cancel")], emoji="✅"),
        lambda m: finalize_approve(m, pid, src_mid))

def finalize_approve(message, pid, src_mid=None):
    if step_guard(message): return
    cid = message.chat.id
    amount = safe_float((message.text or "").strip(), 0)
    if amount <= 0:
        retry(message, lambda m: finalize_approve(m, pid, src_mid), panel("INVALID", [("❌", "SIRF NUMBER BHEJO (>0)")], emoji="✅")); return
    amount = int(amount) if amount == int(amount) else round(amount, 2)
    with db_lock:
        db = load_db()
        p = db["payments"].get(pid)
        if not p or p["status"] != "pending":
            clean(message); toast(cid, "❌ Not found / already done"); return
        uid = p["uid"]
        u = get_user(db, uid)
        u["balance"] += amount
        p["status"] = "approved"; p["amount"] = amount
        save_db(db)
    clean(message)
    if src_mid: safe_delete(cid, src_mid)
    toast(cid, panel("APPROVED", [("✅", f"₹{amount} → <code>{uid}</code>")], emoji="✅"), 4)
    try: bot.send_message(int(uid), panel("DEPOSIT APPROVED", [("💰", f"ADDED : ₹{amount}"), ("💵", f"BALANCE : ₹{money(u['balance'])}")], emoji="✅"))
    except Exception: pass

@cbh(func=lambda c: c.data.startswith("pay_rj_"))
def cb_pay_rj(call):
    if not is_owner(call.from_user.id): return
    pid = call.data.replace("pay_rj_", "")
    with db_lock:
        db = load_db()
        p = db["payments"].get(pid)
        if not p or p["status"] != "pending":
            ans(call, "Not found / already done", True); return
        p["status"] = "rejected"; save_db(db)
    ans(call, "Rejected")
    safe_delete(call.message.chat.id, call.message.message_id)
    try: bot.send_message(int(p["uid"]), panel("DEPOSIT REJECTED", [("❌", "PAYMENT VERIFY NAHI HUA")], emoji="❌"))
    except Exception: pass

# ═══════════════════════════════════════════════
#  OTP / LOGOUT
# ═══════════════════════════════════════════════
@cbh(func=lambda c: c.data.startswith("otp_"))
def cb_otp(call):
    try:
        oid = call.data.replace("otp_", "")
        order = load_db()["orders"].get(oid)
        if not order:
            ans(call, "Not found", True); return
        if not is_owner(call.from_user.id) and order["uid"] != str(call.from_user.id):
            ans(call, "❌", True); return
        phone = order["phone"]; twofa = order.get("2fa", DEFAULT_2FA)
        if not phone.startswith("+"):
            ans(call, "Not phone", True); return
        ans(call, "⏳")
        cid = call.message.chat.id
        wait_msg = bot.send_message(cid, panel("FETCHING OTP", [("⏳", "PLEASE WAIT...")], emoji="🔑"))
        start = time.time()
        otp, error = fetch_otp_sync(phone, timeout=10, retries=3)
        elapsed = time.time() - start
        if otp:
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.row(IB("🔓 LOGOUT", callback_data=f"logout_{oid}", style="danger"))
            kb.row(IB("⬅️ Main Menu", callback_data="back_main", style=None))
            edit_ui(panel("LOGIN DETAILS", [
                ("📞", f"<code>{esc(phone)}</code>"), ("🔐", f"OTP : <code>{otp}</code>"),
                ("🔒", f"2FA : <code>{esc(twofa)}</code>"), None, ("⚡", f"{elapsed:.1f}s")], emoji="🔑"),
                cid, wait_msg.message_id, kb)
        else:
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.row(IB("🔄 RETRY", callback_data=f"otp_{oid}", style="primary"))
            kb.row(IB("🔓 LOGOUT", callback_data=f"logout_{oid}", style="danger"))
            kb.row(IB("⬅️ Main Menu", callback_data="back_main", style=None))
            safe_delete(cid, wait_msg.message_id)  # purana wait msg hatao, naya result do
            bot.send_message(cid, panel("OTP NOT FOUND", [("⚠️", esc(error))], emoji="⚠️"), reply_markup=kb)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("logout_"))
def cb_logout(call):
    try:
        oid = call.data.replace("logout_", "")
        order = load_db()["orders"].get(oid)
        if not order:
            ans(call, "Not found", True); return
        if not is_owner(call.from_user.id) and order["uid"] != str(call.from_user.id):
            ans(call, "❌", True); return
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(IB("✅ Yes", callback_data=f"logoutyes_{oid}", style="danger"),
               IB("❌ No", callback_data=f"myorder_{oid}", style="success"))
        edit_ui(panel("LOGOUT?", [("📞", f"<code>{esc(order['phone'])}</code>"), None, ("⚠️", "SESSION KHATAM HO JAYEGA")], emoji="🔓"),
                call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("logoutyes_"))
def cb_logout_yes(call):
    try:
        oid = call.data.replace("logoutyes_", "")
        order = load_db()["orders"].get(oid)
        if not order:
            ans(call, "Not found", True); return
        if not is_owner(call.from_user.id) and order["uid"] != str(call.from_user.id):
            ans(call, "❌", True); return
        ans(call, "⏳")
        success, error = logout_session(order["phone"])
        text = (panel("LOGGED OUT", [("✅", f"<code>{esc(order['phone'])}</code>")], emoji="🔓") if success
                else panel("LOGOUT FAILED", [("⚠️", esc(error))], emoji="⚠️"))
        edit_ui(text, call.message.chat.id, call.message.message_id, back_kb("back_main", "⬅️ Main Menu"))
    except Exception as e: ans(call, f"Error: {e}", True)

# ═══════════════════════════════════════════════
#  ADMIN — owner reply keyboard actions
# ═══════════════════════════════════════════════
USER_ROUTES = {U_BROWSE: "browse", U_ADD: "add_balance", U_ORDERS: "my_orders", U_PROFILE: "my_profile",
               U_SUPPORT: "support", U_CHANNEL: "official_channel", U_TERMS: "terms"}

def dispatch_cb(cid, user, data):
    """Bottom button -> wahi screen jo inline button se khulti hai (video wale UI me)."""
    funcs = {"browse": cb_browse, "add_balance": cb_add_balance, "my_orders": cb_my_orders,
             "my_profile": cb_my_profile, "support": cb_support,
             "official_channel": cb_official_channel, "terms": cb_terms}
    msg = send_ui(cid, home_text(user.id), main_menu(user.id))
    call = SimpleNamespace(id="0", data=data, message=msg, from_user=user)
    funcs[data](call)

# label -> (inline callback data, handler function name, naya keyboard menu ya None)
ADM_OPEN = {
    BTN_STATS: ("adm_stats", "cb_adm_stats", None),
    A_STOCK:   ("adm_view_stock", "cb_adm_view_stock", None),
    A_ORD:     ("adm_orders", "cb_adm_orders", None),
    A_SALES:   ("adm_sales", "cb_adm_sales", None),
    A_SCAM:    ("adm_scam", "cb_adm_scam", "scam"),
    A_CHAN:    ("adm_channels", "cb_adm_channels", "chan"),
    A_CATS:    ("adm_cats", "cb_adm_cats", "cats"),
    A_API:     ("adm_api", "cb_adm_api", "api"),
    A_SET:     ("adm_settings", "cb_adm_settings", "settings"),
    A_USERS:   ("adm_users", "cb_adm_users", "users"),
}
# (menu, label) -> (callback data, handler function name)
ADM_SUB = {
    ("scam", A_ADDX): ("scam_add", "cb_scam_add"),   ("scam", A_DELX): ("scam_del_list", "cb_scam_del_list"),
    ("chan", A_ADDX): ("chan_add", "cb_chan_add"),   ("chan", A_DELX): ("chan_del_list", "cb_chan_del_list"),
    ("cats", A_ADDX): ("cat_add", "cb_cat_add"),     ("cats", A_DELX): ("cat_del_list", "cb_cat_del_list"),
    ("cats", A_PRICE): ("cat_price", "cb_cat_price"),
    ("api", S_TOG): ("api_toggle", "cb_api_toggle"), ("api", S_SYNC): ("api_sync", "cb_api_sync"),
    ("api", S_URL): ("api_set_url", "cb_api_set_url"), ("api", S_KEY): ("api_set_key", "cb_api_set_key"),
    ("settings", F_UPI): ("setf_upi", "cb_setf"),    ("settings", F_NAME): ("setf_upiname", "cb_setf"),
    ("settings", F_MIN): ("setf_min", "cb_setf"),    ("settings", F_SUP): ("setf_support", "cb_setf"),
    ("settings", F_CHAN): ("setf_channel", "cb_setf"),
    ("users", U_FIND): ("usr_find", "cb_usr_find"),  ("users", U_BALP): ("usr_balp", "cb_usr_bal"),
    ("users", U_BALM): ("usr_balm", "cb_usr_bal"),   ("users", U_BAN): ("usr_ban", "cb_usr_ban"),
    ("users", U_UNBAN): ("usr_unban", "cb_usr_ban"),
}

def _fake_call(cid, user, data, fresh=False):
    """Keyboard button -> wahi inline handler (call.id='0' = keyboard se aaya)."""
    mid = LAST_UI.get(cid)
    if fresh or not mid:
        msg = send_ui(cid, panel("LOADING", [("⏳", "PLEASE WAIT")], emoji="⏳"))
    else:
        msg = SimpleNamespace(chat=SimpleNamespace(id=cid), message_id=mid,
                                    content_type="video" if (cid, mid) in MEDIA_MSGS else "text")
    return SimpleNamespace(id="0", data=data, message=msg, from_user=user)

@bot.message_handler(func=lambda m: m.text in ALL_BTNS and m.chat.type == "private")
def kb_router(m):
    cid, uid, t = m.chat.id, m.from_user.id, m.text
    safe_delete(cid, m.message_id)
    owner = is_owner(uid)
    if t in OWNER_BTNS and not owner: return          # sirf owner (step_guard se bhi safe)
    if not owner and is_banned(uid): return
    try:
        if t in USER_BTNS:
            dispatch_cb(cid, m.from_user, USER_ROUTES[t]); return
        menu = KB_MENU.get(uid, "main")
        if t == BTN_HOME:
            set_kb(cid, uid, "main"); send_ui(cid, home_text(uid), main_menu(uid))
        elif t == BTN_ADMIN:
            set_kb(cid, uid, "admin"); send_ui(cid, admin_text(), admin_menu())
        elif t == BTN_BACK:
            parent = BACK_TO.get(menu, "main")
            set_kb(cid, uid, parent)
            if parent == "main": send_ui(cid, home_text(uid), main_menu(uid))
            else: send_ui(cid, admin_text(), admin_menu())
        elif t == BTN_SETVID: drop_ui(cid); ask_video(cid)
        elif t == BTN_DELVID: remove_video(cid)
        elif t == BTN_ADD:    drop_ui(cid); start_add_account(cid, uid)
        elif t == BTN_APPR:   drop_ui(cid); show_pending(cid)
        elif t == BTN_BCAST:  drop_ui(cid); ask_broadcast(cid)
        elif t in ADM_OPEN:
            data, fn, sub = ADM_OPEN[t]
            if sub: set_kb(cid, uid, sub)
            globals()[fn](_fake_call(cid, m.from_user, data, fresh=True))
        elif (menu, t) in ADM_SUB:
            data, fn = ADM_SUB[(menu, t)]
            globals()[fn](_fake_call(cid, m.from_user, data))
        else:
            # keyboard purana/state reset (bot restart) -> admin keyboard dobara kholo
            if t in OWNER_BTNS: set_kb(cid, uid, "admin"); send_ui(cid, admin_text(), admin_menu())
    except Exception as e:
        log.exception(f"kb_router {t}: {e}")
        toast(cid, panel("ERROR", [("⚠️", "KUCH GALAT HUA — DOBARA TRY KARO")], emoji="⚠️"), 4)

@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    cid, uid = message.chat.id, message.from_user.id
    safe_delete(cid, message.message_id)
    if not is_owner(uid): return
    set_kb(cid, uid, "admin"); send_ui(cid, admin_text(), admin_menu())

# ═══════════════════════════════════════════════
#  ADMIN — panel
# ═══════════════════════════════════════════════
@cbh(func=lambda c: c.data == "admin_panel")
def cb_admin_panel(call):
    if not is_owner(call.from_user.id): return
    try:
        edit_ui(admin_text(), call.message.chat.id, call.message.message_id, admin_menu())
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "adm_stats")
def cb_adm_stats(call):
    if not is_owner(call.from_user.id): return
    edit_ui(stats_text(), call.message.chat.id, call.message.message_id, None)
    ans(call)

# ─── START VIDEO ───
def ask_video(cid):
    ask(cid, panel("SET START VIDEO", [
        ("🎬", "VIDEO YA GIF BHEJO"),
        ("🙈", "START PE BLUR (SPOILER) ME DIKHEGA"),
        ("📌", "MENU BADALNE PE VIDEO UPAR HI RAHEGA"),
        ("❌", "STOP KARNE KE LIYE: cancel")], emoji="🎬"), process_set_video)

def process_set_video(message):
    try:
        if step_guard(message): return
        fid = ftype = None
        if message.video: fid, ftype = message.video.file_id, "video"
        elif message.animation: fid, ftype = message.animation.file_id, "animation"
        if not fid:
            retry(message, process_set_video, panel("VIDEO CHAHIYE", [("🎬", "SIRF VIDEO / GIF BHEJO")], emoji="🎬")); return
        db = load_db()
        db["settings"]["start_video"] = fid
        db["settings"]["start_video_type"] = ftype
        save_db(db)
        clean(message)
        toast(message.chat.id, panel("VIDEO SAVED", [("✅", "START VIDEO SET HO GAYA")], emoji="🎬"), 3)
        drop_ui(message.chat.id)
    except Exception as e: print(f"[setvideo] {e}")

def remove_video(cid):
    db = load_db()
    if not db["settings"].get("start_video"):
        toast(cid, panel("NO VIDEO", [("ℹ️", "KOI VIDEO SET NAHI HAI")], emoji="🎬"), 3); return
    db["settings"]["start_video"] = ""
    save_db(db)
    toast(cid, panel("VIDEO REMOVED", [("🗑", "START VIDEO HATA DIYA")], emoji="🎬"), 3)
    drop_ui(cid)

@cbh(func=lambda c: c.data == "adm_setvideo")
def cb_adm_setvideo(call):
    if not is_owner(call.from_user.id): return
    ans(call); ask_video(call.message.chat.id)

@cbh(func=lambda c: c.data == "adm_delvideo")
def cb_adm_delvideo(call):
    if not is_owner(call.from_user.id): return
    ans(call); remove_video(call.message.chat.id)

# ─── PENDING PAYMENTS ───
def show_pending(cid):
    db = load_db()
    pending = {k: v for k, v in db["payments"].items() if v["status"] == "pending"}
    if not pending:
        toast(cid, panel("NO PENDING", [("✅", "KOI PENDING PAYMENT NAHI")], emoji="💰"), 3); return
    for pid, p in list(pending.items())[:5]:
        try:
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.row(IB("✅ Approve", callback_data=f"pay_ap_{pid}", style="success"),
                   IB("❌ Reject", callback_data=f"pay_rj_{pid}", style="danger"))
            bot.send_photo(cid, p["file_id"], caption=panel("PENDING", [
                ("👤", f"<code>{p['uid']}</code>"), ("🧾", f"<code>{esc(p.get('utr', 'N/A'))}</code>"),
                ("🆔", f"<code>{pid}</code>")], emoji="💰"), reply_markup=kb)
        except Exception: pass

@cbh(func=lambda c: c.data == "adm_approve")
def cb_adm_approve(call):
    if not is_owner(call.from_user.id): return
    ans(call); show_pending(call.message.chat.id)

# ─── ADD ACCOUNT ───
def start_add_account(cid, uid):
    PENDING_ADMIN[uid] = {"action": "awaiting_phone"}
    ask(cid, panel("ADD ACCOUNT", [("📱", "PHONE BHEJO"), ("📝", "<code>+919876543210</code>"), ("❌", "cancel")], emoji="➕"),
        process_add_phone)

@cbh(func=lambda c: c.data == "adm_add")
def cb_adm_add(call):
    if not is_owner(call.from_user.id): return
    ans(call); start_add_account(call.message.chat.id, call.from_user.id)

def process_add_phone(message):
    try:
        if step_guard(message): return
        uid, cid = message.from_user.id, message.chat.id
        phone = (message.text or "").strip().replace(" ", "")
        if not phone.startswith("+") or len(phone) < 8:
            retry(message, process_add_phone, panel("INVALID", [("❌", "FORMAT: <code>+919876543210</code>")], emoji="➕")); return
        async def _send_code():
            client = TelegramClient(session_path(phone), API_ID, API_HASH)
            await client.connect()
            await client.send_code_request(phone)
            return client
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client = loop.run_until_complete(_send_code())
        except Exception as e:
            clean(message); toast(cid, f"❌ {esc(str(e)[:200])}", 6); return
        PENDING_ADMIN[uid] = {"action": "awaiting_otp", "phone": phone, "client": client, "loop": loop}
        clean(message)
        ask(cid, panel("ENTER OTP", [("📱", f"SENT TO <code>{esc(phone)}</code>"), ("❌", "cancel")], emoji="➕"), process_add_otp)
    except Exception as e: print(f"[add_phone] {e}")

def _ask_category(cid, uid, phone, name, title, twofa=None):
    PENDING_ADMIN[uid] = {"action": "awaiting_category", "phone": phone, "name": name, "twofa": twofa or DEFAULT_2FA}
    db = load_db()
    kb = types.InlineKeyboardMarkup(row_width=1)
    for key, cat in db.get("categories", {}).items():
        kb.row(IB(f"{cat['name']} • {len(cat.get('stock', []))}"[:45], callback_data=f"addcat_{hid(key)}", style="primary"))
    if not kb.keyboard:
        kb.row(IB("(No categories)", callback_data="noop", style=None))
    bot.send_message(cid, panel(title, [("📱", f"<code>{esc(phone)}</code>"), ("👤", esc(name)), None, ("📁", "CATEGORY CHUNO")], emoji="✅"),
                     reply_markup=kb)

def process_add_otp(message):
    try:
        if step_guard(message): return
        uid, cid = message.from_user.id, message.chat.id
        data = PENDING_ADMIN.get(uid)
        if not data:
            clean(message); toast(cid, "❌ Expired"); return
        otp = (message.text or "").strip().replace(" ", "")
        phone, client, loop = data["phone"], data["client"], data["loop"]
        async def v():
            try:
                await client.sign_in(phone, otp)
                return "OK", None
            except SessionPasswordNeededError: return "2FA", None
            except Exception as e: return "ERROR", str(e)[:150]
        try: result, error = loop.run_until_complete(v())
        except Exception as e:
            clean(message); toast(cid, f"❌ {esc(str(e)[:150])}", 6); abort_admin(uid); return
        clean(message)  # OTP chat se hat jaye
        if result == "2FA":
            PENDING_ADMIN[uid]["action"] = "awaiting_2fa"
            ask(cid, panel("2FA PASSWORD", [("🔒", "PASSWORD BHEJO"), ("❌", "cancel")], emoji="➕"), process_add_2fa); return
        if result == "ERROR":
            if any(w in (error or "").lower() for w in ("invalid", "incorrect", "empty")) and "expired" not in (error or "").lower():
                ask(cid, panel("WRONG OTP", [("❌", "SAHI OTP DOBARA BHEJO"), ("❌", "cancel")], emoji="➕"), process_add_otp); return
            toast(cid, f"❌ {esc(error)}", 6); abort_admin(uid); return
        try:
            me = loop.run_until_complete(client.get_me())
            loop.run_until_complete(client.disconnect())
            loop.close()
        except Exception: me = None
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() if me else "Unknown"
        _ask_category(cid, uid, phone, name, "LOGIN SUCCESS")
    except Exception as e: print(f"[add_otp] {e}")

def process_add_2fa(message):
    try:
        if step_guard(message): return
        uid, cid = message.from_user.id, message.chat.id
        data = PENDING_ADMIN.get(uid)
        if not data:
            clean(message); toast(cid, "❌ Expired"); return
        password = (message.text or "").strip()
        phone, client, loop = data["phone"], data["client"], data["loop"]
        async def v():
            try:
                await client.sign_in(password=password)
                me = await client.get_me()
                await client.disconnect()
                return me, None
            except Exception as e: return None, str(e)[:150]
        try:
            me, error = loop.run_until_complete(v())
        except Exception as e:
            clean(message); toast(cid, f"❌ {esc(str(e)[:150])}", 6); abort_admin(uid); return
        clean(message)  # password chat se delete
        if error:
            if "password" in error.lower() and "flood" not in error.lower():
                ask(cid, panel("WRONG PASSWORD", [("❌", "SAHI 2FA DOBARA BHEJO"), ("❌", "cancel")], emoji="➕"), process_add_2fa); return
            toast(cid, f"❌ {esc(error)}", 6); abort_admin(uid); return
        try: loop.close()
        except Exception: pass
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        _ask_category(cid, uid, phone, name, "2FA LOGIN SUCCESS", password)
    except Exception as e: print(f"[add_2fa] {e}")

@cbh(func=lambda c: c.data.startswith("addcat_"))
def cb_addcat(call):
    try:
        uid, cid = call.from_user.id, call.message.chat.id
        if not is_owner(uid): return
        data = PENDING_ADMIN.get(uid)
        if not data or data.get("action") != "awaiting_category":
            ans(call, "Session expired", True); return
        phone = data["phone"]
        with db_lock:
            db = load_db()
            key = unhid(db["categories"].keys(), call.data.replace("addcat_", ""))
            cat = db["categories"].get(key) if key else None
            if not cat:
                ans(call, "❌", True); return
            if any(stock_phone(e) == phone for c in db["categories"].values() for e in c.get("stock", [])):
                ans(call, "⚠️ Already in stock", True); return
            cat.setdefault("stock", []).append({"phone": phone, "twofa": data.get("twofa", DEFAULT_2FA)})
            save_db(db); PENDING_ADMIN.pop(uid, None)
        ans(call)
        safe_delete(cid, call.message.message_id)
        toast(cid, panel("ADDED", [("📱", f"<code>{esc(phone)}</code>"), ("📁", esc(cat["name"])), ("📦", f"STOCK : {len(cat['stock'])}")], emoji="✅"), 4)
        drop_ui(cid)
    except Exception as e: ans(call, f"Error: {e}", True)

# ─── SCAM ADMIN ───
def render_adm_scam(call):
    db = load_db()
    text = panel("SCAM / FAKE MGMT", [
        ("🔌", f"API SCAM : {len(API_CACHE['scam'])}"),
        ("✍️", f"MANUAL SCAM : {len(db['manual'].get('scam_fake', {}))}"),
        None, ("ℹ️", "MANUAL FAKE/SCAM TAG ADD KARO")], emoji="⚠️")
    kb = None   # buttons neeche keyboard me hain
    edit_ui(text, call.message.chat.id, call.message.message_id, kb)

@cbh(func=lambda c: c.data == "adm_scam")
def cb_adm_scam(call):
    if not is_owner(call.from_user.id): return
    try: render_adm_scam(call); ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "scam_add")
def cb_scam_add(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("ADD SCAM / FAKE", [
        ("📝", "<code>cc | name | phone | price | flag</code>"),
        ("💡", "<code>ind | India Fake | +919876543210 | 50 | 🇮🇳</code>"),
        ("❌", "cancel")], emoji="⚠️"), process_scam_add)

def process_scam_add(message):
    try:
        if step_guard(message): return
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) < 4:
            retry(message, process_scam_add, panel("FORMAT WRONG", [("❌", "<code>cc | name | phone | price | flag</code>")], emoji="⚠️")); return
        cc, cn, phone, price = parts[0].lower(), parts[1], parts[2], safe_float(parts[3])
        flag = parts[4] if len(parts) > 4 else ""
        db = load_db()
        db["manual"].setdefault("scam_fake", {})[f"scam_{cc}_{int(time.time())}"] = {
            "country": cc, "country_name": cn, "phone": phone,
            "price": price, "flag": flag, "added": datetime.now().isoformat()}
        save_db(db)
        clean(message)
        toast(message.chat.id, panel("ADDED", [("✅", esc(cn))], emoji="⚠️"), 3)
        drop_ui(message.chat.id)
    except Exception as e: toast(message.chat.id, f"❌ {esc(e)}", 5)

@cbh(func=lambda c: c.data == "scam_del_list")
def cb_scam_del_list(call):
    if not is_owner(call.from_user.id): return
    try:
        items = load_db()["manual"].get("scam_fake", {})
        if not items:
            ans(call, "No items", True); return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for k, v in list(items.items())[:20]:
            kb.row(IB(f"🗑 {v.get('country_name')} — {v.get('phone')}"[:45], callback_data=f"scam_del_{hid(k)}", style="danger"))
        kb.row(IB("⬅️ Back", callback_data="adm_scam", style=None))
        edit_ui(panel("DELETE SCAM", [("👇", "SELECT ITEM")], emoji="🗑"), call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("scam_del_") and c.data != "scam_del_list")
def cb_scam_del(call):
    if not is_owner(call.from_user.id): return
    with db_lock:
        db = load_db()
        key = unhid(db["manual"].get("scam_fake", {}).keys(), call.data.replace("scam_del_", ""))
        if key: del db["manual"]["scam_fake"][key]; save_db(db)
    ans(call, "Deleted")
    render_adm_scam(call)

# ─── CHANNELS ADMIN ───
def render_adm_channels(call):
    count = len(load_db()["manual"].get("channels", {}))
    kb = None   # buttons neeche keyboard me hain
    edit_ui(panel("CHANNELS MGMT", [("📊", f"{count} ITEMS")], emoji="📢"),
            call.message.chat.id, call.message.message_id, kb)

@cbh(func=lambda c: c.data == "adm_channels")
def cb_adm_channels(call):
    if not is_owner(call.from_user.id): return
    try: render_adm_channels(call); ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "chan_add")
def cb_chan_add(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("ADD CHANNEL", [
        ("📝", "<code>cc | name | title | link | price | flag</code>"),
        ("💡", "<code>ind | India | My Group | https://t.me/EGOXCHAT | 50 | 🇮🇳</code>"),
        ("❌", "cancel")], emoji="📢"), process_chan_add)

def process_chan_add(message):
    try:
        if step_guard(message): return
        parts = [p.strip() for p in (message.text or "").split("|")]
        if len(parts) < 5:
            retry(message, process_chan_add, panel("FORMAT WRONG", [("❌", "<code>cc | name | title | link | price | flag</code>")], emoji="📢")); return
        cc, cn, title, link = parts[0].lower(), parts[1], parts[2], parts[3]
        price = safe_float(parts[4]); flag = parts[5] if len(parts) > 5 else ""
        db = load_db()
        db["manual"].setdefault("channels", {})[f"chan_{cc}_{int(time.time())}"] = {
            "country": cc, "country_name": cn, "title": title, "link": link,
            "price": price, "flag": flag, "added": datetime.now().isoformat()}
        save_db(db)
        clean(message)
        toast(message.chat.id, panel("ADDED", [("✅", esc(title))], emoji="📢"), 3)
        drop_ui(message.chat.id)
    except Exception as e: toast(message.chat.id, f"❌ {esc(e)}", 5)

@cbh(func=lambda c: c.data == "chan_del_list")
def cb_chan_del_list(call):
    if not is_owner(call.from_user.id): return
    try:
        items = load_db()["manual"].get("channels", {})
        if not items:
            ans(call, "No items", True); return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for k, v in list(items.items())[:20]:
            kb.row(IB(f"🗑 {v.get('title', '')}"[:45], callback_data=f"chan_del_{hid(k)}", style="danger"))
        kb.row(IB("⬅️ Back", callback_data="adm_channels", style=None))
        edit_ui(panel("DELETE CHANNEL", [("👇", "SELECT ITEM")], emoji="🗑"), call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("chan_del_") and c.data != "chan_del_list")
def cb_chan_del(call):
    if not is_owner(call.from_user.id): return
    with db_lock:
        db = load_db()
        key = unhid(db["manual"].get("channels", {}).keys(), call.data.replace("chan_del_", ""))
        if key: del db["manual"]["channels"][key]; save_db(db)
    ans(call, "Deleted")
    render_adm_channels(call)

# ─── CATEGORIES ADMIN ───
def render_adm_cats(call):
    cats = load_db().get("categories", {})
    rows = [("📁", f"TOTAL : {len(cats)}"), None]
    for k, c in list(cats.items())[:10]:
        pr = safe_float(c.get("price"))
        rows.append(("▫️", f"{esc(c['name'])} • ₹{money(pr) if pr else 'NO PRICE'} • STOCK {len(c.get('stock', []))}"))
    if not cats: rows.append(("ℹ️", "ABHI KOI CATEGORY NAHI"))
    kb = None   # buttons neeche keyboard me hain
    edit_ui(panel("CATEGORIES", rows, emoji="📁"), call.message.chat.id, call.message.message_id, kb)

@cbh(func=lambda c: c.data == "adm_cats")
def cb_adm_cats(call):
    if not is_owner(call.from_user.id): return
    try: render_adm_cats(call); ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "cat_add")
def cb_cat_add(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("ADD CATEGORY", [
        ("📝", "<code>name | price</code>"), ("💡", "<code>India No Spam | 60</code>"),
        ("ℹ️", "PRICE DALOGE TABHI USERS KO DIKHEGA"), ("❌", "cancel")], emoji="📁"),
        process_cat_add)

def process_cat_add(message):
    try:
        if step_guard(message): return
        parts = [p.strip() for p in (message.text or "").split("|")]
        name = parts[0][:40]
        price = safe_float(parts[1]) if len(parts) > 1 else 0
        if len(name) < 2:
            retry(message, process_cat_add, panel("INVALID", [("❌", "FORMAT: <code>name | price</code>")], emoji="📁")); return
        with db_lock:
            db = load_db()
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"cat{int(time.time())}"
            if key in db["categories"]: key = f"{key}-{int(time.time()) % 10000}"
            db["categories"][key] = {"name": name, "price": price, "stock": []}
            save_db(db)
        clean(message)
        toast(message.chat.id, panel("ADDED", [("✅", esc(name))], emoji="📁"), 3)
        drop_ui(message.chat.id)
    except Exception as e: toast(message.chat.id, f"❌ {esc(e)}", 5)

@cbh(func=lambda c: c.data == "cat_del_list")
def cb_cat_del_list(call):
    if not is_owner(call.from_user.id): return
    try:
        cats = load_db().get("categories", {})
        if not cats:
            ans(call, "No categories", True); return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for k, c in list(cats.items())[:20]:
            kb.row(IB(f"🗑 {c['name']} • {len(c.get('stock', []))}"[:45], callback_data=f"cat_del_{hid(k)}", style="danger"))
        kb.row(IB("⬅️ Back", callback_data="adm_cats", style=None))
        edit_ui(panel("DELETE CATEGORY", [("👇", "SELECT ITEM")], emoji="🗑"), call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("cat_del_") and c.data != "cat_del_list")
def cb_cat_del(call):
    if not is_owner(call.from_user.id): return
    with db_lock:
        db = load_db()
        key = unhid(db["categories"].keys(), call.data.replace("cat_del_", ""))
        if key: del db["categories"][key]; save_db(db)
    ans(call, "Deleted")
    render_adm_cats(call)

@cbh(func=lambda c: c.data == "cat_price")
def cb_cat_price(call):
    if not is_owner(call.from_user.id): return
    cats = load_db().get("categories", {})
    if not cats:
        ans(call, "No categories", True); return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for k, c in list(cats.items())[:20]:
        pr = safe_float(c.get("price"))
        kb.row(IB(f"{c['name']} • ₹{money(pr) if pr else '—'}"[:45], callback_data=f"catpr_{hid(k)}", style="primary"))
    kb.row(IB("⬅️ Back", callback_data="adm_cats", style=None))
    edit_ui(panel("SET PRICE", [("👇", "CATEGORY CHUNO")], emoji="💰"), call.message.chat.id, call.message.message_id, kb)
    ans(call)

@cbh(func=lambda c: c.data.startswith("catpr_"))
def cb_catpr(call):
    if not is_owner(call.from_user.id): return
    key = unhid(load_db().get("categories", {}).keys(), call.data.replace("catpr_", ""))
    if not key:
        ans(call, "Not found", True); return
    ans(call)
    ask(call.message.chat.id, panel("PRICE", [("💰", "NEW PRICE BHEJO (₹)"), ("❌", "cancel")], emoji="💰"),
        lambda m: save_cat_price(m, key))

def save_cat_price(message, key):
    try:
        if step_guard(message): return
        price = safe_float((message.text or "").strip(), 0)
        if price <= 0:
            retry(message, lambda m: save_cat_price(m, key), panel("INVALID", [("❌", "SIRF NUMBER (>0)")], emoji="💰")); return
        with db_lock:
            db = load_db()
            if key in db["categories"]:
                db["categories"][key]["price"] = price; save_db(db)
        clean(message)
        toast(message.chat.id, panel("SAVED", [("✅", f"PRICE : ₹{money(price)}")], emoji="💰"), 3)
        drop_ui(message.chat.id)
    except Exception as e: log.exception(e)

# ─── ORDERS / SALES / BROADCAST / STOCK ───
@cbh(func=lambda c: c.data == "adm_orders")
def cb_adm_orders(call):
    if not is_owner(call.from_user.id): return
    try:
        db = load_db()
        if not db["orders"]:
            ans(call, "No orders", True); return
        rows = [("📦", f"TOTAL : {len(db['orders'])}"), None]
        for o in reversed(list(db["orders"].values())[-10:]):
            rows.append(("🆔", f"{o['oid']} • <code>{esc(o['phone'][:20])}</code> • ₹{money(o['price'])}"))
        edit_ui(panel("ORDERS", rows, emoji="📦"), call.message.chat.id, call.message.message_id, None)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "adm_sales")
def cb_adm_sales(call):
    if not is_owner(call.from_user.id): return
    try:
        orders = list(load_db()["orders"].values())
        total = sum(o.get("price", 0) for o in orders)
        cs = {}
        for o in orders:
            c = o.get("country", "?")
            cs.setdefault(c, {"count": 0, "revenue": 0})
            cs[c]["count"] += 1; cs[c]["revenue"] += o.get("price", 0)
        rows = [("📦", f"ORDERS : {len(orders)}"), ("💰", f"REVENUE : ₹{money(total)}"), None]
        for c, s in sorted(cs.items(), key=lambda x: -x[1]["revenue"])[:8]:
            rows.append(("🌍", f"{esc(c)} : {s['count']} • ₹{money(s['revenue'])}"))
        edit_ui(panel("SALES", rows, emoji="📈"), call.message.chat.id, call.message.message_id, None)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

def ask_broadcast(cid):
    ask(cid, panel("BROADCAST", [("📢", "MESSAGE / PHOTO / VIDEO BHEJO"), ("❌", "cancel")], emoji="📢"), do_broadcast)

@cbh(func=lambda c: c.data == "adm_broadcast")
def cb_adm_broadcast(call):
    if not is_owner(call.from_user.id): return
    ans(call); ask_broadcast(call.message.chat.id)

def do_broadcast(message):
    try:
        if step_guard(message): return
        cid, mid = message.chat.id, message.message_id
        users = [int(u) for u, v in load_db()["users"].items() if not v.get("banned")]
        prompts = PROMPTS.pop(cid, [])
        status = toast(cid, panel("BROADCASTING", [("⏳", f"{len(users)} USERS")], emoji="📢"), 600)

        def worker():
            ok = fail = 0
            for u in users:
                try: bot.copy_message(u, cid, mid); ok += 1
                except Exception: fail += 1
                time.sleep(0.05)
            for p in prompts: safe_delete(cid, p)
            safe_delete(cid, mid)
            if status: safe_delete(cid, status.message_id)
            toast(cid, panel("BROADCAST DONE", [("✅", f"SENT : {ok}"), ("❌", f"FAILED : {fail}")], emoji="📢"), 6)
            drop_ui(cid)
        threading.Thread(target=worker, daemon=True).start()
    except Exception as e: log.exception(f"[broadcast] {e}")

@cbh(func=lambda c: c.data == "adm_view_stock")
def cb_adm_view_stock(call):
    if not is_owner(call.from_user.id): return
    try:
        db = load_db()
        text = panel("STOCK", [
            ("🔴", f"PHISHING : {len(API_CACHE['phishing'])}"), ("🟢", f"GOOD : {len(API_CACHE['good'])}"),
            ("⚠️", f"API SCAM : {len(API_CACHE['scam'])}"),
            ("✍️", f"MANUAL SCAM : {len(db['manual'].get('scam_fake', {}))}"),
            ("📢", f"CHANNELS : {len(db['manual'].get('channels', {}))}"),
            ("⚡", f"READY STOCK : {sum(len(c.get('stock', [])) for c in db.get('categories', {}).values())}")], emoji="📋")
        edit_ui(text, call.message.chat.id, call.message.message_id, None)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

# ─── SETTINGS ───
@cbh(func=lambda c: c.data == "adm_settings")
def cb_adm_settings(call):
    if not is_owner(call.from_user.id): return
    try:
        s = load_db()["settings"]
        text = panel("SETTINGS", [
            ("📱", f"UPI : <code>{esc(s['upi_id'])}</code>"), ("👤", esc(s.get("upi_name", ""))),
            ("💵", f"MIN : ₹{s['min_deposit']}"), ("📞", esc(s["support"])), ("📢", esc(s["channel"]))], emoji="⚙️")
        kb = None   # buttons neeche keyboard me hain
        edit_ui(text, call.message.chat.id, call.message.message_id, kb)
        ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data.startswith("setf_"))
def cb_setf(call):
    if not is_owner(call.from_user.id): return
    key = call.data.replace("setf_", "")
    prompts = {"upi": "📱 NEW UPI ID", "upiname": "👤 NEW NAME", "min": "💵 MIN DEPOSIT",
               "support": "📞 SUPPORT USERNAME", "channel": "📢 CHANNEL LINK"}
    ans(call)
    ask(call.message.chat.id, panel("SETTING", [(prompts.get(key, "VALUE").split(" ", 1)[0], prompts.get(key, "VALUE").split(" ", 1)[-1]),
                                               ("❌", "cancel")], emoji="⚙️"),
        lambda m: save_setting(m, key))

def save_setting(message, key):
    try:
        if step_guard(message): return
        db = load_db()
        s = db["settings"]
        val = (message.text or "").strip()
        if key == "upi": s["upi_id"] = val
        elif key == "upiname": s["upi_name"] = val
        elif key == "min":
            try: s["min_deposit"] = int(val)
            except Exception:
                retry(message, lambda m: save_setting(m, key), panel("INVALID", [("❌", "SIRF NUMBER")], emoji="⚙️")); return
        elif key == "support": s["support"] = val
        elif key == "channel": s["channel"] = val
        save_db(db)
        clean(message)
        toast(message.chat.id, panel("SAVED", [("✅", "SETTING UPDATE HO GAYI")], emoji="⚙️"), 3)
        drop_ui(message.chat.id)
    except Exception as e: print(f"[setting] {e}")

# ─── API MODE ───
def render_api(call):
    api = load_db()["settings"].get("api_mode", {})
    last = datetime.fromtimestamp(API_CACHE["last_sync"]).strftime("%H:%M:%S") if API_CACHE["last_sync"] else "Never"
    text = panel("API MODE", [
        ("📡", f"STATUS : {'ON ✅' if api.get('enabled') else 'OFF ❌'}"),
        ("🌐", f"<code>{esc(api.get('api_url', 'Not set'))}</code>"), None,
        ("🔴", f"PHISHING : {len(API_CACHE['phishing'])}"), ("🟢", f"GOOD : {len(API_CACHE['good'])}"),
        ("⚠️", f"SCAM : {len(API_CACHE['scam'])}"), ("⏱", f"LAST SYNC : {last}")], emoji="🔌")
    kb = None   # buttons neeche keyboard me hain
    edit_ui(text, call.message.chat.id, call.message.message_id, kb)

@cbh(func=lambda c: c.data == "adm_api")
def cb_adm_api(call):
    if not is_owner(call.from_user.id): return
    try: render_api(call); ans(call)
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "api_toggle")
def cb_api_toggle(call):
    if not is_owner(call.from_user.id): return
    db = load_db()
    api = db["settings"].setdefault("api_mode", {})
    api["enabled"] = not api.get("enabled", False)
    save_db(db)
    ans(call, "ON" if api["enabled"] else "OFF")
    if api["enabled"]: threading.Thread(target=sync_api_stock, daemon=True).start()
    render_api(call)

@cbh(func=lambda c: c.data == "api_sync")
def cb_api_sync(call):
    if not is_owner(call.from_user.id): return
    try:
        ans(call, "⏳ Syncing...")
        ok = sync_api_stock()
        if ok:
            text = panel("SYNCED", [
                ("🔴", f"PHISHING : {len(API_CACHE['phishing'])}"), ("🟢", f"GOOD : {len(API_CACHE['good'])}"),
                ("⚠️", f"SCAM : {len(API_CACHE['scam'])}"), None,
                ("🌍", f"P={len(API_CACHE['phishing_countries'])} G={len(API_CACHE['good_countries'])} S={len(API_CACHE['scam_countries'])}")], emoji="✅")
        else:
            text = panel("SYNC FAILED", [("❌", esc(API_CACHE.get("last_error") or "Unknown"))], emoji="❌")
        edit_ui(text, call.message.chat.id, call.message.message_id, back_kb("adm_api"))
    except Exception as e: ans(call, f"Error: {e}", True)

@cbh(func=lambda c: c.data == "api_set_url")
def cb_api_set_url(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("API URL", [("🌐", "BASE URL BHEJO"), ("❌", "cancel")], emoji="🔌"),
        lambda m: save_api_field(m, "api_url"))

@cbh(func=lambda c: c.data == "api_set_key")
def cb_api_set_key(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("API KEY", [("🔑", "KEY BHEJO"), ("❌", "cancel")], emoji="🔌"),
        lambda m: save_api_field(m, "api_key"))

def save_api_field(message, field):
    try:
        if step_guard(message): return
        db = load_db()
        api = db["settings"].setdefault("api_mode", {})
        val = (message.text or "").strip()
        if field == "api_url" and val.endswith("/api"): val = val[:-4]
        api[field] = val
        save_db(db)
        clean(message)  # key chat me nahi rehti
        toast(message.chat.id, panel("UPDATED", [("✅", field.upper())], emoji="🔌"), 3)
        drop_ui(message.chat.id)
        if api.get("api_url") and api.get("api_key"):
            threading.Thread(target=sync_api_stock, daemon=True).start()
    except Exception as e: print(f"[api_field] {e}")

# ═══════════════════════════════════════════════
#  ADMIN — USERS (find / balance / ban)
# ═══════════════════════════════════════════════
def parse_uid(text):
    m = re.search(r"\d{5,}", text or "")
    return m.group(0) if m else None

def user_card(uid):
    db = load_db()
    u = db["users"].get(str(uid))
    if not u: return None
    n_orders = len([o for o in db["orders"].values() if o["uid"] == str(uid)])
    return panel("USER INFO", [
        ("🆔", f"<code>{uid}</code>"), ("👤", esc(u.get("name") or "-")),
        ("💰", f"BALANCE : ₹{money(u.get('balance', 0))}"), ("📊", f"SPENT : ₹{money(u.get('total_spent', 0))}"),
        ("📦", f"ORDERS : {n_orders}"), ("🚫", "BANNED : YES" if u.get("banned") else "BANNED : NO")], emoji="👤")

@cbh(func=lambda c: c.data == "adm_users")
def cb_adm_users(call):
    if not is_owner(call.from_user.id): return
    db = load_db()
    users = db["users"]
    top = sorted(users.items(), key=lambda x: -x[1].get("total_spent", 0))[:5]
    rows = [("👥", f"TOTAL : {len(users)}"), ("🚫", f"BANNED : {len([u for u in users.values() if u.get('banned')])}"),
            ("💵", f"BALANCE : ₹{money(sum(u.get('balance', 0) for u in users.values()))}"), None, ("🏆", "TOP BUYERS")]
    for uid, u in top:
        rows.append(("▫️", f"<code>{uid}</code> • ₹{money(u.get('total_spent', 0))}"))
    edit_ui(panel("USERS", rows, emoji="👥"), call.message.chat.id, call.message.message_id, None)
    ans(call)

@cbh(func=lambda c: c.data == "usr_find")
def cb_usr_find(call):
    if not is_owner(call.from_user.id): return
    ans(call)
    ask(call.message.chat.id, panel("FIND USER", [("🆔", "USER ID BHEJO"), ("❌", "cancel")], emoji="🔍"), process_usr_find)

def process_usr_find(message):
    try:
        if step_guard(message): return
        uid = parse_uid(message.text)
        card = user_card(uid) if uid else None
        if not card:
            retry(message, process_usr_find, panel("NOT FOUND", [("❌", "USER NAHI MILA — ID DOBARA BHEJO")], emoji="🔍")); return
        clean(message)
        send_ui(message.chat.id, card)
    except Exception as e: log.exception(e)

@cbh(func=lambda c: c.data in ("usr_balp", "usr_balm"))
def cb_usr_bal(call):
    if not is_owner(call.from_user.id): return
    sign = 1 if call.data == "usr_balp" else -1
    ans(call)
    ask(call.message.chat.id, panel("ADD BALANCE" if sign > 0 else "CUT BALANCE",
        [("📝", "<code>user_id amount</code>"), ("💡", "<code>123456789 100</code>"), ("❌", "cancel")], emoji="💰"),
        lambda m: process_usr_bal(m, sign))

def process_usr_bal(message, sign):
    try:
        if step_guard(message): return
        parts = (message.text or "").split()
        uid = parse_uid(parts[0]) if parts else None
        amount = safe_float(parts[1], 0) if len(parts) > 1 else 0
        if not uid or amount <= 0:
            retry(message, lambda m: process_usr_bal(m, sign), panel("FORMAT WRONG", [("❌", "<code>user_id amount</code>")], emoji="💰")); return
        with db_lock:
            db = load_db()
            if uid not in db["users"]:
                clean(message); toast(message.chat.id, "❌ User not found"); return
            u = db["users"][uid]
            u["balance"] = max(0, u.get("balance", 0) + sign * amount)
            save_db(db)
            bal = u["balance"]
        clean(message)
        toast(message.chat.id, panel("DONE", [("✅", f"{'+' if sign > 0 else '-'}₹{money(amount)} • <code>{uid}</code>"),
                                              ("💼", f"BALANCE : ₹{money(bal)}")], emoji="💰"), 5)
        drop_ui(message.chat.id)
        try:
            bot.send_message(int(uid), panel("BALANCE UPDATED", [("💰", f"{'ADDED' if sign > 0 else 'DEDUCTED'} : ₹{money(amount)}"),
                                                                 ("💼", f"BALANCE : ₹{money(bal)}")], emoji="💰"))
        except Exception: pass
    except Exception as e: log.exception(e)

@cbh(func=lambda c: c.data in ("usr_ban", "usr_unban"))
def cb_usr_ban(call):
    if not is_owner(call.from_user.id): return
    flag = call.data == "usr_ban"
    ans(call)
    ask(call.message.chat.id, panel("BAN USER" if flag else "UNBAN USER", [("🆔", "USER ID BHEJO"), ("❌", "cancel")], emoji="🚫"),
        lambda m: process_usr_ban(m, flag))

def process_usr_ban(message, flag):
    try:
        if step_guard(message): return
        uid = parse_uid(message.text)
        if not uid or is_owner(uid):
            retry(message, lambda m: process_usr_ban(m, flag), panel("INVALID", [("❌", "SAHI USER ID BHEJO")], emoji="🚫")); return
        with db_lock:
            db = load_db()
            if uid not in db["users"]:
                clean(message); toast(message.chat.id, "❌ User not found"); return
            db["users"][uid]["banned"] = flag; save_db(db)
        clean(message)
        toast(message.chat.id, panel("DONE", [("🚫" if flag else "✅", f"{'BANNED' if flag else 'UNBANNED'} • <code>{uid}</code>")], emoji="👥"), 4)
        drop_ui(message.chat.id)
    except Exception as e: log.exception(e)

# ═══════════════════════════════════════════════
#  STARTUP
# ═══════════════════════════════════════════════
@bot.message_handler(content_types=["text", "photo", "video", "document", "audio", "voice", "sticker",
                                    "animation", "video_note", "contact", "location"])
def stray_cleanup(message):
    """Koi flow active nahi -> faltu msg delete (chat saaf rahe)."""
    if message.chat.type == "private":
        safe_delete(message.chat.id, message.message_id)

if __name__ == "__main__":
    log.info(f"{BRAND} starting...")
    threading.Thread(target=api_sync_loop, daemon=True).start()

    def initial_sync():
        try:
            if load_db()["settings"].get("api_mode", {}).get("enabled"):
                sync_api_stock()
                print(f"[✓] P={len(API_CACHE['phishing'])}, G={len(API_CACHE['good'])}, S={len(API_CACHE['scam'])}")
        except Exception as e: print(f"[!] {e}")
    threading.Thread(target=initial_sync, daemon=True).start()

    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except Exception as e:
            log.error(f"polling: {e}"); time.sleep(5)
