# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI: python check_missing.py <animatica_blender folder> [report.json]."""
from pathlib import Path
import importlib.util
import json
import sys

if __package__:
    from . import core
else:
    spec = importlib.util.spec_from_file_location('animatica_zh_core', Path(__file__).with_name('core.py'))
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)

def scan(root):
    candidates, skipped = {}, {}
    for path in sorted(Path(root).rglob('*.py')):
        if 'vendor' in path.parts or 'icons' in path.parts or '__pycache__' in path.parts:
            continue
        rel = path.relative_to(root)
        name = core.TARGET + '.' + '.'.join(rel.with_suffix('').parts)
        try:
            _, visitor = core.transform(path.read_text(encoding='utf-8'), str(path), name, {})
            for text in visitor.candidates:
                if text.strip() and any(c.isascii() and c.isalpha() for c in text):
                    candidates.setdefault(text, []).append(str(rel))
        except Exception as exc:
            skipped[str(rel)] = str(exc)
    return {'total': len(candidates), 'translated': sum(t in core.CATALOG for t in candidates),
            'missing': {k: candidates[k] for k in sorted(candidates) if k not in core.CATALOG},
            'scan_errors': skipped, 'runtime_skipped': core.STATUS['skipped']}

if __name__ == '__main__':
    report = scan(Path(sys.argv[1]).resolve())
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('animatica_missing_zh.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{report["translated"]}/{report["total"]} covered; {len(report["missing"])} missing. {output}')
