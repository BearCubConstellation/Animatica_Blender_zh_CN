import ast, importlib.util, pathlib, unittest, sys
base = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('core', base / 'animatica_zh_cn/core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

class Tests(unittest.TestCase):
    def run_source(self, source, module='animatica_blender.test'):
        namespace = {'_az_enum_items': core.enum_items, '_az_display': core.display}
        code, visitor = core.transform(source, '<test>', module)
        exec(code, namespace)
        return namespace
    def test_display_data_separation(self):
        ns = self.run_source('''
class Layout:
    def label(self, **kw): return kw['text']
def ui(arm):
    name = 'Generate'
    payload = {'model_id':'Generate', 'prompt':'Generate', 'bone':'LeftHand'}
    label = 'Generate'
    caption = Layout().label(text=label)
    original = Layout().label(text=name)
    return caption, original, payload, Layout().label(text=arm.name)
''')
        obj = type('Obj', (), {'name': 'Generate'})()
        caption, original, payload, user_name = ns['ui'](obj)
        self.assertEqual(caption, '生成')
        self.assertEqual((original, user_name), ('Generate', 'Generate'))
        self.assertEqual(payload, {'model_id':'Generate', 'prompt':'Generate', 'bone':'LeftHand'})
    def test_interpolation_preserves_errors_and_names(self):
        ns = self.run_source('''
class Layout:
    def label(self, **kw): return kw['text']
def ui(error):
    return Layout().label(text=f'Generation failed: {error}')
''')
        detail = 'Generate / E:/动作/LeftHand: HTTP 401'
        self.assertEqual(ns['ui'](detail), '生成失败：' + detail)
        self.assertEqual(core.display('Generation failed: ' + detail), '生成失败：' + detail)
    def test_enum_identifiers(self):
        rows = [('RELAXED', 'Relaxed', 'A slight natural curl, as a hand at rest'), None]
        out = core.enum_items(rows)
        self.assertEqual(out[0][0], 'RELAXED')
        self.assertEqual(out[0][1], '放松')
        self.assertIsNone(out[1])
    def test_original_annotation_semantics(self):
        ns = self.run_source('sentinel = object()\nclass Settings:\n    field: sentinel\n')
        self.assertIs(ns['Settings'].__annotations__['field'], ns['sentinel'])
        ns = self.run_source('from __future__ import annotations\nsentinel = object()\nclass Settings:\n    field: sentinel\n')
        self.assertEqual(ns['Settings'].__annotations__['field'], 'sentinel')
    def test_unknown_and_unrelated(self):
        self.assertEqual(core.display('Brand new untranslated control'), 'Brand new untranslated control')
        self.assertIsNone(core.UIFinder().find_spec('another_addon'))
        self.assertIsNone(core.UIFinder().find_spec('animatica_blender.autoposer.vendor.engine'))
    def test_private_font_proxy(self):
        from unittest.mock import patch
        class BLF:
            def load(self, path): return 77
            def size(self, font, size): return font, size
            def dimensions(self, font, text): return font, text
        original = BLF()
        with patch.object(pathlib.Path, 'exists', return_value=True):
            proxy = core.FontProxy(original)
        self.assertEqual(proxy.size(0, 11), (77, 11))
        self.assertEqual(proxy.dimensions(0, '中文'), (77, '中文'))
        self.assertEqual(original.size(0, 11), (0, 11))
    def test_invalid_translation_falls_back(self):
        src = "value = f'Generation failed: {error}'"
        node = ast.parse(src).body[0].value
        transformer = core.UITransformer('animatica_blender.test', {'Generation failed: {0}': '失败 {99}'})
        self.assertIs(transformer.literal(node), node)
    def test_hook_idempotence(self):
        before = list(sys.meta_path)
        core.install(); core.install()
        self.assertEqual(sum(getattr(x, '_animatica_zh_finder', False) for x in sys.meta_path), 1)
        core.uninstall()
        self.assertEqual(sys.meta_path, before)
    def test_loader_compile_failure_is_safe(self):
        class Original:
            def get_source(self, name): return 'x=1'
            def exec_module(self, module): module.x = 1
        module = type(sys)('animatica_blender.compat_test')
        module.__file__ = '<test>'
        saved = core.transform
        try:
            core.transform = lambda *args: (_ for _ in ()).throw(ValueError('Unsupported new UI'))
            core.UILoader(Original(), module.__name__).exec_module(module)
            self.assertEqual(module.x, 1)
            self.assertIn(module.__name__, core.STATUS['skipped'])
        finally:
            core.transform = saved
            core.STATUS['skipped'].clear()

if __name__ == '__main__':
    unittest.main()
