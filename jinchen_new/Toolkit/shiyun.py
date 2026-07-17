#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shiyun.py — 硬核叙事工厂

内置 30+ 题材库、自定义维度审讯、钩子管理、冲突附录。
适合小说、剧本等结构化叙事创作。

注意：本模块不做"自动写书"，而是提供结构化的叙事辅助工具。
"""

import json
import random
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("shiyun")


# ════════════════════════════════════════════════════════
# 题材库（30+）
# ════════════════════════════════════════════════════════

GENRES: dict[str, dict] = {
    "硬核科幻":     {"hooks": ["科技伦理", "文明存亡", "物理极限"], "conflicts": ["技术失控", "星际战争", "AI觉醒"]},
    "赛博朋克":     {"hooks": ["义体改造", "巨型企业", "信息黑市"], "conflicts": ["阶级压迫", "意识上传", "数据战争"]},
    "太空歌剧":     {"hooks": ["星际帝国", "异星文明", "超光速旅行"], "conflicts": ["帝国衰亡", "文明碰撞", "资源争夺"]},
    "末世废土":     {"hooks": ["文明废墟", "资源匮乏", "变异威胁"], "conflicts": ["部落战争", "变异危机", "旧世界遗产"]},
    "时间旅行":     {"hooks": ["时间悖论", "历史改写", "因果循环"], "conflicts": ["蝴蝶效应", "时间警察", "自我相遇"]},
    "架空奇幻":     {"hooks": ["魔法体系", "异世界", "古老预言"], "conflicts": ["善恶大战", "王位争夺", "远古觉醒"]},
    "都市异能":     {"hooks": ["隐藏世界", "超能力者", "秘密组织"], "conflicts": ["身份暴露", "组织对抗", "能力失控"]},
    "悬疑推理":     {"hooks": ["密室谜题", "连环案件", "不在场证明"], "conflicts": ["真凶反转", "证据消失", "时间诡计"]},
    "心理惊悚":     {"hooks": ["精神崩溃", "记忆篡改", "人格分裂"], "conflicts": ["自我认知", "他人操控", "现实模糊"]},
    "社会寓言":     {"hooks": ["极端社会", "人性实验", "制度批判"], "conflicts": ["个体vs体制", "自由vs安全", "平等vs效率"]},
    "历史架空":     {"hooks": ["历史if线", "古代重生", "文明碰撞"], "conflicts": ["时代变革", "文化冲突", "命运改写"]},
    "武侠江湖":     {"hooks": ["门派恩怨", "武学秘籍", "江湖规矩"], "conflicts": ["正邪之争", "师门背叛", "武林大会"]},
    "仙侠修真":     {"hooks": ["修仙体系", "天地灵气", "飞升成仙"], "conflicts": ["道心魔障", "宗门大战", "天劫降临"]},
    "克苏鲁":       {"hooks": ["不可名状", "古神低语", "禁忌知识"], "conflicts": ["理智崩溃", "邪教崛起", "旧日支配"]},
    "蒸汽朋克":     {"hooks": ["蒸汽机械", "维多利亚", "飞行船"], "conflicts": ["工业革命", "阶级冲突", "技术禁忌"]},
    "暗黑哥特":     {"hooks": ["古老城堡", "家族诅咒", "黑暗秘密"], "conflicts": ["血脉宿命", "宗教审判", "永生诅咒"]},
    "校园青春":     {"hooks": ["青春成长", "同窗情谊", "初恋懵懂"], "conflicts": ["升学压力", "家庭变故", "友情裂痕"]},
    "职场商战":     {"hooks": ["公司政治", "商业机密", "创业热血"], "conflicts": ["行业竞争", "道德困境", "利益诱惑"]},
    "家庭伦理":     {"hooks": ["代际冲突", "家族秘密", "亲情考验"], "conflicts": ["观念碰撞", "遗产纠纷", "赡养困境"]},
    "美食治愈":     {"hooks": ["料理修行", "食材故事", "食客百态"], "conflicts": ["传承危机", "创新阻力", "味觉记忆"]},
    "运动竞技":     {"hooks": ["热血训练", "赛场对决", "团队精神"], "conflicts": ["伤病考验", "对手宿命", "退役抉择"]},
    "音乐艺术":     {"hooks": ["才华觉醒", "艺术追求", "舞台人生"], "conflicts": ["商业vs艺术", "灵感枯竭", "名利诱惑"]},
    "军事战争":     {"hooks": ["战场生死", "军事谋略", "家国情怀"], "conflicts": ["战争伦理", "战友背叛", "战后创伤"]},
    "侦探Noir":     {"hooks": ["昏暗巷弄", "蛇蝎美人", "黑色交易"], "conflicts": ["道德灰色", "权力腐蚀", "自我救赎"]},
    "童话暗黑":     {"hooks": ["经典重构", "童年阴影", "童话反转"], "conflicts": ["纯真丧失", "邪恶胜利", "现实残酷"]},
    "极简寓言":     {"hooks": ["动物拟人", "自然哲理", "道德小品"], "conflicts": ["弱肉强食", "生态平衡", "人性本质"]},
    "讽刺荒诞":     {"hooks": ["官僚体系", "消费主义", "信息茧房"], "conflicts": ["个体异化", "系统荒谬", "真相遮蔽"]},
    "循环轮回":     {"hooks": ["无限重复", "记忆碎片", "宿命纠缠"], "conflicts": ["打破循环", "遗忘痛苦", "选择自由"]},
    "平行世界":     {"hooks": ["世界线分支", "镜像自我", "蝴蝶效应"], "conflicts": ["身份混淆", "选择后悔", "世界碰撞"]},
    "生物朋克":     {"hooks": ["基因编辑", "生物改造", "生态灾难"], "conflicts": ["伦理边界", "物种战争", "自然报复"]},
    "虚拟世界":     {"hooks": ["元宇宙", "VR沉浸", "数字永生"], "conflicts": ["现实逃避", "AI意识", "虚拟犯罪"]},
}


# ════════════════════════════════════════════════════════
# 维度审讯器
# ════════════════════════════════════════════════════════

INTERROGATION_DIMENSIONS: list[dict] = [
    {"dim": "主角想要什么",     "purpose": "明确驱动力"},
    {"dim": "主角害怕什么",     "purpose": "制造弱点"},
    {"dim": "主角最深的秘密",   "purpose": "埋伏笔"},
    {"dim": "谁在阻止主角",     "purpose": "确立反派/障碍"},
    {"dim": "代价是什么",       "purpose": "提高张力"},
    {"dim": "如果失败会怎样",   "purpose": "提升紧迫感"},
    {"dim": "世界规则是什么",   "purpose": "建立设定边界"},
    {"dim": "这个场景的钩子",   "purpose": "吸引读者"},
    {"dim": "这一章的转折",     "purpose": "避免平铺直叙"},
    {"dim": "读者此刻的感受",   "purpose": "情绪节奏控制"},
]


@dataclass
class SceneCard:
    """场景指令卡 —— 刚性结构，喂给 AI 时它不会跑偏"""
    scene_id: str
    pov: str
    timeline: str
    location: str
    goal: str
    must_include: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    output_hint: str = ""  # 字数/风格提示


class Shiyun:
    """硬核叙事工厂"""

    def __init__(self, store_dir: str = "shiyun_store"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    # ── 题材 ────────────────────────────────────────
    def list_genres(self) -> list[str]:
        return list(GENRES.keys())

    def get_genre(self, name: str) -> Optional[dict]:
        return GENRES.get(name)

    def random_genre(self) -> str:
        return random.choice(list(GENRES.keys()))

    # ── 维度审讯 ────────────────────────────────────
    def interrogate(self, dims: list[str] | None = None) -> list[dict]:
        """返回一组审讯问题"""
        if dims:
            return [d for d in INTERROGATION_DIMENSIONS if d["dim"] in dims]
        return list(INTERROGATION_DIMENSIONS)

    # ── 场景卡 ──────────────────────────────────────
    def make_scene_card(self, **kwargs) -> SceneCard:
        return SceneCard(**kwargs)

    def scene_to_prompt(self, card: SceneCard) -> str:
        """把场景卡转成喂给 AI 的 prompt"""
        lines = [
            f"# 场景指令卡 {card.scene_id}",
            f"",
            f"**POV**: {card.pov}",
            f"**时间线**: {card.timeline}",
            f"**地点**: {card.location}",
            f"**场景目标**: {card.goal}",
            f"",
            f"## 必须包含",
        ]
        for item in card.must_include:
            lines.append(f"- {item}")
        if card.must_not:
            lines.append(f"")
            lines.append(f"## 绝对禁止")
            for item in card.must_not:
                lines.append(f"- {item}")
        if card.output_hint:
            lines.append(f"")
            lines.append(f"## 输出要求")
            lines.append(f"{card.output_hint}")
        return "\n".join(lines)

    # ── 钩子管理 ────────────────────────────────────
    def generate_hooks(self, genre: str, count: int = 3) -> list[str]:
        """为指定题材生成钩子"""
        g = self.get_genre(genre)
        if not g:
            return []
        hooks = g.get("hooks", [])
        return random.sample(hooks, min(count, len(hooks)))

    # ── 冲突附录 ────────────────────────────────────
    def list_conflicts(self, genre: str) -> list[str]:
        g = self.get_genre(genre)
        return g.get("conflicts", []) if g else []

    # ── 保存/加载 ───────────────────────────────────
    def save_scene(self, card: SceneCard) -> Path:
        p = self.store_dir / f"scene_{card.scene_id}.json"
        p.write_text(json.dumps(card.__dict__, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p


if __name__ == "__main__":
    s = Shiyun("test_shiyun")
    print(f"📖 支持 {len(s.list_genres())} 种题材")
    print(f"   题材示例: {s.list_genres()[:5]}")

    # 随机选题材
    g = s.random_genre()
    print(f"\n🎲 随机题材: {g}")
    print(f"   钩子: {s.generate_hooks(g)}")
    print(f"   冲突: {s.list_conflicts(g)}")

    # 做一张场景卡
    card = s.make_scene_card(
        scene_id="1-1",
        pov="金呈（第三人称有限）",
        timeline="第十世·丙辰年·清晨",
        location="朱墙内殿",
        goal="他发现自己今天起床时，指尖是半透明的",
        must_include=[
            "他照镜子的动作（但不要写'他感到恐惧'）",
            "他对着镜子说'我是金呈，我还在'",
            "镜子里映出的不是他现在的脸，是第七世'一日帝'的脸（一闪而过）",
            "他忽略这个异常（认知封印在起作用）",
        ],
        must_not=[
            "任何心理描写直接说'他害怕/孤独/绝望'",
            "任何关于'权柄''消散''博士'的直白解释",
            "AI 常用的比喻（如'像蜡烛燃烧''像沙漏流逝'）",
        ],
        output_hint="800-1200字，白描为主，对话不超过3句",
    )
    prompt = s.scene_to_prompt(card)
    print(f"\n📋 场景指令卡:\n{prompt}")
    s.save_scene(card)
    print(f"\n💾 已保存: scene_1-1.json")
