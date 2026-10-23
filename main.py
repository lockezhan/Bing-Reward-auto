import argparse
import datetime
import json
import sys
import time
from typing import List, Dict, Any

from config.settings import (
    load_accounts,
    DEFAULT_PC_SEARCH_COUNT,
    DEFAULT_MOBILE_SEARCH_COUNT,
    DEFAULT_HEADLESS,
    SESSIONS_DIR,
    DASHBOARD_REPORT_URL,
    DASHBOARD_REPORT_TOKEN
)
from core.browser import BrowserManager
from core.auth import is_already_logged_in, login_microsoft, sync_bing_sso
from core.tasks import (
    get_points_summary,
    do_daily_checkin,
    complete_promotions,
    claim_pending_points,
    get_streak_days
)
from core.searcher import execute_search_session
from core.hotwords import get_hotwords
from utils.logger import logger
from utils.notifier import format_report, send_notification

POINTS_CACHE_FILE = SESSIONS_DIR / "points_cache.json"

def get_cached_points(email: str) -> int:
    """获取指定账号上一次成功记录的总积分"""
    if not POINTS_CACHE_FILE.exists():
        return 0
    try:
        with open(POINTS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return int(data.get(email, {}).get("points", 0))
    except Exception as e:
        logger.warning(f"读取积分缓存异常: {e}")
        return 0

def save_cached_points(email: str, points: int):
    """保存指定账号的最新的总积分至本地缓存"""
    if points <= 0:
        return
    try:
        data = {}
        if POINTS_CACHE_FILE.exists():
            try:
                with open(POINTS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[email] = {
            "points": points,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(POINTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"写入积分缓存异常: {e}")

def ensure_active_page(context, current_page, email: str = ""):
    """确保页面存活可用；若页面已崩溃或关闭，则自动重建新页面"""
    try:
        if current_page is None or current_page.is_closed():
            logger.warning(f"检测到页面未激活或已关闭，正在为 {email} 自动创建新页面...")
            return context.new_page()
        # 快速探测活跃度
        current_page.evaluate("1 + 1")
        return current_page
    except Exception as e:
        logger.warning(f"检测到页面已崩溃或失联 ({e})，正在自动为 {email} 重建页面...")
        try:
            current_page.close()
        except Exception:
            pass
        return context.new_page()


def process_single_account(
    browser_manager: BrowserManager,
    account: Dict[str, Any],
    hotwords: List[str],
    args: argparse.Namespace
) -> Dict[str, Any]:
    """处理单个账号的全流程自动化任务"""
    email = account.get("email")
    password = account.get("password")
    result = {
        "email": email,
        "status": "failed",
        "start_points": "0",
        "end_points": "0",
        "earned_today": "0",
        "streak_days": 0,
        "message": ""
    }

    logger.info(f"\n==========================================")
    logger.info(f"👤 开始处理账号: {email}")
    logger.info(f"==========================================")

    desktop_context = None
    try:
        # 1. 创建桌面端上下文
        desktop_context = browser_manager.create_context(email=email, is_mobile=False)
        page = desktop_context.new_page()

        # 2. 检查或执行登录
        logged_in = is_already_logged_in(page)
        if not logged_in:
            if not password:
                logger.error(f"账号 {email} 会话已失效或未生效，且 accounts.json 中未配置密码，无法自动重新认证")
                result["message"] = "Session失效且未提供密码"
                return result
            logger.info(f"账号 {email} 未登录或 Session 已失效，尝试密码登录...")
            if not login_microsoft(page, email, password):
                result["message"] = "登录失败（可能触发人机验证或密码错误）"
                return result
            # 登录成功后持久化会话
            browser_manager.save_session(desktop_context, email)
        else:
            logger.info(f"账号 {email} 会话依然有效，免密直通！")

        # 3. 激活并同步 Bing 域 SSO 单点登录状态
        sync_bing_sso(page)

        # 3.1 获取任务前初始基准积分，并清理此前已就绪的暂存积分
        start_total, _ = get_points_summary(page)
        if start_total == "0":
            logger.warning(f"⚠️ 账号 {email} 任务前未能从仪表盘直接提取到积分，尝试从本地缓存读取基准积分...")
            cached_pts = get_cached_points(email)
            if cached_pts > 0:
                start_total = str(cached_pts)
                logger.info(f"📊 账号 {email} 成功使用本地历史缓存作为初始积分基准: {start_total}")
            else:
                logger.warning(f"⚠️ 账号 {email} 未找到本地历史积分缓存，初始基准暂为 0")
        else:
            save_cached_points(email, int(start_total))

        result["start_points"] = start_total
        logger.info(f"📊 账号 {email} 任务前基准总积分: {start_total}")
        claim_pending_points(page)

        # 4. 优先执行 PC 端搜索任务（先搜后领，打通并激活 Rewards 会话）
        if not args.skip_search and not args.mobile_only:
            pc_count = args.pc_count
            execute_search_session(page, hotwords, is_mobile=False, max_count=pc_count)

        # 保存最新的 desktop context 状态
        browser_manager.save_session(desktop_context, email)

        # 5. 移动端搜索（模拟手机设备）
        if not args.skip_search and not args.pc_only:
            logger.info(f"📱 启动移动端模拟上下文，执行手机端搜索赚取额外积分...")
            mobile_context = browser_manager.create_context(email=email, is_mobile=True)
            mobile_page = mobile_context.new_page()

            # 移动端也同步一次 Bing SSO 并搜索
            sync_bing_sso(mobile_page)
            execute_search_session(
                mobile_page,
                hotwords[args.pc_count:],
                is_mobile=True,
                max_count=args.mobile_count
            )
            browser_manager.save_session(mobile_context, email)
            mobile_page.close()
            mobile_context.close()

        # 6. 搜索完毕后，进入 Rewards 仪表盘页面（此时会话已完全激活，卡片与积分均能完整展现）
        logger.info(f"🎯 搜索任务已完成，访问 Rewards 仪表盘处理签到与任务卡片...")
        # 确保桌面端页面存活（防止长时间移动端搜索导致后台页面被 Chromium 淘汰或崩溃）
        page = ensure_active_page(desktop_context, page, email)
        
        # 每日连续签到与暂存积分认领
        logger.info(f"账号 {email} 执行每日签到...")
        do_daily_checkin(page)

        # 扫描并完成任务卡片
        logger.info(f"账号 {email} 扫描并完成任务卡片...")
        complete_promotions(page, desktop_context)

        # 再次执行暂存箱认领，彻底收割本轮搜索与卡片生成的积分
        claim_pending_points(page)

        # 7. 获取最终结算积分并核对今日成效
        page = ensure_active_page(desktop_context, page, email)
        end_total, _ = get_points_summary(page)

        # 若读取为 0 且此前有基准积分，触发单次强力重建自愈读取
        if (end_total == "0" or not end_total) and int(start_total) > 0:
            logger.warning(f"⚠️ 最终积分读取为 0 (初始基准为 {start_total})，疑似页面崩溃，尝试新建页面重试读取...")
            try:
                page = ensure_active_page(desktop_context, None, email)
                end_total, _ = get_points_summary(page)
            except Exception as recover_e:
                logger.error(f"自愈重试读取积分异常: {recover_e}")

        result["end_points"] = end_total
        try:
            end_pts = int(end_total)
            start_pts = int(start_total)

            # 核心防呆：若 end_pts == 0 且 start_pts > 0，绝不允许归零与虚假成功！
            if end_pts == 0 and start_pts > 0:
                logger.error(f"❌ 严重异常：结算积分读为 0，而任务前基准积分为 {start_pts}！触发保护：保留历史基准，标记失败！")
                result["end_points"] = str(start_pts)
                result["earned_today"] = "0"
                result["status"] = "failed"
                result["message"] = "积分读取异常（页面崩溃或未获取到数值，已保留原积分）"
            else:
                # 正常计算逻辑
                if start_pts == 0 and end_pts > 0:
                    cached_pts = get_cached_points(email)
                    if cached_pts > 0 and end_pts >= cached_pts:
                        start_pts = cached_pts
                        earned = end_pts - cached_pts
                        logger.warning(f"⚠️ 初始积分丢失(0)，通过本地缓存({cached_pts})推算今日增量: +{earned}")
                    else:
                        logger.warning(f"⚠️ 初始积分为 0 且无有效历史缓存，为防止虚增，今日收益暂记 0")
                        earned = 0
                else:
                    earned = max(0, end_pts - start_pts)

                if end_pts > 100 and earned == end_pts:
                    cached_pts = get_cached_points(email)
                    if cached_pts > 0 and end_pts >= cached_pts:
                        earned = end_pts - cached_pts
                        logger.warning(f"⚠️ 收益异常等于总积分，通过历史缓存校准为真实差值: +{earned}")
                    else:
                        logger.warning(f"⚠️ 收益异常等于总积分且无有效历史缓存，为防止虚增记为 0")
                        earned = 0

                result["earned_today"] = str(earned)
                if end_pts > 0:
                    save_cached_points(email, end_pts)
                result["status"] = "success"
                result["message"] = "任务全部顺利完成"
        except Exception as e:
            logger.warning(f"计算今日积分收益异常: {e}")
            result["earned_today"] = "0"
            result["status"] = "failed"
            result["message"] = f"收益计算异常: {e}"

        # 提取真实连续打卡天数
        try:
            streak = get_streak_days(page)
            result["streak_days"] = streak
        except Exception as se:
            logger.debug(f"提取连续打卡天数提示: {se}")

        # 最终保存会话
        browser_manager.save_session(desktop_context, email)
        page.close()
        desktop_context.close()
        desktop_context = None

        logger.info(f"🎉 账号 {email} 任务顺利结束！最终积分: {result['end_points']} (今日净增: +{result['earned_today']})")

    except Exception as e:
        logger.error(f"账号 {email} 自动化处理流程异常: {e}", exc_info=True)
        result["message"] = f"异常报错: {str(e)[:100]}"
    finally:
        if desktop_context:
            try:
                desktop_context.close()
            except Exception:
                pass

    return result

def push_to_remote_dashboard(results: List[Dict[str, Any]]):
    """自动将每日打卡数据推送至远程监控大盘（若配置了 DASHBOARD_REPORT_URL）"""
    if not DASHBOARD_REPORT_URL:
        return
    try:
        import requests
        headers = {
            "Content-Type": "application/json"
        }
        if DASHBOARD_REPORT_TOKEN:
            headers["X-Rewards-Token"] = DASHBOARD_REPORT_TOKEN

        resp = requests.post(DASHBOARD_REPORT_URL, json=results, headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info("📡 成功将今日打卡战报同步推送至监控大盘！")
        else:
            logger.warning(f"推送至监控大盘提示 ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.debug(f"推送监控大盘网络提示: {e}")

def run_all(args: argparse.Namespace):
    """执行全部账号自动化流程"""
    accounts = load_accounts()
    if not accounts:
        logger.error("未找到有效的账号配置！请在 accounts.json 或通过环境变量 ACCOUNTS_CONFIG 配置账号。")
        logger.info("可参考 config/accounts.example.json 模板创建 accounts.json")
        return

    logger.info(f"🚀 Bing Rewards Pro 启动！共加载 {len(accounts)} 个有效账号")

    # 若指定了 --account，仅处理目标账号
    if getattr(args, "account", ""):
        accounts = [a for a in accounts if args.account.lower() in a.get("email", "").lower()]
        if not accounts:
            logger.error(f"未找到匹配 --account '{args.account}' 的有效账号！")
            return
        logger.info(f"🎯 已筛选目标账号: {[a.get('email') for a in accounts]}")

    # 预先生成关键词库，保证本次运行词汇丰富充足
    total_search_needed = (args.pc_count + args.mobile_count) * len(accounts) + 20
    hotwords = get_hotwords(count=total_search_needed)

    browser_manager = BrowserManager(headless=not args.no_headless)
    browser_manager.start()

    results = []
    try:
        for idx, acc in enumerate(accounts):
            res = process_single_account(browser_manager, acc, hotwords, args)
            results.append(res)
            # 多账号之间微休眠，防止同一 IP 突发高频请求
            if idx < len(accounts) - 1:
                logger.info("等待 10 秒后开始处理下一个账号...")
                time.sleep(10)
    finally:
        browser_manager.close()

    # 结果汇总与通知
    report = format_report(results)
    logger.info("\n" + report)
    send_notification(title="Bing Rewards 任务执行简报", content=report)
    push_to_remote_dashboard(results)

def daemon_loop(args: argparse.Namespace):
    """常驻后台，每天指定时间自动执行"""
    target_hour, target_minute = map(int, args.schedule_time.split(":"))
    logger.info(f"⏰ 守护进程已启动，将在每天 {target_hour:02d}:{target_minute:02d} 自动运行...")

    while True:
        try:
            now = datetime.datetime.now()
            target_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now >= target_time:
                target_time += datetime.timedelta(days=1)

            wait_seconds = (target_time - now).total_seconds()
            hours = wait_seconds // 3600
            minutes = (wait_seconds % 3600) // 60
            logger.info(f"距离下次定时运行还有 {int(hours)} 小时 {int(minutes)} 分钟 ({target_time.strftime('%Y-%m-%d %H:%M:%S')})")

            # 休眠等待
            if wait_seconds > 300:
                time.sleep(300)
            else:
                time.sleep(wait_seconds)
                logger.info("=== 触发定时任务执行 ===")
                run_all(args)
                time.sleep(60)

        except KeyboardInterrupt:
            logger.info("收到退出信号，退出守护进程")
            break
        except Exception as e:
            logger.error(f"守护进程出现未知错误: {e}")
            time.sleep(60)

def main():
    parser = argparse.ArgumentParser(description="Bing Rewards Pro - 现代化自动签到与搜索积分系统")
    parser.add_argument("--once", action="store_true", default=True, help="单次执行模式（默认）")
    parser.add_argument("--daemon", action="store_true", help="常驻守护模式，每天定时自动执行")
    parser.add_argument("--schedule-time", type=str, default="09:30", help="定时执行时间 (格式 HH:MM，默认 09:30)")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（调试排查时推荐）")
    parser.add_argument("--pc-only", action="store_true", help="仅执行 PC 端搜索任务")
    parser.add_argument("--mobile-only", action="store_true", help="仅执行移动端搜索任务")
    parser.add_argument("--skip-search", action="store_true", help="仅执行签到和任务卡片，跳过搜索")
    parser.add_argument("--pc-count", type=int, default=DEFAULT_PC_SEARCH_COUNT, help=f"PC 搜索次数 (默认 {DEFAULT_PC_SEARCH_COUNT})")
    parser.add_argument("--mobile-count", type=int, default=DEFAULT_MOBILE_SEARCH_COUNT, help=f"移动端搜索次数 (默认 {DEFAULT_MOBILE_SEARCH_COUNT})")
    parser.add_argument("--account", type=str, default="", help="仅执行指定的邮箱账号（支持模糊匹配）")

    args = parser.parse_args()

    if args.daemon:
        daemon_loop(args)
    else:
        run_all(args)

if __name__ == "__main__":
    main()

