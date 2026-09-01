"""Configuration Manager - Central configuration handling"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv


class ConfigManager:
    """Manages all application configuration"""

    def __init__(self):
        self.config = {}
        self.env_config = {}
        self.project_root = Path(__file__).parent.parent

    def load(self):
        """Load all configuration"""
        load_dotenv(self.project_root / ".env")
        self._load_env()
        self._load_settings()
        self._load_risk_config()
        return self.config

    def _load_env(self):
        """Load environment variables"""
        env_keys = [
            "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD",
            "ANGEL_TOTP_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "DATABASE_PATH", "LOG_LEVEL", "MODE",
            "TELEGRAM_CHANNEL_ID", "UPI_ID", "UPI_NAME", "SUBSCRIPTION_PRICE"
        ]
        for key in env_keys:
            value = os.getenv(key)
            if value:
                self.env_config[key] = value

    def _load_settings(self):
        """Load settings.json"""
        settings_path = self.project_root / "config" / "settings.json"
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                self.config = json.load(f)
        else:
            raise FileNotFoundError(f"Settings file not found: {settings_path}")

    def _load_risk_config(self):
        """Load risk configuration"""
        risk_path = self.project_root / "config" / "risk.json"
        if risk_path.exists():
            with open(risk_path, 'r') as f:
                self.config["risk"] = json.load(f)

    def get(self, key, default=None):
        """Get configuration value with dot notation support"""
        if key in self.env_config:
            return self.env_config[key]
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_int(self, key, default=0):
        """Get integer configuration value"""
        try:
            return int(self.get(key, default))
        except (ValueError, TypeError):
            return default

    def now(self):
        """P1-3: Config-driven timezone-aware current time (Asia/Kolkata default)"""
        from datetime import datetime
        try:
            import pytz
            tz_name = self.get("timezone", "Asia/Kolkata")
            tz = pytz.timezone(tz_name)
            return datetime.now(tz)
        except Exception:
            return datetime.now()

    def get_float(self, key, default=0.0):
        """Get float configuration value"""
        try:
            return float(self.get(key, default))
        except (ValueError, TypeError):
            return default

    def get_bool(self, key, default=False):
        """Get boolean configuration value"""
        value = self.get(key, default)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes')
        return bool(value)
