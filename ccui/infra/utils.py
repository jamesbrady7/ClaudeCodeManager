"""通用方法（基础设施层）：路径 / 时间转换等，所有人可调用。"""
import re
import datetime


def munge(p):
    """项目目录名编码（Claude Code 的 projects 目录名规则）。"""
    return re.sub(r'[^A-Za-z0-9_-]', '-', re.sub(r'[\\/:]', '-', p))


def norm_path(p):
    """统一路径分隔符为 '/'，去掉尾部 '/'。"""
    return re.sub(r'[\\/]+', '/', str(p)).rstrip('/')


def best_effort_decode(enc):
    """尽力把编码目录名还原为路径（仅对纯 ASCII 路径有效）。"""
    parts = enc.split('-')
    if len(parts) >= 2:
        return parts[0] + ':' + '/'.join(parts[1:])
    return enc


def iso_to_ms(ts):
    try:
        if '.' in ts:
            # Python <3.11 的 fromisoformat 只接受 ≤6 位小数；hook 写 7 位 → 截断。
            # 注意保留小数后的时区后缀（Z / ±HH:MM），否则会被当本地时间解析（差 8h）。
            base, _, frac = ts.partition('.')
            i = 0
            while i < len(frac) and frac[i].isdigit():
                i += 1
            digits, suffix = frac[:i], frac[i:]   # 纯小数位 + 时区后缀（Z / ±HH:MM）
            ts = base + '.' + digits[:6] + suffix
        return int(datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp() * 1000)
    except Exception:
        return 0


def ms_to_iso(ms):
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
