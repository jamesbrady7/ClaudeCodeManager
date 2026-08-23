// ============================================================
//  cc-sessions.mjs  —  Claude Code 会话管理网页服务器
//  零依赖，仅用 Node 内置模块。启动后仅供本机 (127.0.0.1) 访问。
//
//  用法:
//    node "D:\ClaudeCode\cc-sessions.mjs"     # 或 cc ui
//  环境变量:
//    CLAUDE_CONFIG_DIR   配置目录（默认 D:\ClaudeCode）
//    CC_SESSIONS_PORT    起始端口（默认 18080，忙则 +1 扫描）
//    CC_SESSIONS_NO_OPEN=1   不自动打开浏览器
//
//  注意: 删除会话时会顺带清理按会话命名的残留（subagents/、
//  file-history/<id>/、tasks/<id>/、telemetry），并精确过滤
//  history.jsonl（按 sessionId 字段，而非按行），最后把
//  .claude.json 里指向已删会话的 lastSessionId 置空。
// ============================================================

import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import child_process from 'node:child_process';

const CONFIG_DIR  = process.env.CLAUDE_CONFIG_DIR || 'D:\\ClaudeCode';
const PROJECTS    = path.join(CONFIG_DIR, 'projects');
const SESSIONS    = path.join(CONFIG_DIR, 'sessions');      // 运行中进程的元数据
const HISTORY     = path.join(CONFIG_DIR, 'history.jsonl'); // prompt 历史
const CLAUDE_JSON = path.join(CONFIG_DIR, '.claude.json');  // 全局状态
const UI_FILE     = path.join(CONFIG_DIR, 'cc-sessions-ui.html');

const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// ---- 角色系统 ----
const ROLES = path.join(CONFIG_DIR, 'roles');
const ROLE_NAME_RE = /^[a-zA-Z0-9_-]+$/;
const ROLE_RESERVED = ['new', 'list', 'ls', 'help', 'rm', 'roles', 'role'];

// ------------------------------------------------------------
// 小工具
// ------------------------------------------------------------

async function exists(p) {
  try { await fs.access(p); return true; } catch { return false; }
}

async function sizeRecursive(p) {
  try {
    const st = await fs.stat(p);
    if (!st.isDirectory()) return st.size;
    let total = 0;
    for (const e of await fs.readdir(p)) total += await sizeRecursive(path.join(p, e));
    return total;
  } catch { return 0; }
}

// 把 glob 里的 * 转成正则，只匹配一层目录下的文件
async function globIn(dir, pattern) {
  const re = new RegExp('^' + pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*') + '$');
  try {
    const entries = await fs.readdir(dir);
    return entries.filter(e => re.test(e)).map(e => path.join(dir, e));
  } catch { return []; }
}

// ------------------------------------------------------------
// 项目目录名 <-> 真实路径
//   磁盘目录名 = 真实路径去掉盘符冒号/斜杠/非 ASCII 后变成的串，
//   编码是有损的（中文/空格会变成 -），所以解码必须靠
//   .claude.json 的 projects 键反向映射；cwd 兜底；再不行做
//   尽力解码（只对纯 ASCII 路径有效）。
// ------------------------------------------------------------

const munge = p => p.replace(/[\\/:]/g, '-').replace(/[^A-Za-z0-9_-]/g, '-');

function bestEffortDecode(enc) {
  const parts = enc.split('-');
  if (parts.length >= 2) return parts[0] + ':' + parts.slice(1).join('/');
  return enc;
}

async function buildReverseMap() {
  const m = new Map();
  try {
    const cfg = JSON.parse(await fs.readFile(CLAUDE_JSON, 'utf8'));
    for (const real of Object.keys(cfg.projects || {})) m.set(munge(real), real);
  } catch { /* .claude.json 缺失/损坏时忽略，走兜底 */ }
  return m;
}

// ------------------------------------------------------------
// 运行中会话：sessions\<pid>.json 里有 sessionId + pid，
// 用 process.kill(pid, 0) 探测该进程是否真的还活着。
// ------------------------------------------------------------

async function liveIds() {
  const set = new Set();
  for (const v of (await liveSessionMap()).values()) set.add(v.id);
  return set;
}

// 返回运行中会话的详情 Map: id -> { id, cwd, startedAt, pid }
async function liveSessionMap() {
  const map = new Map();
  try {
    for (const f of await fs.readdir(SESSIONS)) {
      if (!f.endsWith('.json')) continue;
      try {
        const o = JSON.parse(await fs.readFile(path.join(SESSIONS, f), 'utf8'));
        let alive = true;
        try { process.kill(o.pid, 0); } catch { alive = false; }
        if (alive && o.sessionId && ID_RE.test(o.sessionId)) {
          map.set(o.sessionId, { id: o.sessionId, cwd: o.cwd || '', startedAt: o.startedAt || 0, pid: o.pid });
        }
      } catch { /* 跳过损坏的元数据 */ }
    }
  } catch { /* sessions 目录不存在 */ }
  return map;
}

// ------------------------------------------------------------
// history.jsonl 不是严格的一行一个 JSON：出现过两个对象连在
// 一起、中间没有换行的情况。按"行内含 sid 就删整行"会把邻居
// 的条目一起误删。这里改成逐字符跟踪引号/转义/花括号深度，
// 把粘连对象拆开，再按 sessionId 字段精确过滤。
// ------------------------------------------------------------

function splitJsonStream(text) {
  const out = [];
  let depth = 0, inStr = false, esc = false, start = -1;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      if (esc) esc = false;
      else if (ch === '\\') esc = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') { inStr = true; continue; }
    if (ch === '{') { if (depth === 0) start = i; depth++; }
    else if (ch === '}') {
      depth--;
      if (depth === 0) {
        const seg = text.slice(start, i + 1);
        let obj = null;
        try { obj = JSON.parse(seg); } catch { /* 保留原始段 */ }
        out.push({ start, end: i + 1, ok: !!obj, obj });
      }
    }
  }
  return out;
}

async function cleanHistory(deleted) {
  if (!deleted.size) return;
  try {
    const raw = await fs.readFile(HISTORY, 'utf8');
    const segs = splitJsonStream(raw);
    // 只有真正过滤掉条目时才写盘，避免每次删除都无谓地重写这个
    // 由 Claude Code 自己维护的文件（拆粘连行/规整换行等）。
    const removed = segs.some(t => t.ok && t.obj && t.obj.sessionId && deleted.has(t.obj.sessionId));
    if (!removed) return;
    const kept = segs
      .filter(t => !(t.ok && t.obj && t.obj.sessionId && deleted.has(t.obj.sessionId)))
      .map(t => (t.ok ? JSON.stringify(t.obj) : raw.slice(t.start, t.end)));
    const eol = raw.includes('\r\n') ? '\r\n' : '\n';
    await fs.writeFile(HISTORY, kept.join(eol) + (kept.length ? eol : ''), 'utf8');
  } catch (e) {
    console.warn('[cc-sessions] 警告: history.jsonl 清理失败:', e.message);
  }
}

async function cleanClaudeJson(deleted) {
  try {
    const raw = await fs.readFile(CLAUDE_JSON, 'utf8');
    const cfg = JSON.parse(raw);
    let changed = false;
    if (cfg.projects) {
      for (const k of Object.keys(cfg.projects)) {
        const p = cfg.projects[k];
        if (p && p.lastSessionId && deleted.has(p.lastSessionId)) { p.lastSessionId = null; changed = true; }
      }
    }
    if (changed) {
      const eol = raw.includes('\r\n') ? '\r\n' : '\n';
      await fs.writeFile(CLAUDE_JSON, JSON.stringify(cfg, null, 2) + eol, 'utf8');
    }
  } catch (e) {
    console.warn('[cc-sessions] 警告: .claude.json 更新失败:', e.message);
  }
}

// ------------------------------------------------------------
// 会话定位与删除
// ------------------------------------------------------------

// 在 projects 下按 id 找主 .jsonl，返回所有匹配（理论上一个 id 只在一个项目下）
async function locateSession(id) {
  const found = [];
  const root = path.resolve(PROJECTS);
  try { var projDirs = await fs.readdir(root); } catch { return found; }
  for (const dir of projDirs) {
    if (dir === 'memory') continue;
    const full = path.join(root, dir);
    let st;
    try { st = await fs.stat(full); } catch { continue; }
    if (!st.isDirectory()) continue;
    const jsonl = path.join(full, id + '.jsonl');
    let jst;
    try { jst = await fs.stat(jsonl); } catch { continue; }
    if (!jst.isFile()) continue;
    // 防越界：确认最终路径仍在 projects 根下
    if (!path.resolve(jsonl).toLowerCase().startsWith(root.toLowerCase() + path.sep)) continue;
    found.push({ projDir: dir, jsonlPath: jsonl, size: jst.size });
  }
  return found;
}

// 删一个会话：主 .jsonl + 同名子目录（subagents）+ file-history/tasks/telemetry
async function deleteOne(id) {
  const found = await locateSession(id);
  if (!found.length) return { ok: false, reason: 'not-found', errors: [] };

  const targets = [];
  let freed = 0;
  for (const f of found) {
    targets.push(f.jsonlPath);
    freed += f.size;
    const subdir = f.jsonlPath.slice(0, -'.jsonl'.length); // 去掉扩展名即 <proj>\<id>
    if (await exists(subdir)) { targets.push(subdir); freed += await sizeRecursive(subdir); }
  }
  const fh = path.join(CONFIG_DIR, 'file-history', id);
  if (await exists(fh)) { targets.push(fh); freed += await sizeRecursive(fh); }
  const tk = path.join(CONFIG_DIR, 'tasks', id);
  if (await exists(tk)) { targets.push(tk); freed += await sizeRecursive(tk); }
  for (const t of await globIn(path.join(CONFIG_DIR, 'telemetry'), `1p_failed_events.${id}.*.json`)) {
    targets.push(t);
    freed += await sizeRecursive(t);
  }

  const errors = [];
  for (const t of targets) {
    try {
      const s = await fs.stat(t);
      if (s.isDirectory()) await fs.rm(t, { recursive: true, force: true });
      else await fs.unlink(t);
    } catch (e) {
      errors.push({ target: t, message: e.message });
    }
  }
  return { ok: true, freed, errors };
}

async function deleteMany(ids) {
  ids = [...new Set(ids.filter(x => typeof x === 'string'))];
  const live = await liveIds();
  const deleted = [];
  const errors = [];
  let totalFreed = 0;

  for (const id of ids) {
    if (!ID_RE.test(id)) { errors.push({ id, reason: 'invalid-id' }); continue; }
    if (live.has(id)) { errors.push({ id, reason: 'live' }); continue; }
    const res = await deleteOne(id);
    if (res.ok) { deleted.push(id); totalFreed += res.freed; }
    else { errors.push({ id, reason: res.reason }); }
    for (const e of res.errors) errors.push({ id, reason: 'file', target: e.target, message: e.message });
  }

  const deletedSet = new Set(deleted);
  await cleanHistory(deletedSet);
  await cleanClaudeJson(deletedSet);
  return { deleted, errors, totalFreed };
}

// ------------------------------------------------------------
// 会话扫描与汇总
// ------------------------------------------------------------

async function summarize(jsonlPath, id, projDir, reverseMap) {
  const raw = await fs.readFile(jsonlPath, 'utf8');
  let title = '', lastTime = '', firstTime = '', cwd = '';
  let userCount = 0, assistantCount = 0;
  const models = new Set();

  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; }
    if (!o || typeof o !== 'object') continue;
    if (o.timestamp) {
      if (!firstTime || o.timestamp < firstTime) firstTime = o.timestamp;
      if (o.timestamp > lastTime) lastTime = o.timestamp;
    }

    if (o.type === 'user') {
      userCount++;
      if (!title && o.message) {
        const c = o.message.content;
        if (typeof c === 'string') title = c;
        else if (Array.isArray(c)) {
          for (const blk of c) {
            if (blk && blk.type === 'text' && blk.text) { title = blk.text; break; }
          }
        }
      }
      if (!cwd && o.cwd) cwd = o.cwd;
    } else if (o.type === 'assistant') {
      assistantCount++;
      if (o.message && o.message.model) models.add(o.message.model);
    }
  }

  if (!lastTime) lastTime = new Date((await fs.stat(jsonlPath)).mtimeMs).toISOString();

  return {
    id,
    project: projDir,
    projectPath: reverseMap.get(projDir) || cwd || bestEffortDecode(projDir),
    title: title || '',
    firstTime,
    lastTime,
    userCount,
    assistantCount,
    models: [...models],
    isEmpty: assistantCount === 0,          // 没有任何回复 = 半途而废的测试残留
  };
}

async function scanSessions() {
  const live = await liveIds();
  const reverseMap = await buildReverseMap();
  const sessions = [];
  let totalSize = 0, liveCount = 0;

  let projDirs;
  try { projDirs = await fs.readdir(PROJECTS); } catch { projDirs = []; }
  for (const dir of projDirs) {
    if (dir === 'memory') continue;
    if (!/^[A-Za-z0-9_-]+$/.test(dir)) continue;
    const full = path.join(PROJECTS, dir);
    let st;
    try { st = await fs.stat(full); } catch { continue; }
    if (!st.isDirectory()) continue;

    let files;
    try { files = await fs.readdir(full); } catch { continue; }
    for (const f of files) {
      if (!f.endsWith('.jsonl')) continue;
      const id = f.slice(0, -'.jsonl'.length);
      if (!ID_RE.test(id)) continue;
      const jsonlPath = path.join(full, f);
      let fstat;
      try { fstat = await fs.stat(jsonlPath); } catch { continue; }
      if (!fstat.isFile()) continue;

      const info = await summarize(jsonlPath, id, dir, reverseMap);
      info.sizeBytes = fstat.size;
      info.isLive = live.has(id);
      if (info.isLive) liveCount++;
      totalSize += info.sizeBytes;
      sessions.push(info);
    }
  }

  // 服务器追踪的已启动会话（UI 创建、等待首次输入）占位
  mergeSpawnedPlaceholders(sessions);

  sessions.sort((a, b) => (b.lastTime || '').localeCompare(a.lastTime || ''));
  return { sessions, totals: { count: sessions.length, sizeBytes: totalSize, liveCount } };
}

// 详情预览：最后 ~20 条 user/assistant 文本块
async function sessionDetails(id) {
  const found = await locateSession(id);
  if (!found.length) return null;
  const raw = await fs.readFile(found[0].jsonlPath, 'utf8');
  const blocks = [];
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; }
    if (o.type !== 'user' && o.type !== 'assistant') continue;
    const c = o.message && o.message.content;
    let text = '';
    if (typeof c === 'string') text = c;
    else if (Array.isArray(c)) {
      for (const blk of c) {
        if (blk && blk.type === 'text' && blk.text) { text = blk.text; break; }
      }
    }
    if (!text) continue;
    blocks.push({
      role: o.type === 'user' ? 'user' : 'assistant',
      text,
      timestamp: o.timestamp || '',
      model: o.type === 'assistant' ? (o.message && o.message.model) || '' : '',
    });
  }
  return { id, blocks: blocks.slice(-20) };
}

// 在新终端里恢复会话（走 cc.cmd 的 :resume，自动读供应商配置）
function resumeSession(id) {
  const child = child_process.spawn(
    'cmd.exe', ['/c', 'start', '', 'cmd', '/k', `cc resume ${id}`],
    { cwd: CONFIG_DIR, detached: true, stdio: 'ignore', windowsHide: false }
  );
  child.unref();
}

// ------------------------------------------------------------
// 角色系统
// ------------------------------------------------------------

function validRoleName(name) {
  return typeof name === 'string' && ROLE_NAME_RE.test(name) && !ROLE_RESERVED.includes(name);
}

function roleDirOf(name) {
  const dir = path.resolve(ROLES, name);
  const root = path.resolve(ROLES);
  if (!dir.toLowerCase().startsWith(root.toLowerCase() + path.sep)) return null;
  return dir;
}

async function readRoleMeta(name) {
  try {
    return JSON.parse(await fs.readFile(path.join(ROLES, name, 'meta.json'), 'utf8'));
  } catch { return null; }
}

const personaTemplate = (name, desc) => `# 角色：${name}

${desc}

你是 ${name}，一个拥有长期记忆的资深专家。你的知识库文件是：
D:\\ClaudeCode\\roles\\${name}\\knowledge.md

## 会话开始
每次会话开始时，第一步用 Read 阅读知识库 D:\\ClaudeCode\\roles\\${name}\\knowledge.md。
若存在 D:\\ClaudeCode\\roles\\${name}\\inherit.md，一并阅读它（那是本次继承的要点）。
不要复述知识库内容，直接运用。

## 自动学习（重要）
学到**重要且可复用**的知识时，立即用 Write 或 Edit 写回知识库。
判断标准：下次遇到同类问题还会用到的才算重要，包括：
- 关键结论与决策（以及原因）
- 项目/代码的约定与结构
- 常用 API、命令、配置项用法
- 踩过的坑与规避方法
- 可复用的模式与流程

## 知识库格式
- 用「## 主题」分节，每节 3-6 行精炼要点，中文书写
- 主题已存在则用 Edit 更新，不新建重复小节
- 删除/精简过时内容
- 不记录：临时过程、无关闲聊、大段代码全文

## 会话结束
会话末尾回顾本次工作，如有值得沉淀的知识，先更新知识库再结束。

现在，请先 Read 知识库文件，然后等待任务。
`;

const knowledgeTemplate = (name) => `# 知识库：${name}

> 本文件是本角色的长期记忆，随会话自动积累。
> 由角色在会话中学到重要知识后用 Write/Edit 维护。

## 维护规范
- 用「## 主题」分节，每节 3-6 行精炼要点，中文书写
- 同主题用 Edit 更新，不新建重复小节；删除/精简过时内容
- 记录：关键结论、约定、API、命令、坑、可复用模式
- 不记录：过程、闲聊、大段代码全文
- 知识库应保持精炼；若超过约 30KB / 600 行，请主动合并精简

## 开始
（此处随会话积累）
`;

async function listRoles() {
  const sessionMap = new Map();
  try {
    const { sessions } = await scanSessions();
    for (const s of sessions) sessionMap.set(s.id, s);
  } catch { /* 会话扫描失败不阻断角色列表 */ }

  const roles = [];
  let dirs;
  try { dirs = await fs.readdir(ROLES); } catch { return roles; }
  for (const d of dirs) {
    if (!ROLE_NAME_RE.test(d)) continue;
    const dir = path.join(ROLES, d);
    let st;
    try { st = await fs.stat(dir); } catch { continue; }
    if (!st.isDirectory()) continue;
    const meta = await readRoleMeta(d);

    const kPath = path.join(dir, 'knowledge.md');
    let knowledgeSize = 0, knowledgeExists = false;
    try { const ks = await fs.stat(kPath); knowledgeSize = ks.size; knowledgeExists = true; } catch { /* 无知识库 */ }

    const sPath = path.join(dir, 'sessions.jsonl');
    let sessionCount = 0, lastSessionTime = '', lastSessionTitle = '';
    if (await exists(sPath)) {
      const lines = (await fs.readFile(sPath, 'utf8')).split(/\r?\n/).filter(l => l.trim());
      sessionCount = lines.length;
      for (const line of lines) {
        try {
          const o = JSON.parse(line);
          if (!o.session_id) continue;
          const ref = sessionMap.get(o.session_id);
          const t = ref ? ref.lastTime : (o.timestamp || '');
          if (t > lastSessionTime) {
            lastSessionTime = t;
            lastSessionTitle = ref ? ref.title : '';
          }
        } catch { /* 跳过坏行 */ }
      }
    }

    roles.push({
      name: d,
      description: (meta && meta.description) || '',
      created: (meta && meta.created) || '',
      knowledgeSize, knowledgeExists, sessionCount,
      lastSessionTime, lastSessionTitle,
    });
  }
  return roles;
}

async function roleDetail(name) {
  const dir = roleDirOf(name);
  if (!dir || !(await exists(dir))) return null;
  const meta = await readRoleMeta(name);
  const kPath = path.join(dir, 'knowledge.md');
  let knowledge = '', knowledgeSize = 0;
  if (await exists(kPath)) {
    knowledge = await fs.readFile(kPath, 'utf8');
    knowledgeSize = knowledge.length;
  }
  const sessionMap = new Map();
  try {
    const { sessions } = await scanSessions();
    for (const s of sessions) sessionMap.set(s.id, s);
  } catch { /* ignore */ }
  const tracked = [];
  const sPath = path.join(dir, 'sessions.jsonl');
  if (await exists(sPath)) {
    for (const line of (await fs.readFile(sPath, 'utf8')).split(/\r?\n/)) {
      if (!line.trim()) continue;
      try {
        const o = JSON.parse(line);
        const id = o.session_id;
        const ref = sessionMap.get(id);
        tracked.push({
          id,
          trackedTime: o.timestamp || '',
          cwd: o.cwd || '',
          exists: !!ref,
          title: ref ? ref.title : '',
          lastTime: ref ? ref.lastTime : '',
          userCount: ref ? ref.userCount : 0,
          assistantCount: ref ? ref.assistantCount : 0,
        });
      } catch { /* 跳过坏行 */ }
    }
  }
  return { name, meta, knowledge, knowledgeSize, sessions: tracked };
}

async function createRole({ name, description }) {
  if (!validRoleName(name)) return { ok: false, error: 'invalid-name' };
  const dir = path.join(ROLES, name);
  if (await exists(dir)) return { ok: false, error: 'exists' };
  await fs.mkdir(dir, { recursive: true });
  const desc = description && String(description).trim() ? String(description).trim() : `角色 ${name}`;
  await fs.writeFile(path.join(dir, 'meta.json'), JSON.stringify({ name, description: desc, created: new Date().toISOString() }, null, 2), 'utf8');
  await fs.writeFile(path.join(dir, 'persona.md'), personaTemplate(name, desc), 'utf8');
  await fs.writeFile(path.join(dir, 'knowledge.md'), knowledgeTemplate(name), 'utf8');
  return { ok: true };
}

async function writeKnowledge(name, content) {
  const dir = roleDirOf(name);
  if (!dir || !(await exists(dir))) return { ok: false, error: 'not-found' };
  if (typeof content !== 'string') return { ok: false, error: 'bad-content' };
  await fs.writeFile(path.join(dir, 'knowledge.md'), content, 'utf8');
  return { ok: true };
}

async function pruneRole(name) {
  const dir = roleDirOf(name);
  if (!dir || !(await exists(dir))) return { ok: false, error: 'not-found' };
  const sPath = path.join(dir, 'sessions.jsonl');
  if (!(await exists(sPath))) return { ok: true, removed: [] };
  const removed = [];
  const kept = [];
  for (const line of (await fs.readFile(sPath, 'utf8')).split(/\r?\n/)) {
    if (!line.trim()) { kept.push(line); continue; }
    try {
      const o = JSON.parse(line);
      const found = await locateSession(o.session_id);
      if (found.length) kept.push(line);
      else removed.push(o.session_id);
    } catch { kept.push(line); }
  }
  await fs.writeFile(sPath, kept.join('\r\n') + (kept.length ? '\r\n' : ''), 'utf8');
  return { ok: true, removed };
}

function spawnRole(name, fromIds) {
  const inherit = (fromIds && fromIds.length) ? ` --from ${fromIds.join(',')}` : '';
  const child = child_process.spawn(
    'cmd.exe', ['/c', 'start', '', 'cmd', '/k', `cc role ${name}${inherit}`],
    { cwd: CONFIG_DIR, detached: true, stdio: 'ignore', windowsHide: false }
  );
  child.unref();
}

// ------------------------------------------------------------
// 命令中心（终端命令的 UI 化）
// ------------------------------------------------------------

const CONFIG_FILE = path.join(CONFIG_DIR, 'cc-config.json');

async function listProviders() {
  try {
    const cfg = JSON.parse(await fs.readFile(CONFIG_FILE, 'utf8'));
    const pc = cfg['provider config'];
    if (!pc) return { current: null, providers: [] };
    const current = pc['current provider'];
    const providers = Object.keys(pc)
      .filter(k => k !== 'current provider')
      .map(n => ({
        name: n,
        model: pc[n].model,
        baseUrl: pc[n].baseUrl,
        fastModel: pc[n].fastModel || null,
      }));
    return { current, providers };
  } catch {
    return { current: null, providers: [] };
  }
}

async function switchProvider(name) {
  try {
    const raw = await fs.readFile(CONFIG_FILE, 'utf8');
    const cfg = JSON.parse(raw);
    const pc = cfg['provider config'];
    if (!pc || name === 'current provider' || typeof pc[name] !== 'object') return { ok: false, error: 'not-found' };
    const newRaw = raw.replace(/("current provider"\s*:\s*)"[^"]*"/, `$1"${name}"`);
    JSON.parse(newRaw); // 校验
    await fs.writeFile(CONFIG_FILE, newRaw, 'utf8');
    return { ok: true, current: name };
  } catch (e) {
    return { ok: false, error: 'failed' };
  }
}

function spawnTerminal(command, cwd) {
  const child = child_process.spawn('cmd.exe', ['/k', command], {
    cwd: cwd || CONFIG_DIR, detached: true, stdio: 'ignore', windowsHide: false,
  });
  child.unref();
  return child.pid;
}

function spawnSession(mode, cwd) {
  return spawnTerminal(mode === 'danger' ? 'cc danger' : 'cc', cwd);
}

function spawnAsk(prompt) {
  // 去除 shell 元字符，防止从 cmd /k 逃逸
  const clean = String(prompt).replace(/["&|<>^%\r\n]/g, ' ').trim();
  spawnTerminal(`cc -p "${clean}"`);
}

async function listDir(target) {
  const abs = path.resolve(target || '');
  try {
    const st = await fs.stat(abs);
    if (!st.isDirectory()) return { ok: false, error: 'not-dir' };
    const entries = await fs.readdir(abs);
    const dirs = [];
    for (const e of entries) {
      try {
        const es = await fs.stat(path.join(abs, e));
        if (es.isDirectory()) dirs.push(e);
      } catch { /* 跳过不可读项 */ }
    }
    dirs.sort((a, b) => a.localeCompare(b));
    return { ok: true, path: abs, parent: path.dirname(abs), dirs };
  } catch {
    return { ok: false, error: 'invalid' };
  }
}

function runBackup() {
  return new Promise((resolve) => {
    child_process.exec(
      'powershell -NoProfile -ExecutionPolicy Bypass -File "D:\\ClaudeCode\\cc-backup.ps1"',
      { cwd: CONFIG_DIR, encoding: 'utf8', timeout: 60000 },
      (err, stdout, stderr) => resolve({ ok: !err, output: String(stdout || '').trim() + (stderr ? '\n' + String(stderr).trim() : '') })
    );
  });
}

// ------------------------------------------------------------
// 已启动会话追踪（UI 创建、等待首次输入的会话占位）
//   claude 交互式会话在首条消息前不写 transcript，无法靠扫描
//   projects/ 发现。服务器记录它启动过的会话，显示"等待首次输入"
//   占位；一旦该目录出现首条消息时间晚于启动时间的真实会话
//   （用户输入了），占位即被真实会话取代。
// ------------------------------------------------------------

const spawnedSessions = [];
const SPAWNED_TTL = 2 * 60 * 60 * 1000; // 占位最长保留 2 小时

function normPath(p) {
  return String(p).replace(/[\\/]+/g, '/').replace(/\/+$/, '');
}

function mergeSpawnedPlaceholders(sessions) {
  const now = Date.now();
  const kept = [];
  for (const e of spawnedSessions) {
    // 终端已关闭（cmd 进程不存在）→ 占位移除，避免"已关闭还显示运行中"
    // 宽限 30 秒：刚创建时不做存活检测，确保占位必显示
    if (e.pid && (now - e.startedAt > 30000)) {
      let alive = true;
      try { process.kill(e.pid, 0); } catch { alive = false; }
      if (!alive) continue;
    }
    if (now - e.startedAt > SPAWNED_TTL) continue;
    // 该 cwd 下已有首条消息时间 ≥ 启动时间的真实会话 → 用户已输入，占位让位
    const becameReal = sessions.some(s =>
      !s.isSpawned && s.firstTime && e.cwd &&
      normPath(s.projectPath) === normPath(e.cwd) &&
      new Date(s.firstTime).getTime() >= e.startedAt - 5000
    );
    if (becameReal) continue;
    kept.push(e);
  }
  spawnedSessions.length = 0;
  spawnedSessions.push(...kept);

  for (const e of kept) {
    sessions.push({
      id: 'spawn-' + e.startedAt,
      project: 'spawned',
      projectPath: e.cwd.replace(/\\/g, '/'),
      title: '',
      firstTime: new Date(e.startedAt).toISOString(),
      lastTime: new Date(e.startedAt).toISOString(),
      userCount: 0, assistantCount: 0, models: [], sizeBytes: 0,
      isEmpty: true, isLive: true, isSpawned: true,
    });
  }
}

// ------------------------------------------------------------
// HTTP 服务
// ------------------------------------------------------------

function sendJson(res, code, obj) {
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',   // 防止浏览器缓存导致列表/状态不更新
  });
  res.end(JSON.stringify(obj));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', c => {
      data += c;
      if (data.length > 1024 * 1024) { req.destroy(); reject(new Error('body too large')); }
    });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

async function serveStatic(res) {
  try {
    const html = await fs.readFile(UI_FILE, 'utf8');
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(html);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('cc-sessions-ui.html 不存在于 ' + CONFIG_DIR);
  }
}

const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, 'http://127.0.0.1');
    const p = u.pathname;

    if (req.method === 'GET' && p === '/') return serveStatic(res);
    if (req.method === 'GET' && p === '/favicon.ico') { res.writeHead(204); return res.end(); }
    if (req.method === 'GET' && p === '/api/sessions') return sendJson(res, 200, await scanSessions());

    if (req.method === 'GET') {
      const m = p.match(/^\/api\/session\/([0-9a-f-]+)$/);
      if (m) {
        const d = await sessionDetails(m[1]);
        if (!d) return sendJson(res, 404, { error: 'not-found' });
        return sendJson(res, 200, d);
      }
    }

    if (req.method === 'POST') {
      const mr = p.match(/^\/api\/session\/([0-9a-f-]+)\/resume$/);
      if (mr) {
        const id = mr[1];
        if (!ID_RE.test(id)) return sendJson(res, 400, { error: 'invalid-id' });
        const found = await locateSession(id);
        if (!found.length) return sendJson(res, 404, { error: 'not-found' });
        if ((await liveIds()).has(id)) return sendJson(res, 409, { error: 'live' });
        resumeSession(id);
        return sendJson(res, 200, { ok: true });
      }
      if (p === '/api/sessions/delete') {
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        const ids = Array.isArray(payload.ids) ? payload.ids : [];
        return sendJson(res, 200, await deleteMany(ids));
      }

      // ---- 角色系统 ----
      if (p === '/api/roles') {
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        const r = await createRole({ name: payload.name, description: payload.description });
        return sendJson(res, r.ok ? 200 : 400, r);
      }

      const mStart = p.match(/^\/api\/roles\/([a-zA-Z0-9_-]+)\/start-with$/);
      if (mStart) {
        if (!validRoleName(mStart[1])) return sendJson(res, 400, { error: 'invalid-name' });
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        const ids = Array.isArray(payload.ids) ? payload.ids.filter(x => typeof x === 'string' && ID_RE.test(x)) : [];
        spawnRole(mStart[1], ids);
        return sendJson(res, 200, { ok: true });
      }

      const mStart2 = p.match(/^\/api\/roles\/([a-zA-Z0-9_-]+)\/start$/);
      if (mStart2) {
        if (!validRoleName(mStart2[1])) return sendJson(res, 400, { error: 'invalid-name' });
        spawnRole(mStart2[1], []);
        return sendJson(res, 200, { ok: true });
      }

      const mPrune = p.match(/^\/api\/roles\/([a-zA-Z0-9_-]+)\/prune$/);
      if (mPrune) {
        if (!validRoleName(mPrune[1])) return sendJson(res, 400, { error: 'invalid-name' });
        return sendJson(res, 200, await pruneRole(mPrune[1]));
      }

    }

    if (req.method === 'PUT') {
      const mKnowledge = p.match(/^\/api\/roles\/([a-zA-Z0-9_-]+)\/knowledge$/);
      if (mKnowledge) {
        if (!validRoleName(mKnowledge[1])) return sendJson(res, 400, { error: 'invalid-name' });
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        return sendJson(res, 200, await writeKnowledge(mKnowledge[1], payload.content));
      }
    }

    if (req.method === 'GET') {
      const mRoleDetail = p.match(/^\/api\/roles\/([a-zA-Z0-9_-]+)$/);
      if (mRoleDetail) {
        if (!validRoleName(mRoleDetail[1])) return sendJson(res, 400, { error: 'invalid-name' });
        const d = await roleDetail(mRoleDetail[1]);
        if (!d) return sendJson(res, 404, { error: 'not-found' });
        return sendJson(res, 200, d);
      }
    }

    if (req.method === 'GET' && p === '/api/roles') {
      return sendJson(res, 200, { roles: await listRoles() });
    }

    // ---- 命令中心 ----
    if (req.method === 'GET' && p === '/api/providers') {
      return sendJson(res, 200, await listProviders());
    }

    if (req.method === 'GET' && p === '/api/fs/list') {
      return sendJson(res, 200, await listDir(u.searchParams.get('path') || ''));
    }

    if (req.method === 'POST') {
      if (p === '/api/providers/switch') {
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        const r = await switchProvider(payload.name);
        return sendJson(res, r.ok ? 200 : 400, r);
      }
      if (p === '/api/session/start') {
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        let cwd = '';
        if (payload.cwd && String(payload.cwd).trim()) {
          cwd = path.resolve(String(payload.cwd).trim());
          try {
            if (!(await fs.stat(cwd)).isDirectory()) return sendJson(res, 400, { error: 'invalid-cwd' });
          } catch { return sendJson(res, 400, { error: 'invalid-cwd' }); }
        }
        const pid = spawnSession(payload.mode === 'danger' ? 'danger' : 'normal', cwd);
        spawnedSessions.push({ cwd: cwd || CONFIG_DIR, startedAt: Date.now(), pid });
        return sendJson(res, 200, { ok: true, cwd });
      }
      if (p === '/api/session/ask') {
        let payload;
        try { payload = JSON.parse((await readBody(req)) || '{}'); } catch { return sendJson(res, 400, { error: 'bad-json' }); }
        if (!payload.prompt || !String(payload.prompt).trim()) return sendJson(res, 400, { error: 'empty-prompt' });
        spawnAsk(payload.prompt);
        return sendJson(res, 200, { ok: true });
      }
      if (p === '/api/backup') {
        return sendJson(res, 200, await runBackup());
      }
    }

    return sendJson(res, 404, { error: 'not-found' });
  } catch (e) {
    console.error('[cc-sessions] 错误:', e);
    try { sendJson(res, 500, { error: 'internal' }); } catch { /* 响应已发出 */ }
  }
});

async function startServer() {
  const portStart = Number(process.env.CC_SESSIONS_PORT) || 18080;
  for (let port = portStart; port <= portStart + 10; port++) {
    try {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, '127.0.0.1', () => {
          server.removeListener('error', reject);
          resolve(port);
        });
      });
      return port;
    } catch (e) {
      if (e.code !== 'EADDRINUSE') throw e;
    }
  }
  throw new Error(`端口 ${portStart}..${portStart + 10} 都被占用，请设置 CC_SESSIONS_PORT`);
}

const port = await startServer();
const url = `http://127.0.0.1:${port}/`;
console.log('[cc-sessions] 会话管理已启动: ' + url);
console.log('[cc-sessions] 按 Ctrl+C 停止');

if (process.env.CC_SESSIONS_NO_OPEN !== '1') {
  child_process.spawn('cmd.exe', ['/c', 'start', '', url], { detached: true, stdio: 'ignore' }).unref();
}

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => server.close(() => process.exit(0)));
}
