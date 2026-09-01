"""Subscription Manager - Premium ₹499/month (Manual UPI Approval)"""
import threading
import time
import requests
from datetime import datetime


class SubscriptionManager:
    def __init__(self, config, logger, db, bot):
        self.config = config
        self.logger = logger
        self.db = db
        self.bot = bot
        self.token = config.get("TELEGRAM_BOT_TOKEN", "")
        self.base = f"https://api.telegram.org/bot{self.token}"
        self.owner_id = str(config.get("TELEGRAM_CHAT_ID", ""))
        self.channel_id = str(config.get("TELEGRAM_CHANNEL_ID", "") or "")
        self.upi_id = config.get("UPI_ID", "yourname@upi")
        self.price = str(config.get("SUBSCRIPTION_PRICE", "499"))
        self.offset = 0
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.logger.info("Subscription Manager started (polling)")

    def stop(self):
        self.running = False

    def _api(self, method, payload):
        try:
            r = requests.post(f"{self.base}/{method}", json=payload, timeout=10)
            return r.json()
        except Exception:
            return None

    def _send(self, chat_id, text):
        self._api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

    def _poll_loop(self):
        while self.running:
            try:
                r = requests.get(f"{self.base}/getUpdates",
                                 params={"offset": self.offset, "timeout": 15}, timeout=20)
                for u in r.json().get("result", []):
                    self.offset = u["update_id"] + 1
                    self._route(u)
                self._expiry_check()
            except Exception:
                time.sleep(3)

    def _route(self, u):
        # 🔥 Channel auto-detect (bot admin hai to channel_post milta hai)
        cp = u.get("channel_post")
        if cp:
            cid = str(cp.get("chat", {}).get("id", ""))
            if cid and not self.channel_id:
                self.channel_id = cid
                self.bot.channel_id = cid
                self.logger.info(f"VIP Channel auto-detected: {cid}")
            return

        msg = u.get("message")
        if not msg:
            return
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        frm = msg.get("from", {})
        user_id = str(frm.get("id", ""))
        username = frm.get("username", "")
        first_name = frm.get("first_name", "")
        if not text:
            return

        if text == "/start":
            self.db.upsert_user(user_id, username, first_name)
            self._send(chat_id,
                f"🤖 <b>BLOCKORA_TRADE VIP</b>\nAI-powered NIFTY options signals.\n\n"
                f"💰 Plan: ₹{self.price}/month\n👉 /subscribe se payment shuru karein.")
        elif text == "/subscribe":
            self.db.upsert_user(user_id, username, first_name)
            self._send(chat_id,
                f"💳 <b>Payment Instructions</b>\n\n"
                f"1️⃣ UPI par ₹{self.price} bhejein:\n<code>{self.upi_id}</code>\n\n"
                f"2️⃣ Payment ke baad <b>UTR / Transaction ID</b> yahan bhejein.\n\n"
                f"✅ Verify hote hi aapko VIP channel me add kar denge.")
        elif text == "/status":
            row = self.db.get_user(user_id)
            if row and row["status"] == "ACTIVE":
                self._send(chat_id, f"✅ Subscription ACTIVE\n📅 Expiry: {row['expiry_date']}")
            else:
                self._send(chat_id, "❌ Koi active subscription nahi. /subscribe karein.")
        elif text.startswith("/approve") and chat_id == self.owner_id:
            self._approve(text, chat_id)
        elif text.startswith("/remove") and chat_id == self.owner_id:
            self._remove(text, chat_id)
        elif text == "/subscribers" and chat_id == self.owner_id:
            self._list(chat_id)
        elif chat_id != self.owner_id and len(text) >= 6:
            self._utr(chat_id, user_id, username, first_name, text)

    def _utr(self, chat_id, user_id, username, first_name, utr):
        self.db.add_pending(user_id, username, first_name, utr, self.price)
        self._send(chat_id, "📨 UTR mil gaya! Verification chal rahi hai (5-10 min). Approve hote hi VIP channel me add ho jayenge.")
        self._send(self.owner_id,
            f"💳 <b>NAYI PAYMENT CLAIM</b>\n👤 {first_name} (@{username})\n"
            f"🆔 <code>{user_id}</code>\n🔢 UTR: <code>{utr}</code>\n💵 ₹{self.price}\n\n"
            f"UPI app me verify karein, phir likhein:\n/approve {user_id}")

    def _approve(self, text, chat_id):
        parts = text.split()
        if len(parts) < 2:
            self._send(chat_id, "Usage: /approve <user_id>")
            return
        uid = parts[1]

        # P1-5: Channel access PEHLE, DB activate BAAD ME (safer order)
        if not self.channel_id:
            self._send(chat_id, "⚠️ Channel detect nahi hua. Pehle channel me koi ek message post karein (bot admin ho).")
            return

        access_granted = False
        access_method = ""
        invite_link = None

        # Try 1: Direct addChatMember
        res = self._api("addChatMember", {"chat_id": self.channel_id, "user_id": int(uid)})
        if res and res.get("ok"):
            access_granted = True
            access_method = "direct"
        else:
            # Try 2: One-time invite link fallback
            link_res = self._api("createChatInviteLink", {
                "chat_id": self.channel_id,
                "member_limit": 1,
                "expire_date": int(time.time()) + 86400,
            })
            if link_res and link_res.get("ok"):
                access_granted = True
                access_method = "invite"
                invite_link = link_res["result"]["invite_link"]
            else:
                err = (res or {}).get("description", "no response")
                self._send(chat_id, f"❌ Channel access fail: {err} | channel={self.channel_id}")
                self._send(chat_id, "⚠️ DB activate nahi hua — retry karein")
                return

        # Ab DB activate karo (channel access confirmed)
        expiry = self.db.activate(uid, days=30)

        if access_method == "direct":
            self._send(chat_id, f"✅ {uid} added + active till {expiry}")
            self._send(int(uid), f"🎉 <b>Welcome to BLOCKORA VIP!</b>\n📅 Active till: {expiry}\n\nAb har signal channel me milega. 🚀")
        else:
            self._send(chat_id, f"⚠️ Direct add fail. 1-use invite link bheja gaya. Active till {expiry}")
            self._send(int(uid), f"🎉 <b>Payment Verified! Welcome to BLOCKORA VIP</b>\n\n"
                            f"🎟️ VIP Channel join link (sirf 1 use, 24 hr valid):\n{invite_link}\n\n"
                            f"📅 Subscription active till: {expiry}")

    def _remove(self, text, chat_id):
        parts = text.split()
        if len(parts) < 2:
            self._send(chat_id, "Usage: /remove <user_id>")
            return
        uid = parts[1]
        if self.channel_id:
            self._api("banChatMember", {"chat_id": self.channel_id, "user_id": int(uid)})
            self._api("unbanChatMember", {"chat_id": self.channel_id, "user_id": int(uid), "only_if_banned": True})
        self.db.expire(uid)
        self._send(chat_id, f"🗑️ {uid} removed + expired.")

    def _list(self, chat_id):
        rows = self.db.list_active()
        if not rows:
            self._send(chat_id, "Koi active subscriber nahi.")
            return
        lines = [f"👥 <b>ACTIVE SUBSCRIBERS ({len(rows)})</b>"]
        for r in rows:
            lines.append(f"• {r['first_name']} (@{r['username']}) | 🆔 {r['user_id']} | 📅 {r['expiry_date']}")
        self._send(chat_id, "\n".join(lines))

    def _expiry_check(self):
        today = datetime.now().strftime("%Y-%m-%d")
        for r in self.db.list_active():
            if r["expiry_date"] <= today:
                if self.channel_id:
                    self._api("banChatMember", {"chat_id": self.channel_id, "user_id": int(r["user_id"])})
                    self._api("unbanChatMember", {"chat_id": self.channel_id, "user_id": int(r["user_id"]), "only_if_banned": True})
                self.db.expire(r["user_id"])
                self._send(r["user_id"], "❌ Subscription EXPIRED. Renew: /subscribe")
                self._send(self.owner_id, f"⏳ {r['user_id']} expired & removed.")
            else:
                days = (datetime.strptime(r["expiry_date"], "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
                if days in (3, 1) and r.get("last_reminder") != today:
                    self._send(r["user_id"], f"⚠️ {days} din me subscription expire hogi. Renew: /subscribe")
                    self.db.set_reminder(r["user_id"], today)
