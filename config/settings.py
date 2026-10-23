import json
import os
from pathlib import Path
from typing import List, Dict, Any

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 浏览器会话缓存目录
SESSIONS_DIR = BASE_DIR / ".sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# 日志与截图保存目录
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# 基础 URL
BING_URL = "https://www.bing.com"
REWARDS_URL = "https://rewards.bing.com/dashboard"
LOGIN_URL = "https://login.live.com"

# 任务与搜索参数配置
DEFAULT_PC_SEARCH_COUNT = 30       # PC 端搜索次数（每次 3 分，上限通常 90 分）
DEFAULT_MOBILE_SEARCH_COUNT = 20   # 移动端搜索次数（每次 3 分，上限通常 60 分）
SEARCH_INTERVAL = (6, 15)          # 单次搜索随机等待间隔 (秒)
COOLDOWN_SEARCH_COUNT = 4          # 搜索批次冷却触发阈值（每搜多少次进入小冷却）
COOLDOWN_SLEEP_SECONDS = 300       # 批次冷却等待秒数（默认 5 分钟，应对微软 Rewards 搜索限制）

# 浏览器配置
DEFAULT_HEADLESS = True            # 默认无头模式
DEFAULT_TIMEOUT = 30000            # 页面导航和等待超时 (毫秒)
PROXY_SERVER = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or None

# 推送配置
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY", "")
CUSTOM_WEBHOOK = os.getenv("CUSTOM_WEBHOOK", "")

# 远程监控看板自动汇报配置 (可选)
DASHBOARD_REPORT_URL = os.getenv("DASHBOARD_REPORT_URL", "")
DASHBOARD_REPORT_TOKEN = os.getenv("DASHBOARD_REPORT_TOKEN", "")

def load_accounts() -> List[Dict[str, Any]]:
    """
    加载账号配置，具有多种来源降级与格式兼容能力：
    1. 优先从环境变量 ACCOUNTS_CONFIG 读取 JSON 字符串（GitHub Actions Secrets 推荐）
    2. 尝试读取根目录 accounts.json
    3. 尝试读取 config/accounts.json
    兼容两种数据格式：
    - 旧版分组字典格式：{"group1": [{"email": "...", "password": "..."}], ...}
    - 现代化列表格式：{"accounts": [{"email": "...", "password": "..."}]} 或 [{"email": "...", "password": "..."}]
    """
    raw_data = None

    # 1. 尝试环境变量
    env_config = os.getenv("ACCOUNTS_CONFIG")
    if env_config and env_config.strip():
        try:
            raw_data = json.loads(env_config.strip())
        except Exception as e:
            print(f"[配置错误] 环境变量 ACCOUNTS_CONFIG JSON 解析失败: {e}")

    # 2. 尝试本地配置文件
    if not raw_data:
        candidate_paths = [
            BASE_DIR / "accounts.json",
            BASE_DIR / "config" / "accounts.json"
        ]
        for path in candidate_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    break
                except Exception as e:
                    print(f"[配置错误] 读取配置文件 {path} 失败: {e}")

    if not raw_data:
        return []

    # 规范化转换为账号列表
    accounts: List[Dict[str, Any]] = []

    if isinstance(raw_data, list):
        accounts = raw_data
    elif isinstance(raw_data, dict):
        if "accounts" in raw_data and isinstance(raw_data["accounts"], list):
            accounts = raw_data["accounts"]
        else:
            # 兼容 group 分组格式
            for group_name, acc_list in raw_data.items():
                if isinstance(acc_list, list):
                    for acc in acc_list:
                        if isinstance(acc, dict) and "email" in acc:
                            acc_copy = dict(acc)
                            acc_copy.setdefault("group", group_name)
                            accounts.append(acc_copy)

    # 过滤无效项（只要包含 email 即为有效账号，支持纯 Session 免密模式）
    valid_accounts = [
        acc for acc in accounts
        if isinstance(acc, dict) and acc.get("email")
    ]
    return valid_accounts

