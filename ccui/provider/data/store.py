"""cc-config.json 读写仓储（provider 模块 data 层）。

本模块是 cc-config.json 的**唯一写通道**（cc-provider.ps1 的 switch 也写，
但 UI 侧写只走这里）。格式为兼容扩展：

  "provider config": {
    "default provider": "deepseek",
    "<name>": { baseUrl, apiKey, model, fastModel, models: [...] }
  }

- `models` 为新增的可选项（模型池）；`model`/`fastModel` 保留，语义 = 池中"主/快"。
  老 cc-config-read.ps1 只读四个老字段 → 新格式对旧启动器完全兼容。
- 读时无 `models` 由 provider_models() 从 [model, fastModel] **现算**（不回写、不脏化文件）。
- 读-改-写保留顶层与 provider 内的未知字段及键序（python dict 保插入序）。
- 原子写（临时文件 + os.replace），覆盖前滚动备份 cc-config.json.bak。
"""
import json
import os
import re
import shutil

from ccui.infra.config import CC_CONFIG_FILE, log

DEFAULT_KEY = 'default provider'
SECTION = 'provider config'

# 镜像 cc-config-read.ps1 的 Test-ValidModelName
_BAD_MODEL_PREFIX = re.compile(r'^(sk-|sk_|gsk_|AKIA|AIza)', re.I)


def provider_models(p):
    """模型池 = 显式 models 列表 ∪ {默认模型, 快速模型}（去重，保持顺序）。

    并集设计治「模型消失」bug（2026-08-28）：指针模型永远是池成员；旧格式无
    models 字段时至少含两个指针。⚠️ 但两个指针指向同一模型时推导不出第三个——
    所以 write_config 会把并集**物化**成显式 models 持久化，此后池成员与指针解耦。
    """
    pool = []
    raw = p.get('models')
    if isinstance(raw, list):
        pool.extend(x.strip() for x in raw if isinstance(x, str) and x.strip())
    for ptr in (p.get('model'), p.get('fastModel')):
        if isinstance(ptr, str) and ptr.strip():
            pool.append(ptr.strip())
    return [m for m in dict.fromkeys(pool)]


def valid_model_name(name):
    """模型名校验：拒空 / URL / key 样式前缀 / 空格 / 路径分隔符。"""
    if not name:
        return False
    t = name.strip()
    if not t or '://' in t or _BAD_MODEL_PREFIX.match(t):
        return False
    return not re.search(r'\s|[/\\]', t)


def valid_provider_name(name):
    """provider 名：非空、无空白/路径字符、不与保留键冲突（与 cc-provider.ps1 宽容度一致）。"""
    if not name:
        return False
    t = name.strip()
    if not t or t == DEFAULT_KEY or re.search(r'\s|[/\\:*?"<>|]', t):
        return False
    return True


def read_config():
    """读 cc-config.json → (default_provider, {name: cfg})。缺失/损坏返回空结构。"""
    try:
        with open(CC_CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception as e:
        log(f'读 cc-config.json 失败: {e}')
        return '', {}
    pc = data.get(SECTION) if isinstance(data, dict) else None
    if not isinstance(pc, dict):
        return '', {}
    providers = {k: v for k, v in pc.items()
                 if k != DEFAULT_KEY and isinstance(v, dict)}
    default = pc.get(DEFAULT_KEY) or ''
    return default, providers


def write_config(default, providers, materialize=True):
    """整体写回（读-改-写合并语义：保留顶层未知键与 provider 内未知字段）。

    providers: {name: dict}——调用方应在 read_config() 结果上改，未知字段自然带回。
    materialize=True：把模型池并集物化进各 provider 的 models 字段（默认开）。
    返回 True/False。
    """
    try:
        data = {}
        if os.path.exists(CC_CONFIG_FILE):
            try:
                with open(CC_CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    data = old  # 保留顶层未知键
            except Exception:
                pass
        pc = data.get(SECTION)
        if not isinstance(pc, dict):
            pc = {}
            data[SECTION] = pc
        # 重建 provider config：default 键置首，其余按 providers 顺序，保留各自未知字段
        merged = {DEFAULT_KEY: default}
        for name, cfg in providers.items():
            base = dict(pc.get(name) or {})
            base.update(cfg)
            # 物化模型池：显式持久化并集，令池成员与 默认/快速 指针解耦
            # （治「把默认+快速设同一模型 → 另一个消失」；见 provider_models）
            if materialize:
                base['models'] = provider_models(base)
            elif cfg.get('models') is not None:
                base['models'] = list(cfg['models'])
            merged[name] = base
        # 删除不在 providers 里的旧键
        for k in [k for k in pc if k != DEFAULT_KEY]:
            del pc[k]
        pc.update(merged)
        # 滚动备份后原子写
        if os.path.exists(CC_CONFIG_FILE):
            try:
                shutil.copy2(CC_CONFIG_FILE, CC_CONFIG_FILE + '.bak')
            except Exception:
                pass
        tmp = CC_CONFIG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CC_CONFIG_FILE)
        return True
    except Exception as e:
        log(f'写 cc-config.json 失败: {e}')
        return False
