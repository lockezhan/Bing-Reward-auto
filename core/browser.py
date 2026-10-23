import hashlib
from pathlib import Path
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page
from config.settings import (
    DEFAULT_HEADLESS,
    DEFAULT_TIMEOUT,
    PROXY_SERVER,
    SESSIONS_DIR
)
from utils.logger import logger

# 常用反指纹检测注入脚本
STEALTH_JS = """
// 隐藏 webdriver 标志
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// 禁用 WebAuthn 通行密钥 (Passkey) 自动唤起，强制微软等平台回退到常规账号密码登录
if (window.PublicKeyCredential) {
    try {
        window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
        if (window.PublicKeyCredential.isConditionalMediationAvailable) {
            window.PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
        }
    } catch (e) {}
}
if (navigator.credentials) {
    try {
        const originalCredGet = navigator.credentials.get.bind(navigator.credentials);
        navigator.credentials.get = function(options) {
            if (options && (options.publicKey || options.mediation === 'conditional')) {
                return Promise.reject(new DOMException("Passkey cancelled by client policy", "NotAllowedError"));
            }
            return originalCredGet(options);
        };
    } catch (e) {}
}

// 模拟真实 Chrome 插件
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// 模拟语言
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en']
});

// 修复 permissions 查询
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""

# 桌面端 User-Agent
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"

# 移动端 User-Agent (模拟 Edge 移动版以最大化兼容 Rewards)
MOBILE_UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 EdgA/128.0.0.0"

def get_session_file(email: str) -> Path:
    """根据邮箱计算唯一的 session 存储文件路径"""
    safe_name = hashlib.md5(email.encode("utf-8")).hexdigest()
    return SESSIONS_DIR / f"{safe_name}.json"

class BrowserManager:
    """管理 Playwright 浏览器实例及 Desktop/Mobile 上下文生命周期"""

    def __init__(self, headless: bool = DEFAULT_HEADLESS):
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    def start(self):
        """启动浏览器引擎"""
        self.playwright = sync_playwright().start()
        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-http2",
        ]
        proxy = {"server": PROXY_SERVER} if PROXY_SERVER else None

        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            proxy=proxy
        )
        logger.info(f"Chromium 浏览器启动成功 [Headless={self.headless}]")

    def create_context(
        self,
        email: str,
        is_mobile: bool = False
    ) -> BrowserContext:
        """为指定账号创建隔离的 BrowserContext，支持移动端模拟和 Session 加载"""
        if not self.browser:
            raise RuntimeError("浏览器尚未启动，请先调用 start()")

        session_file = get_session_file(email)
        storage_state = str(session_file) if session_file.exists() else None

        if storage_state:
            logger.info(f"账号 {email} 检测到已保存的 Session，免密直登加载...")

        if is_mobile:
            # 移动端配置
            context = self.browser.new_context(
                user_agent=MOBILE_UA,
                viewport={"width": 393, "height": 851},
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                storage_state=storage_state
            )
        else:
            # 桌面端配置
            context = self.browser.new_context(
                user_agent=DESKTOP_UA,
                viewport={"width": 1920, "height": 1080},
                is_mobile=False,
                has_touch=False,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                storage_state=storage_state
            )

        # 注入反爬脚本与默认超时
        context.add_init_script(STEALTH_JS)
        context.set_default_timeout(DEFAULT_TIMEOUT)
        return context

    def save_session(self, context: BrowserContext, email: str):
        """持久化当前 context 的 Cookies 与 LocalStorage"""
        session_file = get_session_file(email)
        try:
            context.storage_state(path=str(session_file))
            logger.info(f"账号 {email} 的登录 Session 已成功保存至 {session_file.name}")
        except Exception as e:
            logger.warning(f"保存 Session 失败: {e}")

    def close(self):
        """释放所有浏览器资源"""
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        logger.info("浏览器资源已释放")

