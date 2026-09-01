"""Telegram Bot Engine - Alert delivery via Telegram"""
import requests
from datetime import datetime


class TelegramBot:
    """Manages Telegram notifications"""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.bot_token = config.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = config.get("TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._fail_logged = False
        self.channel_id = str(config.get("TELEGRAM_CHANNEL_ID", "") or "")

    def initialize(self):
        """Initialize Telegram bot"""
        self.connected = False  # P1-2: default not connected
        if not self.bot_token or not self.chat_id:
            self.logger.warning("Telegram not configured - skipping")
            return
        try:
            response = requests.get(f"{self.base_url}/getMe", timeout=10)
            if response.status_code == 200:
                self.connected = True  # P1-2: mark connected
                self.logger.info("Telegram Bot connected")
            else:
                self.logger.error(f"Telegram Bot connection failed: {response.status_code}")
        except Exception as e:
            self.logger.error(f"Telegram init error: {str(e)[:80]}")

    def send_message(self, text, parse_mode="HTML"):
        """Send message to Telegram with STRICT timeout to prevent freezing"""
        if not self.bot_token or not self.chat_id:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            data = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}
            # 🔥 STRICT TIMEOUT: 3 sec connect, 5 sec read. Prevents script freezing!
            response = requests.post(url, json=data, timeout=(3, 5))
            if response.status_code == 200:
                self._fail_logged = False
                return True
            return False
        except Exception:
            if not self._fail_logged:
                self.logger.warning("Telegram timeout/blocked. Skipping to protect analysis loop.")
                self._fail_logged = True
            return False

    def send_channel(self, text):
        """VIP Channel me signal post karta hai (subscribers ke liye)"""
        if not self.channel_id:
            return False
        try:
            r = requests.post(f"{self.base_url}/sendMessage",
                              json={"chat_id": self.channel_id, "text": text, "parse_mode": "HTML"},
                              timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def send_recommendation(self, rec):
        """Send trade recommendation — FIX #8: clear source labels, no fake live"""
        action = rec.get("action", "N/A")
        price_status = rec.get("price_status", "REAL")
        buy_blocked = rec.get("buy_blocked", False)
        blocked_reason = rec.get("buy_blocked_reason", "")

        # 🎯 FIX #8: Source label (REAL = no label, ESTIMATED/STALE/INVALID = shown)
        _src_labels = {
            "REAL": "",
            "ESTIMATED": " <i>(estimated)</i>",
            "STALE": " <i>(stale)</i>",
            "INVALID": " <i>(invalid)</i>",
            "MISSING": " <i>(missing)</i>",
        }
        src_label = _src_labels.get(price_status, f" <i>({price_status})</i>")

        # Header — BUY blocked ka banner
        if buy_blocked or price_status != "REAL":
            header = (
                f"⚠️ <b>BLOCKORA_TRADE — BUY BLOCKED</b>\n"
                f"{'='*30}\n"
                f"🚫 <b>Reason:</b> {blocked_reason or 'Real-time option LTP unavailable/stale'}\n"
                f"📌 <i>Estimated premium is NOT eligible for BUY.</i>\n\n"
            )
        else:
            header = (
                f"📊 <b>BLOCKORA_TRADE SIGNAL</b>\n"
                f"{'='*30}\n"
            )

        msg = (
            f"{header}"
            f"📅 Date: {rec.get('date', 'N/A')}\n"
            f"⏰ Time: {rec.get('time', 'N/A')}\n"
            f"📈 Bias: {rec.get('bias', 'N/A')}\n\n"
            f"🎯 <b>ACTION:</b> {action}\n"
            f"🏷️ <b>Price Source:</b> {price_status}\n"
            f"📊 Confidence: {rec.get('confidence', 0)}% ({rec.get('grade', 'N/A')})\n\n"
            f"💰 Entry: {rec.get('entry', 'N/A')}{src_label}\n"
            f"🛑 Stop Loss: {rec.get('stop_loss', 'N/A')}\n"
            f"🎯 Target 1: {rec.get('target_1', 'N/A')}\n"
            f"🎯 Target 2: {rec.get('target_2', 'N/A')}\n"
            f"🎯 Target 3: {rec.get('target_3', 'N/A')}\n\n"
            f"📊 LTP Source: {rec.get('premium_source', 'REAL')}\n"
            f"📊 Volume Source: {rec.get('volume_source', 'UNKNOWN')}\n"
            f"📊 IV Source: {rec.get('iv_source', 'UNKNOWN')}\n"
            f"📊 Bid/Ask Source: {rec.get('bid_source', 'UNKNOWN')}/{rec.get('ask_source', 'UNKNOWN')}\n"
            f"⏱️ Holding: {rec.get('holding_time', 'N/A')}\n"
            f"⚠️ Risk: {rec.get('risk', 'N/A')}\n\n"
            f"📋 <b>REASONS:</b>\n"
        )
        for reason in rec.get("reasons", [])[:10]:
            msg += f"• {reason}\n"
        msg += f"\n{'='*30}\n⚠️ <i>Recommendation Only - User decides trade</i>"

        # 🎯 FIX #8: Blocked WATCHLIST sirf OWNER ko, VIP channel me nahi
        if buy_blocked or price_status != "REAL":
            return self.send_message(msg)
        self.send_channel(msg)
        return self.send_message(msg)

    def send_no_trade(self, reasons):
        pass # NO_TRADE spam disabled

    def send_system_status(self, title, message):
        """Send system status update"""
        text = (
            f"🔧 <b>{title}</b>\n"
            f"{'='*30}\n"
            f"{message}\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(text)

    def send_session_summary(self, summary):
        """Send end-of-day session summary"""
        msg = (
            f"📊 <b>DAILY SESSION SUMMARY</b>\n"
            f"{'='*30}\n"
            f"📅 Date: {summary.get('date', 'N/A')}\n"
            f"🔄 Total Cycles: {summary.get('total_cycles', 0)}\n"
            f"📈 Signals: {summary.get('signals_generated', 0)}\n"
            f"📊 Avg Confidence: {summary.get('avg_confidence', 0):.1f}%\n"
            f"{'='*30}"
        )
        return self.send_message(msg)

    # 🔥 VOLATILITY ALERTS — HIGH vs EXTREME (graduated policy)
    def send_extreme_volatility_alert(self, regime=None):
        """EXTREME_VOLATILITY: market unstable -> NO new positions."""
        regime = regime or {}
        adx = regime.get("adx", 0)
        rsi = regime.get("rsi", 0)
        atr_pct = regime.get("atr_pct", 0)
        msg = (
            f"🚨 <b>EXTREME VOLATILITY — NO TRADE</b>\n"
            f"{'='*30}\n"
            f"⚠️ Market unstable. No new positions.\n\n"
            f"📊 ADX: {adx:.1f}\n"
            f"📊 RSI: {rsi:.1f}\n"
            f"📊 ATR%: {atr_pct:.2f}\n"
            f"{'='*30}"
        )
        return self.send_message(msg)

    def send_high_volatility_alert(self, flags=None, reject=None, position_pct=0.5):
        """HIGH_VOLATILITY: trade allowed with intraday restrictions (scalp mode)."""
        flags = flags or []
        reject = reject or []
        lines = []
        if flags:
            lines.append("✅ <b>Intraday Rules Passed:</b>")
            for f in flags[:10]:
                lines.append(f"  • {f}")
        if reject:
            lines.append("🚫 <b>Blocked by rules:</b>")
            for r in reject[:10]:
                lines.append(f"  • {r}")
        msg = (
            f"⚠️ <b>HIGH VOLATILITY — SCALP MODE</b>\n"
            f"{'='*30}\n"
            f"📏 Position: {int(position_pct*100)}% of normal\n"
            f"⏱️ Max hold: 30 min\n"
            f"{chr(10).join(lines)}\n"
            f"{'='*30}"
        )
        return self.send_message(msg)
