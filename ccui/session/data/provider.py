"""Provider 配置与会话→provider 映射（会话模块 data 层）。"""
import json
import os

from ccui.infra.config import CC_CONFIG_FILE, PROVIDER_FILE, log

_provider_cache = {'key': None, 'map': {}}  # (mtime,size) → 映射，文件未变走缓存


def read_provider_mapping():
    """会话→provider 映射。文件未变时走缓存（热路径：每棵树重建都读）。"""
    try:
        st = os.stat(PROVIDER_FILE)
        key = (st.st_mtime, st.st_size)
    except Exception:
        return {}
    if _provider_cache.get('key') == key:
        return _provider_cache['map']
    try:
        with open(PROVIDER_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
    except Exception:
        mapping = {}
    _provider_cache['key'] = key
    _provider_cache['map'] = mapping
    return mapping


def write_provider_mapping(mapping):
    try:
        with open(PROVIDER_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        _provider_cache.clear()  # 写后失效缓存，下次读按新 mtime 重建
    except Exception as e:
        log(f'写 session-providers.json 失败: {e}')


def record_session_provider(sid, provider):
    """记录会话 → provider（映射优先的依据）。"""
    m = read_provider_mapping()
    if m.get(sid) == provider:
        return
    m[sid] = provider
    write_provider_mapping(m)


def list_providers():
    """返回 {names, default, providers}。"""
    try:
        cfg = json.load(open(CC_CONFIG_FILE, encoding='utf-8-sig'))
        pc = cfg.get('provider config') or {}
        names = [n for n in pc if n != 'default provider']
        return {
            'names': names,
            'default': pc.get('default provider'),
            'providers': {n: pc[n] for n in names},
        }
    except Exception:
        return {'names': [], 'default': None, 'providers': {}}


def infer_provider(models, providers):
    """从模型列表反推 provider：匹配 provider 模型池（models 或 model/fastModel）。

    两层配置后一个 provider 可有多个模型；此处不 import provider 模块（data 层
    隔离规则），models 字段本就在读到的 cfg 里，逻辑与 store.provider_models 同构。
    """
    want = set(models or [])
    for name, p in providers.items():
        pool = p.get('models') or [p.get('model'), p.get('fastModel')]
        if want & {m for m in pool if m}:
            return name
    return None


def resolve_provider(sid, models):
    """会话的 provider：映射 → 模型推断 → 全局 default。"""
    m = read_provider_mapping()
    if sid in m:
        return m[sid]
    provs = list_providers()
    inf = infer_provider(models, provs['providers'])
    if inf:
        return inf
    return provs['default']
