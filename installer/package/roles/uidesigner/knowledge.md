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
- **漏网之鱼 `prune_stale`（role/data/manager.py）**：曾直接用裸 `fromisoformat` 解析 sessions.jsonl 的 7 位小数 → 抛 ValueError → `except: stale=True` **绕过 10 分钟年龄守卫**，把刚启动（transcript 尚未生成、sid 不在 existing_ids）的会话记录**立即误删** → 症状=角色面板丢会话 + 会话面板角色列丢。修复：改用 `iso_to_ms`（内部截断小数），年龄守卫恢复生效
- **排查手法**：transcript 里找 `【角色系统】你是 <名>` 标记即可反推「哪个角色会话丢了关联」；记录可从 transcript 首条 timestamp + cwd 重建 sessions.jsonl（去重追加）

## 设计技能（Emil Kowalski）
- 已装 6 个技能：emil-design-eng（核心）/ animate / apple-design / animation-vocabulary / find-animation-opportunities / review-animations，挂到 uidesigner 角色
- 核心原则：弹窗属「偶尔出现」→ 标准动画 <300ms、进场 ease-out；高频操作（列表刷新/状态）不动画；**克制**
- **对话框淡入**：`ccui/app/dialogs.py::FadeDialog`（windowOpacity 0→1，220ms OutCubic），全部 8 个对话框继承它——弹窗不闪现，顺带盖住首次白闪
- 按钮已有反馈（Fusion 下沉 + QSS :pressed 变暗），无需额外动画

## 主题刷新（去生硬，apple-design §12/§15/§16）
- 背景 #1b1b1e / 树 #242428 / 描边用 **rgba(255,255,255,0.06~0.10)**（柔化硬边框）
- **去斑马纹**：删 `setAlternatingRowColors(True)` + 去 alternate-background-color
- **按钮垂直渐变**：`qlineargradient`（上亮下暗），hover/pressed 变体
- **主按钮光晕**：`theme.apply_glow()` = QGraphicsDropShadowEffect 蓝色 glow，加在 btn_new / btn_start
- **排版**：标题 `QFont.setLetterSpacing(AbsoluteSpacing, 0.6)` 加字距；表头 font-weight 600
- 树 item padding 5px 8px（留白更多）
- **`ccui/app/widgets.py::ElidedLabel`**：自动省略号标签（paintEvent 按宽度省略 + sizeHint 封顶 ≤240），用于 `lbl_skills`——长技能列表不再撑宽布局挤压 QSplitter 左列（角色切换时左列表宽度恒定）

## 图标系统（ccui/app/icons.py）
- `provider_icon(name)`：品牌色首字母徽章兜底；**`assets/providers/<name>.png|.svg` 存在则用之**（官方 logo 已放 deepseek.svg/glm.svg）
- `role_icon(name, icon_path)`：自定义图标优先，否则首字母彩色徽章（颜色按 crc32 稳定哈希）
- provider 徽章显示在：会话列表模型列（`provider_map` 每会话解析）+ 新建/恢复对话框下拉
- **角色图标库**：`assets/role-icons/`（用户放 SVG/PNG，现 17 个矢量图）；`IconPickerDialog`（role/view/dialogs.py）网格点选 + 上传
- **编辑角色信息**：`EditRoleDialog`（名称/图标/**描述用 QTextEdit 大文本框放最下面**，内部复用 IconPickerDialog）；`update_role` 支持重命名（os.rename 目录）+ 改描述 + 改图标；**新角色默认用图标库第一个 SVG 作头像**（`set_default_icon`）
- **QListWidget 统一样式**：所有列表（角色/技能/新建角色勾选）统一浅表面 #202024 + item padding 8px 10px + **选中灰 #3a3a3e 而非蓝**（去掉蓝色整行高亮，保留 currentItem 供「编辑选中技能」用）
- **勾选交互统一**：技能列表/新建角色/继承会话对话框都加 `itemClicked → 切换 checkState`——点行任意位置即切换勾选（与会话列表一致），不必精确点框
- **勾选框双重切换坑**：Qt 点勾选框会「默认切换 + itemClicked」双重切换（净不变）→ 必须加 `_changed_at` 时间戳守卫（itemChanged 记录，itemClicked 时 <0.1s 跳过），会话面板早已有；InheritDialog 时间列要填 `fmt_time(s.lastTime)`（别传空串）
- **右键菜单**：`ccui/app/widgets.py::FadeMenu`（QMenu 淡入 140ms OutCubic）+ QMenu QSS（深色表面/留白/悬停）；角色列表右键 = 创建会话/编辑信息/删除（QMessageBox 确认 → `delete_role`）；会话右键菜单也用 FadeMenu
- **失焦文字变色统一修复**：QListWidget/QTreeWidget 的 `::item` 全部显式钉 `color: #f5f5f7`（选中/选中失焦也钉），失焦不再变色——palette 看似浅色但实际渲染会偏，必须 QSS 显式钉色
- **字号规范（apple-design §15）**：系统字体（Segoe UI）优先；大字**负字距**、小字略正字距、正文≈0；层级=字重+字号+行距。应用规格：标题 17px/700/字距-0.2、正文 13px/400/0、次要 12px/400/+0.2、Tab 13px/500/0（已修正标题正字距 +0.6→-0.2、Tab 0.3→0）
- **优雅细节**：`widgets.py::EmptyHint`（列表/树空状态提示，**必须是 viewport 的子控件**且几何用 `viewport().rect()`，事件过滤器装 viewport 上且**别用 `isVisible()` 判断**（可见性标志不可靠）+ `QTimer(0)` 延迟定位，否则首次打开不居中）；`AccentBarDelegate`（角色列表选中项左侧 3px 蓝条，微信式活跃指示）
- **创建角色会话可选工作目录**：`InheritDialog` 加 `cwd_visible/cwd` 参数（默认不显示，会话模块继承不受影响）+ `directory()`；`start_role(name, ids, cwd=None)` 支持指定工作目录；`_start` 传 `cwd_visible=True, cwd=dirname(ROLES_DIR)`，共享占位也用所选 cwd
- **炫酷视觉批次**：窗口背景 `qlineargradient`（上 #222226 → 下 #18181b 深度感）；会话工具栏包 `QFrame#toolbarBar`（底部细分割条带）；角色详情 Hero（头像 44px + 名称大字 + 描述 #98989d 置灰，竖排右区）
- **`AnimatedTabBar`**：选中 tab 底部 3px 蓝色指示条，切换时 **QVariantAnimation 220ms OutCubic 滑动**（需 `time.sleep` 让事件循环推进才看得到动画，offscreen 测试勿只用 processEvents）
- **炫酷弹药批**：行悬停左缘 2px 淡蓝条（QSS `border-left`）；「● LIVE」微呼吸（700ms 定时器插值红色明暗，仅 liveCount>0 时工作）；`apply_shadow` 浮起阴影（角色侧栏+角色会话树，注意 QGraphicsDropShadowEffect 会栅格化大控件——大会话树**别加**，且与入场淡入互斥）；会话树首次入场淡入（QGraphicsOpacityEffect + QPropertyAnimation 320ms，**完成后 `setGraphicsEffect(None)` 移除**避免常驻）；EmptyHint 前缀星标 ✨
- **坑**：**QTextEdit 也要配 QSS**（否则系统默认白框）——用 `QLineEdit, QTextEdit` 统一深色 + `:focus` 蓝框
- **详情区头像**：`role_icon_full`（无灰底容器，SVG 裁剪透明边距后铺满 90%）——彩色 logo 在深色底清晰，别用带容器的 `role_avatar`（那会「灰底包小图标」）；`_svg_content_pixmap` 用 QSvgRenderer 渲染 128px 找非透明 bbox 裁剪
- **会话模块移除操作列**：删掉每行「恢复」按钮 + 整列（7 列），改**右键菜单**（启动（恢复）/ 删除，运行中两项禁用）；注意 `setColumnCount` 别和 `setHeaderLabels` 冲突；分组标题行（sid=None）右键不弹菜单
- **会话模式记忆**：`store.detect_permission_mode` 读 transcript 里 **`type=="permission-mode"`** 独立条目的 `permissionMode`（**不是** user 消息里），取**最后一条**；`bypassPermissions`→danger，其余→normal。老代码找 `type=='user'` 里的字段永远匹配不到、恒返回 normal
- **会话树角色列带头像**：col 1 用 `role_icon_full(role, role_store.role_icon_path(role), 16)` 设图标（`session_role_map` 按 session_id 查角色）
- **LIVE 呼吸**：`_breath_tick` 用 `math.sin(self._breath*0.6)` 正弦，亮红 #ff453a ↔ 暗红 #6e1a15（红通道 110~254、亮度差 ~72，肉眼可辨），500ms 定时器；太微弱会看不见——幅度要拉大
- **关键坑：LIVE 行别 `setDisabled(True)`**——禁用态用灰色覆盖 `setForeground`，呼吸色白设！改为去掉 `ItemIsUserCheckable`（运行中不可勾选但不禁用）；交互守卫（右键禁用、删除跳过 live）已有，无需禁用行
- **更深的坑：QSS `background`（QTreeWidget 或全局 QWidget 渐变）会覆盖 `setBackground` 和 palette Base**——LIVE 行底衬用**自定义 delegate**（`LiveRowDelegate` 在 `super().paint()` 后 `fillRect` 浅红）才可靠；非 LIVE 行状态列显示「已结束」；窗体加宽 1440x820、列宽加大、标题 trunc 放宽（超宽自动省略号）
- **LIVE 整行铺红**：delegate 查标记必须用 `index.siblingAtColumn(0).data(LIVE_ROLE)`（`index.data` 只返回**当前列**数据，标记只设第 0 列时其它列不生效）
- **角色名帅气字体**：24px 400，QSS `font-family: "Dancing Script", "STXingkai", "Segoe UI"`——**按字形回退**：英文用 Dancing Script（手写体）、中文用华文行楷（STXingkai），两者都是 Windows 自带（C:\Windows\Fonts 下有 DancingScript-Regular.ttf / STXINGKA.TTF）；**坑：`setFont` 的字号会被全局 QSS `font-size:13px` 盖掉**（pointSize 变 -1）——必须用**标签级 `setStyleSheet`**（优先级更高）；QSS `font-family` 逗号列表 = QFont families 列表，支持按字形回退
- **中文角色名**：Python `store.NAME_RE` 与 `cc-role.ps1` 的 `$nameRe` **都要**放开（`[\w一-鿿-]+`，\w 已含中文、再加 CJK 范围），否则 Python 侧能建但启动会话被 ps1 拒
- **状态栏 provider 徽章已移除**：它显示的是全局默认 provider，用户会误以为当前会话的模型——语义有歧义，待设计好再考虑
- `ASSETS_DIR` 已移到 `infra/config.py`（角色 data 层也能访问图标库）
- **角色列表微信式**：`QListWidget#roleList` QSS（浅表面 #202024 + item padding 8px 10px + hover/选中）；行高 46px、图标 26px；`role_avatar()` 把自定义图标放进**圆角浅底容器**（#3f3f46）——黑色图标也可见
- `role_store.write_role_icon` 保留源扩展名存 `roles/<name>/icon.{png|svg}`；`role_icon_path` 查两者
- 统一风格修复：`QListWidget::indicator` QSS（技能勾选框边框）；`InheritDialog` 设 NoSelection（点击不整行蓝选）
- 字体规范（apple-design §15）：用系统字体（Segoe UI）+ 字距/字重建层级，不加自定义字体选择器

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

## 技能分类体系（按类型分组勾选）
- **权威来源** = SKILL.md frontmatter 的 `category:` 行；缺省时 `store.infer_skill_category(name, desc)` 按关键字兜底（规则表 `_CATEGORY_RULES`，顺序即优先级）
- 分类：`SKILL_CATEGORY_LABELS = ['动效动画','界面设计','设计系统','品牌视觉','内容演示','综合','其他']`；`store.create_skill(..., category='')` 自动把类别写进 frontmatter
- `Skill` 模型新增 `category` 字段；`read_skill` 返回的 dict 含 `category`；`role_service.list_skills/get_skill` 透传
- **已装 ui-ux-pro-max 技能**（7 个，nextlevelbuilder/ui-ux-pro-max-skill）：banner-design/brand/design/design-system/slides/ui-styling/ui-ux-pro-max；`design` 是全能 megaskill（依赖 Gemini 生成 logo，可只做设计智能用）。回填脚本 `scripts/backfill_skill_categories.py`
- **SkillGroupList**（`ccui/app/widgets.py`）：QTreeWidget 按分类分组；**分类头**粗体弱色+浅底条，显示「类型 · X/Y 已选」，点击整行=全选/全不选；**技能行**勾选框+名称（— 描述），点行任意位置切换勾选（`_changed_at` 防双重切换）
- **坑 1**：`QTreeWidgetItem.setData/data` 必须带列参（`setData(0, role, v)`/`data(0, role)`）——不像 QListWidgetItem 可省列
- **坑 2**：`_build` 里 `setCheckState` 会触发 `itemChanged` → `_changed_at` 被设为"刚刚"，随后第一次点击被防重逻辑吞掉——**构建完必须 `_changed_at = 0`**
- **坑 3**：QSS 作用域 `QTreeWidget#skillGroupTree::item:selected` 把树选中从蓝改灰（与 QListWidget 全局一致）；QTreeWidget::item 全局不设 color 才能让 setForeground 生效
- 防重守卫局限：同一技能行 0.1s 内连点第二次会被吞（与旧 QListWidget 行为一致，接受）

## 高级感改造批次（emil-design-eng + ui-ux-pro-max 审计产出）
- **按钮光晕 `PressButton`**（widgets.py）：光晕 = **交互状态指示**，非装饰常驻——静止无光晕（干净蓝按钮，`#btnNew` QSS 已醒目）、**悬停浮现柔光**（t=0.5）、**按下全亮再 160ms 衰减**（t=1.0）；静止时 `effect.setEnabled(False)` 避免常驻离屏渲染。**设计原则：常驻不变的光晕会让人误以为是状态/加载指示，效果必须有目的**。坑：新动画前必须 `stop()` 旧动画；悬停/按下互切用 `_rest_target()`（按 `_hovered` + `isDown()` 决定回落目标）
- **对话框退场淡出已撤销**：曾用 `windowOpacity` 做退场淡出（120ms），但**用户实测每次关对话框主界面都闪烁**——windowOpacity 动画让对话框变透明时会暴露并强制重混合底下主窗口，主窗口上的投影/光晕等 graphics effect 会闪。**结论：只保留进场淡入（对话框从不透明往上盖，无此问题），关闭保持即时**（FadeDialog 不再覆写 accept/reject）
- **⚠️ PySide6 模态死锁坑（若再尝试退场动画必踩）**：把对话框自身绑定方法**直接**连到动画 `finished`（`anim.finished.connect(super().accept)`）→ 在 `exec()` 里**死锁**——opacity 动画能跑完但 `finished`→`accept` 的关闭不生效，模态窗体透明但一直抓取输入、整个 app 冻结。**必须包一层普通 Python 函数**（`def _finish(): done()` 再 connect）才正常；再加保险丝定时器兜底。诊断方法：离屏 + QTimer.singleShot 触发 accept + 看门狗单测每个对话框的顶层 exec
- **相对时间 `fmt_relative`**（theme.py）：刚刚/N 分钟前/N 小时前/N 天前/超一周回退 MM-DD HH:MM；会话面板与角色面板时间列都用它（tooltip 保留完整时间戳）
- **键盘快捷键**（main_window.py）：Ctrl+N 新建 / Ctrl+F 聚焦搜索 / Ctrl+R 刷新 / Delete 删除选中。**坑：Delete 必须查 `QApplication.focusWidget()` 是否输入框，否则搜索框里按退格会触发删除**
- **焦点环**：`QTreeWidget:focus, QListWidget:focus { border: 1px solid rgba(10,132,255,.45) }`——移除 `outline:none` 完全无焦点的问题
- **`should_reduce_motion()`**（theme.py）：读 Windows `SPI_GETCLIENTAREAANIMATION`（0x1042），系统关「显示动画」时跳过位移/进场动画、保留颜色过渡；所有动画入口先查它
- **工具栏精简**：删「刷新」按钮（文件监听 + 300ms 防抖 + live 2s tick 已自动刷新，冗余；Ctrl+R 快捷键保留）；「选中空会话」→ 升级为「清理空会话」一键删除（on_clean_empty：过滤 isEmpty 且非 live → DeleteDialog 确认 → service.delete）。DeleteDialog 加可选 `title/confirm_text/intro` 参数复用

## 批量优化（品牌一致 + 信息设计）
- **空状态画 spark**：`splash.spark_pixmap(size)`/`warning_pixmap(size)` 导出绘制 helper；`EmptyHint` 改 `paintEvent` 在文字上方画启动画面的 Claude spark（56px，替代 emoji ✨——emoji 渲染不一致且廉价）；DeleteDialog 的 ⚠ 换 `warning_pixmap` 内联图标。**品牌一致：启动画面与主界面共用同一视觉语言（Cohesion）**
- **总数 stat 集群**：`lbl_totals` 用富文本 HTML（`<b>`/`<span style=color>`），三段式「会话数 · 体积 · ● 运行中」，运行中用呼吸红（`_breath_tick` 每 500ms 同步刷新该 span 颜色，与列表 LIVE 徽章呼应）；搜索时前缀「N 个匹配」。**注意 `setTextFormat(RichText)`**
- **搜索框**：`setClearButtonEnabled(True)` 一键清除按钮
- **目录 inline 校验**：NewSessionDialog/InheritDialog(cwd_visible) 目录空时禁用「创建」按钮（`textChanged`→`_sync_ok`）；对话框默认预填 home 目录所以默认启用，清空即禁用
- **会话树行距**：`QTreeWidget::item` padding 5px→7px（8px 间距体系）

## 交互补充批次（双击/右键/tab 记忆）
- **双击会话 = 恢复**：会话面板 `tree.itemDoubleClicked → _on_item_double_clicked`、角色面板 `session_tree.itemDoubleClicked → _on_sess_double_clicked`（live 跳过）。会话管理器核心直觉交互
- **右键菜单增强**：加「打开所在目录」（`os.startfile(projectPath)`，目录不存在时禁用/提示）与「复制会话 ID」（`QApplication.clipboard().setText`）；live 会话禁用启动/删除，打开目录/复制保持可用
- **记住上次 tab**：`config.py` 加 `ui-state.json` 轻量 UI 状态（`load_ui_state`/`save_ui_state`，不含密钥，与 cc-config.json 分开）；MainWindow 恢复 `last_tab`（连线前 setCurrentIndex 避免触发淡切）+ currentChanged 时保存；**ui-state.json 已加 .gitignore**

## Lucide 图标体系
- **图标源**：Lucide（MIT、统一 2px 描边、成体系），从 `unpkg.com/lucide-static/icons/<name>.svg` 下载到 `ccui/app/assets/icons/`（12 个：plus/trash-2/broom/book-open/settings/wrench/play/folder-open/copy/message-square/users/search）
- **`icons.ui_icon(name, size, color)`**：读 SVG → `svg.replace('currentColor', color)` 换色 → QSvgRenderer 渲染 QIcon（HiDPI 感知：`devicePixelRatio` 下按 px=size*dpr 渲染并 `setDevicePixelRatio`）。渲染一次静态色，hover 不变色
- **应用**：主按钮 icon+文字（plus 白）；**纯图标**（普世可辨识 + tooltip 兜底）：删除选中（trash 红）、编辑知识库（book）、编辑角色信息（settings）；其余 icon+文字（清理空会话 broom、管理技能 wrench、tab 会话 message-square/角色 users、右键菜单 play/folder-open/copy/trash、搜索框 leading search）
- 纯图标按钮用 `setFixedSize`（32~34px）对抗 QSS `padding:6px 16px` 的过宽；菜单项图标用 `menu.addAction(QIcon, text)`
- 图标颜色按语义：主按钮白 / 普通 `#c8c8cc` / 菜单 `#d4d4d8` / 危险红 `#ff6961` / tab 灰 `#9a9aa0` / 搜索弱灰 `#6b6b70`
- **⚠️ Qt QSS rgba alpha 坑**：`background:`（简写）**忽略 rgba 的 alpha，渲染成不透明**（实测 `background:rgba(255,255,255,0.06)` 是纯白）——危险按钮 `background:rgba(255,69,58,0.14)` 一直是纯红块，遮挡图标。**但 `border:` 尊重 alpha**。修复：危险按钮改用不透明暗红 `#3d2423`（近似 14% 红染意图）；凡是 `background:rgba(...,0.xx)` 都可能渲染不透明
- **纯图标按钮必须**：`#iconBtn { padding:0 }` 覆盖全局 `padding:6px 16px`（否则 34px 按钮只剩 2px 给图标 → 被裁切/遮挡）+ `setIconSize(QSize(15,15))`（否则图标撑满按钮）
- **图标+文字居中**：文字前**不能加空格**（会导致整体右偏 ~8px）；Qt QPushButton 自身有 ~2px 左偏的通用行为（纯文字按钮也如此，忽略）
- **⚠️ HiDPI 渲染矩形坑（严重）**：QPixmap 设了 `devicePixelRatio` 后，**QPainter 用逻辑坐标**（`fillRect(0,0,size,size)` 就涂满整个 `size*dpr` 物理像素）。`ui_icon` 曾用 `QRectF(0,0,px,px)`（px=size*dpr 物理）渲染 SVG → DPR>1 时图标被放大 size/px 倍、**右/下溢出被裁剪**（Windows 125%/150% 缩放时图标右缘被挡住）。**必须传逻辑尺寸 `QRectF(0,0,size,size)`**。离屏 dpr=1 时 px==size 恰好掩盖此 bug，真机才会暴露

## 代码审视优化批次（性能/架构/复用）
- **人设路径硬编码修复（真实 bug）**：`role_service._persona_template` 曾硬编码 `D:\ClaudeCode\roles\...`，换 `CLAUDE_CONFIG_DIR` 就生成错路径——改用 `os.path.join(ROLES_DIR, name, ...)`
- **工具函数去重**：`trunc`/`text_content` 提取到 `infra/utils.py`；`theme.py` 重导出 trunc（各 view 继续 `from theme import trunc`，兼容）；session_service 的局部 `text_of`/`trunc`、store 的 `_text_content` 全部删掉改用 utils
- **磁盘 IO 缓存**：`build_reverse_map`/`read_provider_mapping` 按 **(mtime,size) 失效**缓存（写 provider 后 clear 缓存）；`session_role_map` 2s **TTL**（热路径树重建）；`_svg_content_pixmap` 按 path 缓存（角色列表/头像热路径）。**缓存访问用 `.get()` 而非 `['key']`**，避免被 clear 后 KeyError
- **`mk_buttons(dialog, ok_text, cancel_text, danger_ok)`**（app/dialogs.py）：统一装配 QDialogButtonBox + 连接 accept/reject，收编 9 个对话框的 6 行重复；NewSessionDialog/InheritDialog 需要 btn_ok 引用做目录校验，从返回的 btns 取

## 权限模式与主按钮一致化
- **权限模式改下拉单**：ResumeDialog 从两个 QRadioButton 改为 `cb_mode`（QComboBox，`addItem('正常模式','normal')`/`('危险模式…','danger')`，`mode()` 用 `currentData()` 返回 'normal'/'danger'——注意 QComboBox 的 currentData 返回 item data，currentText 才返回显示文本）
- **新建会话可选权限模式**：NewSessionDialog 加 `cb_mode`；`session_service.new_session(cwd, provider, mode='normal', ...)` 里 `mode=='danger'` 时 args 为 `['cc','danger','--provider',p]`（danger 紧跟 cc 后，与 resume 一致）；session_panel.on_new_session 传 `dlg.mode()` 并状态栏报模式
- **主按钮一致化**：`创建角色会话`/`新建角色` 之前是 PressButton（只有光晕）没设 `btnNew` objectName → 灰色底。补 `setObjectName('btnNew')` 后与「新建会话」一致（蓝色渐变 + 白色图标）

## 三项修复（未来时间戳/角色会话模式/列分布）
- **⚠️ 未来时间戳脏数据**：transcript 里可能混入 `timestamp=2099-01-01` 这类异常条目（顶层 user 行），`_parse_transcript` 取最大时间戳时把它当 lastTime → 时间列显示 `01-01 08:00`。修复：**过滤未来时间戳**（`iso_to_ms(ts) <= now+1h`，容忍时钟偏差）；`build_inherit` 的 first_ts 同理
- **创建角色会话可选权限模式**：InheritDialog（cwd_visible=True 即该场景）加 `cb_mode` 下拉；`role_service.start_role(name, from_ids, cwd, mode)` 传 `--mode danger`；**cc-role.ps1 Start-Role 加 `--mode` 解析**（danger 时 `& $claudeCmd danger`，与恢复会话语法一致）；role_panel._start 传 `dlg.mode()`
- **继承/删除对话框列分布**：InheritDialog（会话/时间）、DeleteDialog（会话/项目）列宽不平衡——加 `header.setStretchLastSection(False)` + col0 `Stretch` + col1 `ResizeToContents`，标题列吃满剩余、次要列收缩到内容

## 技能列表交互拆分（编辑 vs 勾选不冲突）
- **SkillGroupList 加 `row_select_toggles` 开关 + `doubleClickedSkill` 信号**：
  · True（新建角色，默认）：点行任意位置切换勾选（快速分配，无编辑需求）
  · False（技能管理）：**点勾选框才切换、点行仅选中**（供「编辑选中技能」按钮）、**双击行发信号**（宿主直接开编辑）
- **SkillsDialog** 用 False 模式 + `doubleClickedSkill → _edit_skill_named(name)`（从 `_edit_skill` 抽出按名编辑，按钮与双击共用）；提示文案更新「点勾选框切换 · 双击技能行可编辑」
- 离屏测试限制：QTest 模拟不了 dblclick（真实鼠标会产生 MouseButtonDblClick → itemDoubleClicked），双击逻辑用直接调用 `_on_double_clicked` 验证（发信号且不改勾选）

## 图标扩展（权限模式/列头/模型列）
- **权限模式图标**：正常 `shield-check`（护盾生效，#c8c8cc）、危险 `shield-off`（护盾关闭，#ff6961 红）——三个模式下拉（ResumeDialog/NewSessionDialog/InheritDialog-cwd）的 `cb_mode.addItem(icon, text, data)`
- **会话面板列头图标**（7 列）：会话 message-square / 角色 users / 时间 clock / 轮数 repeat / 模型 cpu / 大小 database / 状态 activity
- **角色面板列头图标**（4 列）：标题 message-square / 时间 clock / 轮数 repeat / 模型 cpu
- **⚠️ 列头图标设法**：`QHeaderView` **没有 `setSectionIcon`**（AttributeError）——必须用 `tree.model().setHeaderData(col, Qt.Orientation.Horizontal, QIcon, Qt.ItemDataRole.DecorationRole)`
- **角色面板模型列补 provider 图标**：`_load_role_sessions` 的 col3 原来只有模型名文字，现加 `item.setIcon(3, provider_icon(resolve_provider(u, s.models)))`（与会话面板 col4 一致）
- **⚠️ SVG 缓存键必须是 (path, mtime, size)**：`_svg_content_pixmap` 曾只按 path 缓存，角色换头像会**覆盖写同一 `roles/<name>/icon.svg`**，缓存返回旧图 → 头像保存不生效（用户实测 bug）。键带 mtime/size 后文件变化自动失效。凡是缓存文件内容（会被覆盖写的）都该带 mtime/size，不能只按 path

## ⚠️ claude 危险模式调用坑（自动输入 danger）
- **`claude danger` 会把 `danger` 当提示词自动运行**（用户实测：角色会话第一条 user 消息就是 'danger'）——正确开启危险模式必须用 **`claude --dangerously-skip-permissions`**（cc.cmd 的 :danger 分支就是这么写的）
- **cc-role.ps1 曾写 `& $claudeCmd danger`**（传位置参数）→ 每次以危险模式启动角色会话都会把 "danger" 当 prompt 注入。已改为 `--dangerously-skip-permissions`
- 排查方法：`roles/<role>/sessions.jsonl` 取最近 session_id → 找 transcript → 第一条 user 消息若是 'danger' 即命中此 bug；验证用 `CC_CLAUDE_BIN=<mock>` 跑 cc-role.ps1 看 claude 实际收到的参数
- 注意：`cc danger --resume`（session_service.resume）走 cc.cmd :danger 分支是正确的（`claude --dangerously-skip-permissions --resume`），只有 cc-role.ps1 直调 claude 时踩坑
- **Tab 内容淡切**：`QTabWidget.currentChanged` → 新面板 QGraphicsOpacityEffect + QPropertyAnimation 200ms OutCubic，**动画结束必须 `setGraphicsEffect(None)` 移除**（防常驻栅格化）；在 addTab 之后再连线，避免首次触发

## 技能独立模块化（P1）
- **技能是一等公民**：新增 `ccui/skill/`（data/models+store+manager / service/skill_service / view/dialogs），技能存全局 `skills/<name>/SKILL.md`，frontmatter 加 `uuid:`（稳定身份），角色 meta.json 的 `skills` 从名字数组改为 **uuid 数组**
- **角色按 uuid 引用技能**：改名/换目录不破坏引用；`role_service.update_role_skills(name, uuids)` 只写 meta（技能业务全在 skill 模块，隔离）
- **迁移** `ccui/skill/migrate.py`：幂等（技能逐行注入 uuid + 角色 meta 名→uuid），prewarm 里自动自愈；`SkillManager` 加载时对缺 uuid 的技能自动回填
- **frontmatter 解析保留未知键**：`parse_frontmatter/serialize_skill` 逐行处理，多行 `metadata:` 子键和 argument-hint/license 等字节原样保留（编辑技能不丢键）；`serialize_skill` 用 `raw_front.strip('\n')`（否则 `---\n\nname:` 空行影响外部 skill 加载器）
- **track-session.ps1 按 uuid 解析**：`Get-SkillMap` 扫所有技能建 uuid→路径+名→路径双映射，`Get-RoleSkillsText` 按 uuid 解析、**缺失优雅跳过**（未导入技能不出现在技能段）；兼容迁移前旧名字
- 角色专属技能（roles/<role>/skills/）废弃；`SKILL_CATEGORY_LABELS`/`infer_skill_category` 迁到 skill 模块
- SignalHub 新增 `skills.changed` 事件；SkillGroupList 改为 uuid 标识（checked_ids/selected_uuids/current_skill_uuid/doubleClickedSkill 发 uuid）

## 技能 tab + 三资产导入导出（P2/P3）
- **技能 tab**（`ccui/skill/view/skill_panel.py`，主窗口第 3 个 tab）：左按类分组树（行=名字—描述+N 角色引用）、右详情（名字/类型/uuid 可复制/描述/正文预览/被引用角色/编辑/重命名/删除/导出）；双击编辑、右键菜单
- **导入导出：模块分离、不内嵌**（`ccui/infra/archive.py` 通用 zip 工具，manifest 约定 kind=cc.sessions/cc.skill/cc.role）
  · 会话：export=transcript+同名子目录+file-history+tasks+telemetry（zip）；import 落盘 + `ensure_project_in_claude_json`（补 .claude.json 项目条目，保 eol 风格）；运行中拒绝覆盖、存在冲突返回
  · 技能：export=整目录树；import 三模式 skip/overwrite/new_uuid（换 uuid 落盘，角色引用旧 uuid 优雅跳过）
  · 角色：export **白名单** meta/persona/knowledge/icon/sessions.jsonl（**不含技能内容/transcript**）；import 后返回 skillUuids/sessionUuids，view 层检查缺失并弹摘要（技能未安装→去技能库导；会话不存在→追踪自动清理）
- **安全**：`safe_extract_zip` 防 zip-slip（拒绝对路径/.. 成员）；`make_zip` 支持内联 3 元组写 manifest
- **⚠️ 角色导入必须解包到临时目录再 move**：`os.rename` 跨盘（临时目录在 C:，roles 在 D:）会 WinError 17，且直接解到已有目录上再改名会**毁掉原角色**（实测把 uidesigner 目录改名删了，靠 git 恢复）——先 `tempfile.mkdtemp` 解包、`shutil.move` 到目标，原角色目录绝不触碰
- **⚠️ QSplitter 必须显式 stretch**：`QVBoxLayout.addWidget(toolbarBar)` + `addWidget(splitter)`（不加 stretch）时，QSplitter 不吃拉伸，**工具栏 QFrame 被拉到整面板高**（skill tab 实测 375px、统计标签 365px 黑底）。修复 `addWidget(splitter, 1)`；会话面板是 `addWidget(tree)`（QTreeWidget 天然 Expanding）所以正常

## 技能面板分组管理 + 批量导出（已实施）
- **技能树勾选框批量导出**：技能行带勾选框（交互与会话表一致——勾选框切换选择、点行显示详情、分组头 tri-state 全选）；`_checked_names()` 收集勾选 → `export_skills_to_zip(names)` 批量导出一个 zip（manifest.skills 数组，兼容 v1 单技能）
- **分组管理**：分组头带图标（`CATEGORY_ICONS`：动效动画 zap/界面设计 palette/设计系统 layers/品牌视觉 star/内容演示 presentation/综合 layout-grid/其他 folder）；「新建」按钮改下拉（新建技能/新建分组，`QPushButton.setMenu`）；分组右键=编辑分组/新增技能/删除分组，技能右键=编辑/删除
- **自定义分组持久化** `skills/.categories.json`：新建的空分组也显示（预置 `SKILL_CATEGORY_LABELS` + 自定义索引）；`rename_category` 同步技能 frontmatter + 索引（uuid 不变）、`delete_category` 把技能移到「其他」+ 清索引
- **NewSkillDialog 支持 `preset_category`**：从分组右键「新增技能」时预选该分组（自定义分组自动加进下拉）
- **分组图标可配置**：`skills/.categories.json` 存 `{"categories": [...], "icons": {分组: 图标key}}`（兼容旧裸列表）；图标 key = Lucide 名（如 'zap'）或 role-icons 文件名（如 'claude-color.svg'）；分组右键「设置图标」→ `GroupIconPicker`（网格显示 assets/icons/ 65 个 Lucide + role-icons/ 17 个 SVG）；`_render_group_icon` 优先配置→CATEGORY_ICONS 默认→folder；重命名分组图标跟随、删除分组清图标

## 双击/箭头交互修复（技能树）
- **无延迟、行为分离**：延迟单机被移除（用户嫌太慢+勾选框/点行延迟不一致）。新模型——**分组勾选框=立即全选**（`_on_item_changed` 对 header 传播到子项）、**分组行单击=立即折叠/展开**（`expandItem/collapseItem`，勾选框点击用 `_changed_at` 守卫跳过）、**分组双击=Qt 默认折叠/展开且不编辑**（`_on_item_double_clicked` 仅技能行才编辑）、技能双击仍编辑
- **分组收起/展开箭头**：`setRootIsDecorated(True)` + 作用域 QSS `QTreeWidget#skillGroupTree::branch:closed:has-children`（**chevron-right**，收起来朝右）/ `:open:has-children`（chevron-down）；着色版 SVG（currentColor→#9a9aa0）给 QSS image 用（QSS 不解析 currentColor 会画黑）
- **「新建」下拉按钮指示器**：`QPushButton#btnNew::menu-indicator` 用 chevron-down-color.svg（与分组箭头风格一致）；QSS url 用 `os.path.join(ASSETS_DIR,...).replace(os.sep,'/')` 拼（QSS 需正斜杠）
- **坑**：`QTreeWidget` 没有 `setItemExpanded`（QTreeView 才有）——折叠/展开用 `expandItem(item)`/`collapseItem(item)`

## 架构/性能审查优化（MVC + 性能 + 复用）
- **MVC 分层确认**：Data（store/manager=模型+仓储）→ Service（业务=控制器）→ View（Qt 控件=视图+编排）。隔离规则：Service 不跨模块 import（已验证 role/session/skill_service 各只依赖本模块 data + infra）；View 可跨模块调 Data/Service（如 skill_panel 用 RoleManager 算引用）
- **`skill_refcounts` 从 skill 数据层移到 view**（skill_panel 的 `_ref_map()` 用 RoleManager）——之前 skill data 直接读 roles/*/meta.json 是跨模块数据依赖，违反"各模块 data 自包含"
- **性能**：
  · `ui_icon` 加 `_UI_ICON_CACHE`（(name,size,color)→QIcon）——树重建/工具栏热路径不再重复渲染 SVG
  · 会话面板 + 技能面板的**搜索框加防抖**（textChanged → `_schedule_rescan/_schedule_reload` 走 debounce），打字不再逐键全量重建
  · `_refs` 在 `_reload` 缓存一次，`_show_detail/_delete_current` 复用（不再每次重算引用）
- **死代码清理**：移除 role/view/dialogs.py 的 RoleService 导入、`_persona_template` 未用 skills_text 参数、cc-role.ps1 未用 $skillsDir、session_panel 未用 session store 导入、以及 11 处未使用导入（AST 扫描 + 人工确认）；theme.trunc 保留（重导出给各 view）
- 审查方法：AST 扫描未使用导入（`import ast` 遍历 ImportFrom/Import + Name 使用集）；pyflakes 不可用

## 「新建」下拉按钮箭头
- **QSS `QPushButton::menu-indicator` 的 chevron 太丑**（小、歪、SVG 渲染怪）——移除 QSS 指示器，改用**按钮文字里的 `▾` 字形**（U+25BE，继承按钮白色，随 Segoe UI 清晰渲染）：`PressButton(' 新建  ▾')`
- **⚠️ `setMenu` 会强制显示 Qt 默认菜单指示器（又一个下箭头）**——出现双箭头。**不要用 setMenu**：改 `clicked.connect(_show_new_menu)` 手动弹菜单（`menu.exec(mapToGlobal(QPoint(0, btn.height())))`），默认指示器自然消失，只剩 ▾
- 注意：GBK 控制台 print 含 ▾ 的字符串会 UnicodeEncodeError——验证用 `'▾' in text` 而非直接打印

## 发布安装包（已构建）
- **产物**：`dist/ClaudeCodeManager-setup.exe`（52MB，PyInstaller 单文件自解压安装器）；`dist/cc-ui/cc-ui.exe`（便携版 app）
- **打包流程**：PyInstaller 打 app exe（`--windowed --icon=icon.ico --add-data "ccui/app/assets;ccui/app/assets"`）→ `scripts/assemble_installer.py` 组装 package（便携 app + 启动器 cc.cmd/cc-role.ps1/roles/skills/settings.json）→ `zip_installer.py` 压成 installer-data.zip（46.5MB）→ `installer_main.py`（解压 + 跑 setup.ps1）PyInstaller `--onefile --add-data "installer-data.zip;."`
- **setup.ps1**：装到 `%LOCALAPPDATA%\ClaudeCodeManager`；生成 settings.json（SessionStart hook 指向安装目录的 track-session.ps1）+ cc-config.json 模板（无密钥）；设 `CLAUDE_CONFIG_DIR`(User) + 安装目录入 PATH；桌面快捷方式（章鱼图标 `IconLocation=<exe>,0`）；**检查 claude，缺则 `npm install -g @anthropic-ai/claude-code`**（node 缺失则提示）
- **可移植化**：cc.cmd 的 `D:\ClaudeCode` 硬编码全改 `%~dp0`（cmd 必须 CRLF 行尾否则语法错）；cc-config-read/cc-provider 用 `$env:CLAUDE_CONFIG_DIR` 兜底；`config.py` 冻结时默认 CONFIG_DIR = exe 目录
- **⚠️ PowerShell 5.1 读无 BOM 的 UTF-8 .ps1 会按 GBK 解析导致中文乱码/语法错**——脚本必须存 UTF-8 BOM（`utf-8-sig`）
- **⚠️ 实测再踩（cc-config-read.ps1）**：无 BOM + 行尾中文注释 → PS5.1 按 GBK 解析注释乱码，**吞掉紧跟的下一行**（`Write-Output "ANTHROPIC_MODEL|$mainModel"` 整行消失）→ 模型环境变量没设 → 实际用了 provider 端默认模型（deepseek-v4-pro 而非配置的 v4-flash）。**根因：Edit/Write 工具默认写无 BOM UTF-8**，编辑含中文的 .ps1 会悄悄丢 BOM。排查：`head -c 3 x.ps1 | od -An -tx1` 看前 3 字节是否 `efbbbf`；修复：二进制方式在前面补 `\xef\xbb\xbf`（别用文本重写，会再丢 BOM）
- **坑**：Inno Setup 静默安装在本环境失败（GUI 安装器被 UAC/headless 拦）、IExpress 挂起——最终用 PyInstaller 自解压方案；测试安装器必须把 `LOCALAPPDATA` 指向临时目录并清理副作用（快捷方式/环境变量）
- **任意 Windows 可安装**：setup.ps1 的 claude 安装分三级——已装 claude → 直接配置；无 claude 有 node → `npm install -g @anthropic-ai/claude-code`；**无 claude 无 node → 自动下载便携版 Node**（nodejs.org/dist/v20.11.1/node-*-win-x64.zip，解压免管理员 + 加 PATH）再 npm 装 claude。便携 Node 已实测（下载 29MB → 解压 → node --version 正常）
- **已知限制**（诚实告知）：仅 64 位 Windows 10/11（exe 是 64 位）；自动安装需联网（下载 Node/npm）；未签名 exe 会触发 SmartScreen（点"仍要运行"）；PATH 改动需新开终端
- **图形安装向导（wizard.ps1）**：WinForms 表单——可选安装目录（默认 %LOCALAPPDATA%\ClaudeCodeManager，可改到非系统盘）、可选 cc-config.json（用户已有 provider 配置，给了就装成 Dest\cc-config.json）、检测已有安装（提示覆盖升级或先卸载）、「卸载旧版」按钮（删快捷方式/环境变量/目录）。`setup.ps1` 加 `-Dest/-ConfigPath` 参数；installer_main.py 跑 wizard.ps1
- **合并升级（覆盖不删数据）**：setup.ps1 **不再 `Remove-Item` 整个目录**——只覆盖应用/启动器脚本，`roles`/`skills` 合并（保留用户自定义），cc-config.json/projects/sessions 等用户数据保留；升级时用户填的密钥不会丢
- **兼容老版 claude**：`cc-config-read.ps1` 同时输出 `ANTHROPIC_API_KEY`（老版用）和 `ANTHROPIC_AUTH_TOKEN`（新版用）——否则老 claude 认不出 provider 配置，回退 api.anthropic.com 报 ERR_BAD_REQUEST；且目标机 cc-config.json 是空模板（安装器不打包密钥），用户必须填真实 apiKey（或从开发机复制 cc-config.json）

## 安装向导二次优化（GUI + 检测）
- **纯图形**：安装器 exe 用 `--windowed`（Windows GUI 子系统，无控制台黑窗）；wizard.ps1 用 WinForms（Segoe UI、标题+副标题、字段全宽、浏览按钮右对齐、按钮右下角标准布局）
- **安装检测修正**：`Test-ExistingInstall` 判定「有 cc-ui.exe」**或**「有 cc.cmd + cc-role.ps1」（启动器式安装也算）——否则识别不出 D:\ClaudeCode 这类用启动器的旧安装；**智能默认路径**：先扫 `%LOCALAPPDATA%\ClaudeCodeManager` 和 `D:\ClaudeCode`，找到已安装的作为默认，并在状态区提示「检测到已有安装（覆盖升级/先卸载）」
- **⚠️ PowerShell `New-Object Type($a * 2, 40)` 会把含 `*` 的表达式误解析（op_Multiply 数组错误）**——所有算术先预计算成变量再传构造器
- **向导参数**：`setup.ps1 -Dest <路径> -ConfigPath <cc-config.json>`；向导表单里用户可选安装目录 + 可选配置文件（给了就装成 Dest\cc-config.json）；出错弹 MessageBox + 写 `~/ccm-install-error.log`
