# sms-to-email-forwarder

macOS 短信自动转发邮件工具：监听 iPhone 转发到 Mac 的短信，命中指定前缀关键词后，自动通过 SMTP 发送通知邮件到你的邮箱。

```
iPhone 短信
    ↓  iMessage 同步（短信转发）
macOS Messages 同步
    ↓  读取 ~/Library/Messages/chat.db
检测新短信（轮询）
    ↓  匹配前缀关键词
SMTP 发送邮件
    ↓
指定邮箱收到通知
```

## 功能特性

- ✅ 只读访问 `~/Library/Messages/chat.db`，绝不修改数据库（SQLite `mode=ro`）
- ✅ 兼容新版 macOS（自动识别 High Sierra 之后「纳秒级」时间戳，换算本地时间）
- ✅ 后台轮询新短信，默认每 5 秒一次（`poll_interval` 可配置）
- ✅ 基于 `message ROWID` 去重：首次启动跳过历史短信、重启不重复发送（`state.json`）
- ✅ 双规则关键词匹配：`start_with`（开头匹配）+ `contains`（正文包含），任一命中即转发（先去除首尾空格）
- ✅ 支持 SMTP 明文 / SSL / STARTTLS 三种方式
- ✅ 发送失败自动重试 2 次（指数退避）、超时控制、失败记日志、单次失败不影响主流程
- ✅ 中文邮件（UTF-8 MIME）、自动生成 Message-ID 降低被判定为群发的概率
- ✅ 日志轮转（`logs/app.log`，单文件 5MB，保留 5 个备份）
- ✅ 纯 Python 标准库，零第三方依赖，Python 3.9+ 直接运行

## 目录结构

```
sms-to-email-forwarder/
├── main.py                  # 程序入口（轮询循环 + 状态管理 + 信号处理）
├── config.json.example      # 配置模板（可入库）
├── config.json              # 真实配置（含授权码，禁止入库，见 .gitignore）
├── requirements.txt         # 无第三方依赖
├── README.md
├── .gitignore
├── start.sh                 # 后台启动脚本
├── stop.sh                  # 停止脚本
├── com.cangwei.sms2email.plist  # launchd 开机自启配置
├── src/
│   ├── __init__.py
│   ├── config.py            # 配置加载与校验
│   ├── logger.py            # 日志初始化（控制台 + 文件轮转）
│   ├── database.py          # 只读访问 chat.db
│   ├── message_filter.py    # 关键词匹配（start_with 开头 / contains 包含）
│   └── email_sender.py      # SMTP 邮件发送（重试/超时/中文）
└── logs/                    # 日志目录（自动创建）
    └── app.log
```

## 环境要求

- macOS（已在 macOS 14 验证；兼容 Python 3.9 及以上）
- Python 3.9+（macOS 自带 `/usr/bin/python3` 或 Homebrew `python3`）
- 电脑需开启「短信转发」且与 iPhone 使用同一 Apple ID（见下方权限说明）

## 安装步骤

```bash
cd /Users/cangwei/Personal.localized/develop/github/sms-to-email-forwarder

# 1. 生成真实配置
cp config.json.example config.json

# 2. 编辑 config.json，填写你的 SMTP 信息（见下方配置说明）
open -e config.json
```

> 本项目无需安装任何依赖。如希望使用虚拟环境（可选）：
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> ```

## 配置说明

`config.json` 字段：

| 字段 | 说明 |
| --- | --- |
| `poll_interval` | 轮询间隔（秒），默认 5 |
| `prefixes` | 匹配关键词，两种写法：① 新版对象 `{"start_with": [...], "contains": [...]}`；② 旧版列表（等价于只配 `start_with`）。短信去除首尾空格后，`start_with` 命中开头 **或** `contains` 命中正文任意位置，即转发（逻辑为「或」） |
| `smtp.server` | SMTP 服务器，139 邮箱为 `smtp.139.com` |
| `smtp.port` | 端口，139 邮箱为 `25`（明文）或 `465`（SSL） |
| `smtp.security` | 安全模式：`""`（明文，默认）、`"ssl"`、`"starttls"` |
| `smtp.username` | SMTP 登录账号（139 邮箱完整地址） |
| `smtp.password` | **邮箱授权码**（不是登录密码，见下方） |
| `smtp.receiver` | 收件人邮箱，支持多个：单个字符串、逗号分隔（如 `a@x.com,b@y.com`，中文 `；`/`、`/空格均可）或列表 `["a@x.com","b@y.com"]`，自动去重，会同时发给所有收件人 |
| `smtp.retry` | 发送失败重试次数，默认 2 |
| `smtp.timeout` | 连接超时（秒），默认 30 |
| `db_path` | 短信数据库路径，默认 `~/Library/Messages/chat.db` |
| `state_path` | 状态文件，默认 `state.json` |
| `log_dir` / `log_level` | 日志目录 / 级别 |

匹配规则举例（`start_with` 与 `contains` 之间是「或」关系）：

```json
"prefixes": {
  "start_with": ["【示例平台】"],
  "contains":   ["验证码"]
}
```

- `【示例平台】验证码412659` → 命中 start_with ✅
- `尊敬的客户，您的验证码是 1234` → 命中 contains ✅
- `【示例系统】会议通知`（若未配） → 不命中 ❌

> 旧版写法 `"prefixes": ["【示例平台】"]` 仍然兼容，等价于只配置 `start_with`。

多收件人示例（任选一种写法，都会同时发给所有收件人）：

```json
"receiver": "a@x.com,b@y.com"
// 或
"receiver": ["a@x.com", "b@y.com"]
```

### 139 邮箱授权码获取

1. 登录 [139 邮箱网页版](https://mail.10086.cn)，进入 **设置 → 客户端设置（POP3/SMTP/IMAP）**
2. 开启 **SMTP 服务**，按提示获取「客户端授权密码」（授权码）
3. 将授权码填入 `smtp.password`；`username` 填 139 邮箱完整地址（如 `138xxxx@139.com`）

### 密码不落盘（可选）

`config.json` 中的密码会明文保存。更安全的做法是把密码放到环境变量，**不写入配置文件**：

```bash
# 在 config.json 中把 password 留空，然后：
export SMS2EMAIL_SMTP_PASSWORD='你的授权码'
./start.sh
```

环境变量优先级高于配置文件中的 `password`。若使用 launchd 自启，请按需在 plist 中补充 `EnvironmentVariables`。

## macOS 权限说明（必须！）

### 1. 完全磁盘访问权限

`~/Library/Messages/chat.db` 受 macOS 隐私保护（TCC），**必须**授权后才能读取。

**开启方式：**

```
系统设置
  → 隐私与安全性
  → 完全磁盘访问权限
  → 点「+」添加并勾选
```

需要授权以下之一：

- **Terminal**（如果你用 `./start.sh` 或 `python3 main.py` 启动，只需授权「终端」即可）
- 或 **Python 解释器**（若使用 launchd 自启，则需授权所用解释器，如 `/usr/bin/python3` 或 `/opt/homebrew/opt/python/bin/python3`）

> 未授权时的典型报错：`unable to open database file` 或 `无法访问短信数据库`。

### 2. iPhone 短信转发（让短信同步到 Mac）

在 **iPhone** 上开启：

```
设置
  → 信息
  → 短信转发
  → 打开你的 Mac
```

要求：iPhone 与 Mac 登录**同一 Apple ID**，且 Mac 已登录 iMessage（信息 App 已激活）。

> 说明：国内三大运营商的短信（含「【示例服务】」这类 106 开头的短信）都可以通过此方式转发到 Mac 并入库。iMessage（蓝色气泡）文本同样在库中，但本工具默认只处理收到的、非空的短信。

## 运行

### 前台运行（调试）

```bash
python3 main.py
```

### 测试模式（只检查一次即退出）

```bash
python3 main.py --once
```

日志会打印 `匹配到短信` / `邮件发送成功` 等信息。

### 后台运行

```bash
./start.sh      # 后台启动（PID 写入 run.pid）
./stop.sh       # 停止
```

> **热重载**：程序每轮轮询（默认 5 秒）都会检查 `config.json` 是否被修改。修改并保存后，SMTP 账号/授权码、收件人、匹配前缀、轮询间隔等会**自动生效，无需重启**。仅修改 `db_path` / `state_path` / `log_dir` 等影响连接与日志的项仍需重启。配置写错（如 JSON 语法错误）时程序会保留旧配置继续运行并在日志中提示。

### 开机自启（launchd）

`./start.sh` 启动的程序在电脑重启后**不会自动运行**，需要手动重新执行。如需常驻（开机/登录后自动运行、崩溃自动重启），使用项目自带的 launchd 配置 `com.cangwei.sms2email.plist`，把它注册为 macOS 的 LaunchAgent 后台服务。

> 只需要偶尔跑一下的话，可以完全忽略本小节，直接用 `./start.sh` 即可。

#### 1. 按需修改 plist 中的路径

plist 里写死了本项目当前路径与解释器：

| 键 | 默认值 | 何时需要改 |
| --- | --- | --- |
| `ProgramArguments` | `/usr/bin/python3` + 项目绝对路径 + `main.py` | 项目移到别处时改路径；使用 Homebrew Python 时把 `/usr/bin/python3` 换成其绝对路径（如 `/opt/homebrew/opt/python/bin/python3`） |
| `WorkingDirectory` | 项目绝对路径 | 项目移到别处时同步修改 |

可用 `plutil -lint com.cangwei.sms2email.plist` 检查文件语法是否正确。

#### 2. 安装并启动

```bash
# 安装：复制到当前用户的 LaunchAgents 目录
cp com.cangwei.sms2email.plist ~/Library/LaunchAgents/

# 启动服务（登录后也会自动运行）
launchctl load ~/Library/LaunchAgents/com.cangwei.sms2email.plist

# 查看是否运行
launchctl list | grep sms2email
```

#### 3. 停止 / 卸载自启

```bash
# 停止服务（但保留自启配置）
launchctl unload ~/Library/LaunchAgents/com.cangwei.sms2email.plist

# 彻底卸载（删除配置）
rm -f ~/Library/LaunchAgents/com.cangwei.sms2email.plist
```

#### 4. 查看日志

launchd 方式运行时，标准输出/错误分别写入：

- `logs/launchd.log`
- `logs/launchd.err.log`

（与 `./start.sh` 方式共用 `logs/app.log`。）

#### 5. 权限注意

launchd 启动的进程**不经过终端**，因此「完全磁盘访问权限」中只勾选「终端」**无效**。请确认已勾选 plist 实际使用的那个 Python 解释器：

```
系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 勾选 /usr/bin/python3（或所用解释器）
```

否则程序仍会报 `unable to open database file`。

#### 工作原理（简要）

plist 是 launchd（macOS 系统服务管理器）的 LaunchAgent 配置：

- `Label`：服务唯一标识 `com.cangwei.sms2email`
- `ProgramArguments`：启动命令（解释器 + 主程序 + 参数）
- `RunAtLoad`：加载时立即运行
- `KeepAlive`：进程退出/崩溃后自动重启
- `StandardOutPath` / `StandardErrorPath`：输出与错误日志路径

## 测试步骤

1. **验证配置加载**：`python3 -m py_compile main.py src/*.py` 通过；`python3 main.py` 正常打印启动日志。
2. **验证权限**：直接执行
   ```bash
   sqlite3 ~/Library/Messages/chat.db "SELECT COUNT(*) FROM message;"
   ```
   若能返回数字说明权限正常；若报 `unable to open database file`，请先授权完全磁盘访问权限。
3. **测试模式跑一轮**：
   ```bash
   python3 main.py --once
   ```
   首次运行会「跳过历史短信」，把当前最大 ROWID 写入 `state.json`。
4. **真实发送测试**：用 iPhone 给自己发一条以关键词开头的短信（如 `【示例平台】测试`），等待一个轮询周期（约 5 秒），查看 `logs/app.log` 是否出现 `邮件发送成功`，并检查收件邮箱。
5. **确认不重复发送**：`./stop.sh && ./start.sh` 重启后观察日志，已处理过的短信不会被再次发送。

## 日志

所有日志写入 `logs/app.log`，单文件 5MB 轮转，保留 5 个备份。前台运行同时输出到控制台。

关键日志示例：

```
[INFO] 服务启动: 配置文件=config.json
[INFO] 首次启动：跳过历史短信，从 ROWID=1234 开始监听
[INFO] 匹配到短信: ROWID=1235 来源=106xxxx 时间=2024-09-02 12:00:00 内容=【示例平台】...
[INFO] 邮件发送成功: 来源=106xxxx 收件人=you@139.com
[ERROR] 邮件发送最终失败（已重试 2 次放弃）: SMTPServerDisconnected: ...
```

## 常见问题（FAQ）

**Q1：报 `unable to open database file` / `无法访问短信数据库`？**
未开启「完全磁盘访问权限」，按上文授权后重启程序。

**Q2：登录 SMTP 失败（`SMTPAuthenticationError`）？**
- 确认 `username` 是完整的 139 邮箱地址（**逐字核对，容易少写点或写错**）
- 确认 `password` 是**授权码**而非登录密码（网易/139 均需授权码）
- 若报 `454 ... USER_NOTFOUND_ERR`：说明 139 服务器**不认这个用户名**。多半是邮箱地址本身填错（如漏了 `.`），或 SMTP 客户端服务未在网页版开启、授权码无效。登录 [mail.10086.cn](https://mail.10086.cn) → 设置 → 客户端设置 → 开启 SMTP 服务并重新生成「客户端授权码」
- 若报 `450 Mail rejected, please try again`：是 139 的**临时拒信**，程序会自动重试，通常第二次即可成功
- 部分运营商会限制 25 端口，可改用 `"port": 465, "security": "ssl"` 或 587 + STARTTLS

**Q3：收不到邮件？**
- 先看 `logs/app.log` 是否有 `邮件发送成功`
- 检查垃圾邮件箱
- 用 `--debug` 模式查看详细连接信息

**Q4：重启后会不会重复发送？**
不会。程序通过 `state.json` 记录最后处理的 `message ROWID`，重启后从该位置继续。

**Q5：为什么删除 `state.json` 后不会补发历史短信？**
设计如此：删除状态文件等同「首次启动」，程序会跳过全部历史短信，只处理之后到达的新短信。

**Q6：手机/电脑重启后程序还在吗？**
`./start.sh` 方式启动的程序不会随开机自动启动，需重新运行；如需常驻请使用 launchd 自启配置。

## 安全说明

- `config.json` 含邮箱账号与授权码，**已被 `.gitignore` 排除**，不会进入 git 仓库
- 请勿将 `config.json` 或 `state.json` 分享/提交到任何公开仓库
- 推荐使用环境变量 `SMS2EMAIL_SMTP_PASSWORD` 存放授权码，避免明文落盘
- 本程序只读取短信数据库，不写入、不删除任何数据

## 卸载

```bash
# 1. 停止程序
./stop.sh
# 或卸载 launchd 自启
launchctl unload ~/Library/LaunchAgents/com.cangwei.sms2email.plist
rm -f ~/Library/LaunchAgents/com.cangwei.sms2email.plist

# 2. 删除项目（可选）
rm -rf /Users/cangwei/Personal.localized/develop/github/sms-to-email-forwarder
```
