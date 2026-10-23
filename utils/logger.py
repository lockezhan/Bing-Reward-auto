import logging
import sys
import time
from pathlib import Path
from config.settings import LOGS_DIR, SCREENSHOTS_DIR

class ColoredFormatter(logging.Formatter):
    """终端彩色日志格式化器"""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

    FORMATS = {
        logging.DEBUG: f"[DEBUG] %(asctime)s - %(message)s",
        logging.INFO: f"{GREEN}[INFO]{RESET} %(asctime)s - %(message)s",
        logging.WARNING: f"{YELLOW}[WARN]{RESET} %(asctime)s - %(message)s",
        logging.ERROR: f"{RED}[ERROR]{RESET} %(asctime)s - %(message)s",
        logging.CRITICAL: f"{RED}[FATAL]{RESET} %(asctime)s - %(message)s",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, "%(asctime)s - %(message)s")
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

def setup_logger(name: str = "bing_rewards") -> logging.Logger:
    """初始化并返回日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)

        # 文件 Handler
        log_file = LOGS_DIR / f"bing_{time.strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger

logger = setup_logger()

def save_error_screenshot(page, prefix: str = "error") -> str:
    """保存错误截图供故障排查"""
    try:
        timestamp = int(time.time())
        filename = f"{prefix}_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        page.screenshot(path=str(filepath), full_page=False, timeout=5000)
        logger.info(f"已保存调试截图至: {filepath}")
        return str(filepath)
    except Exception as e:
        logger.warning(f"保存调试截图失败: {e}")
        return ""

