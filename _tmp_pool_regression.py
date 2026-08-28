import os, sys, io, glob
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import py_compile
for f in glob.glob('ccui/**/*.py', recursive=True):
    py_compile.compile(f, doraise=True)
print('compile OK')

# ---- 纯逻辑回归：用临时 config，模拟「默认+快速设同一模型 → 另一个不消失」----
import tempfile, json
tmp = os.path.join(tempfile.gettempdir(), 'cc_pool_regression.json')
io.open(tmp, 'w', encoding='utf-8').write(json.dumps({'provider config': {
    'default provider': 'glm',
    'glm': {'baseUrl': 'https://x', 'apiKey': 'k',
            'model': 'glm-5.2', 'fastModel': 'glm-4.7'},   # 旧格式：无 models
}}, ensure_ascii=False))
from ccui.provider.data import store
store.CC_CONFIG_FILE = tmp
from ccui.provider.service.provider_service import ProviderService
svc = ProviderService()

# 关键复现：把快速模型也设成 glm-5.2（与默认相同）
ok, msg = svc.set_fast('glm', 'glm-5.2')
print('set_fast==default:', ok, msg)
# 物化后 glm-4.7 必须还在池里
d, p = store.read_config()
pool = p['glm']['models']
print('pool after set_fast:', pool)
assert 'glm-4.7' in pool, 'glm-4.7 消失了（回归失败）'
assert 'glm-5.2' in pool
assert p['glm']['model'] == 'glm-5.2' and p['glm']['fastModel'] == 'glm-5.2'

# 删除被引用的默认模型应被守卫拒绝
ok, msg = svc.remove_model('glm', 'glm-5.2')
print('remove referenced default:', ok, msg)
assert not ok

# 删掉非引用模型正常
ok, msg = svc.set_default('glm'); svc.set_main('glm', 'glm-4.7'); svc.set_fast('glm', 'glm-4.7')
ok, msg = svc.remove_model('glm', 'glm-5.2')   # 现在 glm-5.2 不再是引用
print('remove unreferenced:', ok, msg)
assert ok and store.provider_models(store.read_config()[1]['glm']) == ['glm-4.7']

# ---- UI：模型池渲染（默认/快速标记）+ 建会话下拉（去快、空池占位）----
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
# 恢复一个双模型 provider 供面板测
store.write_config('glm', {'glm': {'baseUrl': 'https://x', 'apiKey': 'k-1234567890ab',
                                   'model': 'glm-5.2', 'fastModel': 'glm-4.7',
                                   'models': ['glm-5.2', 'glm-4.7']}})
from ccui.session.view.dialogs import ModelComboBox
cb = ModelComboBox()
cfg = store.read_config()[1]['glm']
cb.populate(cfg)
texts = [cb.itemText(i) for i in range(cb.count())]
print('combo texts:', texts)
assert not any('快' in t for t in texts), '快速标签仍出现在建会话下拉'
assert any('默认' in t for t in texts)
assert cb.itemData(cb.findText([t for t in texts if '5.2' in t and '默认' in t][0])) == 'glm-5.2'
empty = ModelComboBox(); empty.populate({'model': '', 'fastModel': ''})
print('empty combo:', empty.itemText(0), '| model()=', repr(empty.currentData()))
assert empty.count() == 1 and empty.currentData() == ''

os.remove(tmp)
print('\nALL PASS')
