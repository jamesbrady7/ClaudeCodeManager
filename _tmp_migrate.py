"""一次性迁移：恢复 glm-5.2 + 物化所有 provider 的显式模型池。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccui.provider.data import store

default, providers = store.read_config()
# 修复被「默认=快速=glm-4.7」推导吞掉的 glm-5.2；恢复模板默认（主 glm-5.2 / 快 glm-4.7）
g = providers['glm']
g['model'] = 'glm-5.2'
g['fastModel'] = 'glm-4.7'
g['models'] = ['glm-5.2', 'glm-4.7']
assert store.write_config(default, providers)  # materialize=True：全量物化

d, p = store.read_config()
for name, cfg in p.items():
    print(name, '| model:', cfg.get('model'), '| fast:', cfg.get('fastModel'),
          '| pool:', cfg.get('models'))
assert p['glm']['models'] == ['glm-5.2', 'glm-4.7']
