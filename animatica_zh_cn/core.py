# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-only, package-scoped UI adaptation. Never writes Animatica bytecode."""
from __future__ import annotations
import ast
import importlib.abc
import importlib.machinery
import json
import pathlib
import sys
import string
import types
import re

ROOT = pathlib.Path(__file__).parent
TARGET = 'animatica_blender'
CATALOG = json.loads((ROOT / 'zh_CN.json').read_text(encoding='utf-8')) if (ROOT / 'zh_CN.json').exists() else {}
STATUS = {'adapted': {}, 'skipped': {}, 'missing': set()}
_patterns = None

def display(text):
    """Translate local status templates, preserving interpolated names/errors verbatim."""
    global _patterns
    if not isinstance(text, str):
        return text
    if text in CATALOG:
        return CATALOG[text]
    if _patterns is None:
        _patterns = []
        for english, chinese in CATALOG.items():
            try:
                parts = list(string.Formatter().parse(english))
                fields = [f for _, f, _, _ in parts if f is not None]
                literal_size = sum(len(t) for t, _, _, _ in parts)
                if not fields or not all(f.isdigit() for f in fields) or literal_size < 8:
                    continue
                pattern = ''.join(re.escape(t) + ('(.*?)' if f is not None else '') for t, f, _, _ in parts)
                _patterns.append((literal_size, re.compile('^' + pattern + '$', re.S), fields, chinese))
            except ValueError:
                continue
        _patterns.sort(key=lambda row: row[0], reverse=True)
    for _, pattern, fields, chinese in _patterns:
        match = pattern.fullmatch(text)
        if match:
            values = {f: v for f, v in zip(fields, match.groups())}
            try:
                return chinese.format(*(values.get(str(i), '') for i in range(max(map(int, fields)) + 1)))
            except (IndexError, KeyError, ValueError):
                pass
    return text

def tr(text):
    if not isinstance(text, str):
        return text
    value = CATALOG.get(text)
    if value is None:
        if text.strip() and any(c.isalpha() and c.isascii() for c in text):
            STATUS['missing'].add(text)
        return text
    return value

def enum_items(items):
    # Keep strings alive: Blender's dynamic enum API keeps C pointers to them.
    if callable(items):
        cache = []
        def translated(self, context):
            result = enum_items(items(self, context))
            cache[:] = [result]
            return result
        return translated
    return [None if row is None else (row[0], tr(row[1]), tr(row[2]), *row[3:]) for row in items]

def _fkey(node):
    chunks, values = [], []
    for part in node.values:
        if isinstance(part, ast.Constant):
            chunks.append(part.value.replace('{', '{{').replace('}', '}}'))
        else:
            chunks.append('{' + str(len(values)) + '}')
            values.append(part)
    return ''.join(chunks), values

class UITransformer(ast.NodeTransformer):
    """Only human-facing slots are rewritten; identifiers and requests are untouched."""
    def __init__(self, module, catalog=None):
        self.module = module
        self.catalog = CATALOG if catalog is None else catalog
        self.candidates = set()
        self.count = 0
        self.bindings = []
        self.busy = set()

    def literal(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if text.strip() and any(c.isascii() and c.isalpha() for c in text) and not any('\u4e00' <= c <= '\u9fff' for c in text):
                self.candidates.add(text)
            if text in self.catalog:
                self.count += 1
                return ast.copy_location(ast.Constant(self.catalog[text]), node)
        elif isinstance(node, ast.JoinedStr):
            key, values = _fkey(node)
            for value in values:
                value.value = self.literal(value.value)
            if any(c.isascii() and c.isalpha() for c in key) and not any('\u4e00' <= c <= '\u9fff' for c in key):
                self.candidates.add(key)
            if key in self.catalog:
                parts = []
                try:
                    for text, field, spec, conversion in string.Formatter().parse(self.catalog[key]):
                        if text:
                            parts.append(ast.Constant(text))
                        if field is not None:
                            if spec or conversion:
                                raise ValueError('Translations must retain numbered placeholders only')
                            parts.append(values[int(field)])
                    # A translation must preserve every placeholder, exactly once.
                    fields = [int(f) for _, f, _, _ in string.Formatter().parse(self.catalog[key]) if f is not None]
                    if sorted(fields) != list(range(len(values))):
                        raise ValueError('placeholder mismatch')
                    self.count += 1
                    return ast.copy_location(ast.JoinedStr(parts), node)
                except (ValueError, IndexError):
                    return node
        elif isinstance(node, ast.IfExp):
            if isinstance(node.body, ast.Constant) and isinstance(node.orelse, ast.Constant) and {node.body.value, node.orelse.value} <= {'', 's'}:
                return ast.copy_location(ast.Constant(''), node)
            node.body = self.literal(node.body)
            node.orelse = self.literal(node.orelse)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            node.left = self.literal(node.left)
            # Percent-format arguments may be user data.
            if isinstance(node.op, ast.Add):
                node.right = self.literal(node.right)
        elif isinstance(node, (ast.List, ast.Tuple)):
            node.elts = [self.literal(x) for x in node.elts]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {'join', 'append', 'wrap'} and node.args:
                node.args[0] = self.literal(node.args[0])
            elif node.func.attr in {'strip', 'rstrip', 'lstrip', 'capitalize'}:
                node.func.value = self.literal(node.func.value)
        elif isinstance(node, ast.Name):
            names = {'text', 'title', 'label', 'line', 'message', 'msg', 'detail', 'hint', 'suffix', 'status', 'state', 'tip', 'note', 'who', 'where', 'parts', 'length'}
            if self.module.endswith('.guidance'):
                names.update({'why', 'count'})
            if node.id not in names:
                return node
            # Resolve only local display variables; never chase attributes/user data.
            for scope in reversed(self.bindings):
                assignments = scope.get(node.id, [])
                for assignment in assignments:
                    if id(assignment) in self.busy:
                        continue
                    self.busy.add(id(assignment))
                    assignment.value = self.literal(assignment.value)
                    self.busy.remove(id(assignment))
                if assignments:
                    break
        return node

    def visit_FunctionDef(self, node):
        bindings = {}
        # Do not include nested function scopes.
        def collect(body):
            for item in body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            bindings.setdefault(target.id, []).append(item)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.value:
                    bindings.setdefault(item.target.id, []).append(item)
                elif isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and item.value.func.attr == 'append' and isinstance(item.value.func.value, ast.Name):
                    bindings.setdefault(item.value.func.value.id, []).append(item)
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for field in ('body', 'orelse', 'finalbody'):
                        collect(getattr(item, field, []))
                    for handler in getattr(item, 'handlers', []):
                        collect(handler.body)
        collect(node.body)
        self.bindings.append(bindings)
        # Blender uses description() return values as tooltips.
        if node.name == 'description' or (self.module.endswith('.toolbar') and node.name in {
            'tip', '_waypoint_hint', '_describe_blocker', '_batch_tip',
            '_batch_review_tip', '_clipboard_tip', '_names',
        }) or (self.module.endswith('.retarget') and node.name == 'selection_label'):
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value:
                    child.value = self.literal(child.value)
        if self.module.endswith('.toolbar') and node.name == 'tip':
            for child in ast.walk(node):
                if isinstance(child, ast.Assign) and any(isinstance(t, ast.Tuple) and [getattr(v, 'id', '') for v in t.elts] == ['title', 'line'] for t in child.targets) and isinstance(child.value, ast.Tuple):
                    child.value = self.display_tree(child.value)
        # New hints and clipboard tooltips build their display text in pieces.
        # Only follow variables already identified as display slots, preserving
        # readiness reasons and other values used by the official control flow.
        if self.module.endswith(('.toolbar', '.guidance')):
            display_names = {'title', 'line'} if self.module.endswith('.toolbar') else {'text', 'why'}
            for child in ast.walk(node):
                if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name) and child.target.id in display_names:
                    child.value = self.literal(child.value)
        self.generic_visit(node)
        self.bindings.pop()
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        # Operator docstrings are the fallback tooltip.
        if any(isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_idname' for t in x.targets) for x in node.body):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                node.body[0].value = self.literal(node.body[0].value)
        return self.generic_visit(node)

    def visit_Assign(self, node):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if any(n in {'bl_label', 'bl_description', 'EMPTY_HINT', 'EMPTY_BLOCK_HINT', 'UNCONDITIONED_LABEL', 'PLACEHOLDER'} for n in names):
            node.value = self.literal(node.value)
        if any(n in {'TIPS', '_TOGGLE_TIPS', '_MENU_TIPS'} for n in names) and isinstance(node.value, ast.Dict):
            node.value.values = [self.display_tree(v) for v in node.value.values]
        return self.generic_visit(node)

    def visit_Call(self, node):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ''
        prop = name.endswith('Property')
        for kw in node.keywords:
            if kw.arg in {'text', 'heading'} or (kw.arg in {'label', 'description', 'name'} and (prop or name == 'Item')) or (kw.arg == 'why' and self.module.endswith(('.guidance', '.retarget'))):
                kw.value = self.literal(kw.value)
            if prop and kw.arg == 'items':
                self.collect_enums(kw.value)
                # Static enum lists carry UI labels; callback results may contain user bone/object names.
                if isinstance(kw.value, (ast.List, ast.Tuple)) or (isinstance(kw.value, ast.Name) and kw.value.id in {'ENGINES', '_hand_pose_items'}):
                    kw.value = ast.Call(ast.Name('_az_enum_items', ast.Load()), [kw.value], [])
        if name == 'report' and len(node.args) > 1:
            node.args[1] = self.literal(node.args[1])
            node.args[1] = ast.Call(ast.Name('_az_display', ast.Load()), [node.args[1]], [])
        for kw in node.keywords:
            # Only status fields; user prompts, model/object/bone names never use this path.
            if kw.arg == 'text' and (any(isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in {'error', 'message', 'status'} for n in ast.walk(kw.value)) or any(isinstance(n, ast.Name) and n.id in {'blockers', 'err', 'reason'} for n in ast.walk(kw.value))):
                kw.value = ast.Call(ast.Name('_az_display', ast.Load()), [kw.value], [])
            elif kw.arg == 'text' and self.module.endswith('.mmcp_client'):
                # This module draws only connectivity notices and popup status lines.
                kw.value = ast.Call(ast.Name('_az_display', ast.Load()), [kw.value], [])
        if name in {'popup', 'set_header_text', 'header_text_set'} and node.args:
            node.args[0] = self.literal(node.args[0])
            if name == 'popup' and len(node.args) > 1:
                arg = node.args[1]
                if isinstance(arg, (ast.List, ast.Tuple)):
                    arg.elts = [self.literal(x) for x in arg.elts]
        # Display helpers receive strings before truncation and measurement.
        if self.module.endswith('.timeline_overlay') and name == '_text' and node.args:
            node.args[0] = self.literal(node.args[0])
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'blf' and name in {'draw', 'dimensions'} and len(node.args) > 1:
            if not (isinstance(node.args[1], ast.Constant) and node.args[1].value in {'Ag', 'A', 'M', '0'}):
                node.args[1] = self.literal(node.args[1])
        if self.module.endswith('.toolbar') and name == '_plain_width' and node.args:
            node.args[0] = self.literal(node.args[0])
        if self.module.endswith('.picker') and name in {'_text', '_fit'} and node.args:
            node.args[0] = self.literal(node.args[0])
        return self.generic_visit(node)

    def display_tree(self, node):
        if isinstance(node, (ast.List, ast.Tuple)):
            node.elts = [self.display_tree(x) for x in node.elts]
            return node
        return self.literal(node)

    def collect_enums(self, node):
        if isinstance(node, (ast.Tuple, ast.List)):
            for row in node.elts:
                if isinstance(row, (ast.Tuple, ast.List)) and len(row.elts) >= 3:
                    for label in row.elts[1:3]:
                        self.literal(label)

    def visit_Return(self, node):
        if self.module.endswith('.toolbar') and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 3:
            # gate(): status identifier, label, operator identifier.
            node.value.elts[1] = self.literal(node.value.elts[1])
            node.value.elts[1] = ast.Call(ast.Name('_az_display', ast.Load()), [node.value.elts[1]], [])
        return self.generic_visit(node)

    def visit_Tuple(self, node):
        if len(node.elts) >= 3 and isinstance(node.elts[0], ast.Constant) and isinstance(node.elts[0].value, str) and node.elts[0].value.upper() == node.elts[0].value:
            for item in node.elts[1:3]:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    self.candidates.add(item.value)
            if self.module.endswith('.mmcp_client') and node.elts[0].value == 'NONE':
                node.elts[1] = self.literal(node.elts[1])
        return self.generic_visit(node)


def transform(source, filename, module, catalog=None):
    tree = ast.parse(source, filename)
    visitor = UITransformer(module, catalog)
    tree = visitor.visit(tree)
    # Do not inherit this loader's future flags: Blender RNA annotations must
    # retain the original module's evaluation semantics and callback globals.
    return compile(ast.fix_missing_locations(tree), filename, 'exec', dont_inherit=True), visitor


class FontProxy:
    """Private blf facade per Animatica module, no global monkey patch."""
    def __init__(self, original):
        self.original = original
        self.font = None
        self.configs = {}

    def _id(self, font):
        if font != 0:
            return font
        if self.font is None:
            import os
            candidates = [pathlib.Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc']
            try:
                import bpy
                candidates.extend(pathlib.Path(bpy.utils.system_resource('DATAFILES', path='fonts')).glob('*CJK*'))
            except Exception:
                pass
            self.font = 0
            for path in candidates:
                if path.is_file():
                    try:
                        result = self.original.load(str(path))
                        if result >= 0:
                            self.font = result
                            break
                    except Exception:
                        pass
            if not self.font:
                print('[Animatica 中文] 中文字体加载失败，使用 Blender 默认字体')
        return self.font

    def __getattr__(self, name):
        value = getattr(self.original, name)
        if not callable(value) or name in {'load', 'unload'}:
            return value
        def invoke(font, *args, **kwargs):
            return value(self._id(font), *args, **kwargs)
        return invoke


class UILoader(importlib.abc.Loader):
    def __init__(self, original, fullname):
        self.original, self.fullname = original, fullname
    def create_module(self, spec):
        return self.original.create_module(spec)
    def exec_module(self, module):
        source = self.original.get_source(self.fullname)
        if source is None:
            return self.original.exec_module(module)
        try:
            code, visitor = transform(source, module.__file__, self.fullname)
        except Exception as exc:
            STATUS['skipped'][self.fullname] = str(exc)
            print('[Animatica 中文] 跳过不兼容模块:', self.fullname, exc)
            return self.original.exec_module(module)
        module.__dict__['_az_enum_items'] = enum_items
        module.__dict__['_az_display'] = display
        exec(code, module.__dict__)
        if 'blf' in module.__dict__ and isinstance(module.__dict__['blf'], types.ModuleType):
            module.__dict__['blf'] = FontProxy(module.__dict__['blf'])
        STATUS['adapted'][self.fullname] = visitor.count
        STATUS['missing'].update(visitor.candidates - CATALOG.keys())


class UIFinder(importlib.abc.MetaPathFinder):
    _animatica_zh_finder = True
    def find_spec(self, fullname, path=None, target=None):
        if not (fullname == TARGET or fullname.startswith(TARGET + '.')) or '.vendor' in fullname:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = UILoader(spec.loader, fullname)
        return spec

def install():
    if not any(getattr(f, '_animatica_zh_finder', False) for f in sys.meta_path):
        sys.meta_path.insert(0, UIFinder())

def uninstall():
    sys.meta_path[:] = [f for f in sys.meta_path if not getattr(f, '_animatica_zh_finder', False)]
