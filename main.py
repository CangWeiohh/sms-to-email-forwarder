#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短信自动转发邮件程序入口。

流程：
  1. 加载配置 config.json
  2. 初始化日志 logs/app.log
  3. 以只读方式连接 ~/Library/Messages/chat.db
  4. 加载/初始化状态 state.json（首次启动跳过历史短信；重启不重复发送）
  5. 每 poll_interval 秒轮询新短信，命中前缀关键词后经 SMTP 发送通知邮件

用法：
  python3 main.py            # 前台运行
  python3 main.py --once     # 只检查一次后退出（用于测试）
  python3 main.py --debug    # 输出调试日志
  python3 main.py --config 其他路径/config.json
"""
import argparse
import json
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from src.config import Config, ConfigError, load_config
from src.database import MessageDatabase
from src.email_sender import EmailSender
from src.logger import get_logger, setup_logging
from src.message_filter import filter_messages


class StateStore:
    """
    状态持久化：保存最后处理的 message ROWID，解决重复发送问题。

    写入采用「临时文件 + 原子替换」，避免进程被 kill 时写坏 state.json。
    """

    def __init__(self, path: str = "state.json"):
        self.path = Path(path).expanduser().resolve()

    def load(self) -> Optional[int]:
        """读取最后处理的 ROWID；文件不存在或损坏时返回 None。"""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            get_logger().warning("读取状态文件失败，将重新初始化: %s", e)
            return None
        if not isinstance(data, dict):
            return None
        try:
            value = int(data.get("last_processed_rowid", 0))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def save(self, rowid: int) -> None:
        """原子写入最后处理的 ROWID。"""
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(
                {"last_processed_rowid": int(rowid)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        # 同目录内原子替换，避免写坏状态文件
        os.replace(tmp_path, self.path)


class SmsForwarder:
    """短信检测 + 转发主逻辑。"""

    def __init__(self, cfg: Config, config_path: str = "config.json"):
        self.cfg = cfg
        self._log = get_logger()
        self._db = MessageDatabase(cfg.db_path)
        self._state = StateStore(cfg.state_path)
        self._mailer = EmailSender(cfg.smtp)
        self._stop = False
        self._last_rowid: Optional[int] = None
        # 热重载支持：记录配置文件路径与最后读取时的修改时间
        self._config_path = Path(config_path).expanduser().resolve()
        try:
            self._config_mtime: Optional[float] = self._config_path.stat().st_mtime
        except OSError:
            self._config_mtime = None

    def request_stop(self) -> None:
        """请求停止（供信号处理器调用）。"""
        self._stop = True

    def _reload_config_if_changed(self) -> None:
        """
        检测 config.json 是否被修改，若是则热重载 SMTP/前缀/轮询间隔等配置。

        - 以文件修改时间判断变更，避免每轮重读文件
        - 加载失败（如 JSON 语法错误、关键字段缺失）时保留旧配置继续运行，
          更新记录时间避免反复报错，待下次保存后再尝试
        - db_path / state_path / log_dir 等影响连接与日志的项需重启才能生效
        """
        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return  # 文件暂时不可见（编辑器原子替换等），下一轮再试
        if mtime == self._config_mtime:
            return

        try:
            new_cfg = load_config(str(self._config_path))
        except ConfigError as e:
            self._log.error("config.json 变更但重新加载失败，继续使用旧配置: %s", e)
            self._config_mtime = mtime  # 避免每轮刷屏；下次保存后再触发重载
            return

        self.cfg = new_cfg
        self._mailer = EmailSender(new_cfg.smtp)
        self._config_mtime = mtime
        self._log.info(
            "检测到 config.json 变更，已热重载: SMTP=%s:%d security=%s 前缀=%s 轮询=%ds",
            new_cfg.smtp.server, new_cfg.smtp.port,
            new_cfg.smtp.security or "明文", new_cfg.prefixes,
            new_cfg.poll_interval,
        )

    def _init_last_rowid(self) -> None:
        """
        初始化最后处理的 ROWID：
        - 有状态文件：直接恢复（重启不重复发送）
        - 无状态文件（首次启动）：取当前最大 ROWID，跳过全部历史短信
        - 状态值大于当前最大 ROWID（数据库被重建/重置）：重置为当前最大
        """
        max_rowid = self._db.get_max_rowid()
        saved = self._state.load()

        if saved is None:
            self._last_rowid = max_rowid
            self._state.save(max_rowid)
            self._log.info("首次启动：跳过历史短信，从 ROWID=%d 开始监听", max_rowid)
        else:
            if saved > max_rowid:
                self._log.warning(
                    "状态 ROWID(%d) 大于数据库最大 ROWID(%d)，已重置（不发送历史短信）",
                    saved, max_rowid,
                )
                saved = max_rowid
                self._state.save(saved)
            self._last_rowid = saved
            self._log.info("已恢复上次位置，从 ROWID=%d 继续监听", saved)

    def _process_once(self) -> int:
        """
        检查一次新短信并发送通知邮件。

        :return: 本次发送的邮件数
        """
        # 每轮先检查配置是否有变更，实现免重启热重载
        self._reload_config_if_changed()

        messages = self._db.fetch_new_messages(self._last_rowid or 0)
        new_max = self._db.get_max_rowid()

        sent = 0
        if messages:
            matched = filter_messages(messages, self.cfg.prefixes)
            for m in matched:
                time_str = m.received_at.strftime("%Y-%m-%d %H:%M:%S")
                self._log.info(
                    "匹配到短信: ROWID=%d 来源=%s 时间=%s 内容=%s",
                    m.rowid, m.sender, time_str, m.text[:50],
                )
                ok = self._mailer.send(m.sender, time_str, m.text)
                if ok:
                    sent += 1
                else:
                    self._log.error("短信通知发送失败: ROWID=%d 来源=%s", m.rowid, m.sender)

        # 无论是否命中关键词都推进 ROWID（已过滤项不会再变），避免重复扫描
        if new_max > (self._last_rowid or 0):
            self._last_rowid = new_max
            self._state.save(new_max)
            self._log.debug("本轮扫描 %d 条短信，推进到 ROWID=%d", len(messages), new_max)

        return sent

    def run(self, once: bool = False) -> None:
        """
        运行主循环。

        :param once: 为 True 时只检查一次后退出（用于测试）
        """
        self._db.connect()
        self._init_last_rowid()
        self._log.info(
            "短信转发程序启动: 轮询间隔=%ds 前缀=%s SMTP=%s:%d security=%s",
            self.cfg.poll_interval,
            self.cfg.prefixes,
            self.cfg.smtp.server,
            self.cfg.smtp.port,
            self.cfg.smtp.security or "明文",
        )

        while not self._stop:
            try:
                self._process_once()
            except sqlite3.Error as e:
                # 数据库临时不可用（例如 Messages 重建文件）时重连后重试
                self._log.error("数据库访问出错，将重连后重试: %s", e)
                try:
                    self._db.close()
                    self._db.connect()
                except Exception as reconnect_err:  # noqa: BLE001
                    self._log.exception("数据库重连失败: %s", reconnect_err)
            except Exception as e:  # noqa: BLE001 - 任何异常都不能让守护进程退出
                self._log.exception("轮询处理出错（已跳过本轮）: %s", e)

            if once or self._stop:
                break
            time.sleep(self.cfg.poll_interval)


def parse_args(argv=None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="短信自动转发邮件程序：监听 Messages 新短信，匹配关键词后发送 SMTP 邮件",
    )
    parser.add_argument("--config", default="config.json",
                        help="配置文件路径（默认 config.json）")
    parser.add_argument("--once", action="store_true",
                        help="只检查一次后退出（用于测试）")
    parser.add_argument("--debug", action="store_true",
                        help="输出 DEBUG 级日志")
    return parser.parse_args(argv)


def _install_signal_handlers(forwarder: SmsForwarder) -> None:
    """注册 SIGINT/SIGTERM 处理器，实现优雅退出。"""

    def _handler(signum, _frame):
        get_logger().info("收到信号 %s，正在保存状态并退出…", signum)
        forwarder.request_stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def main(argv=None) -> int:
    """程序入口。"""
    args = parse_args(argv)

    # 1. 加载配置
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        return 1

    # 2. 初始化日志
    if args.debug:
        cfg.log_level = "DEBUG"
    setup_logging(cfg.log_dir, cfg.log_level)
    log = get_logger()
    log.info("=" * 60)
    log.info("服务启动: 配置文件=%s", args.config)

    # 3. 初始化转发器并运行
    forwarder = SmsForwarder(cfg, config_path=args.config)
    _install_signal_handlers(forwarder)

    try:
        forwarder.run(once=args.once)
    except FileNotFoundError as e:
        log.error("无法访问短信数据库: %s", e)
        log.error(
            "请开启完全磁盘访问权限后重试：\n"
            "  系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 勾选「终端」或所用 Python 解释器"
        )
        return 2
    except sqlite3.Error as e:
        log.error("短信数据库打开失败: %s", e)
        log.error("请确认 Messages 已开启短信转发，并检查数据库路径配置。")
        return 2
    finally:
        forwarder._db.close()
        log.info("服务退出")

    return 0


if __name__ == "__main__":
    sys.exit(main())
