import re
import time
from typing import Tuple
from bs4 import BeautifulSoup
from playwright.sync_api import Page, BrowserContext
from config.settings import REWARDS_URL, DEFAULT_TIMEOUT
from utils.logger import logger

def ensure_rewards_dashboard(page: Page) -> bool:
    """
    确保当前页面处于 Rewards 仪表盘 (https://rewards.bing.com/dashboard)
    若被重定向至访客 /about 页面，自动触发登录握手并跳转至仪表盘
    """
    try:
        current_url = page.url or ""
        if "dashboard" not in current_url:
            page.goto(REWARDS_URL, wait_until="commit", timeout=DEFAULT_TIMEOUT)
            page.wait_for_timeout(2500)

        # 检查是否停留在 /about 或 /welcome 访客落地页
        for _ in range(3):
            curr = page.url or ""
            if "/about" in curr or "/welcome" in curr:
                # 1. 尝试点击页面中的“登入”按钮唤醒单点登录态
                login_btn = page.locator("a:has-text('登入'), a:has-text('Sign in'), a:has-text('登录')").first
                if login_btn.is_visible():
                    login_btn.click()
                    page.wait_for_timeout(3000)

                # 2. 点击进入仪表盘链接
                dash_btn = page.locator("a:has-text('移至儀表板'), a:has-text('仪表板'), a:has-text('儀表板'), a:has-text('Dashboard')").first
                if dash_btn.is_visible():
                    dash_btn.click()
                    page.wait_for_timeout(3000)
            else:
                break

        # 按一次 Escape 关闭可能残留的浮层或遮罩
        page.keyboard.press("Escape")
        return True
    except Exception as e:
        logger.warning(f"导航至 Rewards 仪表盘出现提示: {e}")
        return False

def get_points_summary(page: Page, max_wait_sec: int = 15) -> Tuple[str, str]:
    """
    获取账号积分概览：(总积分, 今日已获积分)
    采用动态等待与轮询机制，确保新版 React SPA (p.text-pageHeader) 异步渲染完全加载
    """
    total_points = "0"
    today_points = "0"
    try:
        ensure_rewards_dashboard(page)

        # 轮询等待，直至积分元素加载完成并包含有效正整数
        start_time = time.time()
        while time.time() - start_time < max_wait_sec:
            try:
                # 策略 1: 新版 React 仪表盘核心可用积分元素 (p.text-pageHeader)
                pts_loc = page.locator("p.text-pageHeader").first
                if pts_loc.is_visible():
                    txt = pts_loc.inner_text().strip()
                    digits = re.sub(r"[^\d]", "", txt)
                    if digits and int(digits) > 0:
                        total_points = digits
                        break

                # 策略 2: 导航栏区域积分 (header 内包含数字的标签)
                header_elems = page.locator("header [data-bi-name='points'], header span, header p").all()
                for elem in header_elems:
                    try:
                        if elem.is_visible():
                            txt = elem.inner_text().strip().replace(",", "")
                            if txt.isdigit() and 0 < int(txt) < 1000000:
                                total_points = txt
                                break
                    except Exception:
                        pass
                if total_points != "0":
                    break

                # 策略 3: DOM 解析与内嵌 JSON
                content = page.content()
                soup = BeautifulSoup(content, "html.parser")
                pts_header = soup.select_one("p.text-pageHeader")
                if pts_header:
                    digits = re.sub(r"[^\d]", "", pts_header.get_text())
                    if digits and int(digits) > 0:
                        total_points = digits
                        break

                match_total = re.search(r'"availablePoints"\s*:\s*(\d+)', content)
                if match_total and int(match_total.group(1)) > 0:
                    total_points = match_total.group(1)
                    break
            except Exception as loop_e:
                logger.debug(f"轮询积分数据暂未就绪: {loop_e}")

            # 轮询等待过程中，若超时一半，尝试按一次 Escape 关掉阻挡渲染的弹窗
            if time.time() - start_time > max_wait_sec / 2:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

            page.wait_for_timeout(1000)

        # 若超时后依然为 0，尝试刷新页面单次重试
        if total_points == "0":
            logger.warning("⚠️ 页面首次轮询未获取到积分，尝试刷新 Rewards 页面重试...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
                page.wait_for_timeout(3000)
                page.keyboard.press("Escape")
                pts_loc = page.locator("p.text-pageHeader").first
                if pts_loc.is_visible():
                    txt = pts_loc.inner_text().strip()
                    digits = re.sub(r"[^\d]", "", txt)
                    if digits and int(digits) > 0:
                        total_points = digits
            except Exception as re_err:
                logger.warning(f"刷新后重试读取积分异常: {re_err}")

        # 尝试提取今日已获积分
        try:
            content = page.content()
            match_today = re.search(r'"dailyPoints"\s*:\s*(\d+)', content)
            if match_today:
                today_points = match_today.group(1)
        except Exception:
            pass

        logger.info(f"📊 积分统计 -> 当前可用总积分: {total_points} | 今日已获积分: {today_points}")
    except Exception as e:
        logger.warning(f"获取积分概况异常: {e}")

    return total_points, today_points

def get_streak_days(page: Page) -> int:
    """
    提取当前账号在 Rewards 仪表盘的真实连续打卡天数 (streak days)
    从内嵌 JSON 数据或 DOM 树结构中解析
    """
    try:
        ensure_rewards_dashboard(page)
        content = page.content()

        # 策略 1: 内嵌 JSON 数据提取 (如 "streakCount": 27)
        streak_matches = re.findall(r'"streakCount"\s*:\s*(\d+)', content)
        valid_counts = [int(x) for x in streak_matches if int(x) > 0]
        if valid_counts:
            streak = max(valid_counts)
            logger.info(f"🔥 从仪表盘内嵌数据获取到连续打卡天数: {streak} 天")
            return streak

        # 策略 2: DOM 结构与文本提取
        candidates = page.locator("p:has-text('每日连续打卡'), div:has-text('每日连续打卡'), p:has-text('连续打卡'), div:has-text('连续打卡')").all()
        for cand in candidates:
            try:
                txt = cand.inner_text().strip().replace("\n", " ")
                m = re.search(r'(?:每日连续打卡|连续打卡|streak)\D*(\d+)\s*天', txt, re.I)
                if m and int(m.group(1)) > 0:
                    streak = int(m.group(1))
                    logger.info(f"🔥 从 DOM 元素解析到连续打卡天数: {streak} 天")
                    return streak
            except Exception:
                pass

        # 策略 3: 全文正则兜底
        m = re.search(r'每日连续打卡\D*(\d+)\s*天', content)
        if m and int(m.group(1)) > 0:
            streak = int(m.group(1))
            logger.info(f"🔥 从页面全文正则解析到连续打卡天数: {streak} 天")
            return streak
    except Exception as e:
        logger.warning(f"获取连续打卡天数异常: {e}")

    return 0

def claim_pending_points(page: Page) -> bool:
    """
    检查并认领微软新版 Rewards 暂存箱（準備好領取 / Ready to claim）中的待领积分。
    注意：新版交互中，点击大盘卡片会唤起二级确认弹窗（Modal），必须在弹窗内点击确认按钮（『領取點數』），
    积分才会真正划转至可用总额中，否则会被标记为『擱置』并在一个月后过期作废！
    """
    try:
        ensure_rewards_dashboard(page)
        page.wait_for_timeout(1500)

        # 1. 查找大盘上的“可领取 / 準備好領取”按钮或卡片
        claim_targets = []
        claim_cards = page.locator("div:has-text('可领取'), div:has-text('可領取'), div:has-text('準備好領取')").all()
        for cc in claim_cards:
            b = cc.locator("text='领取', text='領取', text='Claim'").first
            if b.is_visible():
                claim_targets.append(b)

        if not claim_targets:
            buttons = page.locator("button, [role='button'], a").all()
            for b in buttons:
                try:
                    txt = b.inner_text().strip()
                    if ("可领取" in txt or "可領取" in txt or "準備好領取" in txt) and ("领取" in txt or "領取" in txt or "Claim" in txt):
                        claim_targets.append(b)
                except Exception:
                    pass

        if not claim_targets:
            fallback = page.locator("button:has-text('領取'), button:has-text('领取'), button:has-text('Claim')")
            for i in range(fallback.count()):
                fb = fallback.nth(i)
                if fb.is_visible():
                    claim_targets.append(fb)

        if not claim_targets:
            logger.debug("未发现待领取的 Rewards 暂存箱或当前无可领积分")
            return False

        target = claim_targets[0]
        logger.info("🎯 检测到待领取暂存积分，正在点击打开认领面板...")
        target.click()
        page.wait_for_timeout(2500)

        # 2. 检查是否有弹出的确认抽屉/弹窗并点击确认按钮
        confirmed = False
        confirm_locators = [
            page.locator("button").filter(has_text="领取积分"),
            page.locator("button").filter(has_text="領取積分"),
            page.locator("button").filter(has_text="领取点数"),
            page.locator("button").filter(has_text="領取點數"),
            page.locator("button").filter(has_text="Claim points"),
            page.locator("button").filter(has_text="待领取"),
        ]
        for cl in confirm_locators:
            try:
                if cl.first.is_visible():
                    logger.info(f"🎯 成功定位到抽屉/弹窗内确认按钮: '{cl.first.inner_text().strip()}'，执行确认认领...")
                    cl.first.click()
                    page.wait_for_timeout(3500)
                    confirmed = True
                    break
            except Exception:
                pass

        if not confirmed:
            dialogs = page.locator("[role='dialog'], [role='alertdialog'], [aria-modal='true'], .drawer, [class*='drawer'], aside").all()
            for d in dialogs:
                if not d.is_visible():
                    continue
                d_btns = d.locator("button, [role='button']").all()
                for btn in d_btns:
                    try:
                        txt = btn.inner_text().strip()
                        if any(w in txt for w in ["领取积分", "領取積分", "领取点数", "領取點數", "Claim"]):
                            logger.info(f"🎯 在弹窗抽屉容器内定位到确认按钮: '{txt}'，执行点击...")
                            btn.click()
                            page.wait_for_timeout(3500)
                            confirmed = True
                            break
                    except Exception:
                        pass
                if confirmed:
                    break

        if confirmed:
            logger.info("✅ 暂存箱积分确认认领成功！已成功划入可用总积分")
        else:
            logger.debug("弹窗/抽屉内未发现待确认的积分按钮（可能已处于认领状态）")

        # 3. 确保关闭弹窗遮罩
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        return confirmed
    except Exception as e:
        logger.warning(f"处理暂存积分认领时出现异常: {e}")
        return False

def do_daily_checkin(page: Page):
    """
    执行每日连续签到以及新版 Rewards 的暂存积分认领
    """
    try:
        ensure_rewards_dashboard(page)

        # 1. 尝试认领新版“準備好領取”积分
        claim_pending_points(page)

        # 2. 匹配旧版/常规连续签到按钮
        checkin_locators = [
            "button:has-text('签到')",
            "button:has-text('Check in')",
            "button:has-text('Daily check-in')",
            "[aria-label*='签到']",
            ".mee-icon-AddMedium"
        ]
        for selector in checkin_locators:
            btns = page.locator(selector)
            for i in range(btns.count()):
                btn = btns.nth(i)
                if btn.is_visible() and btn.is_enabled():
                    btn.evaluate("e => e.click()")
                    logger.info("🎯 成功点击每日连续签到按钮！")
                    page.wait_for_timeout(2000)
                    return
    except Exception as e:
        logger.warning(f"每日签到/领取操作失败或今日已签到: {e}")

def _click_and_open_card(card, context: BrowserContext, page: Page) -> Page:
    """
    安全点击任务卡片并捕获弹出的新标签页
    多阶段策略：
    1. 平滑滚动并等待 DOM/动效稳定
    2. 优先通过 evaluate 直接触发底层 DOM 的真实 click（确保触发 React Aria 的完整上报链，且不受动效位移或透明遮罩影响）
    3. 备用常规 Playwright 物理点击
    4. 最后使用直链导航作为后备
    """
    try:
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
    except Exception:
        pass

    new_tab = None
    # 阶段 1: 优先使用 DOM 原生 click()，直接触发 a 标签的 React Aria 事件与 _blank 打开新标签页
    try:
        with context.expect_page(timeout=10000) as p_info:
            card.evaluate("el => el.click()")
        new_tab = p_info.value
        return new_tab
    except Exception as eval_e:
        logger.debug(f"evaluate click 未捕获新标签页: {eval_e}")

    # 阶段 2: 尝试 Playwright 真实物理鼠标点击
    try:
        with context.expect_page(timeout=10000) as p_info:
            card.click(force=True, timeout=5000)
        new_tab = p_info.value
        return new_tab
    except Exception as click_e:
        logger.debug(f"物理 click 未捕获新标签页: {click_e}")

    # 阶段 3: 直链降级直达
    href = card.get_attribute("href") or ""
    if href.startswith("http"):
        logger.info(f"🔗 启用直链降级访问: {href[:60]}")
        try:
            new_tab = context.new_page()
            new_tab.goto(href, wait_until="domcontentloaded", timeout=20000)
            return new_tab
        except Exception as nav_e:
            logger.debug(f"直链访问异常: {nav_e}")

    return None

def _process_opened_card_tab(new_tab: Page):
    """
    处理已打开的任务标签页：平滑滚动、识别交互问答投票、等待后端异步结算
    """
    if not new_tab:
        return
    try:
        try:
            new_tab.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(2)

        # 模拟人类阅读：平滑向下滚动并回滚，确保触发 Bing Rewards 浏览时长判定
        try:
            new_tab.mouse.wheel(0, 500)
            time.sleep(2)
            new_tab.mouse.wheel(0, -200)
            time.sleep(1)
        except Exception:
            pass

        # 自动识别并作答单选民意调查/测验/开始按钮
        poll_options = new_tab.locator(
            "#btoption0, #btoption1, .btOption, .wk_Option, "
            "[role='radiogroup'] [role='radio'], input[type='radio'], "
            "button:has-text('投票'), button:has-text('Vote'), "
            "#rqStartQuiz, .rqStartQuiz, input[value='Start playing'], input[value='开始']"
        )
        if poll_options.count() > 0:
            first_opt = poll_options.first
            if first_opt.is_visible():
                logger.info("检测到测验/投票单选项，自动点击提交...")
                first_opt.click()
                time.sleep(2)

        # 停留 6 秒确保微软后端异步打卡结算 (POST /rewardsapp/reportActivity)
        time.sleep(6)
    except Exception as e:
        logger.debug(f"处理任务标签页出现提示: {e}")
    finally:
        try:
            new_tab.close()
        except Exception:
            pass
        time.sleep(2)

def complete_promotions(page: Page, context: BrowserContext):
    """
    完成 Rewards 仪表盘的任务活动：
    1. 自动展开页面中所有收起的手风琴折叠（保证所有打卡任务卡片平铺可见）
    2. 真实物理点击未完成的每日任务卡片（触发前端 onClick 上报，解决新标签页直接访问不计分的问题）
    3. 自动识别并作答单选民意调查/测验
    4. 再次点击『領取』收集所得奖励点数
    """
    logger.info("开始执行 Rewards 每日任务与活动卡片扫描...")
    try:
        ensure_rewards_dashboard(page)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # 1. 自动展开被折叠的手风琴面板（尤其是每日任务与更多活动）
        accordion_patterns = [
            "每日設定", "每日设置", "每日活动", "Daily set",
            "更多活動", "更多活动", "More activities", "其他活動", "其他活动"
        ]
        for pattern in accordion_patterns:
            try:
                acc_btns = page.locator(f"button[aria-expanded='false']:has-text('{pattern}')")
                for j in range(acc_btns.count()):
                    btn = acc_btns.nth(j)
                    if btn.is_visible() and btn.get_attribute("aria-expanded") == "false":
                        logger.info(f"展开手风琴面板: {pattern}")
                        btn.scroll_into_view_if_needed()
                        btn.click(force=True)
                        page.wait_for_timeout(600)
            except Exception:
                pass

        page.wait_for_timeout(1500)

        # 2. 检索所有候选任务卡片链接
        # 特征：带有积分增加 (+10, +5, +30) 或特定的 Rewards 参数
        candidates = page.locator(
            "a[href*='FORM=ML'], a[href*='FORM=tgrew'], a[href*='form=ML'], a[href*='skipopalnative'], a[href*='rnoreward=1'], "
            "a[href*='bing.com/search?q='], "
            "a:has-text('+10'), a:has-text('+5'), a:has-text('+30'), a:has-text('+50'), a:has-text('+100')"
        )
        total_candidates = candidates.count()
        logger.info(f"扫描到 {total_candidates} 个候选任务链接，开始过滤待完成卡片...")

        # 过滤与去重
        tasks_to_click = []
        seen_titles = set()

        for i in range(total_candidates):
            card = candidates.nth(i)
            if not card.is_visible():
                continue
            text = card.inner_text().replace('\n', ' ').strip()
            
            # 过滤已完成项
            if any(done in text for done in ["已完成", "Completed"]):
                continue
            
            # 使用标题首部做去重
            title_key = text[:20]
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            tasks_to_click.append((card, text))

        logger.info(f"🎯 共筛选出 {len(tasks_to_click)} 个待执行的未完成任务卡片")

        # 3. 真实物理点击每个卡片执行任务
        for idx, (card, text) in enumerate(tasks_to_click[:10]):
            logger.info(f"👉 正在执行任务卡片 [{idx + 1}/{len(tasks_to_click[:10])}]: {text[:40]}")
            try:
                new_tab = _click_and_open_card(card, context, page)
                _process_opened_card_tab(new_tab)
            except Exception as ce:
                logger.debug(f"卡片点击交互提示: {ce}")
                time.sleep(2)

        # 4. 刷新仪表板，进行二次校验与未完成任务补做
        try:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 重新展开折叠手风琴
            for pattern in accordion_patterns:
                try:
                    acc_btns = page.locator(f"button[aria-expanded='false']:has-text('{pattern}')")
                    for j in range(acc_btns.count()):
                        btn = acc_btns.nth(j)
                        if btn.is_visible() and btn.get_attribute("aria-expanded") == "false":
                            btn.scroll_into_view_if_needed()
                            btn.click(force=True)
                            page.wait_for_timeout(400)
                except Exception:
                    pass

            page.wait_for_timeout(1000)

            # 扫描仍未完成的卡片进行二次补做
            recheck_candidates = page.locator(
                "a[href*='FORM=ML'], a[href*='FORM=tgrew'], a[href*='form=ML'], a[href*='skipopalnative'], a[href*='rnoreward=1'], "
                "a[href*='bing.com/search?q='], "
                "a:has-text('+10'), a:has-text('+5'), a:has-text('+30'), a:has-text('+50'), a:has-text('+100')"
            )
            retry_tasks = []
            retry_seen = set()
            for k in range(recheck_candidates.count()):
                c_elem = recheck_candidates.nth(k)
                if not c_elem.is_visible():
                    continue
                c_text = c_elem.inner_text().replace('\n', ' ').strip()
                if any(done in c_text for done in ["已完成", "Completed"]):
                    continue
                c_title = c_text[:20]
                if not c_title or c_title in retry_seen:
                    continue
                retry_seen.add(c_title)
                retry_tasks.append((c_elem, c_text))

            if retry_tasks:
                logger.info(f"⚠️ 二次校验发现仍有 {len(retry_tasks)} 个未结算任务，启动强化补做流程...")
                for r_idx, (r_card, r_text) in enumerate(retry_tasks):
                    logger.info(f"🔄 正在补做任务 [{r_idx + 1}/{len(retry_tasks)}]: {r_text[:40]}")
                    try:
                        r_tab = _click_and_open_card(r_card, context, page)
                        _process_opened_card_tab(r_tab)
                    except Exception as re_e:
                        logger.debug(f"补做任务交互提示: {re_e}")
                        time.sleep(2)

                # 再次刷新仪表板
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

            # 收集所得奖励代币
            claim_btn = page.locator("button:has-text('領取'), button:has-text('领取'), button:has-text('Claim')").first
            if claim_btn.is_visible():
                claim_btn.evaluate("e => e.click()")
                logger.info("🎯 任务执行完毕，成功点击『領取』追加积分！")
                page.wait_for_timeout(2000)
                page.keyboard.press("Escape")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"完成每日任务活动异常: {e}")
