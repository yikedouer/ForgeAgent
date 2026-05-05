"""全局日志系统 — 将代码执行流程记录到本地文件。

日志文件默认位于 ``~/.forgecc/logs/forgecc.log``，可通过环境变量覆盖：
  * FORGECC_LOG_LEVEL — DEBUG / INFO / WARNING / ERROR（默认 DEBUG）
  * FORGECC_LOG_FILE  — 日志文件绝对路径

日志格式包含时间戳、模块名、级别和消息，方便追踪完整的执行流程。

使用方式（各模块）::

    from forgecc.core.log import get_logger
    log = get_logger(__name__)
    log.info("引擎启动，模型: %s", model_name)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

# 默认配置
_DEFAULT_LEVEL = "DEBUG"

# 模块级标记，防止重复初始化
_initialized = False


def _default_log_file() -> Path:
    return Path.home() / ".forgecc" / "logs" / "forgecc.log"


def _setup() -> None:
    """初始化根日志器，添加文件处理器。仅执行一次。"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    default_log_file = _default_log_file()
    raw_log_file = os.environ.get("FORGECC_LOG_FILE", str(default_log_file)).strip()
    log_file = Path(raw_log_file or str(default_log_file)).expanduser()
    log_level = os.environ.get("FORGECC_LOG_LEVEL", _DEFAULT_LEVEL).strip().upper()

    # 根日志器：统一格式写入文件
    root = logging.getLogger("forgecc")
    root.setLevel(getattr(logging, log_level, logging.DEBUG))

    # 避免重复添加处理器（reload 安全）
    if not root.handlers:
        fmt = logging.Formatter(
            fmt="%(asctime)s  %(name)-30s  %(levelname)-5s  %(message)s",
            datefmt="%H:%M:%S",
        )
        try:
            log_dir = log_file.parent
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            root.addHandler(logging.NullHandler())

    root.info("═" * 60)
    root.info("日志系统初始化完成  level=%s  file=%s", log_level, log_file)
    root.info("═" * 60)


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器（自动初始化根日志器）。

    推荐使用 ``get_logger(__name__)`` 以便日志输出
    包含当前模块路径，方便定位。
    """
    _setup()
    return logging.getLogger(name)
