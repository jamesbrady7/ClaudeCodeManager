"""角色数据访问（角色模块 data 层）。

无 Qt、无 service 依赖。角色文件在 roles/<name>/（meta/persona/knowledge/icon/sessions.jsonl）。
技能已独立到 ccui/skill 模块，角色以 uuid 数组引用。
"""
import os
import re
import json
import time
import shutil
import tempfile
import zipfile
import datetime

from ccui.infra.config import ROLES_DIR, ASSETS_DIR, log
from ccui.infra.archive import make_zip, zip_read_manifest, safe_extract_zip

NAME_RE = re.compile(r'^[\w一-鿿-]+$')  # 拉丁/数字/下划线/连字符 + 中日韩（中文名可用）


# ------------------------------------------------------------
# 角色文件访问
# ------------------------------------------------------------

def list_role_names():
    try:
        return [d for d in os.listdir(ROLES_DIR)
                if os.path.isdir(os.path.join(ROLES_DIR, d)) and NAME_RE.match(d)]
    except Exception:
        return []


def role_dir(name):
    return os.path.join(ROLES_DIR, name)


def read_meta(name):
    try:
        with open(os.path.join(ROLES_DIR, name, 'meta.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def write_meta(name, meta):
    try:
        with open(os.path.join(ROLES_DIR, name, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f'写角色 meta 失败: {e}')


def read_persona(name):
    try:
        with open(os.path.join(ROLES_DIR, name, 'persona.md'), 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def write_persona(name, content):
    try:
        with open(os.path.join(ROLES_DIR, name, 'persona.md'), 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        log(f'写角色人设失败: {e}')


def read_knowledge(name):
    try:
        with open(os.path.join(ROLES_DIR, name, 'knowledge.md'), 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def write_knowledge(name, content):
    try:
        with open(os.path.join(ROLES_DIR, name, 'knowledge.md'), 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        log(f'写角色知识库失败: {e}')


def role_sessions_from_file(name):
    """读 roles/<name>/sessions.jsonl，返回 [{session_id, timestamp, cwd}]。"""
    out = []
    p = os.path.join(ROLES_DIR, name, 'sessions.jsonl')
    if not os.path.exists(p):
        return out
    try:
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                    out.append({'session_id': o.get('session_id', ''),
                                'timestamp': o.get('timestamp', ''),
                                'cwd': o.get('cwd', '')})
                except Exception:
                    continue
    except Exception as e:
        log(f'读角色会话记录失败: {e}')
    return out


_role_map_cache = {'at': 0.0, 'map': {}}


def session_role_map():
    """全局 session_id → 角色名 反向映射（来自各角色 sessions.jsonl）。

    供会话模块展示「该会话由哪个角色启动」。2s TTL 缓存——树重建热路径，
    角色会话变化由 watcher 触发重扫兜底。
    """
    now = time.time()
    if now - _role_map_cache.get('at', 0.0) < 2.0:
        return _role_map_cache['map']
    m = {}
    for name in sorted(list_role_names()):
        for t in role_sessions_from_file(name):
            sid = t.get('session_id', '')
            if sid:
                m.setdefault(sid, name)
    _role_map_cache['at'] = now
    _role_map_cache['map'] = m
    return m


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def append_role_session(name, session_id, cwd=''):
    """向 roles/<name>/sessions.jsonl 追加一条会话记录。"""
    p = os.path.join(ROLES_DIR, name, 'sessions.jsonl')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    entry = {'session_id': session_id, 'timestamp': _now_iso(), 'cwd': cwd}
    with open(p, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def write_role_sessions(name, entries):
    """整体覆写 roles/<name>/sessions.jsonl（prune/remove 复用）。"""
    p = os.path.join(ROLES_DIR, name, 'sessions.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def role_icon_path(name):
    """角色自定义图标路径（roles/<name>/icon.{png|svg}），不存在返回 ''。"""
    for ext in ('icon.png', 'icon.svg'):
        p = os.path.join(ROLES_DIR, name, ext)
        if os.path.exists(p):
            return p
    return ''


def write_role_icon(name, src):
    """把用户选的图片复制为角色的 icon.<ext>（保留扩展名，SVG/PNG 均可）。"""
    import shutil
    ext = os.path.splitext(src)[1].lower() or '.png'
    if ext not in ('.png', '.svg', '.jpg', '.jpeg', '.ico', '.webp'):
        ext = '.png'
    dst = os.path.join(ROLES_DIR, name, f'icon{ext}')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def remove_role_icon(name):
    for ext in ('icon.png', 'icon.svg'):
        p = os.path.join(ROLES_DIR, name, ext)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def set_default_icon(name):
    """把图标库第一个 SVG 复制为新角色默认头像。"""
    d = os.path.join(ASSETS_DIR, 'role-icons')
    if not os.path.isdir(d):
        return
    svgs = sorted(f for f in os.listdir(d) if f.lower().endswith('.svg'))
    if svgs:
        write_role_icon(name, os.path.join(d, svgs[0]))


# ------------------------------------------------------------
# 导入 / 导出（zip）
# ------------------------------------------------------------

def export_role_to_zip(name, out_path):
    """导出角色为 zip。**白名单**：meta/persona/knowledge/icon/sessions.jsonl，
    不含技能内容、不含会话 transcript、不含角色专属技能/inherit.md。"""
    d = role_dir(name)
    if not os.path.isdir(d):
        return {'ok': False, 'error': 'not-found'}
    meta = read_meta(name)
    manifest = {
        'kind': 'cc.role', 'version': 1,
        'role': {'name': name,
                 'uuid': meta.get('uuid', ''),
                 'skillUuids': meta.get('skills', []),
                 'sessionUuids': [t['session_id'] for t in role_sessions_from_file(name)
                                  if t.get('session_id')]},
    }
    entries = [
        (f'{name}/meta.json', os.path.join(d, 'meta.json')),
        (f'{name}/persona.md', os.path.join(d, 'persona.md')),
        (f'{name}/knowledge.md', os.path.join(d, 'knowledge.md')),
    ]
    sp = os.path.join(d, 'sessions.jsonl')
    if os.path.isfile(sp):
        entries.append((f'{name}/sessions.jsonl', sp))
    icon = role_icon_path(name)
    if icon:
        entries.append((f'{name}/{os.path.basename(icon)}', icon))
    make_zip(out_path, entries + [('manifest.json', None, json.dumps(manifest, ensure_ascii=False))])
    return {'ok': True}


def import_role_from_zip(zip_path, mode='skip', new_name=''):
    """从 zip 导入角色（白名单文件）。mode: skip / overwrite / rename(new_name)。

    返回 manifest 里的 skillUuids/sessionUuids 供 view 层做存在性检查
    （技能/会话各自独立导入；缺失的优雅跳过，不由本模块判断）。
    """
    manifest = zip_read_manifest(zip_path)
    if manifest.get('kind') != 'cc.role':
        return {'ok': False, 'error': 'not-role-zip'}
    info = manifest.get('role', {})
    src_name = info.get('name', '')
    if not src_name or not NAME_RE.match(src_name):
        return {'ok': False, 'error': 'invalid-name'}
    dest_name = (new_name or src_name).strip()
    if not NAME_RE.match(dest_name):
        return {'ok': False, 'error': 'invalid-name'}
    dest_dir = os.path.join(ROLES_DIR, dest_name)
    conflict = os.path.isdir(dest_dir)
    if conflict and mode != 'overwrite':
        return {'ok': False, 'error': 'exists', 'conflict': True}
    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = [n for n in zf.namelist()
                   if n == src_name + '/' or n.startswith(src_name + '/')]
    # 先解包到临时目录，再移动到目标——**绝不覆盖/改名磁盘上已存在的原角色目录**
    tmp = tempfile.mkdtemp(prefix='cc-role-import-')
    try:
        safe_extract_zip(zip_path, tmp, members=members)
        src_dir = os.path.join(tmp, src_name)
        if not os.path.isdir(src_dir):
            return {'ok': False, 'error': 'zip 内缺少角色目录'}
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)  # overwrite 才走到这
        shutil.move(src_dir, dest_dir)  # 跨盘（临时目录可能在别的盘）用 move 而非 rename
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # 重命名导入：meta.name 更新
    if dest_name != src_name:
        meta = read_meta(dest_name)
        meta['name'] = dest_name
        write_meta(dest_name, meta)
    return {'ok': True, 'name': dest_name,
            'skillUuids': info.get('skillUuids', []),
            'sessionUuids': info.get('sessionUuids', []),
            'conflict': conflict}
