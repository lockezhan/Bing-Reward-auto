import random
import requests
import re
from bs4 import BeautifulSoup
from typing import List
from utils.logger import logger

# 预设种子词库（用于发散联想）
SEED_KEYWORDS = [
    "人工智能", "深度学习", "机器学习", "大模型", "芯片制造", "量子计算",
    "航天探索", "火星探测", "韦伯望远镜", "黑洞照片", "可控核聚变",
    "新能源汽车", "固态电池", "自动驾驶", "光伏发电", "储能技术",
    "现代医学", "生物工程", "基因编辑", "微生态", "长寿科技",
    "历史文明", "古罗马", "大汉王朝", "文艺复兴", "丝绸之路",
    "旅行攻略", "川西自驾", "西藏自驾", "冰岛极光", "瑞士风光",
    "家常菜谱", "烘焙技巧", "咖啡豆烘焙", "茶道文化", "减脂食谱",
    "经典电影", "科幻小说", "世界名著", "交响乐赏析", "摄影构图",
    "Python编程", "Linux系统内核", "分布式存储", "高并发架构", "计算机网络"
]

# 兜底备用常用多领域词汇库
FALLBACK_WORDS = [
    "2026年科技创新趋势", "量子计算最新突破进展", "可控核聚变商业化前景",
    "火星基地建设可行性研究", "空间站长期驻留对人体的影响", "韦伯太空望远镜新发现",
    "现代城市轨道交通规划", "高效储能电池材料研发", "光伏组件转换效率新纪录",
    "人工智能在药物研发中的应用", "蛋白质结构预测算法演进", "合成生物学未来发展",
    "古代丝绸之路贸易路线考证", "中世纪欧洲建筑风格演变", "唐代诗歌发展脉络",
    "全球深海热泉生态系统研究", "热带雨林生物多样性保护", "极地冰盖消融监测数据",
    "现代微型传感器设计", "RISC-V开源架构生态发展", "高带宽内存HBM技术路线",
    "低延迟网络传输协议优化", "多模态大模型对齐技术", "自动驾驶端到端神经网络",
    "智能电网调度优化模型", "第三代半导体氮化镓应用", "超导材料最新实验验证",
    "脑机接口信号解码新方法", "固态硬盘主控芯片架构演进", "现代密码学抗量子算法"
]

def fetch_bing_suggestions(keyword: str) -> List[str]:
    """通过 Bing 自身联想接口获取当前最真实的相关搜索词"""
    results = []
    try:
        url = f"https://cn.bing.com/AS/Suggestions?qry={keyword}&cvid=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        }
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for li in soup.find_all("li", class_="sa_sg"):
                query = li.get("query")
                if query and len(query.strip()) > 1:
                    results.append(query.strip())
    except Exception as e:
        logger.debug(f"Bing 联想词接口获取失败 [{keyword}]: {e}")
    return results

def get_hotwords(count: int = 60) -> List[str]:
    """
    智能获取高质量搜索关键词：
    1. 动态抽取种子词并通过 Bing 实时联想扩充
    2. 若网络受限则融合内置大词库动态重组
    3. 保证生成数量与无序随机性
    """
    collected = set()
    logger.info("开始生成/获取高质量搜索关键词...")

    # 随机打乱种子词
    sampled_seeds = random.sample(SEED_KEYWORDS, min(12, len(SEED_KEYWORDS)))

    for seed in sampled_seeds:
        suggestions = fetch_bing_suggestions(seed)
        for w in suggestions:
            if w not in collected:
                collected.add(w)
        if len(collected) >= count * 1.5:
            break

    # 如果抓取量不足，补充备用词库与随机组合词
    if len(collected) < count:
        logger.info(f"联想词采集到 {len(collected)} 个，使用备用大词库进行丰富与组合...")
        shuffled_fallback = list(FALLBACK_WORDS)
        random.shuffle(shuffled_fallback)
        for word in shuffled_fallback:
            collected.add(word)
            if len(collected) >= count:
                break

    # 动态拼接词组（增强搜索词真实性与多样性）
    prefixes = ["了解一下", "如何看待", "最新资讯", "详细解析", "深度思考", "历史渊源", "未来发展"]
    suffixes = ["现状与未来", "技术原理", "最新报道", "完整指南", "常见误区", "学术探讨"]
    
    while len(collected) < count:
        base = random.choice(SEED_KEYWORDS)
        if random.random() < 0.5:
            phrase = f"{random.choice(prefixes)} {base}"
        else:
            phrase = f"{base} {random.choice(suffixes)}"
        collected.add(phrase)

    result_list = list(collected)
    random.shuffle(result_list)
    logger.info(f"成功准备了 {len(result_list[:count])} 个多样化搜索词")
    return result_list[:count]

