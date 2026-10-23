import time
from playwright.sync_api import Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from config.settings import BING_URL, REWARDS_URL, LOGIN_URL, DEFAULT_TIMEOUT
from utils.logger import logger, save_error_screenshot

def is_already_logged_in(page: Page, max_retries: int = 3) -> bool:
    """检查当前页面是否处于登录有效状态，内置重试与网络容错机制"""
    for attempt in range(1, max_retries + 1):
        try:
            # 使用 wait_until="commit" 避免外部统计脚本/字体慢阻塞导致的假死超时
            page.goto(REWARDS_URL, wait_until="commit", timeout=DEFAULT_TIMEOUT)
            
            # 允许最多 10 秒等待可能的 OAuth 快速置换、宣传页唤醒与重定向稳定
            for _ in range(10):
                current_url = page.url or ""
                page_title = page.title() or ""

                # 1. 如果进入服务条款更新页，触发拦截处理
                if "tou" in current_url or "accrue" in current_url or "条款" in page_title:
                    handle_login_prompts(page)
                    current_url = page.url or ""

                # 2. 如果重定向到了微软账户首页，说明 100% 已登录
                if "account.microsoft.com" in current_url:
                    logger.info("检测到已成功进入 Microsoft 账户中心，确认已登录！")
                    return True

                # 3. 如果停留在 /about 或 /welcome 访客宣传页，主动点击登录按钮唤起静默 SSO
                if "/about" in current_url or "/welcome" in current_url:
                    sso_btn = page.locator("a:has-text('登录'), a:has-text('登入'), a:has-text('Sign in'), button:has-text('登录')").first
                    if sso_btn.is_visible():
                        logger.info("检测到 Rewards 宣传落地页 (/about)，点击登录按钮唤醒静默 SSO...")
                        sso_btn.click()
                        page.wait_for_timeout(3000)
                        continue

                # 4. 如果已经在 rewards.bing.com/dashboard 且不在 oauth 置换过程中，进入后续检测
                if "rewards.bing.com" in current_url and "oauth" not in current_url and "/about" not in current_url:
                    break

                page.wait_for_timeout(1000)

            current_url = page.url or ""

            # 如果最终停留在了登录输入页且有邮箱输入框，说明确实未登录
            if "login.live.com" in current_url and page.locator('input[type="email"], input[name="loginfmt"], #i0116').first.is_visible():
                return False

            # 检查是否包含 Rewards 核心元素或用户状态
            indicators = [
                "#id_l",                        # Bing 顶部账号区
                ".pointsDetail",                # 积分详情
                "#flyout-remind-flyout",        # 积分提醒浮层
                "text=可用积分",
                "text=Available points",
                "text=今日积分",
                "text=Points breakdown",
                "#mectrl_currentAccount",       # 微软顶部用户账号控件
                "#mectrl_headerPicture",        # 微软顶部头像
                "text=查看我的福利"
            ]
            for selector in indicators:
                if page.locator(selector).first.is_visible():
                    return True

            # 如果在 rewards.bing.com 页面且没有出现醒目的未登录按钮，通常已登录
            if "rewards.bing.com" in current_url and "/about" not in current_url:
                sign_in_btn = page.locator("header a:has-text('登录'), header button:has-text('登录'), header a:has-text('Sign in')").first
                if not sign_in_btn.is_visible():
                    return True

            if attempt < max_retries:
                logger.info(f"登录指标未就绪，重试检测 ({attempt}/{max_retries})...")
                page.wait_for_timeout(2000)
                continue

            return False
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"检查登录状态网络波动 ({attempt}/{max_retries}): {e}，将在 3 秒后重试...")
                page.wait_for_timeout(3000)
            else:
                logger.warning(f"检查登录状态多次重试仍出现异常: {e}")
                return False
    return False

def sync_bing_sso(page: Page):
    """
    通过访问 Bing 主页激活 SSO 跨域凭证同步：
    将 live.com / microsoft.com 的全局身份通过单点登录同步至 bing.com 域
    """
    try:
        logger.info("正在激活并同步 Bing 域单点登录凭证 (SSO)...")
        page.goto(BING_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(2000)

        # 检查右上角是否仍显示“登录”按钮，若是则点击一次以触发微软静默跨域授权重定向
        login_btn = page.locator("#id_s, #id_l, header a:has-text('登录'), header a:has-text('Sign in')").first
        if login_btn.is_visible():
            btn_text = login_btn.inner_text()
            if "登录" in btn_text or "Sign in" in btn_text:
                logger.info("点击 Bing 顶部登录按钮触发静默授权绑定...")
                login_btn.click()
                page.wait_for_timeout(3000)
                # 等待跳回 bing.com
                for _ in range(6):
                    if "bing.com" in page.url and "login.live.com" not in page.url:
                        break
                    page.wait_for_timeout(1000)
        logger.info("Bing 域 SSO 同步完成！")
    except Exception as e:
        logger.debug(f"Bing SSO 跨域同步过程异常: {e}")

def handle_login_prompts(page: Page, max_attempts: int = 5):
    """处理微软登录后可能出现的各种干扰弹窗与通行密钥设置"""
    for _ in range(max_attempts):
        page.wait_for_timeout(2000)
        current_url = page.url

        # 0. 检查是否出现"服务协议/条款更新" (Terms of Use / Notice)
        terms_btn = page.locator("button[data-testid='primaryButton'], button:has-text('下一步'), button:has-text('Next'), #iNext, button:has-text('接受'), button:has-text('Accept')").first
        if ("tou" in current_url or "accrue" in current_url or "条款" in (page.title() or "") or "terms" in current_url.lower()) and terms_btn.is_visible():
            try:
                logger.info("检测到微软服务协议/条款更新拦截页，点击下一步确认...")
                terms_btn.click()
                page.wait_for_timeout(3000)
                continue
            except Exception:
                pass

        # 1. 检查是否出现"保持登录状态？" (Stay signed in)
        stay_signed_btn = page.locator("button:has-text('是'), button:has-text('Yes'), input[value='是'], input[value='Yes'], #acceptButton")
        if stay_signed_btn.first.is_visible():
            try:
                logger.info("检测到'保持登录状态'弹窗，正在确认...")
                stay_signed_btn.first.click()
                page.wait_for_timeout(2000)
                continue
            except Exception:
                pass

        # 2. 检查是否出现"创建通行密钥" (Passkey) / "使用无密码方式"
        skip_passkey_btn = page.locator("button:has-text('暂时跳过'), a:has-text('暂时跳过'), button:has-text('Skip for now'), a:has-text('Skip for now'), button:has-text('以后再说'), #btnSecondary")
        if skip_passkey_btn.first.is_visible():
            try:
                logger.info("检测到'创建通行密钥/安全提示'页面，点击暂时跳过...")
                skip_passkey_btn.first.click()
                page.wait_for_timeout(2000)
                continue
            except Exception:
                pass

        # 3. 检查是否有"下一个"、"取消"等常见次级按钮
        if "setup" in current_url or "passkey" in current_url or "security" in current_url:
            cancel_btn = page.locator("button:has-text('取消'), a:has-text('取消'), button:has-text('Cancel')")
            if cancel_btn.first.is_visible():
                cancel_btn.first.click()
                page.wait_for_timeout(2000)
                continue

        # 如果已经跳转到了 bing.com 或 rewards.bing.com，说明已通过所有弹窗
        if "bing.com" in page.url and "login.live.com" not in page.url:
            break

def login_microsoft(page: Page, email: str, password: str) -> bool:
    """
    执行微软账号登录全流程：
    1. 输入邮箱
    2. 处理验证码页转密码
    3. 输入密码
    4. 处理保持登录/通行密钥跳过
    5. 验证跳转
    """
    logger.info(f"开始账号 {email} 的登录流程...")
    try:
        for nav_try in range(3):
            try:
                page.goto(LOGIN_URL, wait_until="commit", timeout=DEFAULT_TIMEOUT)
                break
            except Exception as nav_e:
                if nav_try < 2:
                    logger.warning(f"导航至登录页重试 ({nav_try + 1}/3): {nav_e}")
                    page.wait_for_timeout(2000)
                else:
                    raise nav_e
        page.wait_for_timeout(2500)

        # 防护检查：如果访问 login.live.com 时发现由于 Session 存在已直接跳转到个人主页或 Rewards
        current_url = page.url
        if "account.microsoft.com" in current_url or ("login.live.com" not in current_url and "bing.com" in current_url):
            logger.info(f"🎉 账号 {email} 的 Session 仍然有效，已直接进入用户中心 ({current_url})，无需重新登录！")
            return True

        # 1. 前置状态判定：检查是否已登录，或直接处于密钥错误/验证/密码页
        for _ in range(6):
            current_url = page.url
            if "account.microsoft.com" in current_url or ("login.live.com" not in current_url and "bing.com" in current_url):
                logger.info(f"🎉 账号 {email} 的 Session 仍然有效，已直接进入用户中心 ({current_url})，无需重新登录！")
                return True

            # 检查是否有服务协议/条款更新拦截
            if "tou" in current_url or "accrue" in current_url or "条款" in (page.title() or ""):
                handle_login_prompts(page)
                current_url = page.url
                if "account.microsoft.com" in current_url or ("login.live.com" not in current_url and "bing.com" in current_url):
                    logger.info(f"🎉 账号 {email} 条款确认后直接进入用户中心 ({current_url})，登录成功！")
                    return True

            # 若密码框已直接可见，直接跳至密码输入
            if page.locator('input[type="password"], input[name="passwd"], #i0118').first.is_visible():
                logger.info(f"账号 {email} 已直接定位到密码输入框")
                break

            # 检查是否有“其他登录方式” / “使用另一种方式登录” / “Other ways to sign in”
            other_ways_btn = page.locator(
                "span[role='button']:has-text('Other ways to sign in'), "
                "[role='button']:has-text('使用另一种方式登录'), "
                "[role='button']:has-text('使用另一個方式登入'), "
                "[role='button']:has-text('其他登录方法'), "
                "[role='button']:has-text('其他登录方式'), "
                "[role='button']:has-text('Other ways to sign in'), "
                "a:has-text('使用另一种方式登录'), "
                "a:has-text('使用另一個方式登入'), "
                "a:has-text('Other ways to sign in'), "
                "a:has-text('其他登录方式'), "
                "a:has-text('其他登录方法'), "
                "#signInAnotherWay"
            ).first
            if other_ways_btn.is_visible():
                logger.info("检测到登录中间切换入口（密钥提示/验证引导），点击切换登录方式...")
                other_ways_btn.click()
                page.wait_for_timeout(1500)

                # 寻找“使用密码” / “Use your password” 磁贴或按钮
                pwd_tile = page.locator(
                    "[data-testid='tile']:has-text('password'), "
                    "[data-testid='tile']:has-text('密码'), "
                    "[data-testid='tile']:has-text('密碼'), "
                    "[role='button']:has-text('Use your password'), "
                    "[role='button']:has-text('使用你的密码'), "
                    "[role='button']:has-text('使用密码'), "
                    "[role='button']:has-text('使用您的密碼'), "
                    "div[role='listitem']:has-text('密码'), "
                    "div[role='listitem']:has-text('password'), "
                    "#idA_PWD_SwitchToPassword"
                ).first
                if pwd_tile.is_visible():
                    logger.info("选择使用密码登录...")
                    pwd_tile.click()
                    page.wait_for_timeout(1500)
                break

            if page.locator('input[type="email"], input[name="loginfmt"], #i0116').first.is_visible():
                break
            page.wait_for_timeout(1000)

        # 2. 邮箱输入（若尚未进入密码框）
        pwd_box = page.locator('input[type="password"], input[name="passwd"], #i0118').first
        if not pwd_box.is_visible():
            email_input = page.locator('input[type="email"], input[name="loginfmt"], #i0116').first
            if not email_input.is_visible():
                if "tou" in page.url or "accrue" in page.url or "条款" in (page.title() or ""):
                    handle_login_prompts(page)
                    if "account.microsoft.com" in page.url or ("login.live.com" not in page.url and "bing.com" in page.url):
                        logger.info(f"🎉 账号 {email} 条款确认后直接进入用户中心，登录成功！")
                        return True
                if page.locator("text=注销, text=Sign out, #mectrl_headerPicture").first.is_visible():
                    logger.info(f"账号 {email} 已自动识别登录态，跳过重复认证！")
                    return True
                email_input.wait_for(state="visible", timeout=10000)

            email_input.fill(email)
            logger.info(f"账号 {email} 已输入邮箱")

            # 点击下一步
            next_btn = page.locator('input[type="submit"], button[type="submit"], #idSIButton9, button:has-text("下一步"), button:has-text("Next")').first
            next_btn.click()
            page.wait_for_timeout(2500)

        # 3. 等待密码输入框，若遇到通行密钥 (Passkey) 或验证码界面，主动切换为密码登录
        password_input = None
        for attempt in range(25):
            page.wait_for_timeout(1000)
            
            # 检查密码输入框是否已经可见
            pwd_locator = page.locator('input[type="password"], input[name="passwd"], #i0118').first
            if pwd_locator.is_visible():
                password_input = pwd_locator
                break

            # 检查是否卡在通行密钥、安全验证或错误重试页面
            page_text = page.content()
            if any(w in page_text for w in ["通行密钥", "passkey", "正在验证", "出现问题", "其他登录", "无法让你登录", "密钥登录时出错", "Other ways"]):
                logger.info("检测到通行密钥/验证提示页面，正在切换至密码登录...")
                
                # 1. 优先尝试点击“其他登录方法”或“其他登录方式”
                other_ways_locators = [
                    "span[role='button']:has-text('Other ways to sign in')",
                    "[role='button']:has-text('使用另一种方式登录')",
                    "[role='button']:has-text('使用另一個方式登入')",
                    "[role='button']:has-text('其他登录方法')",
                    "[role='button']:has-text('其他登录方式')",
                    "[role='button']:has-text('Other ways to sign in')",
                    "a:has-text('使用另一种方式登录')",
                    "a:has-text('使用另一個方式登入')",
                    "a:has-text('Other ways to sign in')",
                    "a:has-text('其他登录方式')",
                    "a:has-text('其他登录方法')",
                    "a:has-text('其他登录')",
                    "button:has-text('其他登录方法')",
                    "button:has-text('其他登录方式')",
                    "#signInAnotherWay",
                    "#idA_PWD_SwitchToPassword"
                ]
                for selector in other_ways_locators:
                    btn = page.locator(selector).first
                    if btn.is_visible():
                        logger.info(f"点击切换登录方式入口: {selector}")
                        btn.click()
                        page.wait_for_timeout(1500)
                        break

                # 2. 如果已在选项列表或页面有密码相关选项，点击“密码”
                pwd_option_locators = [
                    "[data-testid='tile']:has-text('password')",
                    "[data-testid='tile']:has-text('密码')",
                    "[data-testid='tile']:has-text('密碼')",
                    "[role='button']:has-text('Use your password')",
                    "[role='button']:has-text('使用你的密码')",
                    "[role='button']:has-text('使用密码')",
                    "[role='button']:has-text('使用您的密碼')",
                    "div[role='listitem']:has-text('密码')",
                    "div[role='listitem']:has-text('password')",
                    'text="使用密码"',
                    'text="使用你的密码"',
                    'text="输入密码"',
                    'text="使用我的密码"',
                    '#idA_PWD_SwitchToPassword'
                ]
                for selector in pwd_option_locators:
                    btn = page.locator(selector).first
                    if btn.is_visible():
                        logger.info(f"点击密码登录选项: {selector}")
                        btn.click()
                        page.wait_for_timeout(1500)
                        break

                # 3. 尝试点击左上角后退返回按钮（重新触发选择）
                back_btn = page.locator('#idBtn_Back, button[aria-label="返回"], button[aria-label="Back"], button[aria-label="后退"], .backButton').first
                if not pwd_locator.is_visible() and back_btn.is_visible() and "出现问题" not in page_text:
                    logger.info("点击返回按钮重置登录方式...")
                    back_btn.click()
                    page.wait_for_timeout(1500)
                    continue

        if not password_input:
            raise PlaywrightTimeoutError("未能找到密码输入框，可能仍卡在通行密钥或验证码页面")

        # 4. 密码输入与提交
        password_input.fill(password)
        logger.info(f"账号 {email} 已输入密码")

        # 点击登录按钮
        submit_btn = page.locator('input[type="submit"], button[type="submit"], #idSIButton9, button:has-text("登录"), button:has-text("Sign in")').first
        submit_btn.click()
        page.wait_for_timeout(3000)

        # 4. 处理登录成功后的过渡弹窗（保持登录、通行密钥等）
        handle_login_prompts(page)

        # 5. 导航至 Rewards 页面做最终登录验证
        page.goto(REWARDS_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        page.wait_for_timeout(3000)

        # 判断是否登录成功
        if "rewards.bing.com" in page.url and "login.live.com" not in page.url:
            logger.info(f"🎉 账号 {email} 成功完成登录！")
            return True
        else:
            logger.warning(f"账号 {email} 登录后 URL 仍停留在 {page.url}")
            save_error_screenshot(page, f"login_uncertain_{email.split('@')[0]}")
            return False

    except PlaywrightTimeoutError as e:
        logger.error(f"账号 {email} 登录过程超时: {e}")
        save_error_screenshot(page, f"login_timeout_{email.split('@')[0]}")
        return False
    except Exception as e:
        logger.error(f"账号 {email} 登录异常: {e}")
        save_error_screenshot(page, f"login_error_{email.split('@')[0]}")
        return False

