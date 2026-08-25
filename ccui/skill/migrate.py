"""一次性迁移：技能注入 uuid + 角色 meta 的 skills 名→uuid。幂等。

用法: python -m ccui.skill.migrate
（prewarm 启动时也会幂等调用，保证旧部署自动升级）
"""
import os
import json
import uuid as uuidlib
import re

from ccui.infra.config import ROLES_DIR
from ccui.skill.data import store as skill_store

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def ensure_skill_uuids():
    """给所有缺 uuid 的 SKILL.md frontmatter 逐行注入 uuid（保留未知键/多行子键）。"""
    migrated = 0
    for name in sorted(skill_store.list_skill_names()):
        p = skill_store.skill_dir(name)
        if not os.path.isfile(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        if not content.startswith('---'):
            continue
        parts = content.split('---', 2)
        if len(parts) < 3:
            continue
        raw_front = parts[1]
        if re.search(r'^\s*uuid\s*:', raw_front, re.MULTILINE):
            continue  # 已有 uuid
        lines = raw_front.split('\n')
        out = []
        injected = False
        for ln in lines:
            out.append(ln)
            if not injected and re.match(r'^\s*name\s*:', ln):
                out.append(f'uuid: {str(uuidlib.uuid4())}')
                injected = True
        if not injected:
            out.append(f'uuid: {str(uuidlib.uuid4())}')
        new_front = '\n'.join(out)
        new_raw = '---' + new_front + '\n' + '---' + parts[2]
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(new_raw)
        migrated += 1
    return migrated


def migrate_role_metas():
    """把角色 meta.json 的 skills 名字数组改成 uuid 数组（幂等）。"""
    u2n = skill_store.uuid_to_name_map()
    n2u = skill_store.name_to_uuid_map()
    updated = 0
    warnings = []
    if not os.path.isdir(ROLES_DIR):
        return updated, warnings
    for role in sorted(os.listdir(ROLES_DIR)):
        meta_path = os.path.join(ROLES_DIR, role, 'meta.json')
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            continue
        skills = meta.get('skills') or []
        new_skills = []
        changed = False
        for item in skills:
            item = str(item)
            if UUID_RE.match(item):
                if item in u2n:
                    new_skills.append(item)
                else:
                    warnings.append(f'{role}: uuid {item} 无对应技能，已丢弃')
                    changed = True
                continue
            # 旧名字 → uuid
            if item in n2u:
                new_skills.append(n2u[item])
                changed = True
            else:
                warnings.append(f'{role}: 技能名 {item} 找不到对应技能，已丢弃')
                changed = True
        # 去重保序
        seen, dedup = set(), []
        for s in new_skills:
            if s not in seen:
                seen.add(s)
                dedup.append(s)
        if changed or len(dedup) != len(skills):
            meta['skills'] = dedup
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            updated += 1
    return updated, warnings


def run():
    """执行迁移，返回报告 dict。幂等：重复调用各计数为 0。"""
    migrated = ensure_skill_uuids()
    skill_store._UUID_MAP_CACHE['key'] = None  # 失效映射缓存
    updated, warnings = migrate_role_metas()
    return {
        'skills_migrated': migrated,
        'roles_updated': updated,
        'warnings': warnings,
    }


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(json.dumps(run(), ensure_ascii=False, indent=2))
