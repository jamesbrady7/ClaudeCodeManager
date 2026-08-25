"""技能数据模型（技能模块 data 层）。"""
from dataclasses import dataclass


@dataclass
class Skill:
    """一个技能（SKILL.md）：全局技能库的一员。

    uuid 是稳定身份（frontmatter `uuid:`），改名/换目录不失效；
    角色 meta.json 以 uuid 数组引用技能。
    """
    name: str            # 目录名 == frontmatter name
    description: str
    category: str = ''
    uuid: str = ''       # 稳定身份（SKILL.md frontmatter）
    content: str = ''    # 完整文件内容
    body: str = ''       # 去 frontmatter 后的指令正文
    path: str = ''
    source: str = 'global'  # 角色专属已废弃，恒 'global'
