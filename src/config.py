#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块：加载并校验 config.json。

- 所有字段都有合理默认值，缺省字段不会导致程序崩溃
- 关键字段（SMTP 服务器、账号、收件人、匹配前缀）缺失时给出明确中文提示
- 密码/授权码不写死：支持环境变量 SMS2EMAIL_SMTP_PASSWORD 覆盖 config.json 中的密码
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# 默认短信数据库路径
DEFAULT_DB_PATH = "~/Library/Messages/chat.db"


class ConfigError(Exception):
    """配置加载或校验失败时抛出。"""


@dataclass
class SMTPConfig:
    """SMTP 邮件发送配置。"""
    server: str = "smtp.139.com"   # SMTP 服务器地址
    port: int = 25                 # 端口（139 邮箱通常为 25）
    security: str = ""             # 安全模式：""(明文) / "ssl" / "starttls"
    username: str = ""             # 登录账号（139 邮箱完整地址）
    password: str = ""             # 邮箱授权码（不是登录密码！）
    receiver: List[str] = field(default_factory=list)  # 收件人邮箱列表（支持单个/多个）
    retry: int = 2                 # 发送失败重试次数
    timeout: int = 30              # 连接超时（秒）


@dataclass
class Config:
    """程序总配置。"""
    poll_interval: int = 5                          # 轮询间隔（秒）
    prefixes: List[str] = field(default_factory=list)   # 匹配前缀关键词
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    db_path: str = DEFAULT_DB_PATH                  # 短信数据库路径
    state_path: str = "state.json"                  # 状态文件路径
    log_dir: str = "logs"                           # 日志目录
    log_level: str = "INFO"                         # 日志级别


def _parse_receivers(value) -> List[str]:
    """
    解析收件人配置，兼容多种写法：
    - 单个字符串：如 "a@x.com"
    - 字符串分隔：如 "a@x.com,b@y.com"（逗号/分号/空格均可，含中文标点）
    - 字符串列表：如 ["a@x.com", "b@y.com"]
    自动去重并保留顺序。
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,，;；、\s]+", value.strip())
    elif isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        return []

    seen = set()
    result: List[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _load_smtp(raw: dict) -> SMTPConfig:
    """解析 SMTP 配置段。"""
    smtp = SMTPConfig()
    smtp.server = str(raw.get("server", smtp.server)).strip()
    smtp.port = int(raw.get("port", smtp.port))
    smtp.security = str(raw.get("security", smtp.security)).strip().lower()
    smtp.username = str(raw.get("username", smtp.username)).strip()
    smtp.password = str(raw.get("password", smtp.password))
    # 兼容两种键名：receiver（字符串或列表）/ receivers（列表）
    smtp.receiver = _parse_receivers(
        raw.get("receivers", raw.get("receiver", smtp.receiver))
    )
    smtp.retry = int(raw.get("retry", smtp.retry))
    smtp.timeout = int(raw.get("timeout", smtp.timeout))

    if smtp.security not in ("", "ssl", "starttls"):
        raise ConfigError(
            f"不支持的 smtp.security 值: {smtp.security!r}（可选: 空、'ssl'、'starttls'）"
        )
    if smtp.port < 1 or smtp.port > 65535:
        raise ConfigError(f"无效的 smtp.port: {smtp.port}")
    return smtp


def load_config(path: str = "config.json") -> Config:
    """
    加载配置文件。文件缺失或 JSON 格式错误会抛出 ConfigError。
    """
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise ConfigError(
            f"未找到配置文件: {cfg_path}\n"
            "请先执行: cp config.json.example config.json\n"
            "然后编辑 config.json 填写 SMTP 信息（服务器、账号、授权码、收件人）。"
        )

    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"配置文件 JSON 解析失败: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是 JSON 对象（花括号包裹）")

    cfg = Config()
    cfg.poll_interval = max(1, int(raw.get("poll_interval", cfg.poll_interval)))

    raw_prefixes = raw.get("prefixes", cfg.prefixes)
    if isinstance(raw_prefixes, list):
        cfg.prefixes = [str(p).strip() for p in raw_prefixes]
    if not cfg.prefixes:
        raise ConfigError("prefixes 不能为空，至少需要一个匹配关键词（如 【示例服务】）")

    raw_smtp = raw.get("smtp")
    if isinstance(raw_smtp, dict):
        cfg.smtp = _load_smtp(raw_smtp)

    cfg.db_path = str(raw.get("db_path", cfg.db_path))
    cfg.state_path = str(raw.get("state_path", cfg.state_path))
    cfg.log_dir = str(raw.get("log_dir", cfg.log_dir))
    cfg.log_level = str(raw.get("log_level", cfg.log_level)).upper()

    # ---- 关键字段校验 ----
    if not cfg.smtp.server:
        raise ConfigError("smtp.server 不能为空")
    if not cfg.smtp.username:
        raise ConfigError("smtp.username 不能为空（139 邮箱完整地址）")
    if not cfg.smtp.receiver:
        raise ConfigError("smtp.receiver 不能为空（单个邮箱、逗号分隔或多个邮箱列表均可）")

    return cfg


def resolve_smtp_password(smtp: SMTPConfig) -> str:
    """
    解析 SMTP 密码/授权码，优先级：
    1. 环境变量 SMS2EMAIL_SMTP_PASSWORD（推荐，避免密码落盘）
    2. config.json 中的 smtp.password
    """
    env_pass = os.environ.get("SMS2EMAIL_SMTP_PASSWORD")
    return env_pass if env_pass is not None else smtp.password
