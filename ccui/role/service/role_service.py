"""角色管理业务层（角色模块 service）：创建/启动/删除角色、技能管理。

调用本模块 data 层 + infra；不依赖其他业务模块的 Data/Service（隔离）。
会话存在/运行态等查询由 View 层编排 RoleManager + SessionManager 完成。
"""
import os
import uuid
import datetime

from ccui.infra.config import ROLES_DIR
from ccui.infra.process import spawn_terminal
from ccui.infra.signalhub import SignalHub
from ccui.role.data import store as role_store
from ccui.role.data.manager import RoleManager

RESERVED_NAMES = {'new', 'list', 'ls', 'help', 'rm', 'roles', 'role'}


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _persona_template(name, desc):
    """角色人设模板（与 cc-role.ps1 一致）。"""
    knowledge = os.path.join(ROLES_DIR, name, 'knowledge.md')  # 用真实配置路径，勿硬编码
    inherit = os.path.join(ROLES_DIR, name, 'inherit.md')
    t = f"""# 角色：{name}

{desc}

你是 {name}，一个拥有长期记忆的资深专家。你的知识库文件是：
{knowledge}

## 会话开始
每次会话开始时，第一步用 Read 阅读知识库 {knowledge}。
若存在 {inherit}，一并阅读它（那是本次继承的要点）。
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
"""
    t += '\n现在，请先 Read 知识库文件，然后等待任务。\n'
    return t


def _knowledge_template(name):
    return f"""# 知识库：{name}

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
"""


class RoleService:
    # ---- 角色 ----
    def list_roles(self):
        return RoleManager.instance().roles()

    def create_role(self, name, description, skills):
        name = (name or '').strip()
        if not name or not role_store.NAME_RE.match(name) or name in RESERVED_NAMES:
            return {'ok': False, 'error': 'invalid-name'}
        if os.path.exists(role_store.role_dir(name)):
            return {'ok': False, 'error': 'exists'}
        os.makedirs(role_store.role_dir(name), exist_ok=True)
        skills = [s for s in (skills or []) if s]
        meta = {'name': name, 'description': description or f'角色 {name}',
                'skills': skills, 'created': _now_iso(), 'uuid': str(uuid.uuid4())}
        role_store.write_meta(name, meta)
        # persona.md 只存基础人设；技能由启动器（cc-role.ps1）动态注入，避免重复
        role_store.write_persona(name, _persona_template(name, meta['description']))
        role_store.write_knowledge(name, _knowledge_template(name))
        role_store.set_default_icon(name)  # 默认用图标库第一个 SVG 作头像
        SignalHub.instance().emit('roles.changed')
        return {'ok': True}

    def update_role(self, name, new_name, description, icon_path=None):
        """编辑角色信息：可选重命名 + 描述 + 图标。"""
        new_name = (new_name or name).strip()
        if not new_name or not role_store.NAME_RE.match(new_name) or new_name in RESERVED_NAMES:
            return {'ok': False, 'error': 'invalid-name'}
        if new_name != name and os.path.exists(role_store.role_dir(new_name)):
            return {'ok': False, 'error': 'exists'}
        if new_name != name:
            try:
                os.rename(role_store.role_dir(name), role_store.role_dir(new_name))
            except Exception as e:
                return {'ok': False, 'error': f'rename: {e}'}
        meta = role_store.read_meta(new_name)
        meta['name'] = new_name
        meta['description'] = description or f'角色 {new_name}'
        role_store.write_meta(new_name, meta)
        if icon_path:
            role_store.write_role_icon(new_name, icon_path)
        SignalHub.instance().emit('roles.changed')
        return {'ok': True, 'name': new_name}

    def delete_role(self, name):
        if not name or not role_store.NAME_RE.match(name):
            return {'ok': False, 'error': 'invalid-name'}
        d = role_store.role_dir(name)
        if os.path.exists(d):
            import shutil
            shutil.rmtree(d)
        SignalHub.instance().emit('roles.changed')
        return {'ok': True}

    def set_role_icon(self, name, src):
        """设置角色自定义图标（复制为 roles/<name>/icon.png）。"""
        if not name or not role_store.NAME_RE.match(name):
            return {'ok': False, 'error': 'invalid-name'}
        role_store.write_role_icon(name, src)
        SignalHub.instance().emit('roles.changed')
        return {'ok': True}

    def start_role(self, name, from_ids=None, cwd=None, mode='normal'):
        args = ['cc', 'role', name]
        if from_ids:
            args += ['--from', ','.join(from_ids)]
        if mode == 'danger':
            args += ['--mode', 'danger']
        return spawn_terminal(args, cwd or os.path.dirname(role_store.ROLES_DIR))

    # ---- 技能（uuid 引用，业务在 skill 模块；这里只把 uuid 当不透明数组写入 meta）----
    def update_role_skills(self, name, skill_uuids):
        """更新角色引用的技能 uuid 数组并广播 roles.changed。

        技能内容/解析在 skill 模块；persona 保持基础人设（技能由
        track-session.ps1 启动时按 uuid 注入）。
        """
        meta = role_store.read_meta(name)
        meta['skills'] = [u for u in (skill_uuids or []) if u]
        role_store.write_meta(name, meta)
        SignalHub.instance().emit('roles.changed')
        return {'ok': True}

    def get_knowledge(self, name):
        return role_store.read_knowledge(name)

    def write_knowledge(self, name, content):
        role_store.write_knowledge(name, content)
        return {'ok': True}

    def export_role(self, name, out_path):
        """导出角色（白名单 zip）。"""
        return role_store.export_role_to_zip(name, out_path)

    def import_role(self, zip_path, mode='skip', new_name=''):
        """从 zip 导入角色，成功后广播 roles.changed。"""
        res = role_store.import_role_from_zip(zip_path, mode=mode, new_name=new_name)
        if res.get('ok'):
            SignalHub.instance().emit('roles.changed')
        return res
