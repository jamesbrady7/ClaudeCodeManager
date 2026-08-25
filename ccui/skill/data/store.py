"""技能库数据访问（技能模块 data 层）。

技能统一存于全局 `skills/<name>/SKILL.md`（角色专属技能已废弃）。
标识：目录名 = frontmatter `name`；`uuid`（frontmatter `uuid:`）是稳定身份，
角色按 uuid 引用。frontmatter 解析/序列化**逐行保留未知键与多行 metadata 子键**，
编辑技能不丢任何原始字段。
"""
import os
import re
import json
import zipfile
import uuid as uuidlib

from ccui.infra.config import SKILLS_DIR, log
from ccui.infra.archive import make_zip, zip_read_manifest, safe_extract_zip

NAME_RE = re.compile(r'^[\w一-鿿-]+$')            # 技能目录名
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

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


# ------------------------------------------------------------
# 路径 / 列表
# ------------------------------------------------------------

def skill_dir(name):
    return os.path.join(SKILLS_DIR, name, 'SKILL.md')


def list_skill_names():
    """全局技能库目录名（含 SKILL.md 且符合命名规则）。"""
    try:
        return [d for d in os.listdir(SKILLS_DIR)
                if os.path.exists(os.path.join(SKILLS_DIR, d, 'SKILL.md')) and NAME_RE.match(d)]
    except Exception:
        return []


# ------------------------------------------------------------
# frontmatter 编解码（保留未知键 + 多行子键）
# ------------------------------------------------------------

def parse_frontmatter(content):
    """解析 SKILL.md frontmatter。返回 (fields: dict, raw_front: str, body: str)。

    fields 只含顶层标量键（name/category/description/uuid 等）；
    raw_front 是原始 frontmatter 块（无 --- 定界符），多行 metadata 子键原样保留；
    body 为去掉 frontmatter 后的正文。
    """
    fields = {}
    raw_front = ''
    body = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            raw_front, body = parts[1], parts[2]
            for line in raw_front.splitlines():
                if line[:1] not in (' ', '\t') and ':' in line:
                    k, _, v = line.partition(':')
                    fields[k.strip()] = v.strip()
    return fields, raw_front, body.strip()


def _upsert_frontmatter_key(raw_front, key, value):
    """在 frontmatter 块内更新/插入一个顶层键，保留其余行（含多行子键）。"""
    lines = raw_front.split('\n')
    out = []
    inserted = False
    for ln in lines:
        is_top = ln[:1] not in (' ', '\t')
        if is_top and ln.lstrip().startswith(key + ':'):
            out.append(f'{key}: {value}')
            inserted = True
        else:
            out.append(ln)
    if not inserted:
        for i, ln in enumerate(out):
            if ln[:1] not in (' ', '\t') and ':' in ln:
                out.insert(i + 1, f'{key}: {value}')
                break
        else:
            out.append(f'{key}: {value}')
    return '\n'.join(out)


def serialize_skill(fields, raw_front, body):
    """按 fields 更新 raw_front（保留未知键/多行子键），拼回完整 SKILL.md 内容。"""
    front = raw_front.strip('\n')  # 剥掉 split('---',2) 带来的首尾换行
    for k, v in fields.items():
        front = _upsert_frontmatter_key(front, k, v)
    return f'---\n{front}\n---\n\n{body}\n'


# ------------------------------------------------------------
# 读写
# ------------------------------------------------------------

def read_skill(name):
    """读全局技能，返回 dict（含 uuid）或 None。"""
    path = skill_dir(name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        log(f'读技能失败: {e}')
        return None
    fields, _raw, body = parse_frontmatter(content)
    return {
        'name': fields.get('name') or name,
        'description': fields.get('description', ''),
        'category': fields.get('category', '') or infer_skill_category(name, fields.get('description', '')),
        'uuid': fields.get('uuid', ''),
        'content': content,
        'body': body,
        'path': path,
        'source': 'global',
    }


def read_skill_by_uuid(skill_uuid):
    """按 uuid 找技能（遍历 frontmatter），返回 dict 或 None。"""
    for name in list_skill_names():
        s = read_skill(name)
        if s and s['uuid'] == skill_uuid:
            return s
    return None


def skill_path_by_uuid(skill_uuid):
    """uuid → SKILL.md 绝对路径，找不到返回 None。"""
    s = read_skill_by_uuid(skill_uuid)
    return s['path'] if s else None


def write_skill(name, content):
    """整体写 SKILL.md（保留扩展文件不动）。"""
    try:
        os.makedirs(os.path.dirname(skill_dir(name)), exist_ok=True)
        with open(skill_dir(name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    except Exception as e:
        log(f'写技能失败: {e}')


def create_skill(name, description, body, category=''):
    """新建技能：生成 uuid，写 frontmatter。返回 {'ok', 'uuid'}。"""
    skill_uuid = str(uuidlib.uuid4())
    content = (f'---\nname: {name}\n'
               f'category: {category}\n'
               f'uuid: {skill_uuid}\n'
               f'description: {description}\n---\n\n{body}').strip() + '\n'
    write_skill(name, content)
    return {'ok': True, 'uuid': skill_uuid}


def update_skill(name, description, body, category, skill_uuid=''):
    """编辑技能：保留 uuid 与未知 frontmatter 键，更新 name/category/description/正文。"""
    existing = read_skill(name)
    raw_front = ''
    if existing:
        _f, raw_front, _b = parse_frontmatter(existing['content'])
    fields = {'name': name, 'category': category, 'description': description}
    if skill_uuid:
        fields['uuid'] = skill_uuid
    write_skill(name, serialize_skill(fields, raw_front, body))


def delete_skill(name):
    """删除技能目录。"""
    import shutil
    d = os.path.join(SKILLS_DIR, name)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=False)
        return True
    return False


def rename_skill(old, new):
    """重命名技能目录；frontmatter name 更新，uuid 不动。"""
    if not old or not new or old == new or not NAME_RE.match(new):
        return False
    old_dir = os.path.join(SKILLS_DIR, old)
    new_dir = os.path.join(SKILLS_DIR, new)
    if not os.path.isdir(old_dir) or os.path.exists(new_dir):
        return False
    try:
        existing = read_skill(old)
        os.rename(old_dir, new_dir)
        if existing:
            fields, raw_front, body = parse_frontmatter(existing['content'])
            write_skill(new, serialize_skill({'name': new}, raw_front, body))
        return True
    except Exception as e:
        log(f'重命名技能失败: {e}')
        return False


# ------------------------------------------------------------
# uuid ↔ name 双向映射（带缓存）
# ------------------------------------------------------------

_UUID_MAP_CACHE = {'key': None, 'u2n': {}, 'n2u': {}}


def _scan_uuid_maps():
    """扫描所有技能 frontmatter，建 uuid→name 与 name→uuid。缓存键=(name,mtime,size)。"""
    key = []
    for name in sorted(list_skill_names()):
        p = skill_dir(name)
        try:
            st = os.stat(p)
            key.append((name, st.st_mtime, st.st_size))
        except Exception:
            pass
    key = tuple(key)
    if _UUID_MAP_CACHE['key'] == key:
        return _UUID_MAP_CACHE['u2n'], _UUID_MAP_CACHE['n2u']
    u2n, n2u = {}, {}
    for name in list_skill_names():
        s = read_skill(name)
        if s and s['uuid'] and UUID_RE.match(s['uuid']):
            u2n[s['uuid']] = s['name']
            n2u.setdefault(s['name'], s['uuid'])
    _UUID_MAP_CACHE['key'] = key
    _UUID_MAP_CACHE['u2n'] = u2n
    _UUID_MAP_CACHE['n2u'] = n2u
    return u2n, n2u


def uuid_to_name_map():
    return _scan_uuid_maps()[0]


def name_to_uuid_map():
    return _scan_uuid_maps()[1]




# ------------------------------------------------------------
# 分组（分类）管理
# ------------------------------------------------------------

_CATEGORIES_FILE = os.path.join(SKILLS_DIR, '.categories.json')
# 结构：{"categories": [自定义分组名...], "icons": {分组名: 图标key}}（兼容旧裸列表格式）


def _read_categories_config():
    try:
        with open(_CATEGORIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):  # 旧格式：裸自定义分类列表
            return {'categories': [c for c in data if isinstance(c, str) and c.strip()],
                    'icons': {}}
        if isinstance(data, dict):
            return {'categories': [c for c in (data.get('categories') or [])
                                   if isinstance(c, str) and c.strip()],
                    'icons': data.get('icons') or {}}
    except Exception:
        pass
    return {'categories': [], 'icons': {}}


def _write_categories_config(cfg):
    try:
        with open(_CATEGORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def list_categories():
    """全部分组：预置 SKILL_CATEGORY_LABELS + 用户自定义（.categories.json）。"""
    cfg = _read_categories_config()
    return SKILL_CATEGORY_LABELS + [c for c in cfg['categories']
                                    if c not in SKILL_CATEGORY_LABELS]


def add_category(name):
    """新建分组：预置分类直接返回 True；自定义分类写入索引（空分组也能显示）。"""
    name = (name or '').strip()
    if not name:
        return False
    if name in SKILL_CATEGORY_LABELS:
        return True
    cfg = _read_categories_config()
    if name not in cfg['categories']:
        cfg['categories'].append(name)
        _write_categories_config(cfg)
    return True


def get_category_icon(cat):
    """分组图标 key（Lucide 名或 role-icons 文件名），未设置返回 ''。"""
    return _read_categories_config()['icons'].get(cat, '')


def set_category_icon(cat, icon_key):
    """设置分组图标。icon_key：'' 清除；Lucide 名如 'zap'；或 role-icons 文件名如 'claude-color.svg'。"""
    cfg = _read_categories_config()
    if icon_key:
        cfg['icons'][cat] = icon_key
    else:
        cfg['icons'].pop(cat, None)
    _write_categories_config(cfg)


def _drop_custom_category(name):
    if name in SKILL_CATEGORY_LABELS:
        return
    cfg = _read_categories_config()
    changed = False
    if name in cfg['categories']:
        cfg['categories'].remove(name)
        changed = True
    if name in cfg['icons']:
        cfg['icons'].pop(name, None)
        changed = True
    if changed:
        _write_categories_config(cfg)


def rename_category(old, new):
    """把 old 分类下所有技能改到 new 分类（图标也迁移）。返回更新的技能数。"""
    new = (new or '').strip()
    if not old or not new or old == new:
        return 0
    count = 0
    for name in list_skill_names():
        s = read_skill(name)
        if s and s.get('category') == old:
            fields, raw, body = parse_frontmatter(s['content'])
            write_skill(name, serialize_skill({**fields, 'category': new}, raw, body))
            count += 1
    # 自定义分类索引 + 图标迁移
    cfg = _read_categories_config()
    if old in cfg['categories']:
        if new not in cfg['categories']:
            cfg['categories'].append(new)
        cfg['categories'].remove(old)
    if old in cfg['icons']:
        cfg['icons'].setdefault(new, cfg['icons'].pop(old))
    _write_categories_config(cfg)
    if new not in SKILL_CATEGORY_LABELS:
        add_category(new)
    return count


def delete_category(name):
    """删除分类：其下技能移到「其他」，并从索引/图标移除。返回移动的技能数。"""
    if not name or name == '其他':
        return 0
    count = 0
    for n in list_skill_names():
        s = read_skill(n)
        if s and s.get('category') == name:
            fields, raw, body = parse_frontmatter(s['content'])
            write_skill(n, serialize_skill({**fields, 'category': '其他'}, raw, body))
            count += 1
    _drop_custom_category(name)
    return count


# ------------------------------------------------------------
# 导入 / 导出（zip）
# ------------------------------------------------------------

def export_skill_to_zip(name, out_path):
    """导出单个技能到 zip（兼容 v1 单技能 manifest）。"""
    r = export_skills_to_zip([name], out_path)
    if not r['ok']:
        return r
    return {'ok': True, 'name': name}


def export_skills_to_zip(names, out_path):
    """**批量**导出技能到 zip（manifest.skills 数组，各技能 <name>/...）。"""
    entries = []
    exported = []
    for name in names:
        d = os.path.join(SKILLS_DIR, name)
        if not os.path.isdir(d):
            continue
        s = read_skill(name)
        entries.append((name, d))
        exported.append({'name': name,
                         'uuid': s['uuid'] if s else '',
                         'category': s['category'] if s else '',
                         'description': s['description'] if s else ''})
    if not exported:
        return {'ok': False, 'error': 'nothing-to-export'}
    manifest = {'kind': 'cc.skill', 'version': 2, 'skills': exported}
    make_zip(out_path, entries + [('manifest.json', None, json.dumps(manifest, ensure_ascii=False))])
    return {'ok': True, 'exported': [s['name'] for s in exported]}


def import_skill_from_zip(zip_path, mode='skip'):
    """从 zip 导入技能（兼容单技能 v1 / 多技能 v2）。冲突处理：skip/overwrite/new_uuid。"""
    manifest = zip_read_manifest(zip_path)
    if manifest.get('kind') != 'cc.skill':
        return {'ok': False, 'error': 'not-skill-zip'}
    items = manifest.get('skills')
    if items is None and manifest.get('skill'):
        items = [manifest['skill']]  # v1 兼容
    if not items:
        return {'ok': False, 'error': 'no-skills'}
    imported, conflicts, errors = [], [], []
    for info in items:
        name = info.get('name', '')
        skill_uuid = info.get('uuid', '')
        if not name or not NAME_RE.match(name):
            errors.append({'name': name, 'reason': 'invalid-name'})
            continue
        dest = os.path.join(SKILLS_DIR, name)
        conflict = os.path.isdir(dest)
        if not conflict and skill_uuid and UUID_RE.match(skill_uuid):
            conflict = read_skill_by_uuid(skill_uuid) is not None
        effective_uuid = skill_uuid
        if conflict:
            if mode == 'skip':
                conflicts.append(name)
                continue
            if mode == 'new_uuid':
                effective_uuid = str(uuidlib.uuid4())
        with zipfile.ZipFile(zip_path, 'r') as zf:
            members = [n for n in zf.namelist()
                       if n == name + '/' or n.startswith(name + '/')]
        safe_extract_zip(zip_path, SKILLS_DIR, members=members)
        # new_uuid 时重写 frontmatter uuid（角色引用旧 uuid 的优雅跳过）
        if mode == 'new_uuid' and effective_uuid:
            existing = read_skill(name)
            if existing:
                fields, raw, body = parse_frontmatter(existing['content'])
                write_skill(name, serialize_skill({**fields, 'uuid': effective_uuid}, raw, body))
        imported.append(name)
    return {'ok': True, 'imported': imported, 'conflicts': conflicts, 'errors': errors}
