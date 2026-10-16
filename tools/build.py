# SPDX-License-Identifier: GPL-3.0-or-later
"""从源码生成可安装 ZIP，不修改 Blender 安装。"""
from pathlib import Path
import ast
import argparse
import hashlib
import json
import os
import shutil
import string
from collections import Counter
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'animatica_zh_cn'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', help='发布时验证 Git 标签与插件版本一致，例如 v1.1.0')
    args = parser.parse_args()
    info = ast.parse((PACKAGE / '__init__.py').read_text(encoding='utf-8'))
    assignment = next(n for n in info.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in n.targets))
    version = '.'.join(map(str, ast.literal_eval(assignment.value)['version']))
    if args.tag and args.tag != f'v{version}':
        parser.error(f'标签 {args.tag} 与插件版本 v{version} 不一致')
    catalog = json.loads((PACKAGE / 'zh_CN.json').read_text(encoding='utf-8'))
    formatter = string.Formatter()
    for english, chinese in catalog.items():
        original = Counter(field for _, field, _, _ in formatter.parse(english) if field is not None)
        translated = Counter(field for _, field, _, _ in formatter.parse(chinese) if field is not None)
        if original != translated:
            parser.error(f'译文占位符不匹配：{english!r}')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / f'Animatica_zh_CN_{version}.zip'
    allowed = {'.py', '.json', '.txt'}
    files = sorted(p for p in PACKAGE.rglob('*') if p.is_file() and p.suffix in allowed and '__pycache__' not in p.parts)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in files:
            entry = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o644 << 16
            z.writestr(entry, path.read_text(encoding='utf-8').encode('utf-8'))
        entry = zipfile.ZipInfo('安装说明.md', date_time=(2026, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.create_system = 3
        entry.external_attr = 0o644 << 16
        z.writestr(entry, (output / '安装说明.md').read_text(encoding='utf-8').encode('utf-8'))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    # A stable ASCII filename supports a permanent one-click download link.
    download = output / 'Animatica_zh_CN.zip'
    shutil.copyfile(archive, download)
    (output / 'INSTALL_zh_CN.md').write_bytes((output / '安装说明.md').read_text(encoding='utf-8').encode('utf-8'))
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  {download.name}\n{digest}  {archive.name}\n', encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write(f'archive=dist/{archive.name}\n')
    print(json.dumps({'archive': archive.name, 'sha256': digest, 'files': len(files)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
