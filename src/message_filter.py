#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息过滤模块：根据关键词匹配短信内容。

支持两类匹配规则（任一类命中即转发）：
1. start_with：短信去除首尾空白后，以其中任意关键词开头
2. contains：  短信去除首尾空白后，正文包含其中任意关键词
"""
from typing import Iterable, List

from .database import Message


def normalize_text(text: str) -> str:
    """去除首尾空白。"""
    return (text or "").strip()


def matches_start_with(text: str, keywords: Iterable[str]) -> bool:
    """判断文本是否以任意关键词开头。"""
    stripped = normalize_text(text)
    if not stripped:
        return False
    return any(stripped.startswith(k) for k in keywords if k)


def matches_contains(text: str, keywords: Iterable[str]) -> bool:
    """判断文本正文是否包含任意关键词（子串匹配）。"""
    stripped = normalize_text(text)
    if not stripped:
        return False
    return any(k in stripped for k in keywords if k)


def matches(text: str,
            start_with: Iterable[str],
            contains: Iterable[str]) -> bool:
    """
    判断文本是否命中规则：start_with 或 contains 任一命中即返回 True。

    :param text: 短信内容
    :param start_with: 开头匹配关键词列表
    :param contains: 正文包含关键词列表
    :return: 命中返回 True
    """
    if matches_start_with(text, start_with):
        return True
    if matches_contains(text, contains):
        return True
    return False


def filter_messages(messages: Iterable[Message],
                    start_with: Iterable[str],
                    contains: Iterable[str]) -> List[Message]:
    """
    从消息列表中筛选出命中任意关键词的消息。

    :param messages: 消息列表
    :param start_with: 开头匹配关键词列表
    :param contains: 正文包含关键词列表
    :return: 命中关键词的消息列表
    """
    sw = [k for k in start_with if k]
    ct = [k for k in contains if k]
    if not sw and not ct:
        return []
    return [m for m in messages if matches(m.text, sw, ct)]
