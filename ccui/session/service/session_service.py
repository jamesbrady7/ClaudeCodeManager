"""会话管理业务层（会话模块 service）：新建 / 恢复 / 删除 / 占位生命周期 / Provider 解析。

持有 spawned（占位生命周期）状态；调用本模块 data 层 + infra；无 Qt 事件循环依赖。
"""
import os
import json
import time
import datetime

from ccui.infra.config import CONFIG_DIR
from ccui.infra.process import spawn_terminal
from ccui.infra.signalhub import SignalHub
from ccui.infra.utils import trunc, text_content, iso_to_ms
from ccui.session.data import store
from ccui.session.data import provider as provider_data
from ccui.session.data.manager import SessionManager
from ccui.session.data.models import SpawnedSession


class SessionService:
    """会话管理业务。"""

    def __init__(self):
        self.manager = SessionManager.instance()

    @property
    def spawned(self):
        """占位生命周期状态（会话模块共享的 SessionManager 持有）。"""
        return self.manager.spawned

    # ---- 查询 ----
    def scan(self):
        """扫描会话列表（含占位合并）。返回 (sessions, totals)。"""
        return self.manager.scan()

    def resolve_provider(self, sid, models):
        return provider_data.resolve_provider(sid, models)

    def provider_map(self, sessions):
        """{sid: provider}：读一次映射文件，其余按模型推断 / 全局默认。"""
        mapping = provider_data.read_provider_mapping()
        provs = provider_data.list_providers()
        out = {}
        for s in sessions:
            prov = mapping.get(s.id)
            if not prov:
                prov = provider_data.infer_provider(s.models, provs['providers'])
            if not prov:
                prov = provs['default']
            out[s.id] = prov
        return out

    def list_providers(self):
        return provider_data.list_providers()

    def detect_permission_mode(self, sid):
        return store.detect_permission_mode(sid)

    # ---- 动作 ----
    def new_session(self, cwd, provider, mode='normal', inherit_path=None):
        """以指定 provider+权限模式在 cwd 启动新会话，登记占位。返回 SpawnedSession 或 None。

        mode: 'normal' | 'danger'（danger 时 `cc danger ...` 跳过权限确认）。
        inherit_path 给定时通过 CC_INHERIT 环境变量传给 SessionStart hook，
        让新会话先读继承摘要文件。
        """
        args = ['cc']
        if mode == 'danger':
            args.append('danger')
        if provider and provider != '(无)':
            args += ['--provider', provider]
        env = {'CC_INHERIT': inherit_path} if inherit_path else None
        proc = spawn_terminal(args, cwd, env=env)
        if proc is None:
            return None
        if hasattr(proc, 'poll'):
            spawned = SpawnedSession(cwd=cwd, startedAt=int(time.time() * 1000),
                                     pid=proc.pid, proc=proc, provider=provider)
        else:
            spawned = SpawnedSession(cwd=cwd, startedAt=int(time.time() * 1000),
                                     pid=proc, proc=None, provider=provider)
        self.manager.register_spawn(spawned)
        return spawned

    def delete(self, ids):
        """批量删除会话（含孤儿清理与 history/.claude.json 清理）。

        删除成功后广播 sessions.changed，各视图据此刷新（而非 View 直接操作列表）。
        """
        res = store.delete_many(ids)
        if res['deleted']:
            SignalHub.instance().emit('sessions.changed')
        return res

    def build_inherit(self, ids):
        """生成继承摘要文件（镜像 cc-role.ps1 的 Write-Inherit）。返回文件路径。

        供「新建会话 / 创建角色会话」选继承时用：把源会话的问答文本摘要写入
        CONFIG_DIR\\inherit\\<ms>.md，再由 SessionStart hook（CC_INHERIT）让新会话先读它。
        """
        ids = [x for x in (ids or []) if x]

        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        out = [f'# 继承自 {len(ids)} 个会话', '', f'生成时间: {now}', '']
        budget = 0
        for sid in ids:
            out.append(f'## 会话 {sid}')
            found = store.locate_session(sid)
            if not found:
                out += ['（未找到记录）', '']
                continue
            path = found[0]['path']
            title = cwd = first_ts = ''
            blocks = []
            try:
                with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    raw = f.read()
            except Exception:
                raw = ''
            for line in raw.splitlines():
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                if not first_ts and o.get('timestamp'):
                    ts_ms = iso_to_ms(o['timestamp'])
                    if ts_ms and ts_ms <= int(time.time() * 1000) + 3600 * 1000:
                        first_ts = o['timestamp']
                if o.get('type') == 'user':
                    if not title:
                        title = trunc(text_content(o.get('message')), 80)
                        cwd = o.get('cwd', '')
                    t = text_content(o.get('message'))
                    if t:
                        blocks.append('用户: ' + trunc(t, 800))
                elif o.get('type') == 'assistant':
                    t = text_content(o.get('message'))
                    if t:
                        blocks.append('助手: ' + trunc(t, 800))
                while len(blocks) > 60:
                    blocks.pop(0)
            out.append(f'标题: {title}')
            if cwd:
                out.append(f'目录: {cwd}')
            if first_ts:
                out.append(f'开始: {first_ts}')
            out.append('')
            out += blocks if blocks else ['（无可提取的问答文本）']
            out.append('')
            budget += sum(len(x) for x in blocks)
            if budget >= 30000:
                out.append('（超出摘要预算，已截断）')
                break
        d = os.path.join(CONFIG_DIR, 'inherit')
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f'{int(time.time() * 1000)}.md')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        return p

    def export_sessions(self, ids, out_path):
        """导出选中会话到 zip。"""
        return store.export_sessions_to_zip(ids, out_path)

    def import_session(self, zip_path, overwrite=False):
        """从 zip 导入会话，成功后广播 sessions.changed。"""
        res = store.import_session_from_zip(zip_path, overwrite=overwrite)
        if res.get('ok') and res.get('imported'):
            SignalHub.instance().emit('sessions.changed')
        return res

    def resume(self, sid, mode, provider):
        """以指定模式+provider 恢复会话，并记录会话→provider 映射。"""
        provider_data.record_session_provider(sid, provider)
        if mode == 'danger':
            args = ['cc', 'danger', '--resume', sid, '--provider', provider]
        else:
            args = ['cc', 'resume', sid, '--provider', provider]
        ok = spawn_terminal(args, CONFIG_DIR) is not None
        if ok:
            SignalHub.instance().emit('sessions.changed')
        return ok

