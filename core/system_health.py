"""System Health Monitor - Termux Compatible"""
from datetime import datetime


class SystemHealth:
    """Monitor system health and resources"""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.status = "HEALTHY"
        self.last_check = None
        self.psutil_available = False

        try:
            import psutil
            self.psutil_available = True
        except ImportError:
            self.logger.warning("psutil not available - using basic health check")

    def check(self):
        """Run health check"""
        self.last_check = datetime.now()

        if self.psutil_available:
            try:
                import psutil
                health = {
                    "status": "HEALTHY",
                    "cpu_percent": psutil.cpu_percent(),
                    "memory_percent": psutil.virtual_memory().percent,
                    "disk_percent": psutil.disk_usage('/').percent,
                    "timestamp": self.last_check.isoformat()
                }
                if health["cpu_percent"] > 90 or health["memory_percent"] > 90:
                    health["status"] = "CRITICAL"
                elif health["cpu_percent"] > 70 or health["memory_percent"] > 70:
                    health["status"] = "WARNING"
                self.status = health["status"]
                return health
            except Exception:
                pass

        # Fallback: basic health check without psutil
        import os
        try:
            stat = os.statvfs('/')
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            disk_percent = ((total - free) / total) * 100 if total > 0 else 0
        except Exception:
            disk_percent = 0

        health = {
            "status": "HEALTHY",
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": round(disk_percent, 1),
            "timestamp": self.last_check.isoformat()
        }

        if disk_percent > 90:
            health["status"] = "WARNING"

        self.status = health["status"]
        return health

    def is_healthy(self):
        """Check if system is healthy"""
        return self.status in ("HEALTHY", "WARNING")
