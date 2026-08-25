"""SkillManager：技能注册表（技能模块 data 层，进程内单例）。

从磁盘加载技能 map（name → Skill），缺 uuid 的旧技能自动回填写回（自愈）。
镜像 RoleManager 的回填模式；缓存键 = 各 SKILL.md 的 (name, mtime, size)。
"""
import os
import uuid as uuidlib

from ccui.skill.data import store as skill_store
from ccui.skill.data.models import Skill


class SkillManager:
    _instance = None

    def __init__(self):
        self._cache = {'key': None, 'skills': {}}

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        key = []
        for name in sorted(skill_store.list_skill_names()):
            p = skill_store.skill_dir(name)
            try:
                st = os.stat(p)
                key.append((name, st.st_mtime, st.st_size))
            except Exception:
                pass
        key = tuple(key)
        if self._cache['key'] == key:
            return self._cache['skills']
        skills = {}
        for name in skill_store.list_skill_names():
            s = skill_store.read_skill(name)
            if not s:
                continue
            # 旧技能缺 uuid → 生成并写回（保留未知 frontmatter 键）
            if not s['uuid'] or not skill_store.UUID_RE.match(s['uuid']):
                s['uuid'] = str(uuidlib.uuid4())
                skill_store.update_skill(name, s['description'], s['body'],
                                         s['category'], s['uuid'])
            skills[name] = Skill(name=s['name'], description=s['description'],
                                 category=s['category'], uuid=s['uuid'],
                                 content=s['content'], body=s['body'],
                                 path=s['path'], source='global')
        self._cache['key'] = key
        self._cache['skills'] = skills
        return skills

    def skills(self):
        return list(self._load().values())

    def get(self, name):
        return self._load().get(name)

    def by_uuid(self):
        return {s.uuid: s for s in self._load().values() if s.uuid}

    def by_name(self):
        return dict(self._load())
