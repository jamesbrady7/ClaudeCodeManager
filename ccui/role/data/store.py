"""角色与技能的数据访问（角色模块 data 层）。

无 Qt、无 service 依赖。角色文件在 roles/<name>/，技能文件在
skills/<name>/SKILL.md（全局）与 roles/<name>/skills/<name>/SKILL.md（角色专属）。
"""
import os
import re
import json
import time
import datetime

from ccui.infra.config import CONFIG_DIR, ROLES_DIR, SKILLS_DIR, ASSETS_DIR, log

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
# 技能（SKILL.md）访问
# ------------------------------------------------------------

# 技能类型（用于技能选择窗体的分组）。规则顺序即优先级：先匹配者生效。
SKILL_CATEGORY_LABELS = ['动效动画', '界面设计', '设计系统', '品牌视觉', '内容演示', '综合', '其他']

_CATEGORY_RULES = (
    ('动效动画', ('animat', 'motion', '动效', '动画', 'spring', 'gesture',
                  'interrupt', 'rubber', 'bounce', 'swipe', 'drag', 'physics')),
    ('设计系统', ('design system', 'design-system', 'design token', '设计系统', 'token',
                  'component spec')),
    ('品牌视觉', ('brand', '品牌', 'logo', '标识', 'identity', 'corporate identity')),
    ('内容演示', ('slide', 'presentation', 'banner', 'social', '演示', '幻灯片', '海报', 'chart')),
    ('界面设计', ('ui', 'interface', '界面', 'web', 'macos', 'apple', 'tailwind', 'shadcn',
                  'css', 'component', 'accessible', 'frontend', 'desktop', 'responsive',
                  'typography', 'color', '用户')),
    ('综合', ('design', '设计')),
)


def infer_skill_category(name, description):
    """从技能名+描述推断类型（frontmatter 无 category 时的兜底）。"""
    text = f'{name} {description or ""}'.lower()
    for label, kws in _CATEGORY_RULES:
        if any(k in text for k in kws):
            return label
    return '其他'


def _parse_frontmatter(content):
    """解析 SKILL.md 的 frontmatter（--- name/description/category ---）。"""
    name = ''
    description = ''
    category = ''
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
                    elif k == 'category':
                        category = v
    return name, description, category, body.strip()


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
        name, desc, cat, body = _parse_frontmatter(content)
        name = name or skill_name
        return {
            'name': name,
            'description': desc,
            'category': cat or infer_skill_category(name, desc),
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


def create_skill(skill_name, description, body, role_name=None, category=''):
    """新建技能：用 frontmatter 包装内容（category 缺省时按关键字推断）。"""
    cat = category or infer_skill_category(skill_name, description)
    content = (f'---\nname: {skill_name}\n'
               f'category: {cat}\n'
               f'description: {description}\n---\n\n{body}').strip() + '\n'
    write_skill(skill_name, content, role_name)
