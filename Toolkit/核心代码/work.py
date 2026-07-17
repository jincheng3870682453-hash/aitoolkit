#!/usr/bin/env python3
"""
Word体系 · 生产级完全体
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心升级（基于深度审计反馈）
1. 补全 AI 修复闭环：诱饵触发错误后，真正调用 AI 进行修复
2. 诱饵移动检测：AST 结构签名比对，识别"搬家"绕过
3. 条件包裹细化：检查 except 捕获类型，识别 if False 无效包裹
4. hybrid 模式真实实现：落盘前增加硬确认点
5. smoke_timeout 可配置：默认 30 秒，支持 --smoke-timeout
6. 规划器多关键词匹配：支持 "计算器|四则运算" 格式
7. AST 降级日志增加 Python 版本提示
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
状态：stable | 可审计 | 可对抗 | 可CI/CD | 闭环完整
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import time
import uuid
import re
import logging
import traceback
import argparse
import fnmatch
import tarfile
import random
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

# ============================================================
# 0. 日志与全局配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.99
STEALTH_EVIDENCE_DIR = "./.word_framework/stealth_evidence"
DEBUG_KEYWORDS = ["修", "改", "调", "错误", "报错", "bug", "异常", "崩溃", "失败"]

DEFAULT_SKELETON_TEMPLATES = {
    "计算器|四则运算": {"steps": ["定义加法", "定义减法", "主循环"], "skeleton": {"src/calc.py": "def add(a,b): return a+b\ndef main(): pass\n"}},
    "排序|sort": {"steps": ["实现排序算法", "测试"], "skeleton": {"src/sort.py": "def sort(arr): return sorted(arr)\n"}},
    "默认": {"steps": ["分析需求", "生成代码", "输出"], "skeleton": {"src/main.py": "def main():\n    print('hello')\n"}}
}

# ============================================================
# 1. 数据类型与上下文
# ============================================================
@dataclass(frozen=True)
class Context:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_root: str = "."
    user_input: str = ""
    error_log: str = ""
    timestamp: float = field(default_factory=time.time)
    planner_type: str = "rule"
    ai_provider: str = "ollama"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = "llama2"
    force_level: Optional[int] = None
    dry_run: bool = False
    strict_rollback: bool = False
    confirm_mode: str = "interactive"
    bait_confidence_threshold: float = CONFIDENCE_THRESHOLD
    mojibake_patterns: List[str] = field(default_factory=lambda: ['\ufffd', '锟斤拷', ' ', '', '', '', ''])
    debug: bool = False
    allow_symlink: bool = False
    smoke_timeout: int = 30
    ai_connect_timeout: int = 10
    ai_read_timeout: int = 120


# ============================================================
# 2. 配置文件加载
# ============================================================
def load_config(config_path: str) -> dict:
    default = {
        "project_root": ".",
        "planner": "rule",
        "ai_provider": "ollama",
        "ai_api_key": "",
        "ai_base_url": "",
        "ai_model": "llama2",
        "ignore_patterns": [".git", "__pycache__", "*.pyc", "*.log", "*.tmp"],
        "confirm_mode": "interactive",
        "bait_confidence_threshold": CONFIDENCE_THRESHOLD,
        "mojibake_patterns": ['\ufffd', '锟斤拷', ' ', '', '', '', ''],
        "allow_symlink": False,
        "smoke_timeout": 30,
        "ai_connect_timeout": 10,
        "ai_read_timeout": 120
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_cfg = json.load(f)
                default.update(user_cfg)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"配置文件 {config_path} 读取失败 ({e})，使用默认配置")
    return default


# ============================================================
# 3. 骨架模板加载（支持YAML，增强日志）
# ============================================================
def load_skeleton_templates(template_path: str = "config/skeleton_templates.yaml") -> dict:
    try:
        import yaml
        with open(template_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.info(f"骨架模板文件 {template_path} 不存在，使用内置默认模板")
    except ImportError:
        logger.warning("pyyaml 未安装，无法加载 YAML 模板，请运行 pip install pyyaml 以启用自定义模板。使用内置默认模板。")
    except Exception as e:
        logger.warning(f"YAML 解析失败 ({e})，使用内置默认模板")
    return DEFAULT_SKELETON_TEMPLATES


# ============================================================
# 4. AI API 调用（含重试 + 超时拆分）
# ============================================================
def retry(max_attempts=3, base_delay=2, backoff=2):
    def decorator(func):
        def wrapper(*args, **kwargs):
            attempt = 0
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    delay = base_delay * (backoff ** (attempt - 1))
                    logger.warning(f"请求失败 ({e})，{delay}s 后重试 ({attempt}/{max_attempts})")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


@retry(max_attempts=3, base_delay=2)
def call_ai_api(prompt: str, ctx: Context) -> str:
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests 未安装，请 pip install requests")

    provider = ctx.ai_provider.lower()
    model = ctx.ai_model
    api_key = ctx.ai_api_key
    base_url = ctx.ai_base_url

    DEFAULT_URLS = {
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "minimax": "https://api.minimax.io/v1/chat/completions",
        "baichuan": "https://api.baichuan-ai.com/v1/chat/completions",
        "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",
    }

    connect_timeout = getattr(ctx, 'ai_connect_timeout', 10)
    read_timeout = getattr(ctx, 'ai_read_timeout', 120)

    if provider in DEFAULT_URLS:
        url = base_url or DEFAULT_URLS[provider]
        if not api_key:
            raise ValueError(f"{provider} 需要提供 --ai-api-key")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 2048}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    if provider == "openai":
        url = base_url or "https://api.openai.com/v1/chat/completions"
        if not api_key:
            raise ValueError("OpenAI 需要提供 --ai-api-key")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 2048}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    if provider == "anthropic":
        url = base_url or "https://api.anthropic.com/v1/messages"
        if not api_key:
            raise ValueError("Anthropic 需要提供 --ai-api-key")
        headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
        payload = {"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    if provider == "gemini":
        if not api_key:
            raise ValueError("Gemini 需要提供 --ai-api-key")
        url = base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if "?" not in url:
            url += f"?key={api_key}"
        else:
            url += f"&key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, headers=headers, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    if provider == "ollama":
        url = base_url or "http://localhost:11434/api/generate"
        payload = {"model": model or "llama2", "prompt": prompt, "stream": False}
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=(connect_timeout, read_timeout))
        resp.raise_for_status()
        return resp.json().get("response", "")

    raise ValueError(f"不支持的AI提供商: {provider}")


# ============================================================
# 5. 规划器（规则引擎 + AI）- 多关键词匹配
# ============================================================
def rule_based_planner(user_input: str, error_log: str) -> Tuple[List[str], Dict[str, str]]:
    templates = load_skeleton_templates()
    for keyword, template in templates.items():
        patterns = keyword.split('|')
        for pattern in patterns:
            if pattern and pattern in user_input:
                return template["steps"], template["skeleton"]
    default = templates.get("默认", DEFAULT_SKELETON_TEMPLATES["默认"])
    return default["steps"], default["skeleton"]


def ai_planner(user_input: str, error_log: str, ctx: Context) -> Tuple[List[str], Dict[str, str]]:
    prompt = f"用户需求：{user_input}\n错误日志：{error_log}\n请输出JSON格式：{{'steps':[...], 'skeleton':{{'文件路径':'文件内容'}}}}"
    try:
        raw = call_ai_api(prompt, ctx)
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if json_match:
            raw = json_match.group(1)
        else:
            json_match = re.search(r'(\{.*\})', raw, re.DOTALL)
            if json_match:
                raw = json_match.group(1)
        result = json.loads(raw)
        steps = result.get("steps", ["1.分析", "2.生成"])
        skeleton = result.get("skeleton", {"src/main.py": "def main(): pass\n"})
        return steps, skeleton
    except Exception as e:
        logger.warning(f"AI规划失败 ({e})，降级到规则引擎")
        return rule_based_planner(user_input, error_log)


def get_planner(ctx: Context):
    if ctx.planner_type == "ai":
        return lambda ui, el: ai_planner(ui, el, ctx)
    else:
        return rule_based_planner


# ============================================================
# 6. 多态诱饵池
# ============================================================
class BaitPool:
    @staticmethod
    def generate_bait(code: str) -> str:
        baits = [
            BaitPool._missing_import,
            BaitPool._type_mismatch,
            BaitPool._infinite_recursion,
            BaitPool._infinite_loop,
            BaitPool._circular_dependency,
        ]
        bait_func = random.choice(baits)
        return bait_func(code)

    @staticmethod
    def _missing_import(code: str) -> str:
        lines = code.split('\n')
        for i, line in enumerate(lines):
            if 'def ' in line and not line.strip().startswith('#'):
                indent = len(line) - len(line.lstrip())
                lines.insert(i+1, ' '*(indent+4) + 'missing_lib.undefined_function()  # [BAIT_INJECTED]')
                break
        else:
            lines.append('missing_lib.undefined_function()  # [BAIT_INJECTED]')
        return '\n'.join(lines)

    @staticmethod
    def _type_mismatch(code: str) -> str:
        lines = code.split('\n')
        for i, line in enumerate(lines):
            if 'return' in line and 'int' not in line:
                lines[i] = line.replace('return ', 'return "string"  # [BAIT_INJECTED]')
                break
        else:
            lines.append('def fake(): return "string"  # [BAIT_INJECTED]')
        return '\n'.join(lines)

    @staticmethod
    def _infinite_recursion(code: str) -> str:
        lines = code.split('\n')
        insertion = """
def recurse_forever(x):
    return recurse_forever(x+1)  # [BAIT_INJECTED]
"""
        lines.insert(2, insertion)
        return '\n'.join(lines)

    @staticmethod
    def _infinite_loop(code: str) -> str:
        lines = code.split('\n')
        insertion = """
def loop_forever():
    while True:
        pass  # [BAIT_INJECTED]
"""
        lines.insert(2, insertion)
        return '\n'.join(lines)

    @staticmethod
    def _circular_dependency(code: str) -> str:
        lines = code.split('\n')
        insertion = """
def circular_a():
    return circular_b()  # [BAIT_INJECTED]
def circular_b():
    return circular_a()  # [BAIT_INJECTED]
"""
        lines.insert(2, insertion)
        return '\n'.join(lines)


# ============================================================
# 7. 后验行为比对（增强版：移动检测 + 条件细化）
# ============================================================
def detect_bait_fix(final_code: str, code_with_bait: str) -> bool:
    try:
        import ast
        tree_bait = ast.parse(code_with_bait)
        tree_final = ast.parse(final_code)
    except (ImportError, SyntaxError) as e:
        logger.debug(f"AST 解析失败 ({e})，降级到关键词匹配")
        return detect_bait_fix_keyword(final_code, code_with_bait)

    injected_lines = set()
    bait_ast_signatures = []
    lines_bait = code_with_bait.split('\n')

    for node in ast.walk(tree_bait):
        if not hasattr(node, 'lineno') or node.lineno is None:
            continue

        try:
            segment = ast.get_source_segment(code_with_bait, node)
            if segment and '[BAIT_INJECTED]' in segment:
                injected_lines.add(node.lineno)
                if hasattr(node, 'end_lineno') and node.end_lineno:
                    for line in range(node.lineno, node.end_lineno + 1):
                        injected_lines.add(line)
                try:
                    signature = ast.unparse(node)
                    bait_ast_signatures.append(signature)
                except Exception:
                    bait_ast_signatures.append(segment[:100])
                continue
        except Exception:
            pass

        idx = node.lineno - 1
        if 0 <= idx < len(lines_bait) and '[BAIT_INJECTED]' in lines_bait[idx]:
            injected_lines.add(node.lineno)
            if hasattr(node, 'end_lineno') and node.end_lineno:
                for line in range(node.lineno, node.end_lineno + 1):
                    injected_lines.add(line)
            try:
                signature = ast.unparse(node)
                bait_ast_signatures.append(signature)
            except Exception:
                bait_ast_signatures.append(lines_bait[idx][:100])

    if not injected_lines:
        logger.debug("未在 AST 中找到 [BAIT_INJECTED] 标记，降级到关键词匹配")
        return detect_bait_fix_keyword(final_code, code_with_bait)

    final_lines = set()
    for node in ast.walk(tree_final):
        if hasattr(node, 'lineno') and node.lineno is not None:
            final_lines.add(node.lineno)
            if hasattr(node, 'end_lineno') and node.end_lineno:
                for line in range(node.lineno, node.end_lineno + 1):
                    final_lines.add(line)

    if all(line not in final_lines for line in injected_lines):
        try:
            final_text = ast.unparse(tree_final)
            for sig in bait_ast_signatures:
                core_sig = sig.replace('[BAIT_INJECTED]', '').strip()
                if core_sig and len(core_sig) > 5 and core_sig in final_text:
                    logger.debug("[BAIT_MOVED] 诱饵代码被移动到其他位置，视为未修复")
                    return False
        except Exception:
            pass
        return True

    for node in ast.walk(tree_final):
        if isinstance(node, ast.Try):
            has_valid_except = False
            for handler in node.handlers:
                if handler.type:
                    try:
                        handler_type = ast.unparse(handler.type)
                        if any(k in handler_type for k in ['ImportError', 'ModuleNotFoundError', 'TypeError', 'RecursionError']):
                            has_valid_except = True
                            break
                    except Exception:
                        pass
            try:
                block_code = ast.unparse(node)
                if '[BAIT_INJECTED]' in block_code:
                    return has_valid_except
            except Exception:
                pass

        if isinstance(node, ast.If):
            try:
                cond = ast.unparse(node.test)
                if cond.strip() == 'False':
                    return False
                block_code = ast.unparse(node)
                if '[BAIT_INJECTED]' in block_code:
                    return True
            except Exception:
                pass

    return False


def detect_bait_fix_keyword(final_code: str, bait_code: str = "") -> bool:
    """关键词降级匹配 + 模糊字符串辅助判断"""
    # 1. 精确正则匹配
    patterns = [
        r'import\s+missing_lib',
        r'except\s+(ImportError|ModuleNotFoundError)',
        r'isinstance\(.*,\s*int\)',
        r'except\s+TypeError',
        r'recurse_forever.*?if',
        r'try.*?except.*?RecursionError',
        r'break',
        r'circular_a\s*=',
        r'circular_b\s*=',
        r'except\s+RecursionError'
    ]
    for pat in patterns:
        if re.search(pat, final_code, re.DOTALL):
            return True

    # 2. 模糊字符串辅助判断：检测 AI 是否只是改了函数名/变量名等微小变种
    if bait_code:
        try:
            import difflib
            # 提取诱饵核心代码（去掉 [BAIT_INJECTED] 标记）
            bait_core_lines = []
            for line in bait_code.split('\n'):
                if '[BAIT_INJECTED]' in line:
                    core = line.replace('[BAIT_INJECTED]', '').strip()
                    if core and len(core) > 10:
                        bait_core_lines.append(core)

            if bait_core_lines:
                # 检查 final_code 中是否包含与诱饵核心高度相似的片段
                final_lines = final_code.split('\n')
                for bait_core in bait_core_lines:
                    for final_line in final_lines:
                        final_line = final_line.strip()
                        if len(final_line) < 5:
                            continue
                        # 计算行级相似度
                        similarity = difflib.SequenceMatcher(None, bait_core, final_line).ratio()
                        if similarity > 0.75:
                            logger.debug(f"[FUZZY_MATCH] 发现高相似度片段 (相似度: {similarity:.2f}): '{final_line}' 接近 '{bait_core}'")
                            return False  # 诱饵核心还在，只是改了名字/微小变种，视为未修复
        except ImportError:
            pass

    return False


# ============================================================
# 8. 核心焊缝（13层）
# ============================================================
class Payload(dict):
    pass


class Layer:
    def process(self, ctx: Context, payload: Payload) -> Payload:
        return payload


class LayerNegativeTwo(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        patterns = ctx.mojibake_patterns
        for ch in patterns:
            if ch in ctx.user_input:
                logger.error(f"[ENCODING_BAIT] 检测到编码混沌: {ch}")
                raise RuntimeError(f"输入包含编码混沌字符: {ch}")
        return payload


class LayerNegativeOne(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        user_type = "甲方" if "请帮我" in ctx.user_input or "需求" in ctx.user_input else "乙方"
        if "报错" in ctx.user_input or "错误" in ctx.user_input:
            user_type = "乙方"
        scene = "NewFeature" if "新增" in ctx.user_input or "实现" in ctx.user_input else "Debug"
        if "重构" in ctx.user_input or "优化" in ctx.user_input:
            scene = "Refactor"
        payload["user_profile"] = {"type": user_type, "scene": scene}
        logger.debug(f"用户画像: {payload['user_profile']}")
        return payload


class LayerZero(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["charter"] = "stable 硬性宪章：所有输出必须包含 steps/skeleton/contract/project_map/preview/variables 之一。"
        return payload


class LayerPointFive(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        planner = get_planner(ctx)
        steps, skeleton = planner(ctx.user_input, ctx.error_log)
        payload["steps"] = steps
        payload["skeleton"] = skeleton

        profile = payload.get("user_profile", {})
        user_type = profile.get("type", "")
        scene = profile.get("scene", "")
        input_text = ctx.user_input
        if user_type == "甲方" and scene == "NewFeature":
            if not any(kw in input_text for kw in DEBUG_KEYWORDS):
                logger.warning("[ROUTE_OVERRIDE] 甲方新功能需求且无调试关键词，强制解锁骨架")
                payload["lock_level"] = "copper"
            else:
                logger.info("[ROUTE_BLOCK] 检测到调试关键词，取消覆盖，维持原锁")
                payload["lock_level"] = "iron"
        else:
            payload["lock_level"] = "iron"

        if ctx.confirm_mode == "interactive":
            print("\n[硬确认1] 骨架已生成，请确认:")
            print(json.dumps(skeleton, indent=2, ensure_ascii=False))
            confirm = input("输入 [CONFIRM] 继续，其他任意键取消: ")
            if confirm.strip().upper() != "CONFIRM":
                raise RuntimeError("用户取消骨架，流程终止")
        elif ctx.confirm_mode == "hybrid":
            logger.info("[AUTO_PASS] hybrid模式，骨架自动确认")
        else:
            logger.info("[AUTO_PASS] auto_confirm模式，骨架自动确认")
        return payload


class LayerFirst(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["preview"] = {"input": "sample", "expected_output": "expected"}
        return payload


class LayerSecond(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["variable_blueprint"] = [{"name": "result", "type": "str", "init": '""'}]
        return payload


class LayerThird(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["contract"] = {"api": "/endpoint", "request": {"param": "string"}, "response": {"code": 200}}
        return payload


class LayerFourth(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["draft"] = "草稿区: 等待AI修复..."
        payload["final"] = ""
        return payload


class LayerFifth(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["sandbox_notes"] = {"experimental": [], "provisional": []}
        return payload


class LayerSixth(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["rollback_snapshot"] = "original_code_copy"
        return payload


class LayerSeventh(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        bookmark_path = os.path.join(ctx.project_root, ".bookmark.json")
        if os.path.exists(bookmark_path):
            with open(bookmark_path, 'r') as f:
                payload["bookmark"] = json.load(f)
        else:
            payload["bookmark"] = {}
        return payload


class LayerEighth(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        payload["project_map"] = {"src/main.py": "入口", "src/utils.py": "工具"}
        return payload


class LayerNinth(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        files = payload.get("files", {})
        if not files:
            skeleton = payload.get("skeleton", {})
            files = skeleton.copy()
            payload["files"] = files

        for path, content in files.items():
            if not path.endswith(".py"):
                continue

            clean_code = content
            clean_ok, clean_output = self._run_smoke(clean_code, ctx)

            bait_code = BaitPool.generate_bait(clean_code)
            bait_ok, bait_error = self._run_smoke(bait_code, ctx)

            if clean_ok and not bait_ok:
                logger.info(f"[BAIT_TRIGGERED] 诱饵触发错误 (文件: {path})，调用AI修复...")

                fix_prompt = f"""以下代码执行时出现错误：

错误信息：
{bait_error}

代码：
```python
{bait_code}
```

请修复这段代码中的错误，直接输出修复后的完整代码，不要添加任何解释。"""

                try:
                    final_code = call_ai_api(fix_prompt, ctx)
                except Exception as e:
                    logger.error(f"AI修复调用失败: {e}")
                    self._archive_evidence(ctx, path, clean_code, bait_code, clean_output, bait_error, payload, "")
                    raise RuntimeError(f"[AI_FIX_FAILED] AI修复调用失败 (文件: {path})")

                if not detect_bait_fix(final_code, bait_code):
                    self._archive_evidence(ctx, path, clean_code, bait_code, clean_output, bait_error, payload, final_code)
                    raise RuntimeError(f"[STEALTH_REMOVE] AI未能修复诱饵 (文件: {path})")

                # 二次影子验证：AI 修复后的代码必须真正运行通过
                fix_ok, fix_output = self._run_smoke(final_code, ctx)
                if not fix_ok:
                    self._archive_evidence(ctx, path, clean_code, bait_code, clean_output, bait_error, payload, final_code)
                    raise RuntimeError(f"[SMOKE_FAIL] AI修复后的代码仍报错 (文件: {path}): {fix_output[:500]}")

                logger.info(f"[BAIT_PASS] AI正确修复诱饵并通过二次验证 (文件: {path})")
                payload["files"][path] = final_code
                payload["final"] = final_code
            else:
                logger.debug(f"[SMOKE] 文件 {path} 正常")

        return payload

    def _run_smoke(self, code: str, ctx: Context) -> Tuple[bool, str]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            tmp_path = f.name
        try:
            timeout = ctx.smoke_timeout if hasattr(ctx, 'smoke_timeout') else 30
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir()
            )
            ok = result.returncode == 0
            output = result.stdout if ok else result.stderr
            return ok, output
        except subprocess.TimeoutExpired:
            return False, f"Timeout (>{timeout}s)"
        finally:
            os.unlink(tmp_path)

    def _archive_evidence(self, ctx: Context, path: str, clean_code: str,
                          bait_code: str, clean_output: str, bait_error: str,
                          payload: Payload, final_code: str = ""):
        with tempfile.TemporaryDirectory(prefix="stealth_evid_") as evidence_dir:
            with open(os.path.join(evidence_dir, "bait_snippet.txt"), 'w') as f:
                f.write(f"文件: {path}\n代码:\n{bait_code}")
            with open(os.path.join(evidence_dir, "sandbox_error.log"), 'w') as f:
                f.write(bait_error)
            with open(os.path.join(evidence_dir, "ai_final_output.txt"), 'w') as f:
                f.write(final_code or payload.get("final", ""))
            with open(os.path.join(evidence_dir, "shadow_diff.log"), 'w') as f:
                f.write(f"干净副本OK: True\n诱饵副本OK: False\n差异: {clean_output[:200]} vs {bait_error[:200]}")
            with open(os.path.join(evidence_dir, "metadata.json"), 'w') as f:
                json.dump({
                    "timestamp": int(time.time()),
                    "model": ctx.ai_model,
                    "provider": ctx.ai_provider,
                    "user_profile": payload.get("user_profile", {}),
                    "file": path,
                    "has_final_code": bool(final_code)
                }, f, indent=2)

            tar_path = os.path.join(os.path.abspath(ctx.project_root), f"stealth_evidence_{int(time.time())}.tar.gz")
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(evidence_dir, arcname=os.path.basename(evidence_dir))
            os.chmod(tar_path, 0o444)
            logger.error(f"[EVIDENCE_ARCHIVED] 证据已打包: {tar_path} (只读)")


class LayerCIAdapter(Layer):
    def process(self, ctx: Context, payload: Payload) -> Payload:
        if ctx.confirm_mode == "auto_confirm":
            logger.info("[CI_MODE] auto_confirm模式，自动跳过硬确认")
        elif ctx.confirm_mode == "hybrid":
            logger.info("[HYBRID_MODE] 骨架已自动确认，等待修复结果确认...")
            print("\n[硬确认2] 修复已完成，请确认是否落盘:")
            files = payload.get("files", {})
            print(f"修改的文件: {list(files.keys())}")
            confirm = input("输入 [CONFIRM] 落盘，其他任意键取消: ")
            if confirm.strip().upper() != "CONFIRM":
                raise RuntimeError("用户取消落盘，流程终止")
        else:
            logger.info("[INTERACTIVE_MODE] 完全交互模式")
        return payload


# ============================================================
# 9. 路由与执行引擎
# ============================================================
def compute_complexity(ctx: Context) -> int:
    if ctx.force_level is not None:
        return max(1, min(10, ctx.force_level))
    score = 1
    if os.path.exists(ctx.project_root):
        py_count = sum(1 for root, _, files in os.walk(ctx.project_root) for f in files if f.endswith('.py'))
        score += py_count // 3
    if ctx.error_log:
        score += len(ctx.error_log.split('\n')) // 5
    if any(kw in ctx.user_input for kw in ["重构", "系统", "架构"]):
        score += 3
    return min(max(score, 1), 10)


def route_and_execute(ctx: Context) -> Payload:
    score = compute_complexity(ctx)
    logger.info(f"路由级别: {score}")

    layers = [
        LayerNegativeTwo, LayerNegativeOne, LayerZero,
        LayerPointFive, LayerFirst, LayerSecond,
        LayerThird, LayerFourth, LayerFifth,
        LayerSixth, LayerSeventh, LayerEighth, LayerNinth,
        LayerCIAdapter
    ]

    payload = Payload()
    for cls in layers:
        layer = cls()
        payload = layer.process(ctx, payload)
    return payload


# ============================================================
# 10. 物理安全落盘
# ============================================================
class Checkpoint:
    def __init__(self, root: str, ignore: Optional[List[str]] = None, strict: bool = False, allow_symlink: bool = False):
        self.root = Path(root).resolve()
        self.ignore = ignore or [".git", "__pycache__", "*.pyc", "*.log", "*.tmp"]
        self.strict = strict
        self.allow_symlink = allow_symlink
        self.snap_dir = tempfile.mkdtemp(prefix="SNAP_")
        self._taken = False
        self._backup_files = set()

    def _ignore_path(self, rel: str) -> bool:
        for pat in self.ignore:
            if fnmatch.fnmatch(rel, pat):
                return True
        return False

    def take(self):
        if os.path.exists(self.snap_dir):
            shutil.rmtree(self.snap_dir)
        os.makedirs(self.snap_dir, exist_ok=True)
        self._backup_files.clear()
        for dirpath, _, files in os.walk(self.root):
            rel = os.path.relpath(dirpath, self.root)
            if rel == '.' or self._ignore_path(rel):
                continue
            for f in files:
                src = Path(dirpath) / f
                relf = str(src.relative_to(self.root))
                if self._ignore_path(relf):
                    continue
                dst = Path(self.snap_dir) / relf
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                self._backup_files.add(relf)
        self._taken = True

    def rollback(self):
        if not self._taken:
            return
        for relf in self._backup_files:
            src = Path(self.snap_dir) / relf
            dst = Path(self.root) / relf
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if self.strict:
            for dirpath, _, files in os.walk(self.root):
                rel = os.path.relpath(dirpath, self.root)
                if rel == '.' or self._ignore_path(rel):
                    continue
                for f in files:
                    target = Path(dirpath) / f
                    relf = str(target.relative_to(self.root))
                    if relf not in self._backup_files and not self._ignore_path(relf):
                        try:
                            if target.is_file():
                                target.unlink()
                            elif target.is_dir():
                                shutil.rmtree(target)
                        except Exception as e:
                            logger.warning(f"删除额外文件失败 {target}: {e}")

    def cleanup(self):
        if os.path.exists(self.snap_dir):
            shutil.rmtree(self.snap_dir, ignore_errors=True)

    def __enter__(self):
        self.take()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.cleanup()
        else:
            self.rollback()
            logger.error(f"异常发生，已回滚，快照保留在 {self.snap_dir}")
        return False


def safe_apply(project_root: str, files: Dict[str, str], dry_run: bool = False, allow_symlink: bool = False):
    root_path = Path(project_root).resolve()
    if not dry_run:
        root_path.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = (root_path / rel_path).resolve()
        if not allow_symlink and target.is_symlink():
            raise ValueError(f"禁止写入符号链接: {rel_path}，请使用 --allow-symlink 授权")
        # 使用 Path.relative_to() 严格校验，防止 ../ 目录遍历
        try:
            target.relative_to(root_path)
        except ValueError:
            raise ValueError(f"非法路径: {rel_path} 不在项目根目录下")
        if dry_run:
            logger.info(f"[DRY-RUN] 将写入 {rel_path}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug(f"写入文件: {rel_path}")


def execute_safe_fix(ctx: Context, payload: Payload, ignore_patterns: List[str]) -> str:
    files = payload.get("files", {})
    if not files:
        return "⚠️ 无文件需要写入"
    if ctx.dry_run:
        safe_apply(ctx.project_root, files, dry_run=True, allow_symlink=ctx.allow_symlink)
        return "✅ 干跑模式完成，未实际写入"
    with Checkpoint(ctx.project_root, ignore_patterns, strict=ctx.strict_rollback, allow_symlink=ctx.allow_symlink) as cp:
        safe_apply(ctx.project_root, files, allow_symlink=ctx.allow_symlink)
        return "✅ 文件已安全落盘，快照已清理"


# ============================================================
# 11. 主入口
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Word体系 · 生产级完全体",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("user_input", help="用户需求或问题")
    parser.add_argument("error_log", nargs="?", default="", help="可选错误日志")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--planner", choices=["rule", "ai"], default="rule",
                        help="规划器类型：rule=规则引擎（默认），ai=调用AI")
    parser.add_argument("--ai-provider", default="ollama",
                        choices=["openai", "anthropic", "gemini", "ollama",
                                 "qwen", "zhipu", "deepseek", "minimax", "baichuan", "hunyuan"],
                        help="AI提供商")
    parser.add_argument("--ai-api-key", default="", help="API密钥")
    parser.add_argument("--ai-base-url", default="", help="API基础地址")
    parser.add_argument("--ai-model", default="llama2", help="模型名")
    parser.add_argument("--force-level", type=int, choices=range(1, 11), help="强制路由级别 1-10")
    parser.add_argument("--confirm-mode", choices=["interactive", "auto_confirm", "hybrid"],
                        default="interactive", help="确认模式")
    parser.add_argument("--bait-threshold", type=float, default=CONFIDENCE_THRESHOLD,
                        help="（保留，已废弃）诱饵置信度阈值")
    parser.add_argument("--smoke-timeout", type=int, default=30,
                        help="冒烟测试超时时间（秒），默认30")
    parser.add_argument("--ai-connect-timeout", type=int, default=10,
                        help="AI API连接超时时间（秒），默认10")
    parser.add_argument("--ai-read-timeout", type=int, default=120,
                        help="AI API读取超时时间（秒），默认120")
    parser.add_argument("--mojibake-patterns", nargs="*",
                        default=['\ufffd', '锟斤拷', '', '', '', ''],
                        help="乱码字符列表（完全替换）")
    parser.add_argument("--mojibake-append", nargs="*", default=[],
                        help="追加乱码字符（不覆盖默认）")
    parser.add_argument("--ignore", nargs="*", default=[".git", "__pycache__", "*.pyc", "*.log", "*.tmp"],
                        help="忽略模式")
    parser.add_argument("--dry-run", action="store_true", help="干跑预览")
    parser.add_argument("--strict-rollback", action="store_true", help="严格回滚")
    parser.add_argument("--allow-symlink", action="store_true", help="允许写入符号链接指向的路径")
    parser.add_argument("--debug", action="store_true", help="调试日志")
    parser.add_argument("--config", default=".word_fusion.json", help="配置文件路径")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(args.config)

    default_mojibake = ['\ufffd', '锟斤拷', '', '', '', '']
    config_mojibake = config.get("mojibake_patterns", default_mojibake)
    cmd_mojibake = args.mojibake_patterns if args.mojibake_patterns != default_mojibake else None
    final_mojibake = list(set(config_mojibake + (cmd_mojibake or []) + args.mojibake_append))

    ctx = Context(
        project_root=args.root or config.get("project_root", "."),
        user_input=args.user_input,
        error_log=args.error_log,
        planner_type=args.planner or config.get("planner", "rule"),
        ai_provider=args.ai_provider or config.get("ai_provider", "ollama"),
        ai_api_key=args.ai_api_key or config.get("ai_api_key", ""),
        ai_base_url=args.ai_base_url or config.get("ai_base_url", ""),
        ai_model=args.ai_model or config.get("ai_model", "llama2"),
        force_level=args.force_level or config.get("force_level"),
        dry_run=args.dry_run,
        strict_rollback=args.strict_rollback,
        confirm_mode=args.confirm_mode or config.get("confirm_mode", "interactive"),
        bait_confidence_threshold=args.bait_threshold or config.get("bait_confidence_threshold", CONFIDENCE_THRESHOLD),
        mojibake_patterns=final_mojibake,
        debug=args.debug,
        allow_symlink=args.allow_symlink or config.get("allow_symlink", False),
        smoke_timeout=args.smoke_timeout or config.get("smoke_timeout", 30),
        ai_connect_timeout=args.ai_connect_timeout or config.get("ai_connect_timeout", 10),
        ai_read_timeout=args.ai_read_timeout or config.get("ai_read_timeout", 120)
    )

    logger.info(f"Word stable 启动 | 项目: {os.path.abspath(ctx.project_root)} | 模式: {ctx.confirm_mode}")

    try:
        payload = route_and_execute(ctx)
        result = execute_safe_fix(ctx, payload, args.ignore)
        print(result)
        sys.exit(0)
    except Exception as e:
        logger.error(f"执行失败: {e}")
        if args.debug:
            traceback.print_exc()
        print(f"❌ 失败，已回滚。证据已归档（如有）。")
        sys.exit(1)


if __name__ == "__main__":
    main()