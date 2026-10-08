# SPDX-License-Identifier: GPL-3.0-or-later
"""隔离测试：复制官方插件，不改变真实工作配置或下载新版本。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--addon', type=Path, required=True, help='官方 animatica_blender 目录')
    args = parser.parse_args()
    official, blender = args.addon.resolve(), args.blender.resolve()
    if not blender.is_file() or not (official / '__init__.py').is_file():
        parser.error('Blender 可执行文件或官方插件目录不存在')
    scratch = ROOT / '.work'
    scratch.mkdir(exist_ok=True)
    isolated = Path(tempfile.mkdtemp(prefix='validation-', dir=scratch))
    addons = isolated / 'scripts/addons'
    addons.mkdir(parents=True)
    baseline = hashes(official)
    shutil.copytree(official, addons / 'animatica_blender', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT / 'animatica_zh_cn', addons / 'animatica_zh_cn', ignore=shutil.ignore_patterns('__pycache__'))
    env = dict(os.environ, BLENDER_USER_RESOURCES=str(isolated), ANIMATICA_ZH_TEST_OUTPUT=str(isolated))
    for key in ('CONFIG', 'SCRIPTS', 'DATAFILES', 'EXTENSIONS'):
        path = isolated / key.lower()
        path.mkdir(exist_ok=True)
        env['BLENDER_USER_' + key] = str(path)

    def run(script, factory=False, extra=()):
        command = [str(blender), '--background']
        if factory:
            command.append('--factory-startup')
        command += ['--python-exit-code', '1', '--python', str(ROOT / 'tests' / script)]
        if extra:
            command += ['--', *extra]
        result = subprocess.run(command, env=env, capture_output=True, timeout=180)
        log = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        (isolated / f'{script}-{extra[0] if extra else "integration"}.log').write_text(log, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(log[-8000:])

    try:
        run('test_blender.py', factory=True)
        config = isolated / 'config/animatica_zh_cn.json'
        for enabled in (True, False, True):
            config.write_text(json.dumps({'enabled': enabled}), encoding='utf-8')
            run('check_restart.py', extra=('中文' if enabled else '英文',))
    finally:
        if hashes(official) != baseline:
            raise RuntimeError('官方安装目录哈希发生变化')
    print('集成测试和中文/英文/中文重启测试通过。真实官方文件未改变。')
    print(f'测试报告保存在：{isolated}')

if __name__ == '__main__':
    main()
