"""角色数据模型（角色模块 data 层）。"""
from dataclasses import dataclass, field


@dataclass
class Role:
    """一个角色：人设 + 知识库 + 技能；持有该角色追踪的会话 uuid 列表。"""
    name: str
    description: str
    skills: list = field(default_factory=list)
    created: str = ''
    uuid: str = ''                     # 稳定标识（旧角色由 RoleManager 回填）
    session_ids: list = field(default_factory=list)  # 该角色的会话 uuid 列表
    sessionCount: int = 0
    knowledgeSize: int = 0
    knowledgeExists: bool = False


@dataclass
class Skill:
    """一个技能（SKILL.md）：全局或角色专属。"""
    name: str
    description: str
    content: str = ''
    body: str = ''      # 去掉 frontmatter 后的指令正文
    path: str = ''
    source: str = ''  # 'global' | 'role'
