"""技能模块：独立资产库（data/service/view 三层）。

技能是全局技能库 `skills/<name>/SKILL.md` 的一等公民，通过 frontmatter 的
`uuid` 作稳定身份；角色 meta.json 以 uuid 数组引用技能（改名不破坏引用）。
"""
