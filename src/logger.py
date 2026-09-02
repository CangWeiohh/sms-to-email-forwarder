#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志模块：统一初始化 logging，支持控制台输出与文件轮转。

- 文件：logs/app.log，单文件 5MB，滚动保留 5 个备份（logs/app.log.1 ... app.log.5）
- 同时输出到控制台，便于前台调试
- 未捕获的异常也会写入日志，便于排查守护进程崩溃原因
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 日志格式：时间 [级别] 模块: 内容
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
# 单文件大小上限（字节）
MAX_BYTES = 5 * 1024 * 1024
# 保留的备份文件数
BACKUP_COUNT = 5

_logger_name = "sms2email"


def setup_logging(log_dir: str = "logs",
                  level: str = "INFO",
                  log_file: str = "app.log") -> logging.Logger:
    """
    初始化全局日志器。

    :param log_dir: 日志目录（自动创建）
    :param level: 日志级别（DEBUG/INFO/WARNING/ERROR）
    :param log_file: 日志文件名
    :return: 配置好的 logger
    """
    log_path = Path(log_dir).expanduser().resolve()
    log_path.mkdir(parents=True, exist_ok=True)

    level_int = getattr(logging, str(level).upper(), logging.INFO)

    logger = logging.getLogger(_logger_name)
    logger.setLevel(level_int)

    # 已配置过则直接复用，避免重复添加 handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(DEFAULT_FORMAT)

    # 文件轮转 handler
    file_handler = RotatingFileHandler(
        log_path / log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level_int)
    logger.addHandler(file_handler)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level_int)
    logger.addHandler(console_handler)

    # 未捕获异常（含线程内）写入日志
    def _excepthook(exc_type, exc_value, exc_tb):
        logger.critical("未捕获异常，程序可能异常退出",
                        exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _excepthook

    return logger


def get_logger() -> logging.Logger:
    """
    获取全局日志器。若尚未初始化，则用默认参数初始化（便于独立模块调试）。
    """
    logger = logging.getLogger(_logger_name)
    if not logger.handlers:
        setup_logging()
    return logger
