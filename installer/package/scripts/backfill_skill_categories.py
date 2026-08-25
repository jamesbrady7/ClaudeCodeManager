"""安装 ui-ux-pro-max 技能 + 给所有已装技能回填 category frontmatter。

用法: python scripts/backfill_skill_categories.py
- 从 /tmp/ui-ux-pro-max-skill/.claude/skills/ 复制缺失的技能到 D:\\ClaudeCode\\skills\\
- 对 skills\\<name>\\SKILL.md 若无 category: 行则在 name: 行后注入
"""
import os
import re
import shutil

CONFIG = r'D:\ClaudeCode'
SRC = r'C:\Users\Zz\AppData\Local\Temp\ui-ux-pro-max-skill\.claude\skills'
SKILLS = os.path.join(CONFIG, 'skills')

# 每个技能的类型（权威映射；不在映射里的用关键字推断）
CATS = {
    # Emil Kowalski 系列（动效/设计工程）
    'animate': '动效动画', 'animation-vocabulary': '动效动画',
    'apple-design': '动效动画', 'apple-ui': '界面设计',
    'emil-design-eng': '界面设计',
    'find-animation-opportunities': '动效动画', 'review-animations': '动效动画',
    # ui-ux-pro-max 系列
    'banner-design': '内容演示', 'brand': '品牌视觉', 'design': '综合',
    'design-system': '设计系统', 'slides': '内容演示',
    'ui-styling': '界面设计', 'ui-ux-pro-max': '界面设计',
}


def infer_cat(name, desc):
    text = f'{name} {desc}'.lower()
    rules = [
        ('动效动画', ('animat', 'motion', '动效', '动画', 'spring', 'gesture',
                      'interrupt', 'rubber', 'bounce', 'swipe', 'drag', 'physics')),
        ('设计系统', ('design system', 'design-system', 'design token', '设计系统', 'token')),
        ('品牌视觉', ('brand', '品牌', 'logo', '标识', 'identity', 'corporate identity')),
        ('内容演示', ('slide', 'presentation', 'banner', 'social', '演示', '幻灯片', '海报', 'chart')),
        ('界面设计', ('ui', 'interface', '界面', 'web', 'macos', 'apple', 'tailwind', 'shadcn',
                      'css', 'component', 'accessible', 'frontend', 'desktop', 'responsive',
                      'typography', 'color', '用户')),
        ('综合', ('design', '设计')),
    ]
    for label, kws in rules:
        if any(k in text for k in kws):
            return label
    return '其他'


def install_new():
    if not os.path.isdir(SRC):
        print(f'[skip] 源仓库不存在: {SRC}')
        return
    os.makedirs(SKILLS, exist_ok=True)
    for d in os.listdir(SRC):
        src = os.path.join(SRC, d)
        if not os.path.isdir(src) or not os.path.exists(os.path.join(src, 'SKILL.md')):
            continue
        dst = os.path.join(SKILLS, d)
        if os.path.exists(dst):
            print(f'[skip] 已存在: {d}')
            continue
        shutil.copytree(src, dst)
        print(f'[copy] {d}')


def backfill_categories():
    if not os.path.isdir(SKILLS):
        return
    for d in os.listdir(SKILLS):
        p = os.path.join(SKILLS, d, 'SKILL.md')
        if not os.path.isfile(p):
            continue
        with open(p, 'r', encoding='utf-8') as f:
            raw = f.read()
        if not raw.startswith('---'):
            continue
        parts = raw.split('---', 2)
        if len(parts) < 3:
            continue
        front, body = parts[1], parts[2]
        if re.search(r'^\s*category\s*:', front, re.MULTILINE):
            continue
        # 提取 name/description 用于推断
        name = d
        desc = ''
        m = re.search(r'^\s*name\s*:\s*(.+)$', front, re.MULTILINE)
        if m:
            name = m.group(1).strip().strip('"\'')
        m = re.search(r'^\s*description\s*:\s*(.+)$', front, re.MULTILINE)
        if m:
            desc = m.group(1).strip().strip('"\'')
        cat = CATS.get(name) or infer_cat(name, desc)
        # 在 name: 行后注入 category
        lines = front.splitlines()
        out = []
        injected = False
        for ln in lines:
            out.append(ln)
            if not injected and re.match(r'^\s*name\s*:', ln):
                out.append(f'category: {cat}')
                injected = True
        if not injected:
            out.append(f'category: {cat}')
        new_front = '\n'.join(out)
        # 关键：闭合分隔符必须独占一行（否则 YAML/frontmatter 解析器会把 `---` 粘到上一行）
        new_raw = '---' + new_front + '\n' + '---' + body
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(new_raw)
        print(f'[cat] {d} -> {cat}')


if __name__ == '__main__':
    install_new()
    backfill_categories()
    print('done')
