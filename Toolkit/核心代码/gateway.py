#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════╗
║           Word体系 · 统一战术扩展坞 (Gateway)               ║
║               —— 命令行 + Python API 双模集成               ║
╚═══════════════════════════════════════════════════════════════╝

【用途】将 work.py（逻辑核验）、guardian.py（物理落盘）、Archive.py（记忆增强）
        封装成一套标准接口。所有配置从统一配置文件读取。
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

# -------------------------------------------------------------
# 导入底层模块
# -------------------------------------------------------------
try:
    from work import Context, route_and_execute, execute_safe_fix, load_config
    from guardian import execute_safe_fix as guardian_execute, PhysicalCheckpoint
    from Archive import MemoryManager
except ImportError as e:
    print(f"错误：缺少核心模块。请确保 work.py, guardian.py, Archive.py 在同一目录。\n{e}")
    sys.exit(1)

# -------------------------------------------------------------
# 日志配置
# -------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# 统一网关类
# -------------------------------------------------------------
class UnifiedGateway:
    def __init__(
        self,
        project_root: str = ".",
        config_path: Optional[str] = None,
        confirm_mode: str = "interactive",
        planner: str = "rule",
        ai_provider: str = "ollama",
        ai_model: str = "llama2",
        ai_api_key: str = "",
        ai_base_url: str = "",
        smoke_timeout: int = 30,
        ai_connect_timeout: int = 10,
        ai_read_timeout: int = 120,
        allow_symlink: bool = False,
        strict_rollback: bool = False,
        ignore_patterns: Optional[List[str]] = None,
        debug: bool = False,
        # ★ 新增：mode 参数，用于区分调用场景
        mode: str = "full",
        batch_file: str = "",
    ):
        self.project_root = project_root
        self.config_path = config_path
        self.confirm_mode = confirm_mode
        self.planner = planner
        self.ai_provider = ai_provider
        self.ai_model = ai_model
        self.ai_api_key = ai_api_key
        self.ai_base_url = ai_base_url
        self.smoke_timeout = smoke_timeout
        self.ai_connect_timeout = ai_connect_timeout
        self.ai_read_timeout = ai_read_timeout
        self.allow_symlink = allow_symlink
        self.strict_rollback = strict_rollback
        self.ignore_patterns = ignore_patterns or [".git", "__pycache__", "*.pyc", "*.log", "*.tmp"]
        self.debug = debug
        self.mode = mode
        self.batch_file = batch_file

        self._memory_manager: Optional[MemoryManager] = None

        # ★ 如果传入了 config_path，加载配置
        if self.config_path and os.path.exists(self.config_path):
            self._加载配置()

    def _加载配置(self):
        """从统一配置文件加载 API Key 等配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if config.get("api_key"):
                self.ai_api_key = config.get("api_key")
                logger.info("✅ 已从配置文件加载 API Key")
            if config.get("provider"):
                self.ai_provider = config.get("provider")
            if config.get("model"):
                self.ai_model = config.get("model")
        except Exception as e:
            logger.warning(f"加载配置文件失败：{e}")

    def _get_memory_manager(self) -> MemoryManager:
        if self._memory_manager is None:
            self._memory_manager = MemoryManager(
                block_size=512,
                topic_threshold=0.3,
                max_recall_repeat=2,
                use_jieba=False,
                logit_bias_enabled=True,
                storage_dir=os.path.join(self.project_root, ".memory_snapshots")
            )
        return self._memory_manager

    def run(
        self,
        user_input: str = "",
        error_log: str = "",
        conversation_id: str = "",
        enable_memory: bool = False,
        enable_guardian: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        执行完整流程，返回统一结果字典。
        """
        logs = []
        start_time = time.time()

        try:
            # ----- 记忆增强（可选） -----
            enhanced_input = user_input
            memory_topic = None
            if enable_memory and conversation_id:
                logger.info("[Gateway] 启用记忆增强模块")
                mm = self._get_memory_manager()
                processed, logit_bias = mm.process_user_input(user_input, conversation_id)
                enhanced_input = processed
                memory_topic = mm.get_current_snapshot().topic_id if mm.get_current_snapshot() else None
                logs.append(f"记忆增强完成，主题ID: {memory_topic}")

            # ----- 调用 Work 核心逻辑 -----
            logger.info("[Gateway] 调用 Work 逻辑核验")
            ctx = Context(
                project_root=self.project_root,
                user_input=enhanced_input,
                error_log=error_log,
                planner_type=self.planner,
                ai_provider=self.ai_provider,
                ai_model=self.ai_model,
                ai_api_key=self.ai_api_key,
                ai_base_url=self.ai_base_url,
                confirm_mode=self.confirm_mode,
                smoke_timeout=self.smoke_timeout,
                ai_connect_timeout=self.ai_connect_timeout,
                ai_read_timeout=self.ai_read_timeout,
                allow_symlink=self.allow_symlink,
                strict_rollback=self.strict_rollback,
                debug=self.debug,
                dry_run=dry_run,
            )
            payload = route_and_execute(ctx)
            files = payload.get("files", {})
            if not files:
                logs.append("Work 未产生任何文件修改")

            # ----- 物理落盘（可选） -----
            evidence_path = None
            if enable_guardian and not dry_run and files:
                logger.info("[Gateway] 启用物理落盘保护 (Guardian)")
                try:
                    from guardian import execute_safe_fix as guardian_exec
                    result_msg = guardian_exec(
                        project_path=self.project_root,
                        fixed_payload={"files": files},
                    )
                    logs.append(f"Guardian 落盘结果: {result_msg}")
                    import glob
                    evidence_files = glob.glob(os.path.join(self.project_root, "stealth_evidence_*.tar.gz"))
                    if evidence_files:
                        evidence_path = evidence_files[-1]
                except Exception as e:
                    logs.append(f"Guardian 落盘失败: {e}")
                    raise
            else:
                if dry_run:
                    logs.append("干跑模式，未实际写入")
                else:
                    from work import safe_apply
                    safe_apply(self.project_root, files, dry_run=False, allow_symlink=self.allow_symlink)
                    logs.append("文件已直接写入（未使用 Guardian）")

            return {
                "status": "success",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "project_root": os.path.abspath(self.project_root),
                "modified_files": files,
                "memory_topic": memory_topic,
                "evidence_archive": evidence_path,
                "logs": logs,
                "elapsed": time.time() - start_time,
            }

        except Exception as e:
            logs.append(f"执行失败: {e}")
            logger.error(f"Gateway 执行失败: {e}")
            return {
                "status": "failed",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "project_root": os.path.abspath(self.project_root),
                "modified_files": {},
                "memory_topic": None,
                "evidence_archive": None,
                "logs": logs,
                "error": str(e),
                "elapsed": time.time() - start_time,
            }


# -------------------------------------------------------------
# 命令行入口
# -------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Word 体系统一战术扩展坞 (Gateway)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模式说明:
  full       完整流程（work + guardian）
  rollback   物理回滚（仅 guardian）
  memory     记忆加载（仅 Archive）
  shiyun     叙事创作（shiyun）
  poc        POC验证（Nuwa 单次）
  batch      批量验证（Nuwa 批量）

示例:
  python gateway.py --config ._word_config.json --mode full --input "修复登录报错"
  python gateway.py --config ._word_config.json --mode rollback
        """
    )
    parser.add_argument("--config", "-c", required=True, help="统一配置文件路径（._word_config.json）")
    parser.add_argument("--mode", "-m", choices=["full", "rollback", "memory", "shiyun", "poc", "batch"],
                        default="full", help="运行模式")
    parser.add_argument("--input", "-i", default="", help="用户需求或问题")
    parser.add_argument("--error", "-e", default="", help="可选错误日志")
    parser.add_argument("--conversation-id", "-cid", default="", help="会话ID（用于记忆模块）")
    parser.add_argument("--batch-file", "-b", default="", help="批量任务文件路径")
    parser.add_argument("--confirm-mode", choices=["interactive", "auto_confirm", "hybrid"],
                        default="interactive", help="确认模式")
    parser.add_argument("--dry-run", action="store_true", help="干跑预览")
    parser.add_argument("--project-root", default=".", help="项目根目录")
    parser.add_argument("--debug", action="store_true", help="启用调试日志")

    args = parser.parse_args()

    # 初始化网关（会自动加载配置）
    gw = UnifiedGateway(
        project_root=args.project_root,
        config_path=args.config,
        confirm_mode=args.confirm_mode,
        debug=args.debug,
        mode=args.mode,
        batch_file=args.batch_file,
    )

    # ★ 根据 mode 执行不同操作
    if args.mode == "rollback":
        # 物理回滚：调用 guardian
        cp = PhysicalCheckpoint(args.project_root)
        cp.hard_rollback()
        print("✅ 物理回滚完成")
        sys.exit(0)

    if args.mode == "memory":
        # 记忆加载：调用 Archive
        mm = gw._get_memory_manager()
        # 如果没有提供 conversation_id，使用默认 ID
        conversation_id = args.conversation_id or f"gateway_{int(time.time())}"
        result, _ = mm.process_user_input(args.input or "测试", conversation_id)
        print(f"处理结果: {result}")
        sys.exit(0)

    if args.mode == "shiyun":
        # 叙事创作：调用 shiyun
        from shiyun import main as shiyun_main
        # 重置 sys.argv 避免 shiyun 的 argparse 收到 gateway 的参数
        sys.argv = ["shiyun.py"]
        # 需要设置 config 路径，让 shiyun 从统一配置读取
        # 直接执行 shiyun 的 main，但需要确保它能读到配置
        # 由于 shiyun 有自己的 main，我们通过环境变量传递配置路径
        os.environ["POEMCLOUD_CONFIG"] = args.config
        shiyun_main()
        sys.exit(0)

    if args.mode == "poc":
        # POC验证：调用 Nuwa
        from Nuwa import main as nuwa_main
        # 强制传递 --confirm-mode auto_confirm 避免子进程阻塞在 input()
        sys.argv = ["Nuwa.py", args.input or "测试", "--confirm-mode", "auto_confirm", "--open-report"]
        # 传递配置路径
        os.environ["NUWA_CONFIG"] = args.config
        nuwa_main()
        sys.exit(0)

    if args.mode == "batch":
        # 批量验证
        from Nuwa import main as nuwa_main
        # 强制传递 --confirm-mode auto_confirm 避免子进程阻塞在 input()
        sys.argv = ["Nuwa.py", "--batch", args.batch_file or "tasks.json", "--confirm-mode", "auto_confirm", "--open-report"]
        os.environ["NUWA_CONFIG"] = args.config
        nuwa_main()
        sys.exit(0)

    # 默认 full 模式
    if not args.input:
        args.input = input("请输入需求或问题: ").strip()
        if not args.input:
            print("❌ full 模式需要输入内容")
            sys.exit(1)

    result = gw.run(
        user_input=args.input,
        error_log=args.error,
        conversation_id=args.conversation_id,
        enable_memory=False,
        enable_guardian=True,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()