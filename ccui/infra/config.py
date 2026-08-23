"""全局配置与日志（基础设施层）。"""
import os
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

READONLY = os.environ.get('CC_UI_READONLY', '') == '1'


def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.datetime.now():%H:%M:%S}] {msg}\n')
    except Exception:
        pass
