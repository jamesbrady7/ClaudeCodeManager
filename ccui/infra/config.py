"""全局配置与日志（基础设施层）。"""
import os
import json
import datetime

CONFIG_DIR = os.environ.get('CLAUDE_CONFIG_DIR', r'D:\ClaudeCode')
PROJECTS = os.path.join(CONFIG_DIR, 'projects')
SESSIONS_DIR = os.path.join(CONFIG_DIR, 'sessions')
HISTORY = os.path.join(CONFIG_DIR, 'history.jsonl')
CLAUDE_JSON = os.path.join(CONFIG_DIR, '.claude.json')
LOG_FILE = os.path.join(CONFIG_DIR, 'cc-ui-qt.log')
PROVIDER_FILE = os.path.join(CONFIG_DIR, 'session-providers.json')
ROLES_DIR = os.path.join(CONFIG_DIR, 'roles')
SKILLS_DIR = os.path.join(CONFIG_DIR, 'skills')
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'assets')
UI_STATE_FILE = os.path.join(CONFIG_DIR, 'ui-state.json')

READONLY = os.environ.get('CC_UI_READONLY', '') == '1'


def load_ui_state():
    """读取轻量 UI 状态（上次 tab 等，不含任何密钥）。"""
    try:
        with open(UI_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(state):
    """保存轻量 UI 状态。"""
    try:
        with open(UI_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.datetime.now():%H:%M:%S}] {msg}\n')
    except Exception:
        pass
