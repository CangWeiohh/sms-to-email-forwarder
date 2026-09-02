#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息过滤模块：根据前缀关键词匹配短信内容。

匹配逻辑：
1. 去除短信内容首尾空白
2. 判断是否以任意关键词开头
"""
from typing import Iterable, List

from .database import Message


def normalize_text(text: str) -> str:
    """去除首尾空白。"""
    return (text or "").strip()


def matches_prefix(text: str, prefixes: Iterable[str]) -> bool:
    """
    判断文本是否以任意前缀关键词开头。

    :param text: 短信内容
    :param prefixes: 前缀关键词列表
    :return: 命中返回 True
    """
    stripped = normalize_text(text)
    if not stripped:
        return False
    return any(stripped.startswith(p) for p in prefixes if p)


def filter_messages(messages: Iterable[Message],
                    prefixes: Iterable[str]) -> List[Message]:
    """
    从消息列表中筛选出匹配任意关键词的消息。

    :param messages: 消息列表
    :param prefixes: 前缀关键词列表
    :return: 命中关键词的消息列表
    """
    prefix_list = [p for p in prefixes if p]
    return [m for m in messages if matches_prefix(m.text, prefix_list)]
