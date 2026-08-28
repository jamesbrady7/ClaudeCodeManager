"""Provider/模型管理业务（provider 模块 service 层）。

所有写操作成功后广播 `providers.changed`（谁改数据谁通知）。
返回统一 `(ok: bool, msg: str)`——View 直接展示 msg。
"""
import re

from ccui.infra.config import READONLY
from ccui.infra.signalhub import SignalHub
from ccui.provider.data import store


def _changed():
    SignalHub.instance().emit('providers.changed')


class ProviderService:

    # ---- 查询 ----
    def list_all(self):
        """(default, {name: cfg})——cfg 原样含 baseUrl/apiKey/model/fastModel(+models)。"""
        return store.read_config()

    def models_of(self, cfg):
        """provider 配置的模型池（兼容无 models 的旧格式）。"""
        return store.provider_models(cfg)

    @staticmethod
    def mask_key(key):
        """密钥掩码：前3…后4（短 key 全打点）。"""
        k = key or ''
        if len(k) <= 8:
            return '•' * max(6, len(k))
        return f'{k[:3]}…{k[-4:]}'

    # ---- provider 增删改 ----
    def add_provider(self, name, base_url, api_key, models):
        """新增 provider。models: 非空 list（首个=默认模型）；无 default 时自动设默认。"""
        if READONLY:
            return False, '只读模式'
        name = (name or '').strip()
        if not store.valid_provider_name(name):
            return False, 'Provider 名称无效（不能含空格/斜杠，且不能为保留字）'
        if not re.match(r'^https?://', (base_url or '').strip()):
            return False, 'baseUrl 需以 http:// 或 https:// 开头'
        models = [m.strip() for m in (models or []) if m.strip()]
        if not models:
            return False, '至少添加一个模型'
        for m in models:
            if not store.valid_model_name(m):
                return False, f'模型名无效：{m}（不能含空格/斜杠/key 样式前缀）'
        default, providers = store.read_config()
        if name in providers:
            return False, f'Provider「{name}」已存在'
        providers[name] = {
            'baseUrl': base_url.strip(),
            'apiKey': (api_key or '').strip(),
            'model': models[0],
            'fastModel': models[0],
            'models': models,
        }
        if not default:
            default = name
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, f'已创建 Provider「{name}」'

    def update_provider(self, old_name, name, base_url, api_key):
        """编辑 provider（name 变化 = 重命名，保持位置与未知字段）。

        重命名后 session-providers.json 里指向旧名的映射失配——resolve_provider
        会优雅回退（模型推断→全局默认），不影响使用。
        """
        if READONLY:
            return False, '只读模式'
        name = (name or '').strip()
        if not store.valid_provider_name(name):
            return False, 'Provider 名称无效'
        if not re.match(r'^https?://', (base_url or '').strip()):
            return False, 'baseUrl 需以 http:// 或 https:// 开头'
        default, providers = store.read_config()
        if old_name not in providers:
            return False, f'Provider「{old_name}」不存在'
        if name != old_name and name in providers:
            return False, f'Provider「{name}」已存在'
        cfg = dict(providers[old_name])  # 保留 models/model/fastModel 等未知字段
        cfg['baseUrl'] = base_url.strip()
        cfg['apiKey'] = (api_key or '').strip()
        if name == old_name:
            providers[name] = cfg
        else:
            # 重建保序：重命名发生在原位
            rebuilt = {}
            for k, v in providers.items():
                if k == old_name:
                    rebuilt[name] = cfg
                else:
                    rebuilt[k] = v
            providers = rebuilt
            if default == old_name:
                default = name
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, '已保存' if name == old_name else f'已重命名为「{name}」'

    def delete_provider(self, name):
        """删除 provider；删的是默认则自动顺延到剩余首个（删空则置空）。"""
        if READONLY:
            return False, '只读模式'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        del providers[name]
        if default == name:
            default = next(iter(providers), '')
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, f'已删除 Provider「{name}」'

    def set_default(self, name):
        if READONLY:
            return False, '只读模式'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        if default == name:
            return True, '已是默认 Provider'
        if not store.write_config(name, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, f'默认 Provider → {name}'

    # ---- 模型池操作 ----
    def add_model(self, name, model, set_main=False):
        if READONLY:
            return False, '只读模式'
        model = (model or '').strip()
        if not store.valid_model_name(model):
            return False, '模型名无效（不能含空格/斜杠/key 样式前缀）'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        cfg = providers[name]
        ms = store.provider_models(cfg)
        if model in ms:
            return False, f'模型「{model}」已存在'
        ms.append(model)
        cfg['models'] = ms
        if set_main or not cfg.get('model'):
            cfg['model'] = model
        if not cfg.get('fastModel'):
            cfg['fastModel'] = model
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, f'已添加模型「{model}」'

    def rename_model(self, name, old_model, new_model):
        """改名并同步更新引用它的 model/fastModel 字段。"""
        if READONLY:
            return False, '只读模式'
        new_model = (new_model or '').strip()
        if not store.valid_model_name(new_model):
            return False, '模型名无效'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        cfg = providers[name]
        ms = store.provider_models(cfg)
        if old_model not in ms:
            return False, f'模型「{old_model}」不存在'
        if new_model != old_model and new_model in ms:
            return False, f'模型「{new_model}」已存在'
        cfg['models'] = [new_model if m == old_model else m for m in ms]
        if cfg.get('model') == old_model:
            cfg['model'] = new_model
        if cfg.get('fastModel') == old_model:
            cfg['fastModel'] = new_model
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, '已重命名模型'

    def remove_model(self, name, model):
        """删除模型；被主/快引用时拒绝（提示先换）。"""
        if READONLY:
            return False, '只读模式'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        cfg = providers[name]
        ms = store.provider_models(cfg)
        if model not in ms:
            return False, f'模型「{model}」不存在'
        if len(ms) <= 1:
            return False, '至少保留一个模型（要删整个 Provider 请用「删除」）'
        roles = []
        if cfg.get('model') == model:
            roles.append('默认模型')
        if cfg.get('fastModel') == model:
            roles.append('快速模型')
        if roles:
            return False, f'「{model}」是当前{"和".join(roles)}，请先换其他模型再删'
        cfg['models'] = [m for m in ms if m != model]
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        return True, f'已删除模型「{model}」'

    def set_main(self, name, model):
        return self._set_role(name, 'model', model)

    def set_fast(self, name, model):
        return self._set_role(name, 'fastModel', model)

    def _set_role(self, name, field, model):
        if READONLY:
            return False, '只读模式'
        default, providers = store.read_config()
        if name not in providers:
            return False, f'Provider「{name}」不存在'
        cfg = providers[name]
        # 先固化旧池再动指针——否则旧格式（无 models）下把默认/快速设成同一模型，
        # 另一个模型会从推导池中消失（provider_models 只并 {两个指针}）。
        cfg['models'] = store.provider_models(cfg)
        if model not in cfg['models']:
            return False, f'模型「{model}」不在池中'
        if cfg.get(field) == model:
            return True, '已是当前设置'
        cfg[field] = model
        if not store.write_config(default, providers):
            return False, '写入配置文件失败'
        _changed()
        label = '默认模型' if field == 'model' else '快速模型'
        return True, f'{label} → {model}'
