"""通用 zip 打包/解包工具（基础设施层，人人可调）。

统一 manifest 约定（各模块自己写）：
  {"kind": "cc.sessions" | "cc.skill" | "cc.role", "version": 1, ...模块特有字段}
"""
import os
import json
import zipfile


def make_zip(out_path, entries, compression=zipfile.ZIP_DEFLATED):
    """打包 zip。entries 支持两种：
      (arcname, abs_path)        文件/目录 → 从磁盘写
      (arcname, None, text)      内联文本 → zf.writestr（如 manifest.json）
    返回写入的 arcname 列表。
    """
    written = []
    with zipfile.ZipFile(out_path, 'w', compression) as zf:
        for entry in entries:
            if len(entry) == 3:
                arcname, _, content = entry
                zf.writestr(arcname.replace('\\', '/'), content)
                written.append(arcname.replace('\\', '/'))
                continue
            arcname, abs_path = entry
            arcname = arcname.replace('\\', '/').rstrip('/')
            if os.path.isdir(abs_path):
                for root, _dirs, files in os.walk(abs_path):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, abs_path).replace('\\', '/')
                        zf.write(full, f'{arcname}/{rel}')
                        written.append(f'{arcname}/{rel}')
            elif os.path.isfile(abs_path):
                zf.write(abs_path, arcname)
                written.append(arcname)
    return written


def safe_extract_zip(zip_path, dest_dir, members=None):
    """解包到 dest_dir。防 zip-slip：拒绝绝对路径 / 含 .. 的成员，目标必须落在 dest_dir 内。"""
    dest_dir = os.path.abspath(dest_dir)
    extracted = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            if members is not None and info.filename not in members:
                continue
            name = info.filename.replace('\\', '/')
            if name.startswith('/') or '..' in name.split('/'):
                raise ValueError(f'不安全的 zip 成员: {info.filename}')
            target = os.path.abspath(os.path.join(dest_dir, name))
            if not (target == dest_dir or target.startswith(dest_dir + os.sep)):
                raise ValueError(f'zip 成员逃逸目标目录: {info.filename}')
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, 'wb') as dst:
                dst.write(src.read())
            extracted.append(target)
    return extracted


def read_zip_json(zip_path, member):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        with zf.open(member) as f:
            return json.load(f)


def zip_read_manifest(zip_path):
    """读取包内根 manifest.json。"""
    return read_zip_json(zip_path, 'manifest.json')


def zip_namelist(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return zf.namelist()


def zip_member_exists(zip_path, member):
    with zipfile.ZipFile(zip_path, 'r') as zf:
        return member in zf.namelist()
