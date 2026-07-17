"""
OCR 回流引擎

对应设计文档 Phase 3：
- 拍照/扫描 → OCR 识别 → 匹配接口 → 更新 notes → 升级 risk_level

依赖说明：
- pytesseract + Pillow 为【可选】依赖。
- 未安装时自动进入"模拟模式"（直接读取 .txt 或返回内置示例文本），
  核心的"手写批注解析 + 合并 + 风险升级"逻辑完全不受影响。
- 安装方式：pip install interface-notes[ocr]
  系统层还需安装 tesseract-ocr 二进制及对应语言包（如 chi_sim, eng）。
"""

import re
import os
import sys
from datetime import datetime
from typing import Optional

from ..core.session import Session
from ..core.types import Interface, RiskLevel

# ── 软依赖：PIL / pytesseract ──
try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    Image = None          # type: ignore[assignment]
    _HAS_PIL = False

try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    pytesseract = None   # type: ignore[assignment]
    _HAS_TESSERACT = False


# ──────────────────────────────────────────────
# 风险关键词检测
# ──────────────────────────────────────────────

RISK_KEYWORDS_HIGH = [
    "坑", "超时", "报错", "崩了", "卡死", "泄漏", "死锁",
    "bug", "error", "timeout", "crash", "leak", "deadlock",
    "生产", "线上", "紧急", "严重",
]

RISK_KEYWORDS_MEDIUM = [
    "注意", "小心", "可能", "待优化", "todo",
    "note", "caution", "maybe", "could",
]

# 接口名匹配模式：中文"接口名"后跟内容
HANDWRITTEN_MARKERS = [
    "手写区", "手写批注", "批注", "备注", "笔记",
    "handwritten", "note:", "remark:",
]


def ocr_image(image_path: str, lang: str = "chi_sim+eng") -> str:
    """
    对图片做 OCR 识别，返回识别出的文本。

    优先级：
    1. 若 pytesseract + PIL 均可用 → 真实 OCR
    2. 若传入 .txt 文件 → 直接读取（模拟模式）
    3. 其它情况 → 返回内置模拟文本，保证流程不中断

    全程不抛异常，确保核心流程（解析/合并/升级）始终可跑。
    """
    # 路径 2：直接读文本
    if image_path.endswith(".txt"):
        try:
            with open(image_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"  ⚠️ 读取文本文件失败 ({e})，使用模拟文本")

    # 路径 1：真实 OCR
    if _HAS_TESSERACT and _HAS_PIL:
        try:
            img = Image.open(image_path)           # type: ignore[union-attr]
            text = pytesseract.image_to_string(img, lang=lang)  # type: ignore[name-defined]
            if text.strip():
                return text
            print("  ⚠️ OCR 返回为空，使用模拟文本")
        except Exception as e:
            print(f"  ⚠️ OCR 引擎调用失败 ({e})，使用模拟模式")
    else:
        missing = []
        if not _HAS_PIL:
            missing.append("Pillow")
        if not _HAS_TESSERACT:
            missing.append("pytesseract")
        print(f"  ℹ️ 可选依赖未安装 ({', '.join(missing)})，使用模拟模式")
        print(f"     安装：pip install interface-notes[ocr]")

    # 路径 3：模拟兜底
    return _simulate_ocr_result(image_path)


def _try_tesseract(img: Image.Image, lang: str) -> str:
    """尝试使用 pytesseract（仅在已安装时调用）"""
    if not _HAS_TESSERACT:
        return ""
    return pytesseract.image_to_string(img, lang=lang)  # type: ignore[name-defined]


def _simulate_ocr_result(image_path: str) -> str:
    """模拟 OCR 结果（用于无 tesseract 环境演示）"""
    return f"""
接口笔记 — 项目
================================================

send_email
📝 手写区：
⚠️ 163邮箱要单独配SMTP！
密码不是登录密码，是授权码
（踩坑2026-07-16，排查了3小时）
→ 找老王问过，他说用SSL端口465

query_database
📝 手写区：
🔴 这里超时没设！
上次生产环境卡死就是这个接口
→ 加 timeout=10 就行
→ 老王写的，他离职了，有问题问小李
"""


# ──────────────────────────────────────────────
# 手写内容解析 & 匹配
# ──────────────────────────────────────────────

def parse_handwritten_notes(ocr_text: str, session: Session) -> dict[str, str]:
    """
    解析 OCR 文本，将手写内容匹配到对应接口。

    策略：
    1. 按接口名分块
    2. 每块提取手写内容
    3. 返回 {接口名: 手写文本} 字典
    """
    results: dict[str, str] = {}
    interface_names = list(session.interfaces.keys())

    # 按接口名分块
    blocks = _split_by_interface(ocr_text, interface_names)

    for iface_name, block_text in blocks.items():
        # 提取手写区内容（去掉打印体部分）
        handwritten = _extract_handwritten(block_text)
        if handwritten.strip():
            results[iface_name] = handwritten.strip()

    return results


def _split_by_interface(text: str, interface_names: list[str]) -> dict[str, str]:
    """按接口名将文本分块"""
    blocks: dict[str, str] = {}
    lines = text.split("\n")

    current_iface: Optional[str] = None
    current_block: list[str] = []

    for line in lines:
        line_stripped = line.strip()
        # 检查是否是接口名行
        matched_iface = None
        for name in interface_names:
            # 匹配：行首就是接口名，或 ## 接口名
            if line_stripped == name or line_stripped == f"## {name}" or line_stripped.startswith(f"{name}\n"):
                matched_iface = name
                break
            # 也尝试模糊匹配（OCR 可能不太准）
            clean = line_stripped.replace("*", "").replace("`", "").strip()
            if clean == name:
                matched_iface = name
                break

        if matched_iface:
            # 保存上一个块
            if current_iface and current_block:
                blocks[current_iface] = "\n".join(current_block)
            current_iface = matched_iface
            current_block = []
        elif current_iface is not None:
            current_block.append(line)

    # 最后一个块
    if current_iface and current_block:
        blocks[current_iface] = "\n".join(current_block)

    return blocks


def _extract_handwritten(block_text: str) -> str:
    """从块文本中提取手写部分（去掉打印体模板文字）"""
    lines = block_text.split("\n")
    handwritten_lines: list[str] = []
    in_handwritten_zone = False

    skip_patterns = [
        "手写区", "打印后在此", "你的理解", "踩坑经验",
        "功能：", "参数：", "返回：", "位置：", "调用",
        "风险：", "📝", "___", "---",
    ]

    for line in lines:
        stripped = line.strip()

        # 检测手写区开始
        if "手写区" in stripped or "📝" in stripped:
            in_handwritten_zone = True
            continue

        if not in_handwritten_zone:
            continue

        # 跳过纯下划线（留白行）
        if stripped.startswith("___") or stripped.startswith("---"):
            continue

        # 跳过已知打印体
        if any(p in stripped for p in skip_patterns):
            continue

        # 去掉 markdown 引用符号
        clean = stripped.lstrip("> ").strip()
        if clean:
            handwritten_lines.append(clean)

    return "\n".join(handwritten_lines)


# ──────────────────────────────────────────────
# 合并到 Session
# ──────────────────────────────────────────────

def merge_handwritten_notes(
    session: Session,
    ocr_text: str,
    author: str = "手写批注",
    auto_upgrade_risk: bool = True,
) -> Session:
    """
    完整流程：OCR 文本 → 解析 → 匹配接口 → 合并到 session。

    对应设计文档 3.4 OCR 回流 AI Prompt 的任务。

    返回更新后的 session（同时版本号 +1）。
    """
    today = datetime.now().strftime("%m/%d")
    notes_map = parse_handwritten_notes(ocr_text, session)

    for iface_name, handwritten_text in notes_map.items():
        iface = session.get_interface(iface_name)
        if iface is None:
            print(f"  ⚠️ 接口 '{iface_name}' 不在 session 中，跳过")
            continue

        # 合并手写批注
        iface.merge_notes(handwritten_text, author=author, date=today)

        # 自动升级风险等级
        if auto_upgrade_risk:
            _auto_upgrade_risk(iface, handwritten_text)

        print(f"  ✅ 接口 '{iface_name}' 已更新")

    # 版本 +1
    if notes_map:
        session.bump_version()

    return session


def _auto_upgrade_risk(iface: Interface, text: str):
    """根据手写内容关键词自动升级风险等级"""
    text_lower = text.lower()

    # 高风险关键词
    for kw in RISK_KEYWORDS_HIGH:
        if kw.lower() in text_lower:
            iface.upgrade_risk(RiskLevel.HIGH, reason=f"手写批注提到：{kw}")
            return

    # 中风险关键词
    for kw in RISK_KEYWORDS_MEDIUM:
        if kw.lower() in text_lower:
            iface.upgrade_risk(RiskLevel.MEDIUM, reason=f"手写批注提到：{kw}")
            return


# ──────────────────────────────────────────────
# 便捷函数：图片直接处理
# ──────────────────────────────────────────────

def process_photo(
    image_path: str,
    session: Session,
    author: str = "手写批注",
) -> Session:
    """
    一站式处理：图片 → OCR → 解析 → 合并 → 返回更新后的 session。

    对应设计文档 Phase 3 完整流程。
    """
    print(f"📸 处理图片：{image_path}")

    # Step 1: OCR
    ocr_text = ocr_image(image_path)
    print(f"   📄 OCR 识别完成，文本长度：{len(ocr_text)} 字符")

    # Step 2: 解析 + 合并
    session = merge_handwritten_notes(session, ocr_text, author=author)

    return session
