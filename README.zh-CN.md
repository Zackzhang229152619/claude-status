# claude-status

> Claude Code 多 session 实时状态看板，7 套环境主题。
> 终端里看不见的 session 状态，搬到任何设备的浏览器里看。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![macOS](https://img.shields.io/badge/macOS-12%2B-blue)]()
[![No build step](https://img.shields.io/badge/build-none-green)]()

**[English README →](README.md)**

---

## 这是什么

跑多个 Claude Code session 时，终端是唯一能看每个 session 在干什么的地方。
`claude-status` 把这些隐形状态变成一个实时看板——你可以在 iPad、iPhone、另一台 Mac 上随时看：

- **每个 session 的状态** —— 工作中 / 思考中 / 等你拍板 / 完成 / 空闲
- **当前在用什么工具** —— `Bash node script.js`、`Edit src/foo.py` 等
- **Token 用量** —— 今日 / 本月 / 累计，带缓存命中率
- **"等你拍板"全屏覆盖层 sticky** —— Claude 调 `AskUserQuestion` 时全屏告警，**直到你真正回复才消失**（不会一闪而过）
- **7 套主题** —— 选个对眼的，随时切换

跑一个本地 Python HTTP server（只用 stdlib + `jq`），靠 Claude Code 的 hook 系统驱动。状态写入用一个迷你 shell 脚本。

## 截图

| 主题 | 风格 |
|---|---|
| [`aurora`](docs/screenshots/aurora.png) | 极光玻璃，舒缓 |
| [`garden`](docs/screenshots/garden.png) | 植物花园，日夜星空 |
| [`glass`](docs/screenshots/glass.png) | 磨砂玻璃，极简 |
| [`jarvis`](docs/screenshots/jarvis.png) | 钢铁侠 HUD |
| [`lab`](docs/screenshots/lab.png) | 实验台标本 |
| [`press`](docs/screenshots/press.png) | 报刊编辑部 |
| [`stage`](docs/screenshots/stage.png) | 演出现场，激光 |

<p align="center">
  <img src="docs/screenshots/jarvis.png" width="700" alt="JARVIS 主题">
</p>

---

## 安装

**1. 克隆到 `~/.claude/status/`**（hook 脚本默认走这个路径）：

```bash
git clone https://github.com/Zackzhang229152619/claude-status.git ~/.claude/status
```

**2. 接入 Claude Code 的 hook**：把 [`examples/settings.json`](examples/settings.json) 合并到 `~/.claude/settings.json`。

合并后简单验证：
```bash
echo '{"session_id":"test","hook_event_name":"PreToolUse"}' | bash ~/.claude/status/update.sh working
cat ~/.claude/status/current.json   # 应该看到 {"global_state":"working", ...}
```

**3. 启动 server**（一次性测试）：
```bash
bash ~/.claude/status/start_server.sh
# 然后在局域网任何设备打开 http://localhost:8765/
```

**4. 开机自启（推荐）** —— 拷贝模板并替换用户名：
```bash
sed "s/YOUR_USERNAME/$USER/g" \
  ~/.claude/status/examples/com.example.claude-status-server.plist \
  > ~/Library/LaunchAgents/com.example.claude-status-server.plist
launchctl load ~/Library/LaunchAgents/com.example.claude-status-server.plist
```

server 日志在 `~/.claude/status/server.log`。

---

## 怎么用

任何设备打开 `http://<你 Mac 的 IP>:8765/`，看到的是默认主题。点右上角齿轮换主题。

看板每秒拉一次 `current.json`，每 5 秒拉一次 `token_stats.json`——没有 websocket，没有 service worker，没有 JS 框架。全部代码 = 一个 Python 文件 + 一个 shell 脚本 + 七个内联 HTML 模板。

### 状态流转

| Hook 事件 | 写入 state | 含义 |
|---|---|---|
| `PreToolUse`（任何工具） | `working` | Claude 在跑工具 |
| `PreToolUse`（`AskUserQuestion`） | `needConfirm` | Claude 问你问题 |
| `PostToolUse` | `thinking` | 工具返回，Claude 在思考 |
| `UserPromptSubmit` | `thinking` | 你刚发了消息 |
| `Notification` | `needConfirm` | 系统级通知（权限请求等） |
| `Stop` | `done` | Claude 完成一轮 |

看板顶部显示的 `global_state` 是所有活跃 session 里优先级最高的：
```
needConfirm > working > thinking > done > idle
```

### "等你拍板" sticky 防覆盖

经典痛点：Claude 调 `AskUserQuestion`，看板闪一下"等你拍板"，然后 `PostToolUse` 立刻触发（工具返回了），状态被覆盖成 `thinking`——你刚看一眼告警就消失了。

`update.sh` v1.3 修复了这个：

> 当某 session 状态是 `needConfirm` 时，**只有 `UserPromptSubmit` hook**
> （你真正回复消息时触发）能清除。其他 hook 触发的 `thinking` / `working` /
> `done` 都被强制覆盖回 `needConfirm`。

覆盖层一直在直到你回复。

---

## 架构

```
┌────────────────────────────────────────────────────────────┐
│  Claude Code (终端)                                         │
│        │ hook 触发                                          │
│        ▼                                                   │
│  update.sh  ──写入──>  ~/.claude/status/current.json       │
└────────────────────────────────────────────────────────────┘
                │ (磁盘文件)
                ▼
┌────────────────────────────────────────────────────────────┐
│  server.py (localhost:8765)                                │
│    GET /                       → dashboard.html            │
│    GET /current.json           → current.json (1s 缓存)    │
│    GET /sessions_detail.json   → 实时解析 transcript        │
│                                  (1s 缓存)                  │
│    GET /token_stats.json       → 遍历 ~/.claude/projects/  │
│                                  统计 usage (5s 缓存)       │
└────────────────────────────────────────────────────────────┘
                │
                ▼
       局域网任意设备的浏览器
```

`dashboard.html` 是单文件 self-contained HTML。7 套主题在 `variants/*.html`，
`scripts/rebuild_dashboard.py` 构建脚本把每个主题 + `variants/_common.js`
inline 进 dashboard 的一个 `<script id="themes-templates">` JSON 块——
这样 iframe srcdoc 不依赖外部文件加载。

## 文件清单

| 文件 | 用途 |
|---|---|
| [`server.py`](server.py) | HTTP server（仅 Python stdlib） |
| [`update.sh`](update.sh) | Hook 入口——写 `current.json` |
| [`dashboard.html`](dashboard.html) | 看板外壳 + 主题选择器（380 KB 完全 self-contained） |
| [`variants/_common.js`](variants/_common.js) | 拉数据 + 派发 `onState` / `onTokens` 给主题 |
| [`variants/{theme}.html`](variants/) | 各主题的 markup / CSS / render 函数 |
| [`scripts/rebuild_dashboard.py`](scripts/rebuild_dashboard.py) | 改完主题后重新打包 `dashboard.html` |
| [`examples/settings.json`](examples/settings.json) | Claude Code hook 配置示例 |
| [`examples/com.example.claude-status-server.plist`](examples/com.example.claude-status-server.plist) | macOS LaunchAgent 模板 |
| [`start_server.sh`](start_server.sh) | LaunchAgent 启动 wrapper（自动找 python3） |

## 自定义主题

每个主题都是一个 self-contained HTML 文件，结构：`<style>` + `<script>` + 实现一个 `onState(current, detail) / onTokens(tok)` 渲染契约。

1. 拷贝任意 `variants/{theme}.html` 为 `variants/mytheme.html`
2. 在 `dashboard.html` 的 `<script id="themes-data">` 数组里加一项（id / name / desc / swatch CSS 渐变）
3. 跑 `python3 scripts/rebuild_dashboard.py` 重新打包
4. 刷新——新主题出现在选择器里

## FAQ

**iPad / iPhone 能用吗？** 能。看板做了 mobile responsive（820 px 断点），fetch 是普通 `fetch()`。iOS Safari 和 Chrome 都没问题。

**需要云端 server 吗？** 不需要。默认全部跑在 `localhost:8765`。如果想从局域网外面访问，自己加个 nginx 反代 / Tailscale / Cloudflare Tunnel 指到这个端口——不属于本 repo 范围。

**隐私呢？** 全部数据留在你 Mac 本地。看板只读 `~/.claude/` 下的文件，通过 HTTP 暴露在 `localhost`。**不要不加 auth 直接把 :8765 暴露公网**。

**怎么改状态颜色？** 每个主题 `<style>` 顶部定义 `--c-working` / `--c-thinking` / `--c-done` / `--c-idle` / `--c-confirm`，改完重新打包即可。

**改完主题看板还是显示旧数据。** 跑 `python3 scripts/rebuild_dashboard.py` 重新打包，然后浏览器强刷。`dashboard.html` 已经有强 no-cache `<meta>` 头，但本地浏览器缓存可能依然 sticky。

## License

[MIT](LICENSE) —— 想怎么用都行。
