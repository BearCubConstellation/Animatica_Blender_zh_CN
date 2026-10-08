# SPDX-License-Identifier: GPL-3.0-or-later
"""从源码生成可安装 ZIP，不修改 Blender 安装。"""
from pathlib import Path
import ast
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'animatica_zh_cn'

def main():
    info = ast.parse((PACKAGE / '__init__.py').read_text(encoding='utf-8'))
    assignment = next(n for n in info.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in n.targets))
    version = '.'.join(map(str, ast.literal_eval(assignment.value)['version']))
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / f'Animatica_简体中文_{version}.zip'
    allowed = {'.py', '.json', '.txt'}
    files = sorted(p for p in PACKAGE.rglob('*') if p.is_file() and p.suffix in allowed and '__pycache__' not in p.parts)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in files:
            entry = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, path.read_bytes())
        entry = zipfile.ZipInfo('安装说明.md', date_time=(2026, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        z.writestr(entry, (output / '安装说明.md').read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(json.dumps({'archive': archive.name, 'sha256': digest, 'files': len(files)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
