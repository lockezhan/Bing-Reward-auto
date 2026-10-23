import requests
import json
from typing import List, Dict, Any
from config.settings import PUSHPLUS_TOKEN, SERVERCHAN_KEY, CUSTOM_WEBHOOK
from utils.logger import logger

def format_report(results: List[Dict[str, Any]]) -> str:
    """生成 Markdown 格式的执行结果汇总报告"""
    total_acc = len(results)
    success_count = sum(1 for r in results if r.get("status") == "success")
    fail_count = total_acc - success_count

    lines = [
        "## 🎁 Bing Rewards 自动签到与搜索任务简报",
        f"- **总执行账号数**: {total_acc}",
        f"- **成功完成**: {success_count}",
        f"- **异常失败**: {fail_count}",
        "",
        "| 账号 | 状态 | 初始积分 | 当前总积分 | 今日新增 | 连签天数 | 备注 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |"
    ]

    for r in results:
        email = r.get("email", "unknown")
        # 邮箱简单脱敏
        parts = email.split("@")
        masked_email = f"{parts[0][:3]}***@{parts[1]}" if len(parts) == 2 else email
        status_icon = "✅ 成功" if r.get("status") == "success" else "❌ 失败"
        start_pts = r.get("start_points", "-")
        end_pts = r.get("end_points", "-")
        earned_pts = r.get("earned_today", "-")
        streak = r.get("streak_days", "-")
        streak_str = f"🔥 {streak}天" if isinstance(streak, int) and streak > 0 else (f"{streak}天" if str(streak).isdigit() and int(streak) > 0 else "-")
        note = r.get("message", "无")

        lines.append(f"| {masked_email} | {status_icon} | {start_pts} | {end_pts} | {earned_pts} | {streak_str} | {note} |")

    return "\n".join(lines)

def send_notification(title: str, content: str):
    """根据配置的 Token 发送推送通知"""
    if PUSHPLUS_TOKEN:
        try:
            url = "http://www.pushplus.plus/send"
            payload = {
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "markdown"
            }
            resp = requests.post(url, json=payload, timeout=10)
            logger.info(f"[通知] PushPlus 推送响应: {resp.text}")
        except Exception as e:
            logger.error(f"[通知] PushPlus 推送失败: {e}")

    if SERVERCHAN_KEY:
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            payload = {
                "title": title,
                "desp": content
            }
            resp = requests.post(url, data=payload, timeout=10)
            logger.info(f"[通知] Server酱推送响应: {resp.text}")
        except Exception as e:
            logger.error(f"[通知] Server酱推送失败: {e}")

    if CUSTOM_WEBHOOK:
        try:
            # 兼容普通 webhook
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": content
                }
            }
            resp = requests.post(CUSTOM_WEBHOOK, json=payload, timeout=10)
            logger.info(f"[通知] Webhook 推送响应: {resp.text}")
        except Exception as e:
            logger.error(f"[通知] Webhook 推送失败: {e}")

