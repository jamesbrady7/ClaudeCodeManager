# 知识库：uidesigner

> 本文件是本角色的长期记忆，随会话自动积累。
> 由角色在会话中学到重要知识后用 Write/Edit 维护。

## 维护规范
- 用「## 主题」分节，每节 3-6 行精炼要点，中文书写
- 同主题用 Edit 更新，不新建重复小节；删除/精简过时内容
- 记录：关键结论、约定、API、命令、坑、可复用模式
- 不记录：过程、闲聊、大段代码全文
- 知识库应保持精炼；若超过约 30KB / 600 行，请主动合并精简

## cc ui 会话面板列布局
- 8 列：0 会话 / 1 角色 / 2 时间 / 3 轮数 / 4 模型 / 5 大小 / 6 状态 / 7 操作
- 列索引在 `_apply_layout`/`_rebalance`/`_rebuild_tree` 多处硬编码，加/删列要全部同步
- 吸收器：标题列（0）没被拖过时标题吸收，拖过则末列（7）吸收；`_rebalance` 保证总宽=视口
- `_on_section_resized` 让右列吸收变化，实现「拖动只影响边界两列，右侧绝对位置不动」

## 角色面板实时刷新（watcher 坑）
- QFileSystemWatcher 的 `directoryChanged` 只在增删改名时触发；**文件内容追加要监听文件本身**（`addPath` 到 sessions.jsonl）才触发 `fileChanged`
- 角色会话由 hook 向 `roles/<role>/sessions.jsonl` 追加 → 面板监听各 sessions.jsonl + PROJECTS 目录即可自动刷新
- `_reload_all` 陷阱：`_load_roles` 在 `blockSignals` 里重设当前项后，selection 信号不再触发 `_show_role`，需显式调 `_load_role_sessions(name)`（key 守卫避免无关事件重建树闪烁）

## 角色↔会话关联
- 关联记录在 `roles/<role>/sessions.jsonl`（`{session_id, timestamp, cwd}`），`ccui/role/data/store.py::session_role_map()` 反查全局 `session_id → 角色名`
- 主会话面板用它显示「角色」列；角色面板用它交叉引用 transcript 出标题/轮数/模型
- **孤儿记录**：hook 启动即记录 session_id，无 transcript 的会残留 → 角色面板只显示 `s.exists` 的会话；`role_service.prune_stale_role_sessions` 年龄守卫清理（无 transcript 且旧于 10 分钟）

## 事件驱动架构（SignalHub）
- `ccui/infra/signalhub.py`：纯 Python 事件总线（单例）`emit(event, **payload)` / `subscribe(event, fn)`；「谁改数据谁通知」
- 事件：`sessions.changed`（创建/删除/恢复/占位）、`roles.changed`（增删角色）、`role.sessions.changed(name)`（角色会话记录变化）
- 发射点：SessionManager.register_spawn、SessionService.delete/resume、RoleService.create/delete_role、RoleManager.prune/remove_session
- 订阅：SessionPanel→sessions.changed→_schedule_rescan；RolePanel→三类事件→_schedule_reload（role.sessions 按 name 过滤无关角色）
- 视图刷新依赖数据层事件，不直接操作列表（删除成功才 emit → 行才移除）
- **跨视图一致（角色启动会话）**：双通道——
  1. 共享占位：`_start` 用 `start_role` 返回的 proc 在 SessionManager 注册 SpawnedSession → `sessions.changed` → 会话面板**立即**显示（两侧同步）
  2. 兜底合并：`_rescan` 合并 `RoleManager.starting_entries(existing, live, now, 20s)`（外部 cc role 启动的），**关联去重**：与共享占位 cwd+时间(≤30s) 匹配的跳过
- **分组坑**：真实会话 projectPath 是**正斜杠**（`best_effort_decode` 生成 `D:/ClaudeCode`），角色追踪的 cwd 是反斜杠 → 合并占位必须 `norm_path(cwd)`，否则同目录会话分到不同组
- **延迟根因**：角色视图「启动中」来自内存 pending（瞬间）；会话面板靠 live/追踪（文件系统，~1-2s）→ 共享占位消除此延迟
- **失焦文字变黑**：角色会话树默认 SingleSelection，失焦时选中行用 Inactive 配色 → 黑字。修：`setSelectionMode(NoSelection)`（与主面板一致）+ QSS `:selected` / `:selected:!active` 兜底；palette 的 Text 三态都设浅色即可保证不黑
- **性能坑**：transcript 可能很大（几 MB~10MB），`by_id()`/`scan()` 每次全量读取解析全部 transcript → 阻塞 UI（~1.5s）。两层修复：
  · 删除/恢复弹窗**不要**现扫：右键菜单 item 的 `UserRole+1` 已存 Session 对象，直接传 ref 即可
  · **`store._parse_transcript` 解析缓存**：按「路径+大小+mtime」为键缓存解析结果（不含 revmap 依赖字段），`scan_sessions` 用 `dataclasses.replace` 现算 sizeBytes/isLive 不污染缓存 → 二次 by_id 从 ~290ms 降到 ~2ms，角色切换/面板刷新都提速
- **启动飞屏**（`ccui/app/splash.py`）：QPainter 画可爱 Claude spark（珊瑚 4 点星芒 + 大眼 + 微笑 + 腮红），`main()` 里 `SplashScreen()` → `prewarm()`（by_id 冷扫、live_ids、RoleManager、对话框 show+hide 预热）→ `MainWindow()` → `splash.finish(win)`。吸收「第一个原生窗口创建 ~1s」+「冷 by_id ~300ms」，之后主窗口 30ms、DeleteDialog 首次 7ms（不再闪）

## 时间戳坑（iso_to_ms）
- **Python 3.9 的 `fromisoformat` 只接受 ≤6 位小数**；hook 写 7 位（`7685894Z`）→ 解析失败返回 0 → 角色面板「物化判定」失灵 → 双启动中
- 修复：先分离纯小数与**时区后缀**（Z/±HH:MM），截断小数到 6 位再拼后缀；别把 Z 截掉，否则按本地时间解析差 8h

## 数据同源架构（SessionManager + RoleManager）
- **隔离规则**：各模块 Data/Service 层互相隔离；只有 View 层可以跨模块调 Data/Service
- **SessionManager**（`ccui/session/data/manager.py`，单例）：owns `spawned` 占位；`scan()`/`by_id()`/`live_ids()` 复用 session_store，是会话存在/state 的唯一来源
- **RoleManager**（`ccui/role/data/manager.py`，单例）：map(name→Role)，每个 Role 有 `uuid`（旧角色自动回填 meta.json）+ `session_ids` 列表；`session_entries`/`prune_stale(existing_ids)`/`remove_session`，不 import 任何 session 模块
- 角色视图渲染 = RoleManager 拿 uuid 列表 → SessionManager 按 uuid 查 Session（同源，不再各自扫描）
- role_service 不再 import session_store；`role_sessions` 等跨模块方法删除，改由 View 编排

## 角色面板会话管理（坑）
- **`setItemWidget` 必须先 `addTopLevelItem`**：item 未入树时无 model index，挂的 widget 会被 Qt 忽略——操作列按钮「消失」的真正原因
- 会话操作改用**右键菜单**（`customContextMenuRequested` + `itemAt(pos)`）：启动（恢复）/ 删除；运行中的会话两项都禁用
- 运行态：Claude Code 会写 `sessions/<pid>.json`（含 pid/sessionId），`live_session_map()` + psutil 判 live；live 行 `setDisabled(True)` + 标题加「（运行中）」
- **启动中**：无 transcript 但 live（或追踪 <20s）→ 显示「（启动中…）」禁用；孤儿（无 transcript 非 live 且旧）→ 隐藏 + prune 清文件。根因：旧代码 `exists` 过滤把启动中的会话也藏了，导致创建后不显示
- 视图级 `_pending` 占位：点击创建后、hook 写入前即刻显示「启动中」，物化或 20s 后清除
- live 变化靠 tick：`_role_live` 为真时每 3s 刷新（捕获进程结束）；`isLive/isSpawned` 纳入 key 守卫
- spawn 后补偿刷新：`QTimer.singleShot` 分段刷（+1s/+2s/+4s/+8s），覆盖 claude 启动 + hook 写文件的时间差

## 会话继承机制（普通会话）
- 角色继承 = `cc role --from` 生成 `inherit.md` + hook 注入；普通会话继承 = `CC_INHERIT=<path>` 环境变量 + hook 注入「先 Read <path>」
- `session_service.build_inherit(ids)` 镜像 cc-role.ps1 Write-Inherit，摘要写 `CONFIG_DIR\inherit\<ms>.md`
- `spawn_terminal(args, cwd, env=None)` 支持注入子进程环境变量（Popen env= 合并 os.environ；QProcess 兜底转 K=V 列表）
- hook 测试注意：`[Console]::In.ReadToEnd()` 需进程级 stdin 重定向（`< file`），PowerShell 管道不算 stdin；且 hook 里中文匹配串在 bash→powershell 命令行会乱码，断言用 ASCII 标记
