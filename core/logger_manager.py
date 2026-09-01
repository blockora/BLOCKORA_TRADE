"""Logger Manager - Centralized logging with loguru"""
import sys
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger


class LoggerManager:
    """Manages application logging"""

    def __init__(self, config):
        self.config = config
        self.log_dir = Path(config.get("logging.directory", "./logs"))

    def _cleanup_old_log_folders(self):
        """Auto-rotation: delete log folders older than 3 days (keep today + last 2 days)"""
        try:
            cutoff = datetime.now().date() - timedelta(days=3)
            deleted = 0
            for item in self.log_dir.iterdir():
                if item.is_dir():
                    try:
                        folder_date = datetime.strptime(item.name, "%Y-%m-%d").date()
                        if folder_date < cutoff:
                            shutil.rmtree(item)
                            deleted += 1
                    except ValueError:
                        # Not a date-named folder, skip
                        pass
            if deleted:
                logger.info(f"Log rotation: deleted {deleted} old log folders")
        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")

    def setup(self):
        """Setup logging configuration"""
        # Cleanup old log folders on startup
        self._cleanup_old_log_folders()
        
        logger.remove()

        if self.config.get_bool("logging.console_output", True):
            logger.add(
                sys.stderr,
                level=self.config.get("logging.level", "INFO"),
                format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
            )

        self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.add(
            str(self.log_dir / "system.log"),
            rotation="10 MB",
            retention="30 days",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )

        logger.add(
            str(self.log_dir / "error.log"),
            rotation="10 MB",
            retention="60 days",
            level="ERROR",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )

    def info(self, message):
        logger.info(message)

    def warning(self, message):
        logger.warning(message)

    def error(self, message):
        logger.error(message)

    def critical(self, message):
        logger.critical(message)

    def debug(self, message):
        logger.debug(message)
