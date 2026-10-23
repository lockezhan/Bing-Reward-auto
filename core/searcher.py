import random
import time
import urllib.parse
from typing import List
from playwright.sync_api import Page
from config.settings import (
    SEARCH_INTERVAL,
    COOLDOWN_SEARCH_COUNT,
    DEFAULT_TIMEOUT
)
from utils.logger import logger

def simulate_reading(page: Page):
    """模拟人类浏览行为：随机微滚动、停留与阅读"""
    try:
        scroll_y = random.randint(250, 600)
        page.mouse.wheel(0, scroll_y)
        time.sleep(random.uniform(1.0, 2.0))

        # 20% 概率微幅回滚
        if random.random() < 0.2:
            page.mouse.wheel(0, -random.randint(100, 300))
            time.sleep(0.8)
    except Exception:
        pass

def execute_search_session(
    page: Page,
    search_terms: List[str],
    is_mobile: bool = False,
    max_count: int = 30
) -> int:
    """
    执行一次完整的搜索批处理会话
    兼容模拟浏览器地址栏直搜与结果页递进搜索，防风控且绝不卡死
    """
    mode_name = "移动端" if is_mobile else "PC桌面端"
    logger.info(f"🚀 开始执行 {mode_name} 自动搜索，目标次数: {max_count} 次")

    success_count = 0
    terms_to_use = search_terms[:max_count]

    for idx, term in enumerate(terms_to_use):
        try:
            logger.info(f"[{mode_name}] 正在进行第 {idx + 1}/{max_count} 次搜索: \"{term}\"")

            search_url = f"https://www.bing.com/search?q={urllib.parse.quote(term)}&form=QBLH"

            # 策略：如果已经在 bing 搜索页面且输入框就绪，模拟输入并回车；否则模拟浏览器地址栏直接访问搜索 URL
            searched_via_input = False
            current_url = page.url or ""
            if "bing.com/search" in current_url:
                try:
                    q_input = page.locator("textarea[name='q'], input[name='q'], #sb_form_q").first
                    if q_input.is_visible():
                        q_input.click(timeout=2000)
                        q_input.fill(term, timeout=2000)
                        page.keyboard.press("Enter")
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        searched_via_input = True
                except Exception:
                    searched_via_input = False

            if not searched_via_input:
                page.goto(search_url, wait_until="commit", timeout=15000)

            page.wait_for_timeout(2000)

            # 模拟随机人类阅读与滚动浏览
            simulate_reading(page)

            success_count += 1

            # 搜索间隔等待
            sleep_time = random.uniform(*SEARCH_INTERVAL)
            logger.debug(f"搜索完成，拟人化等待 {sleep_time:.1f} 秒...")
            time.sleep(sleep_time)

            # 批次冷却微调
            if (idx + 1) % COOLDOWN_SEARCH_COUNT == 0 and (idx + 1) < max_count:
                logger.info(f"已连续搜索 {COOLDOWN_SEARCH_COUNT} 次，执行拟人化微暂停避开风控...")
                time.sleep(random.uniform(4, 7))

        except Exception as e:
            logger.warning(f"[{mode_name}] 第 {idx + 1} 次搜索轻微异常: {e}")
            time.sleep(2)
            continue

    logger.info(f"✅ {mode_name} 搜索任务执行完毕，成功完成 {success_count}/{max_count} 次")
    return success_count
