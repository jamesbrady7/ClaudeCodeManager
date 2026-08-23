# Claude Code 启动器使用说明

Claude Code 通过 Anthropic 兼容 API 后端运行，支持多供应商一键切换。
所有配置、会话、缓存集中在 `D:\ClaudeCode`。

## 快速开始

新开终端后，常用命令：

| 命令 | 说明 |
|------|------|
| `cc` | 用当前供应商启动 Claude Code（正常权限） |
| `cc danger` | 危险模式（跳过所有权限确认） |
| `cc provider` | 列出所有供应商 + 当前模型映射 |
| `cc provider switch <名字>` | 一键切换供应商 |
| `cc mode` | 同 `cc provider` |
| `cc hist` | 查看历史会话 |
| `cc clear` | 列出会话（用于删除） |
| `cc clear <id>` | 删除指定会话 |
| `cc clear all` | 删除全部会话 |
| `cc resume [id]` | 恢复历史会话 |
| `cc ui` | 打开桌面版会话管理（浏览 / 新建 / 恢复 / 批量删除） |
| `cc backup` | 手动备份会话数据到 `D:\ClaudeCode-archive` |
| `cc role <name>` | 以某角色启动会话（人设 + 自动积累的知识库） |
| `cc role <name> --from <ids>` | 启动角色会话并继承指定会话 |
| `cc roles` | 列出所有角色 |
| `cc -p "问题"` | 一次性提问 |

## 配置供应商（重点）

配置文件：`D:\ClaudeCode\cc-config.json`

```json
{
  "provider config": {
    "current provider": "deepseek",
    "deepseek": {
      "baseUrl": "https://api.deepseek.com/anthropic",
      "apiKey": "你的key",
      "model": "deepseek-v4-flash",
      "fastModel": "deepseek-v4-flash"
    },
    "glm": {
      "baseUrl": "https://open.bigmodel.cn/api/anthropic",
      "apiKey": "你的key",
      "model": "glm-4.5",
      "fastModel": "glm-4-flash"
    }
  }
}
```

### 切换供应商（一键完成）

```
cc provider                # 看到所有供应商，当前项标 [current]
cc provider switch glm     # 一键切到 glm
cc provider switch deepseek # 切回 deepseek
```

切换只改 `current provider` 一个字段，其余配置不动。

### 添加新供应商

在 `provider config` 里加一段即可，注意 **model 必须和 baseUrl 是同一家**：

```json
"kimi": {
  "baseUrl": "https://api.moonshot.cn/anthropic",
  "apiKey": "你的key",
  "model": "moonshot-v1-8k",
  "fastModel": "moonshot-v1-8k"
}
```

## fastModel：让"杂活"走便宜模型（可选）

`fastModel` 用于指定"不需要强思考的杂活"所用的模型，它负责：

- **生成会话标题**（`ANTHROPIC_SMALL_FAST_MODEL`）
- **子代理探索**（`CLAUDE_CODE_SUBAGENT_MODEL`）
- **上下文压缩**（`CLAUDE_CONTEXT_COLLAPSE_MODEL`）

### 约束

1. `fastModel` **只填模型名**，不填 apiKey/baseUrl。
2. 必须和 `model` 是**同一供应商**（复用该供应商的 baseUrl/apiKey）。
3. 不填或填错会自动回退到 `model`。

### 验证 fastModel 是否生效

开两个终端，一个用 `debug` 模式启动：

```
cc -p "随便问一句" 2>&1 | findstr "query_source"
```

输出里会看到两条 `unrecognized_model`（第三方模型必有的提示），重点看 `query_source`：

```
{"model":"deepseek-v4-flash","query_source":"generate_session_title"}  ← 标题生成（fastModel）
{"model":"deepseek-v4-pro","query_source":"sdk"}                       ← 主对话（model）
```

- 如果 `generate_session_title` 那条用的模型 == `fastModel` → **fastModel 生效** ✅
- 如果两条都一样 or 全都 == `model` → fastModel 没生效（多半是填错了）

## 会话内切换模型（最省 token 的方式）

在会话内用 `/model` 斜杠命令，上下文连续：

```
/model deepseek-v4-pro      # 切到 pro 思考
/model deepseek-v4-flash    # 切回 flash 执行
```

- `/model` 只切模型名，不切 baseUrl/apiKey。
- ✅ 同一供应商内切换有效（pro ↔ flash）
- ❌ 跨供应商切换无效（baseUrl 没变）

## baseUrl 是什么、怎么填

Claude Code 会自动在 `baseUrl` 后拼 `/v1/messages`：

```
最终请求地址 = baseUrl + /v1/messages
```

所以 baseUrl 里**不要**带 `/v1/messages`。

### 国产模型 baseUrl 速查表（已实测）

| 厂商 | baseUrl | 实测 |
|------|---------|------|
| DeepSeek | `https://api.deepseek.com/anthropic` | ✅ 401 |
| GLM 智谱 | `https://open.bigmodel.cn/api/anthropic` | ✅ 401 |
| Kimi 月之暗面 | `https://api.moonshot.cn/anthropic` | ✅ 401 |
| MiniMax | `https://api.minimax.io/anthropic` | ✅ 401 |
| MiniMax 备用 | `https://api.minimaxi.com/anthropic` | ✅ 401 |
| 火山引擎(豆包) | `https://ark.cn-beijing.volces.com/api/anthropic` | ✅ 401 |
| Qwen 通义 | `https://dashscope.aliyuncs.com/api/v2/apps/claude-code-proxy` | ⚠️ 专供 CC 代理 |

> 401/403 = 端点存在（未带 key 被拒），这是探测正常现象。
> 完整说明见下文「换新厂商怎么找 baseUrl」。

### 换新厂商怎么找 baseUrl

1. 搜「厂商名 + Anthropic 兼容 base_url」或「厂商名 + Claude Code 接入」
2. 抄官方文档里明确的 `BASE_URL`
3. 用 curl 验证：`POST /v1/messages`，看返回 401/403（对）还是 404（错）

## 桌面版会话管理（cc ui）

原生 Qt 桌面应用（`cc-ui-qt.py`，PySide6），直接读写本地文件系统，**实时刷新、无需手动更新**：

```
cc ui
```

- **实时**：文件系统监听 + 进程存活检测，新建会话 / LIVE 状态 / 终端开关全部即时反映，不用刷新
- **新建会话**：原生目录选择器选工作目录，新终端启动；尚未输入第一条消息的会话显示「运行中（等待首次输入）」
- **恢复会话**：弹窗选择「正常 / 危险」模式，默认选中上次会话的权限模式（danger 会话默认危险）
- 会话按项目目录分组，显示时间 / 问答轮数 / 模型 / 大小；勾选多删、空会话一键选中
- 删除会顺带清理残留（subagents、file-history、tasks、telemetry），并精确清除 `history.jsonl` 和 `.claude.json` 里的引用
- **正在运行的会话显示 `● LIVE`，不可勾选、不可删除**
- **会话级 Provider**：新建/恢复会话时可选 Provider（默认 = 该会话已用的 provider，记录在 `session-providers.json`，无记录时从模型推断，兜底全局 default）；恢复时还可选「正常/危险」模式
- 前置依赖：`pip install PySide6 psutil`（已装）

> 旧的网页版（`cc-sessions.mjs` / `cc-sessions-ui.html`）已弃用，文件保留作参考。

## 会话自动清理与备份

Claude Code 有一个 `cleanupPeriodDays` 保留清理（默认 30 天）：启动时后台按**文件修改时间**删除过旧的会话记录，包括 transcript、`file-history/`、`tasks/` 和对应的 `history.jsonl` 条目，官方没有真正的关闭开关。

本机已在 `settings.json` 设置 `"cleanupPeriodDays": 99999`（≈274 年），大幅降低误删概率。但仍建议保留一份**配置目录之外**的备份兜底：

- 每日 03:00 由计划任务 `CC-Config-Backup` 自动执行，把 `projects/`、`file-history/`、`tasks/`、`history.jsonl` 增量复制到 `D:\ClaudeCode-archive`
- 也可随时手动执行：`cc backup`（默认保留 365 天，可用 `cc backup 180` 改天数、`cc backup 0` 表示不清理）
- **归档有界**：会自动清掉「源目录里已不存在、且归档副本超过 365 天」的旧文件；源里还存在的会话不会被清。体积 ≈ 当前会话 + 最近一年被删过的会话，不会无限增长
- 归档放在配置目录的**兄弟目录**（不是 `D:\ClaudeCode\backups\`，那个目录本身也在清理范围内）

> 注意：整目录复制/迁移配置会改动 mtime，可能触发清理误删（这也是本次清理发生的原因）。换电脑时直接复制整个 `D:\ClaudeCode-archive` 即可保留历史。

## 角色系统（cc role）

角色 = 固定人设 + 一个自动积累的知识库。用某个角色启动的会话会：

1. **继承该角色的历史知识** —— 会话开始自动读取 `roles\<name>\knowledge.md`
2. **自动学习** —— 人设指令让模型把学到的重要知识（关键结论/约定/API/坑/模式）用 Write/Edit 写回知识库，随会话增长
3. **可选继承指定会话** —— `cc role <name> --from <id1,id2>` 会把那些会话的问答要点提取到 `inherit.md` 供模型阅读

```
cc role new 后端 "资深后端工程师"     # 创建角色
cc role 后端                          # 启动角色会话
cc role 后端 --from d87ff067-...      # 启动并继承指定会话
cc roles                              # 查看所有角色
```

- 角色数据在 `roles\<name>\`：`persona.md`（人设）、`knowledge.md`（知识库）、`meta.json`、`sessions.jsonl`（该角色的会话记录）
- 角色会话记录由 SessionStart hook 自动写入（普通 `cc` 会话不受影响）
- 在 `cc ui` 的「角色」页也能管理：新建角色、启动、选择继承、编辑知识库

## 命令中心（cc ui 的「命令中心」页）

`cc ui` 的「命令中心」tab 把终端命令搬进网页，无需开终端：
- **会话**：新建会话（`cc`）、危险模式（`cc danger`）、快速提问（输入问题 → 新终端跑 `cc -p "…"`）
- **供应商**：查看当前 provider 与模型映射，一键切换（下次 `cc` 启动生效）
- **维护**：一键备份（`cc backup`），输出直接显示在页面
- 人设通过 `--agents <json>` 内联注入（对第三方模型也可靠）；知识读取指令由 hook 注入会话上下文

## 目录说明

```
D:\ClaudeCode\
  cc.cmd               # 启动器（已加入 PATH）
  cc-config.json       # ★ 供应商配置（改这个）
  cc-config-read.ps1   # 配置读取（不必动）
  cc-provider.ps1      # 供应商管理（不必动）
  cc-history.ps1       # 历史查看（不必动）
  cc-clear.ps1         # 会话清理（不必动）
  cc-ui-qt.py          # ★ 桌面版会话管理（PySide6，cc ui 启动）
  cc-sessions.mjs      # 网页版服务器（已弃用，保留参考）
  cc-sessions-ui.html  # 网页版界面（已弃用，保留参考）
  cc-backup.ps1        # 会话备份脚本（cc backup 调用）
  cc-role.ps1          # 角色系统启动器（cc role 调用）
  roles/               # 角色数据（人设、知识库、会话记录）
  README.md            # 本说明
  settings.json        # Claude Code 用户设置
  .claude.json         # 全局状态
  projects/            # 会话记录
```

## 注意事项

1. `cc.cmd` 每次启动实时读取 `cc-config.json`，改完立即生效。
2. 启动器从配置文件取值，不依赖系统环境变量。
3. `unrecognized_model` 黄色提示是第三方模型的正常现象，不影响使用。
4. 换电脑/重装时备份整个 `D:\ClaudeCode` 即可无缝迁移。