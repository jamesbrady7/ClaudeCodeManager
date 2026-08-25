"""技能管理业务层（技能模块 service）。"""
import os

from ccui.infra.signalhub import SignalHub
from ccui.skill.data import store as skill_store
from ccui.skill.data.manager import SkillManager
from ccui.skill.data.models import Skill


class SkillService:
    """技能库业务：列表/读写/改名/删除 + uuid 解析。"""

    def __init__(self):
        self.manager = SkillManager.instance()

    # ---- 查询 ----
    def list_skills(self):
        return self.manager.skills()

    def get_skill(self, name):
        s = self.manager.get(name)
        if s:
            return s
        info = skill_store.read_skill(name)
        if not info:
            return None
        return Skill(name=info['name'], description=info['description'],
                     category=info['category'], uuid=info['uuid'],
                     content=info['content'], body=info['body'],
                     path=info['path'], source='global')

    def get_skill_by_uuid(self, skill_uuid):
        s = self.manager.by_uuid().get(skill_uuid)
        if s:
            return s
        info = skill_store.read_skill_by_uuid(skill_uuid)
        if not info:
            return None
        return Skill(name=info['name'], description=info['description'],
                     category=info['category'], uuid=info['uuid'],
                     content=info['content'], body=info['body'],
                     path=info['path'], source='global')

    def skill_names_for_uuids(self, uuids):
        """按 uuid 解析技能名：返回 (已存在名字列表, 缺失 uuid 列表)。

        角色按 uuid 引用技能时，缺失的 uuid 优雅跳过（展示/注入时不报错）。
        """
        by_uuid = self.manager.by_uuid()
        names, missing = [], []
        for u in (uuids or []):
            s = by_uuid.get(u)
            if s:
                names.append(s.name)
            else:
                missing.append(u)
        return names, missing

    # ---- 变更（成功后广播 skills.changed）----
    def _invalidate(self):
        self.manager._cache['key'] = None

    def create_skill(self, name, description, body, category=''):
        if not name or not skill_store.NAME_RE.match(name):
            return {'ok': False, 'error': 'invalid-name'}
        if os.path.exists(skill_store.skill_dir(name)):
            return {'ok': False, 'error': 'exists'}
        r = skill_store.create_skill(name, description, body, category)
        if r['ok']:
            self._invalidate()
            SignalHub.instance().emit('skills.changed')
        return {'ok': True, 'uuid': r['uuid']}

    def update_skill(self, name, description, body, category):
        skill_store.update_skill(name, description, body, category)
        self._invalidate()
        SignalHub.instance().emit('skills.changed')
        return {'ok': True}

    def rename_skill(self, name, new_name):
        if not skill_store.rename_skill(name, new_name):
            return {'ok': False, 'error': 'rename-failed'}
        self._invalidate()
        SignalHub.instance().emit('skills.changed')
        return {'ok': True}

    def delete_skill(self, name):
        if not skill_store.delete_skill(name):
            return {'ok': False, 'error': 'not-found'}
        self._invalidate()
        SignalHub.instance().emit('skills.changed')
        return {'ok': True}

    # ---- 分组（分类）管理 ----
    def list_categories(self):
        return skill_store.list_categories()

    def add_category(self, name):
        ok = skill_store.add_category(name)
        if ok:
            SignalHub.instance().emit('skills.changed')
        return {'ok': ok}

    def get_category_icon(self, cat):
        return skill_store.get_category_icon(cat)

    def set_category_icon(self, cat, icon_key):
        skill_store.set_category_icon(cat, icon_key)
        SignalHub.instance().emit('skills.changed')
        return {'ok': True}

    def rename_category(self, old, new):
        n = skill_store.rename_category(old, new)
        if n:
            self._invalidate()
            SignalHub.instance().emit('skills.changed')
        return {'ok': True, 'updated': n}

    def delete_category(self, name):
        n = skill_store.delete_category(name)
        if n:
            self._invalidate()
            SignalHub.instance().emit('skills.changed')
        return {'ok': True, 'moved': n}

    # ---- 导入 / 导出 ----
    def export_skill(self, name, out_path):
        return skill_store.export_skill_to_zip(name, out_path)

    def export_skills(self, names, out_path):
        return skill_store.export_skills_to_zip(names, out_path)

    def import_skill(self, zip_path, mode='skip'):
        res = skill_store.import_skill_from_zip(zip_path, mode=mode)
        if res.get('ok') and res.get('imported'):
            self._invalidate()
            SignalHub.instance().emit('skills.changed')
        return res
