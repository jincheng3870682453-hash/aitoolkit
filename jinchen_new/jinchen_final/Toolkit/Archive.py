#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archive.py — 长对话记忆与主题感知

基于 64 位 SimHash 分块计算，支持：
  - 主题切换检测
  - 短输入保护
  - 紧急度信号
  - 解决 AI 长对话"失忆"问题
"""

import re
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

log = logging.getLogger("archive")


# ═════════════════════════════════════════════════════════
# SimHash 实现（64 位）
# ═════════════════════════════════════════════════════════

class SimHash64:
    """64 位 SimHash 计算"""

    HASH_BITS = 64

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """中文按字符 + 英文按词"""
        tokens = []
        # 中文字符
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(f"c:{ch}")
        # 英文单词
        tokens += [f"w:{w}" for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower())]
        # 数字
        tokens += [f"n:{n}" for n in re.findall(r"\d+", text)]
        return tokens

    @staticmethod
    def hash_token(token: str) -> int:
        return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)

    @classmethod
    def compute(cls, text: str) -> int:
        """计算文本的 64 位 SimHash"""
        tokens = cls.tokenize(text)
        if not tokens:
            return 0
        v = [0] * cls.HASH_BITS
        for tok in tokens:
            h = cls.hash_token(tok)
            for i in range(cls.HASH_BITS):
                if (h >> i) & 1:
                    v[i] += 1
                else:
                    v[i] -= 1
        result = 0
        for i in range(cls.HASH_BITS):
            if v[i] > 0:
                result |= (1 << i)
        return result

    @classmethod
    def distance(cls, h1: int, h2: int) -> int:
        """汉明距离"""
        x = h1 ^ h2
        count = 0
        while x:
            count += 1
            x &= x - 1
        return count


# ═════════════════════════════════════════════════════════
# Archive  长对话记忆引擎
# ═════════════════════════════════════════════════════════

class Archive:
    """
    长对话记忆 —— SimHash + 主题感知。
    解决 AI 长对话"失忆"问题。
    """

    SHORT_INPUT_THRESHOLD = 5      # 短输入字符数
    TOPIC_SHIFT_DISTANCE = 15      # 主题切换汉明距离阈值
    URGENCY_KEYWORDS = [
        "紧急", "立刻", "马上", "尽快", "赶紧", "urgent", "asap",
        "崩溃", "报错", "error", "exception", "failed", "炸了",
    ]

    def __init__(self, store_dir: str = "archive_store"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.conversations: dict[str, list[dict]] = defaultdict(list)

    def _store_path(self, conv_id: str) -> Path:
        return self.store_dir / f"{conv_id}.jsonl"

    def remember(self, conv_id: str, text: str,
                 role: str = "user") -> dict:
        """记住一条对话，返回记忆分析结果"""
        text = text.strip()
        if not text:
            return {"status": "ignored", "reason": "empty"}

        # 计算 SimHash
        h = SimHash64.compute(text)

        # 短输入保护
        is_short = len(text) < self.SHORT_INPUT_THRESHOLD

        # 紧急度检测
        urgency = any(kw in text.lower() for kw in self.URGENCY_KEYWORDS)

        # 主题切换检测
        history = self.conversations[conv_id]
        topic_shift = False
        if history:
            last_h = history[-1].get("hash", 0)
            dist = SimHash64.distance(h, last_h)
            topic_shift = dist >= self.TOPIC_SHIFT_DISTANCE

        # 存储
        entry = {
            "ts": datetime.now().isoformat(),
            "role": role,
            "text": text[:500],
            "hash": h,
            "short": is_short,
            "urgency": urgency,
            "topic_shift": topic_shift,
        }
        self.conversations[conv_id].append(entry)

        # 持久化
        with open(self._store_path(conv_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return {
            "status": "stored",
            "hash": h,
            "short_input": is_short,
            "urgency": urgency,
            "topic_shift": topic_shift,
            "history_len": len(self.conversations[conv_id]),
        }

    def recall(self, conv_id: str, limit: int = 10) -> list[dict]:
        """召回最近 N 条记忆"""
        return self.conversations[conv_id][-limit:]

    def context_inject(self, conv_id: str, limit: int = 5) -> str:
        """生成上下文注入文本（给 AI 的提示）"""
        recent = self.recall(conv_id, limit)
        if not recent:
            return ""
        lines = []
        for e in recent:
            marker = "⚡" if e.get("urgency") else "  "
            shift = " 🔄主题切换" if e.get("topic_shift") else ""
            lines.append(f"{marker} [{e['role']}]{shift} {e['text'][:200]}")
        return "\n".join(lines)

    def detect_shift(self, conv_id: str) -> bool:
        """检测当前对话是否发生了主题切换"""
        hist = self.conversations[conv_id]
        if len(hist) < 2:
            return False
        h1 = hist[-2]["hash"]
        h2 = hist[-1]["hash"]
        return SimHash64.distance(h1, h2) >= self.TOPIC_SHIFT_DISTANCE

    def clear(self, conv_id: str) -> None:
        """清除某对话记忆"""
        self.conversations.pop(conv_id, None)
        p = self._store_path(conv_id)
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    a = Archive("test_archive")
    tests = [
        "帮我写一个 Python 登录接口",
        "加上 JWT 认证",
        "现在帮我构思小说剧情",   # 主题切换
        "算了还是先修 bug 吧",   # 切回来
        "紧急！生产环境崩了",     # 紧急
        "ok",                     # 短输入
    ]
    for t in tests:
        r = a.remember("demo", t)
        print(f"  [{r['status']}] urgent={r['urgency']} shift={r['topic_shift']} short={r['short_input']} | {t[:40]}")
    print("\n--- 上下文注入 ---")
    print(a.context_inject("demo"))
