"""会话数据访问（会话模块 data 层）：扫描 / 存活 / 删除 / 清理 / 权限推断。

无 Qt、无 service 依赖。产出 Session / SpawnedSession 数据模型。
"""
import os
import re
import json
import time
import shutil
import fnmatch
import zipfile
import datetime
from dataclasses import replace

import psutil

from ccui.infra.config import CONFIG_DIR, PROJECTS, SESSIONS_DIR, HISTORY, CLAUDE_JSON, log
from ccui.infra.utils import munge, norm_path, best_effort_decode, iso_to_ms, ms_to_iso, text_content
from ccui.infra.archive import make_zip, zip_read_manifest
from ccui.session.data.models import Session
from ccui.session.data.provider import record_session_provider

ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
PROJ_DIR_RE = re.compile(r'^[A-Za-z0-9_-]+$')

SPAWNED_TTL_MS = 2 * 60 * 60 * 1000      # 占位最长保留 2 小时
SPAWNED_GRACE_MS = 2_000                 # 刚创建 2 秒内不做存活检测（保证占位必显示）
BECAME_REAL_SLACK = 5_000                # firstTime >= startedAt - 5s 视为转正


# ------------------------------------------------------------
# 路径 / 解析
# ------------------------------------------------------------

_revmap_cache = {'key': None, 'map': {}}


def build_reverse_map():
    """项目目录名 → 真实路径。.claude.json 未变时走缓存，避免每次 scan 全读。"""
    try:
        st = os.stat(CLAUDE_JSON)
        key = (st.st_mtime, st.st_size)
    except Exception:
        return {}
    if _revmap_cache.get('key') == key:
        return _revmap_cache['map']
    m = {}
    try:
        with open(CLAUDE_JSON, 'r', encoding='utf-8-sig') as f:
            cfg = json.load(f)
        for real in (cfg.get('projects') or {}).keys():
            m[munge(real)] = real
    except Exception:
        pass
    _revmap_cache['key'] = key
    _revmap_cache['map'] = m
    return m


def size_recursive(p):
    try:
        if os.path.isfile(p):
            return os.path.getsize(p)
        total = 0
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        return total
    except Exception:
        return 0


def glob_in_dir(d, pattern):
    try:
        return [os.path.join(d, e) for e in os.listdir(d) if fnmatch.fnmatch(e, pattern)]
    except Exception:
        return []


# ------------------------------------------------------------
# history.jsonl / .claude.json 清理
# ------------------------------------------------------------

def split_json_stream(text):
    """history.jsonl 流式 JSON 切分：处理"两个对象粘连在同一行"，避免按行误删邻居。"""
    out = []
    depth = 0
    in_str = False
    esc = False
    start = -1
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                seg = text[start:i + 1]
                obj = None
                try:
                    obj = json.loads(seg)
                except Exception:
                    pass
                out.append({'start': start, 'end': i + 1, 'ok': obj is not None, 'obj': obj})
        i += 1
    return out


def clean_history(deleted):
    if not deleted:
        return
    try:
        with open(HISTORY, 'rb') as f:
            raw_bytes = f.read()
        raw = raw_bytes.decode('utf-8-sig', errors='replace')
        segs = split_json_stream(raw)
        removed = any(
            t['ok'] and isinstance(t['obj'], dict) and t['obj'].get('sessionId') in deleted
            for t in segs
        )
        if not removed:
            return
        kept = []
        for t in segs:
            if t['ok'] and isinstance(t['obj'], dict) and t['obj'].get('sessionId') in deleted:
                continue
            kept.append(json.dumps(t['obj'], ensure_ascii=False) if t['ok'] else raw[t['start']:t['end']])
        eol = '\r\n' if '\r\n' in raw else '\n'
        content = eol.join(kept) + (eol if kept else '')
        with open(HISTORY, 'wb') as f:
            f.write(content.encode('utf-8'))
    except Exception as e:
        log(f'clean_history 失败: {e}')


def clean_claude_json(deleted):
    try:
        with open(CLAUDE_JSON, 'rb') as f:
            raw_bytes = f.read()
        raw = raw_bytes.decode('utf-8-sig', errors='replace')
        cfg = json.loads(raw)
        changed = False
        for k, p in (cfg.get('projects') or {}).items():
            if isinstance(p, dict) and p.get('lastSessionId') in deleted:
                p['lastSessionId'] = None
                changed = True
        if changed:
            eol = '\r\n' if '\r\n' in raw else '\n'
            out = json.dumps(cfg, ensure_ascii=False, indent=2) + eol
            with open(CLAUDE_JSON, 'wb') as f:
                f.write(out.encode('utf-8'))
    except Exception as e:
        log(f'clean_claude_json 失败: {e}')


# ------------------------------------------------------------
# 存活检测（从进程直接查询，提供接口）
# ------------------------------------------------------------

def live_session_map():
    """运行中会话：sessions/*.json + psutil 进程存活探测。"""
    m = {}
    try:
        for f in os.listdir(SESSIONS_DIR):
            if not f.endswith('.json'):
                continue
            try:
                with open(os.path.join(SESSIONS_DIR, f), 'r', encoding='utf-8-sig') as fh:
                    o = json.load(fh)
                pid = o.get('pid')
                if pid and isinstance(pid, int) and psutil.pid_exists(pid) \
                   and o.get('sessionId') and ID_RE.match(str(o['sessionId'])):
                    m[str(o['sessionId'])] = o
            except Exception:
                pass
    except Exception:
        pass
    return m


def locate_session(sid):
    found = []
    if not ID_RE.match(sid):
        return found
    try:
        proj_dirs = os.listdir(PROJECTS)
    except Exception:
        return found
    real_root = os.path.realpath(PROJECTS).lower()
    for d in proj_dirs:
        if d == 'memory':
            continue
        full = os.path.join(PROJECTS, d)
        if not os.path.isdir(full):
            continue
        p = os.path.join(full, sid + '.jsonl')
        if not os.path.isfile(p):
            continue
        if not os.path.realpath(p).lower().startswith(real_root + os.sep):
            continue
        found.append({'projDir': d, 'path': p, 'size': os.path.getsize(p)})
    return found


# ------------------------------------------------------------
# 扫描 / 摘要
# ------------------------------------------------------------

_SUMMARY_CACHE = {}


def _parse_transcript(path):
    """解析 transcript 为原始字段；按「大小 + mtime」缓存，避免重复全读大文件。

    缓存的是与 revmap 无关的字段（标题/时间/轮数/模型/cwd），
    projectPath 在 summarize 里用当前 revmap 现算，避免 .claude.json 变更后陈旧。
    """
    key = None
    try:
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime)
        if key in _SUMMARY_CACHE:
            return _SUMMARY_CACHE[key]
    except Exception:
        pass
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
            raw = f.read()
    except Exception:
        raw = ''
    title = ''
    first_time = ''
    last_time = ''
    cwd = ''
    user_count = 0
    assistant_count = 0
    last_model = ''  # 会话最后使用的真实模型（模型列/推断用它）
    now_ms = int(time.time() * 1000)
    future_slack_ms = 3600 * 1000  # 允许 1 小时时钟偏差，忽略异常未来时间戳
    for line in re.split(r'\r?\n', raw):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        ts = o.get('timestamp')
        if ts:
            ts_ms = iso_to_ms(ts)
            if ts_ms and ts_ms <= now_ms + future_slack_ms:  # 未来时间戳视为脏数据
                if not first_time or ts < first_time:
                    first_time = ts
                if ts > last_time:
                    last_time = ts
        if o.get('type') == 'user':
            user_count += 1
            if not title:
                title = text_content(o.get('message'))
            if not cwd and o.get('cwd'):
                cwd = o['cwd']
        elif o.get('type') == 'assistant':
            assistant_count += 1
            msg = o.get('message') or {}
            m = msg.get('model') or ''
            # 过滤伪模型标记（<synthetic> 等内部占位，claude 会写进 assistant 消息），
            # 只保留「最后」一条真实模型——模型列显示会话当前/最终用的模型，
            # 而非所有历史模型的合并（否则同会话中途 /model 会显示一堆 + <synthetic>）
            if m and not m.startswith('<'):
                last_model = m
    data = {'title': title, 'first': first_time, 'last': last_time, 'cwd': cwd,
            'user': user_count, 'assistant': assistant_count,
            'models': [last_model] if last_model else []}
    if key is not None:
        if len(_SUMMARY_CACHE) >= 500:
            _SUMMARY_CACHE.clear()
        _SUMMARY_CACHE[key] = data
    return data


def summarize(path, sid, proj, revmap):
    """解析单个 transcript，产出 Session（解析结果按大小+mtime 缓存）。"""
    d = _parse_transcript(path)
    last_time = d['last']
    if not last_time:
        try:
            mt = os.path.getmtime(path)
            last_time = datetime.datetime.utcfromtimestamp(mt).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        except Exception:
            pass
    return Session(
        id=sid, project=proj,
        projectPath=revmap.get(proj) or d['cwd'] or best_effort_decode(proj),
        title=d['title'], firstTime=d['first'], lastTime=last_time,
        userCount=d['user'], assistantCount=d['assistant'],
        models=d['models'], sizeBytes=0, isEmpty=d['assistant'] == 0,
    )


def merge_spawned_placeholders(sessions, spawned):
    """把本应用启动的占位会话合并进列表，并处理占位生命周期。"""
    now = int(time.time() * 1000)
    kept = []
    for e in spawned:
        if e.pid and (now - e.startedAt > SPAWNED_GRACE_MS):
            exited = False
            if e.proc is not None:
                try:
                    exited = e.proc.poll() is not None
                except Exception:
                    exited = False
            if not exited:
                try:
                    exited = not psutil.pid_exists(e.pid)
                except Exception:
                    exited = False
            if exited:
                continue
        if now - e.startedAt > SPAWNED_TTL_MS:
            continue
        matching = [
            s for s in sessions
            if (not s.isSpawned and s.firstTime and e.cwd
                and norm_path(s.projectPath) == norm_path(e.cwd)
                and iso_to_ms(s.firstTime) >= e.startedAt - BECAME_REAL_SLACK)
        ]
        if matching:
            if e.provider:
                for s in matching:
                    record_session_provider(s.id, e.provider)
            continue
        kept.append(e)
    spawned[:] = kept
    for e in kept:
        sessions.append(Session(
            id=f"spawn-{e.startedAt}", project='spawned',
            projectPath=e.cwd.replace('\\', '/'), title='',
            firstTime=ms_to_iso(e.startedAt), lastTime=ms_to_iso(e.startedAt),
            userCount=0, assistantCount=0, models=[], sizeBytes=0,
            isEmpty=True, isLive=True, isSpawned=True,
        ))
    return spawned


def scan_sessions(spawned):
    """扫描 projects/ 生成会话列表 + 总量统计。spawned 为 SpawnedSession 列表。"""
    live = live_session_map()
    revmap = build_reverse_map()
    sessions = []
    total_size = 0
    live_count = 0
    try:
        proj_dirs = os.listdir(PROJECTS)
    except Exception:
        proj_dirs = []
    for d in proj_dirs:
        if d == 'memory' or not PROJ_DIR_RE.match(d):
            continue
        full = os.path.join(PROJECTS, d)
        if not os.path.isdir(full):
            continue
        try:
            files = os.listdir(full)
        except Exception:
            continue
        for f in files:
            if not f.endswith('.jsonl'):
                continue
            sid = f[:-6]
            if not ID_RE.match(sid):
                continue
            p = os.path.join(full, f)
            if not os.path.isfile(p):
                continue
            s = summarize(p, sid, d, revmap)
            # replace 生成新对象：sizeBytes/isLive 按本次扫描现算，不污染 _SUMMARY_CACHE
            s = replace(s, sizeBytes=os.path.getsize(p), isLive=sid in live)
            if s.isLive:
                live_count += 1
            total_size += s.sizeBytes
            sessions.append(s)
    sessions.sort(key=lambda s: s.lastTime or '', reverse=True)
    merge_spawned_placeholders(sessions, spawned)
    return sessions, {'count': len(sessions), 'sizeBytes': total_size, 'liveCount': live_count}


# ------------------------------------------------------------
# 删除
# ------------------------------------------------------------

def delete_one(sid):
    found = locate_session(sid)
    if not found:
        return {'ok': False, 'reason': 'not-found', 'errors': []}
    targets = []
    freed = 0
    for f in found:
        targets.append(f['path'])
        freed += f['size']
        sub = f['path'][:-6]
        if os.path.exists(sub):
            targets.append(sub)
            freed += size_recursive(sub)
    fh = os.path.join(CONFIG_DIR, 'file-history', sid)
    if os.path.exists(fh):
        targets.append(fh)
        freed += size_recursive(fh)
    tk = os.path.join(CONFIG_DIR, 'tasks', sid)
    if os.path.exists(tk):
        targets.append(tk)
        freed += size_recursive(tk)
    for t in glob_in_dir(os.path.join(CONFIG_DIR, 'telemetry'), f'1p_failed_events.{sid}.*.json'):
        targets.append(t)
        freed += size_recursive(t)
    errors = []
    for t in targets:
        try:
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=False)
            else:
                os.remove(t)
        except Exception as e:
            errors.append({'target': t, 'message': str(e)})
    return {'ok': True, 'freed': freed, 'errors': errors}


def delete_many(ids):
    ids = list(dict.fromkeys(x for x in ids if isinstance(x, str)))
    live = set(live_session_map())
    deleted = []
    errors = []
    total = 0
    for sid in ids:
        if not ID_RE.match(sid):
            errors.append({'id': sid, 'reason': 'invalid-id'})
            continue
        if sid in live:
            errors.append({'id': sid, 'reason': 'live'})
            continue
        res = delete_one(sid)
        if res['ok']:
            deleted.append(sid)
            total += res['freed']
        else:
            errors.append({'id': sid, 'reason': res['reason']})
        for e in res['errors']:
            errors.append({'id': sid, 'reason': 'file', 'target': e['target'], 'message': e['message']})
    clean_history(set(deleted))
    clean_claude_json(set(deleted))
    return {'deleted': deleted, 'errors': errors, 'totalFreed': total}


# ------------------------------------------------------------
# 权限模式推断（恢复会话时默认用上次模式）
# ------------------------------------------------------------

def detect_permission_mode(sid):
    """返回会话最近一次启动的权限模式（'danger' / 'normal'）。

    transcript 里模式以独立条目记录：{"type":"permission-mode","permissionMode":"bypassPermissions"}。
    """
    found = locate_session(sid)
    if not found:
        return 'normal'
    last_pm = None
    try:
        with open(found[0]['path'], 'r', encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if isinstance(o, dict) and o.get('type') == 'permission-mode' and o.get('permissionMode'):
                    last_pm = str(o['permissionMode'])
    except Exception:
        pass
    return 'danger' if last_pm == 'bypassPermissions' else 'normal'


# ------------------------------------------------------------
# 导入 / 导出（zip）
# ------------------------------------------------------------

def gather_session_artifacts(sid):
    """收集一个会话的全部磁盘文件：transcript + 同名子目录 + file-history + tasks + telemetry。"""
    found = locate_session(sid)
    if not found:
        return None
    f = found[0]
    transcript = f['path']
    subdir = f['path'][:-6]  # projects/<projDir>/<sid>/
    fh = os.path.join(CONFIG_DIR, 'file-history', sid)
    tk = os.path.join(CONFIG_DIR, 'tasks', sid)
    telemetry = glob_in_dir(os.path.join(CONFIG_DIR, 'telemetry'), f'1p_failed_events.{sid}.*.json')
    revmap = build_reverse_map()
    return {
        'sid': sid,
        'projDir': f['projDir'],
        'projectPath': revmap.get(f['projDir']) or '',
        'transcript': transcript,
        'subdir': subdir if os.path.isdir(subdir) else '',
        'fileHistory': fh if os.path.isdir(fh) else '',
        'tasks': tk if os.path.isdir(tk) else '',
        'telemetry': telemetry,
    }


def export_sessions_to_zip(ids, out_path):
    """导出多个会话到 zip（manifest + 每个 <sid>/ 前缀的独立文件组）。"""
    entries = []
    exported, skipped = [], []
    for sid in ids:
        art = gather_session_artifacts(sid)
        if not art:
            skipped.append(sid)
            continue
        entries.append((f'{sid}/{sid}.jsonl', art['transcript']))
        if art['subdir']:
            entries.append((f'{sid}/files', art['subdir']))
        if art['fileHistory']:
            entries.append((f'{sid}/file-history', art['fileHistory']))
        if art['tasks']:
            entries.append((f'{sid}/tasks', art['tasks']))
        for t in art['telemetry']:
            entries.append((f'{sid}/telemetry/{os.path.basename(t)}', t))
        exported.append({'sessionUuid': sid, 'projectPath': art['projectPath'],
                         'projectDir': art['projDir']})
    manifest = {'kind': 'cc.sessions', 'version': 1, 'sessions': exported}
    make_zip(out_path, entries + [('manifest.json', None, json.dumps(manifest, ensure_ascii=False))])
    return {'ok': True, 'exported': [s['sessionUuid'] for s in exported], 'skipped': skipped}


def ensure_project_in_claude_json(real_path, sid):
    """确保 .claude.json 里有该项目条目，并把 lastSessionId 设为 sid（保留 eol 风格）。"""
    try:
        with open(CLAUDE_JSON, 'rb') as f:
            raw = f.read()
        raw_text = raw.decode('utf-8-sig', errors='replace')
        cfg = json.loads(raw_text)
        projects = cfg.setdefault('projects', {})
        if real_path not in projects:
            projects[real_path] = {}
        projects[real_path]['lastSessionId'] = sid
        eol = '\r\n' if '\r\n' in raw_text else '\n'
        with open(CLAUDE_JSON, 'wb') as f:
            f.write((json.dumps(cfg, ensure_ascii=False, indent=2) + eol).encode('utf-8'))
    except Exception as e:
        log(f'更新 .claude.json 失败: {e}')


def import_session_from_zip(zip_path, overwrite=False):
    """从 zip 导入会话（按 manifest 的 sessions 逐会话落盘）。运行中会话拒绝覆盖。"""
    manifest = zip_read_manifest(zip_path)
    if manifest.get('kind') != 'cc.sessions':
        return {'ok': False, 'error': 'not-sessions-zip'}
    live = set(live_session_map())
    imported, conflicts = [], []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()
        for s in manifest['sessions']:
            sid = s['sessionUuid']
            if not ID_RE.match(str(sid)):
                continue
            proj_path = s.get('projectPath') or ''
            proj_dir = s.get('projectDir') or munge(proj_path)
            dest_dir = os.path.join(PROJECTS, proj_dir)
            dest_transcript = os.path.join(dest_dir, sid + '.jsonl')
            if sid in live:
                conflicts.append(sid)
                continue
            if os.path.exists(dest_transcript) and not overwrite:
                conflicts.append(sid)
                continue
            prefix = f'{sid}/'
            member_map = {}
            unsafe = False
            for n in names:
                if not n.startswith(prefix):
                    continue
                if n.startswith('/') or '..' in n.split('/'):
                    unsafe = True
                    break
                rel = n[len(prefix):]
                top = rel.split('/')[0]
                if top == sid + '.jsonl':
                    member_map[n] = dest_transcript
                elif top == 'files':
                    member_map[n] = os.path.join(dest_dir, rel)
                elif top == 'file-history':
                    member_map[n] = os.path.join(CONFIG_DIR, 'file-history', rel)
                elif top == 'tasks':
                    member_map[n] = os.path.join(CONFIG_DIR, 'tasks', rel)
                elif top == 'telemetry':
                    member_map[n] = os.path.join(CONFIG_DIR, 'telemetry', os.path.basename(rel))
                # 其余未知成员忽略
            if unsafe:
                return {'ok': False, 'error': f'session {sid} 含不安全成员'}
            os.makedirs(dest_dir, exist_ok=True)
            for n, dest in member_map.items():
                if n.endswith('/'):
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(n) as src, open(dest, 'wb') as dst:
                    dst.write(src.read())
            if proj_path:
                ensure_project_in_claude_json(proj_path, sid)
            imported.append(sid)
    return {'ok': True, 'imported': imported, 'conflicts': conflicts}
