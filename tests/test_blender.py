import bpy, sys, json, pathlib, shutil, hashlib, addon_utils, importlib, os, ast
base = pathlib.Path(__file__).resolve().parents[1]
scripts = pathlib.Path(bpy.utils.user_resource('SCRIPTS', create=True))
sys.path.insert(0, str(scripts / 'addons'))
from animatica_zh_cn import core
language = bpy.context.preferences.view.language
bpy.context.preferences.system.use_online_access = False
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.show_tooltips = False
addon_utils.enable('animatica_zh_cn', default_set=True, persistent=True)
mod = addon_utils.enable('animatica_blender', default_set=True, persistent=True)
assert mod and getattr(mod, '__addon_enabled__', False), 'Official add-on did not enable'
assert bpy.context.preferences.view.language == language
assert mod.operators.ANIMATICA_OT_generate.bl_label == '生成动作'
assert bpy.types.Scene.bl_rna.properties['animatica'].fixed_type.properties['seed'].name == '随机种子'
assert mod.toolbar.PLACEHOLDER == '描述此处发生的动作…'
assert mod.timeline_overlay.EMPTY_BLOCK_HINT == '双击描述动作'
assert mod.hand_pose.STYLES[0][0] == 'RELAXED'
assert mod.properties.AnimaticaSettings.bl_rna.properties['hand_pose_left'].enum_items['RELAXED'].name == '放松'
s = bpy.context.scene.animatica
block = s.prompt_blocks.add()
block.prompt = 'Generate LeftHand: walks to the door'
assert block.prompt == 'Generate LeftHand: walks to the door'
assert mod.updater.REPO == 'animatica-ai/animatica-blender-plugin'
assert mod.updater.RELEASES_URL == 'https://api.github.com/repos/animatica-ai/animatica-blender-plugin/releases?per_page=10'
assert not core.STATUS['skipped'], core.STATUS['skipped']
original_loader = mod.__spec__.loader
assert isinstance(mod.toolbar.blf, core.FontProxy)
import blf
assert mod.toolbar.blf is not blf and not isinstance(blf, core.FontProxy)

# Exercise the actual official swap routine on a disposable installed copy.
before_version = mod.VERSION_TAG
target = pathlib.Path(mod.__file__).parent
stage = scripts / 'addons' / '.animatica-update-test'
stage.mkdir(exist_ok=True)
update_source = pathlib.Path(os.environ.get('ANIMATICA_ZH_UPDATE_SOURCE', target))
shutil.copytree(update_source, stage / 'new' / 'animatica_blender', ignore=shutil.ignore_patterns('__pycache__'))
update_tree = ast.parse((update_source / '__init__.py').read_text(encoding='utf-8'))
update_tag = next(ast.literal_eval(n.value) for n in update_tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'VERSION_TAG' for t in n.targets))
future = stage / 'new' / 'animatica_blender' / 'future_ui.py'
future.write_text('def draw(layout):\n    layout.label(text="Brand new untranslated control")\n', encoding='utf-8')
mod.updater._swap(str(stage), update_tag)
mod = sys.modules['animatica_blender']
assert mod.__addon_enabled__
assert mod.VERSION_TAG == update_tag
assert mod.operators.ANIMATICA_OT_generate.bl_label == '生成动作'
assert (scripts / 'addons' / 'animatica_zh_cn' / 'zh_CN.json').exists()
future_mod = importlib.import_module('animatica_blender.future_ui')
class Capture:
    def label(self, **kw): self.text = kw['text']
capture = Capture(); future_mod.draw(capture)
assert capture.text == 'Brand new untranslated control'
assert 'Brand new untranslated control' in core.STATUS['missing']
if mod.bl_info['version'] >= (1, 0, 4):
    assert mod.toolbar.ANIMATICA_OT_toolbar_close.bl_label == '折叠工具栏'
    assert mod.retarget.ANIMATICA_OT_copy_motion.bl_label == '复制动作'
    assert mod.retarget.ANIMATICA_OT_paste_motion.bl_label == '粘贴动作'
    assert '折叠' in mod.toolbar.tip(bpy.context, mod.toolbar.Item('close_bar', ''))

# Disable translation, reload official source, then re-enable it. No .blend is saved.
prefs = bpy.context.preferences.addons['animatica_zh_cn'].preferences
prefs.enabled = False
addon_utils.disable('animatica_blender', default_set=False)
mod.updater._purge_modules('animatica_blender')
mod = addon_utils.enable('animatica_blender', default_set=False)
assert mod.operators.ANIMATICA_OT_generate.bl_label == 'Generate Motion'
assert mod.toolbar.PLACEHOLDER == 'Describe what happens here…'
prefs.enabled = True
addon_utils.disable('animatica_blender', default_set=False)
mod.updater._purge_modules('animatica_blender')
mod = addon_utils.enable('animatica_blender', default_set=False)
assert mod.operators.ANIMATICA_OT_generate.bl_label == '生成动作'
assert bpy.context.preferences.view.language == language
bpy.ops.wm.save_userpref()
report = {'blender': bpy.app.version_string, 'language_unchanged': language,
          'official_before': before_version, 'official_after': mod.VERSION_TAG,
          'adapted_modules': len(core.STATUS['adapted']), 'replacements': sum(core.STATUS['adapted'].values()),
          'official_swap_passed': True, 'language_switch_passed': True, 'unknown_text_fallback_passed': True,
          'skipped': core.STATUS['skipped']}
output = pathlib.Path(__import__('os').environ['ANIMATICA_ZH_TEST_OUTPUT'])
(output / 'blender-test-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('ANIMATICA_ZH_TEST_OK', report)
