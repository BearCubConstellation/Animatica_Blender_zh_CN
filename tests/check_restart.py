import bpy, sys, json, pathlib
mod = sys.modules.get('animatica_blender')
assert mod and mod.__addon_enabled__
expected = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else '中文'
assert mod.operators.ANIMATICA_OT_generate.bl_label == ('生成动作' if expected == '中文' else 'Generate Motion')
assert bpy.context.preferences.view.language == 'en_US'
print('RESTART_ORDER_OK', expected, list(bpy.context.preferences.addons.keys()))
