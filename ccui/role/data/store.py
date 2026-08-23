"""角色与技能的数据访问（角色模块 data 层）。

无 Qt、无 service 依赖。角色文件在 roles/<name>/，技能文件在
skills/<name>/SKILL.md（全局）与 roles/<name>/skills/<name>/SKILL.md（角色专属）。
"""
import os
import re
import json
import datetime

from ccui.infra.config import CONFIG_DIR, ROLES_DIR, SKILLS_DIR, log

NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')


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


def session_role_map():
    """全局 session_id → 角色名 反向映射（来自各角色 sessions.jsonl）。

    供会话模块展示「该会话由哪个角色启动」。
    """
    m = {}
    for name in sorted(list_role_names()):
        for t in role_sessions_from_file(name):
            sid = t.get('session_id', '')
            if sid:
                m.setdefault(sid, name)
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


# ------------------------------------------------------------
# 技能（SKILL.md）访问
# ------------------------------------------------------------

def _parse_frontmatter(content):
    """解析 SKILL.md 的 frontmatter（--- name/description ---）。"""
    name = ''
    description = ''
    body = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            front = parts[1]
            body = parts[2]
            for line in front.splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    k = k.strip().lower()
                    v = v.strip()
                    if k == 'name':
                        name = v
                    elif k == 'description':
                        description = v
    return name, description, body.strip()


def global_skill_dir(name):
    return os.path.join(SKILLS_DIR, name, 'SKILL.md')


def role_skill_dir(role_name, name):
    return os.path.join(ROLES_DIR, role_name, 'skills', name, 'SKILL.md')


def list_global_skill_names():
    try:
        return [d for d in os.listdir(SKILLS_DIR)
                if os.path.exists(os.path.join(SKILLS_DIR, d, 'SKILL.md')) and NAME_RE.match(d)]
    except Exception:
        return []


def list_role_skill_names(role_name):
    d = os.path.join(ROLES_DIR, role_name, 'skills')
    try:
        return [x for x in os.listdir(d)
                if os.path.exists(os.path.join(d, x, 'SKILL.md')) and NAME_RE.match(x)]
    except Exception:
        return []


def read_skill(skill_name, role_name=None):
    """读一个技能；role_name 给定时优先角色专属，否则全局。返回 Skill 或 None。"""
    path = None
    source = ''
    if role_name:
        p = role_skill_dir(role_name, skill_name)
        if os.path.exists(p):
            path, source = p, 'role'
    if path is None:
        p = global_skill_dir(skill_name)
        if os.path.exists(p):
            path, source = p, 'global'
    if path is None:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        name, desc, body = _parse_frontmatter(content)
        return {
            'name': name or skill_name,
            'description': desc,
            'content': content,
            'body': body,
            'path': path,
            'source': source,
        }
    except Exception as e:
        log(f'读技能失败: {e}')
        return None


def write_skill(skill_name, content, role_name=None):
    """写技能内容（SKILL.md）。role_name 给定时写角色专属，否则写全局。"""
    if role_name:
        path = role_skill_dir(role_name, skill_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    else:
        path = global_skill_dir(skill_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        log(f'写技能失败: {e}')


def create_skill(skill_name, description, body, role_name=None):
    """新建技能：用 frontmatter 包装内容。"""
    content = f'---\nname: {skill_name}\ndescription: {description}\n---\n\n{body}'.strip() + '\n'
    write_skill(skill_name, content, role_name)
