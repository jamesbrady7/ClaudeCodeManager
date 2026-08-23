"""Provider 配置与会话→provider 映射（会话模块 data 层）。"""
import json
import os

from ccui.infra.config import CONFIG_DIR, PROVIDER_FILE, log


def read_provider_mapping():
    try:
        with open(PROVIDER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def write_provider_mapping(mapping):
    try:
        with open(PROVIDER_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
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
        cfg = json.load(open(os.path.join(CONFIG_DIR, 'cc-config.json'), encoding='utf-8'))
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
    """从模型列表反推 provider：匹配任一 provider 的 model/fastModel。"""
    for name, p in providers.items():
        ms = {p.get('model'), p.get('fastModel')} - {None}
        if set(models or []) & ms:
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
