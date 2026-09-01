"""System Shutdown Handler"""
from datetime import datetime


class SystemShutdown:
    """Handle graceful system shutdown"""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def execute(self, market_engine=None, option_engine=None, db=None, telegram=None):
        """Execute graceful shutdown"""
        self.logger.info("Starting graceful shutdown...")
        try:
            if market_engine:
                market_engine.shutdown()
                self.logger.info("Market engine closed")
            if option_engine:
                option_engine.shutdown()
                self.logger.info("Option engine closed")
            if db:
                db.backup()
                db.close()
                self.logger.info("Database saved and closed")
            if telegram:
                telegram.send_system_status(
                    "SYSTEM SHUTDOWN",
                    f"BLOCKORA_TRADE shutdown at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            self.logger.info("Graceful shutdown complete")
        except Exception as e:
            self.logger.error(f"Shutdown error: {str(e)}")
