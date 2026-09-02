#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件发送模块：通过 SMTP 发送「短信转发通知」邮件。

支持：
- 明文连接（security=""）：139 邮箱 25 端口 + 邮箱授权码登录（本项目默认场景）
- SSL（security="ssl"，如 465 端口）
- STARTTLS（security="starttls"，如 587 端口）

健壮性：
- 连接失败自动重试（默认 2 次，可配置），指数退避
- 连接超时控制（smtplib timeout）
- 发送失败记录日志，单次失败不影响主循环继续运行
- 自动生成 Message-ID（仿照 py2email，降低被邮箱服务商判定为群发的概率）
- 支持中文正文（UTF-8 MIME）

邮件格式：
  标题：短信转发通知
  正文：
    来源：
    {sender}

    时间：
    {time}

    内容：
    {text}
"""
import smtplib
import socket
import ssl
import time
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional

from .config import SMTPConfig, resolve_smtp_password
from .logger import get_logger

# 邮件标题
SUBJECT = "短信转发通知"

# 邮件正文模板
_BODY_TEMPLATE = """来源：
{sender}

时间：
{time}

内容：
{text}
"""


class EmailSender:
    """SMTP 邮件发送器，内置重试与超时处理。"""

    def __init__(self,
                 smtp: SMTPConfig,
                 retry: Optional[int] = None,
                 retry_delay: float = 5.0):
        """
        :param smtp: SMTP 配置
        :param retry: 失败重试次数（覆盖配置中的值）
        :param retry_delay: 首次重试等待秒数（指数退避基数）
        """
        self._smtp = smtp
        self._retry = smtp.retry if retry is None else max(0, int(retry))
        self._retry_delay = retry_delay
        self._log = get_logger()

    def send(self, sender: str, time_str: str, text: str) -> bool:
        """
        发送一封短信转发通知邮件。

        :param sender: 短信来源号码
        :param time_str: 短信接收时间（已格式化的字符串）
        :param text: 短信内容
        :return: 成功返回 True，最终失败返回 False（不抛异常）
        """
        password = resolve_smtp_password(self._smtp)
        if not password:
            self._log.error(
                "SMTP 密码/授权码为空，无法登录：请在 config.json 填写 smtp.password，"
                "或设置环境变量 SMS2EMAIL_SMTP_PASSWORD"
            )
            return False

        body = _BODY_TEMPLATE.format(sender=sender, time=time_str, text=text)
        msg = self._build_message(body)
        receivers = self._smtp.receiver

        # 1 次初始尝试 + retry 次重试
        for attempt in range(1, self._retry + 2):
            try:
                self._send_once(msg, password)
                self._log.info(
                    "邮件发送成功: 来源=%s 收件人=%s (第 %d 次尝试)",
                    sender, ", ".join(receivers), attempt,
                )
                return True
            except (smtplib.SMTPException, socket.timeout,
                    ssl.SSLError, OSError) as e:
                if attempt <= self._retry:
                    self._log.warning(
                        "邮件发送失败（%d/%d，将重试）: %s: %s",
                        attempt, self._retry + 1, type(e).__name__, e,
                    )
                    time.sleep(self._retry_delay * attempt)
                else:
                    self._log.error(
                        "邮件发送最终失败（已重试 %d 次放弃）: %s: %s",
                        self._retry, type(e).__name__, e,
                    )
        return False

    def _build_message(self, body: str) -> MIMEText:
        """构建中文 UTF-8 邮件。"""
        msg = MIMEText(body, "plain", "utf-8")
        # 发件人（带名称，兼容中文显示）
        msg["From"] = formataddr((self._smtp.username, self._smtp.username))
        # 多个收件人：To 头用逗号分隔（send_message 会自动逐个投递）
        msg["To"] = ", ".join(self._smtp.receiver)
        msg["Subject"] = SUBJECT
        msg["Date"] = formatdate(localtime=True)
        # 手动生成 Message-ID，避免被判定为群发/垃圾邮件
        domain = (self._smtp.username.split("@")[-1]
                  if "@" in self._smtp.username else "localhost")
        msg["Message-ID"] = make_msgid(domain=domain)
        return msg

    def _connect(self) -> smtplib.SMTP:
        """
        按 security 配置建立 SMTP 连接。

        - "ssl"      -> SMTP_SSL（通常 465）
        - "starttls" -> SMTP + STARTTLS（通常 587）
        - ""（明文）  -> 直接 SMTP 登录（139 邮箱 25 端口 + 授权码）
        """
        security = (self._smtp.security or "").lower()
        timeout = self._smtp.timeout
        if security == "ssl":
            return smtplib.SMTP_SSL(self._smtp.server, self._smtp.port,
                                    timeout=timeout)
        server = smtplib.SMTP(self._smtp.server, self._smtp.port, timeout=timeout)
        if security == "starttls":
            server.starttls()
        return server

    def _send_once(self, msg, password: str) -> None:
        """执行一次完整的发送（连接 → 登录 → 发送 → 退出）。"""
        server = None
        try:
            server = self._connect()
            server.login(self._smtp.username, password)
            server.send_message(msg)
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    try:
                        server.close()
                    except Exception:
                        pass
