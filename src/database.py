#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模块：以只读方式访问 ~/Library/Messages/chat.db。

要点：
- 使用 SQLite URI 参数 mode=ro 强制只读，绝不对数据库做任何写操作
- 兼容新版 macOS：High Sierra 之后 message.date 为「纳秒」级时间戳，自动换算为本地时间
- 只返回「收到的、非空的」短信（排除自己发送、排除空消息）
- 关联 handle 表获取发送号码
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

# Apple 参考纪元：2001-01-01 00:00:00 UTC
_EPOCH_2001 = datetime(2001, 1, 1, tzinfo=timezone.utc)

# 取 ROWID 大于指定值的收件短信（is_from_me=0，排除空文本）
_QUERY_NEW_MESSAGES = """
SELECT m.ROWID AS rowid,
       m.text AS text,
       m.date AS date,
       COALESCE(h.id, '未知') AS sender
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
WHERE m.ROWID > ?
  AND m.is_from_me = 0
  AND m.text IS NOT NULL
  AND TRIM(m.text) != ''
ORDER BY m.ROWID ASC
"""

# 当前数据库最大 ROWID
_QUERY_MAX_ROWID = "SELECT COALESCE(MAX(ROWID), 0) FROM message"


@dataclass
class Message:
    """一条短信记录。"""
    rowid: int            # message.ROWID
    text: str             # 短信正文
    sender: str           # 发送号码（handle.id）
    received_at: datetime # 接收时间（本地时区）


def _apple_time_to_datetime(value: float) -> datetime:
    """
    将 Apple 时间戳转为本地时区 datetime。

    旧版 macOS（<10.13）为「秒」，新版为「纳秒」；
    以 1e11 为阈值自动判断，避免硬编码。
    """
    value = float(value or 0)
    seconds = value / 1_000_000_000 if abs(value) > 1e11 else value
    return (_EPOCH_2001 + timedelta(seconds=seconds)).astimezone()


class MessageDatabase:
    """Messages 数据库的只读访问封装。"""

    def __init__(self, db_path: str = "~/Library/Messages/chat.db"):
        self._db_file = Path(db_path).expanduser().resolve()
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def db_file(self) -> Path:
        """数据库文件路径。"""
        return self._db_file

    def connect(self) -> None:
        """
        以只读模式打开数据库。

        若未开启「完全磁盘访问权限」，macOS 会拒绝访问，抛出异常。
        """
        if not self._db_file.exists():
            raise FileNotFoundError(
                f"短信数据库不存在: {self._db_file}\n"
                "请确认 Messages 已启用（系统设置 → 信息 → 短信转发 → Mac），"
                "或检查 db_path 配置。"
            )
        # as_uri() 生成 file:// 形式 URI 并正确处理路径中的特殊字符；
        # ?mode=ro 强制只读，任何写操作都会直接报错。
        uri = self._db_file.as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, timeout=5)
        self._conn.row_factory = sqlite3.Row
        # WAL 模式下可能短暂等待 Messages 写入，设置忙等待避免立刻报锁
        self._conn.execute("PRAGMA busy_timeout = 5000")

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        """确保连接已建立。"""
        if self._conn is None:
            self.connect()
        return self._conn  # type: ignore[return-value]

    def get_max_rowid(self) -> int:
        """返回数据库中最大的 message ROWID（首次启动用于跳过历史短信）。"""
        cur = self._require_conn().execute(_QUERY_MAX_ROWID)
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def fetch_new_messages(self, after_rowid: int) -> List[Message]:
        """
        获取 ROWID 大于 after_rowid 的收件短信（按 ROWID 升序）。

        :param after_rowid: 上次处理到的 ROWID
        :return: 新消息列表
        """
        rows = self._require_conn().execute(
            _QUERY_NEW_MESSAGES, (int(after_rowid),)
        ).fetchall()

        messages: List[Message] = []
        for r in rows:
            messages.append(
                Message(
                    rowid=int(r["rowid"]),
                    text=str(r["text"] or ""),
                    sender=str(r["sender"] or ""),
                    received_at=_apple_time_to_datetime(r["date"]),
                )
            )
        return messages
