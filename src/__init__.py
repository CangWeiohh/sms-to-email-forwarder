# -*- coding: utf-8 -*-
"""
src 包：短信自动转发邮件程序的业务模块。

- config:         配置加载与校验
- logger:         日志初始化（轮转）
- database:       只读访问 ~/Library/Messages/chat.db
- message_filter: 前缀关键词匹配
- email_sender:   SMTP 邮件发送（重试/超时/中文）
"""
