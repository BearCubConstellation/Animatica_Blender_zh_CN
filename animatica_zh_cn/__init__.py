# SPDX-License-Identifier: GPL-3.0-or-later
"""Animatica 简体中文伴随插件；不包含或改写官方插件。"""
bl_info = {
    'name': 'Animatica 简体中文（独立汉化）',
    'author': 'Cymrise',
    'version': (1, 1, 1),
    'blender': (5, 1, 0),
    'location': 'Preferences > Add-ons > Animatica 简体中文',
    'description': '仅汉化 Animatica，保留官方更新；安装或切换后重启生效',
    'category': 'Interface',
}
import json
import os
from pathlib import Path
import bpy
from bpy.props import BoolProperty, StringProperty
from . import core

PACKAGE = __name__

def config_path():
    return Path(bpy.utils.user_resource('CONFIG', create=True)) / 'animatica_zh_cn.json'

def read_enabled():
    try:
        return bool(json.loads(config_path().read_text(encoding='utf-8'))['enabled'])
    except (OSError, ValueError, KeyError):
        return True

def set_enabled(self, context):
    path = config_path()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({'enabled': self.enabled}), encoding='utf-8')
    os.replace(temp, path)
    if self.enabled:
        core.install()
    else:
        core.uninstall()

BOOTSTRAP = '''# SPDX-License-Identifier: GPL-3.0-or-later
# Installed by the independent Animatica Chinese companion.
def register():
    import bpy, sys
    from pathlib import Path
    package = "animatica_zh_cn"
    # Runs before Blender enables add-ons, regardless of their ordering.
    if package not in bpy.context.preferences.addons:
        return
    path = Path(__file__).resolve().parent.parent / "addons"
    if not (path / package / "__init__.py").is_file():
        return
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    try:
        from animatica_zh_cn import core, read_enabled
        if read_enabled():
            core.install()
    except Exception as exc:
        print("[Animatica 中文] 启动适配未加载，官方插件保持可用:", exc)

def unregister():
    pass
'''

def install_bootstrap():
    scripts = Path(bpy.utils.user_resource('SCRIPTS', create=True))
    # Legacy add-on ZIP installs under scripts/addons, matching bootstrap resolution.
    startup = scripts / 'startup'
    startup.mkdir(parents=True, exist_ok=True)
    target = startup / 'animatica_zh_bootstrap.py'
    if not target.exists() or target.read_text(encoding='utf-8') != BOOTSTRAP:
        target.write_text(BOOTSTRAP, encoding='utf-8')

class ANIMATICA_ZH_OT_scan(bpy.types.Operator):
    bl_idname = 'animatica_zh.scan_missing'
    bl_label = '导出缺失译文报告'
    bl_description = '扫描当前 Animatica 界面文案，保存未收录文字和兼容状态；不修改官方文件'
    filepath: StringProperty(subtype='FILE_PATH', default='animatica_missing_zh.json')
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    def execute(self, context):
        try:
            import importlib.util
            from .check_missing import scan
            spec = importlib.util.find_spec(core.TARGET)
            if spec is None or not spec.submodule_search_locations:
                self.report({'ERROR'}, '未找到 Animatica 插件')
                return {'CANCELLED'}
            report = scan(Path(next(iter(spec.submodule_search_locations))))
            Path(self.filepath).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            self.report({'INFO'}, f'已导出，缺失译文 {len(report["missing"])} 条；请重启应用语言切换')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'导出失败：{exc}')
            return {'CANCELLED'}

class ANIMATICA_ZH_Preferences(bpy.types.AddonPreferences):
    bl_idname = PACKAGE
    enabled: BoolProperty(name='启用 Animatica 简体中文', default=True, update=set_enabled,
                          description='仅改变 Animatica 显示文字。切换后请保存偏好设置并重启 Blender')
    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'enabled')
        layout.label(text='安装、启停或切换语言后，请重启 Blender。', icon='INFO')
        layout.label(text='官方插件照常更新；更新后重启即可重新应用汉化。')
        layout.label(text='新增文案暂显英文；不兼容模块自动跳过。')
        layout.operator('animatica_zh.scan_missing', icon='FILE_TEXT')
        if core.STATUS['skipped']:
            layout.label(text=f'已跳过 {len(core.STATUS["skipped"])} 个不兼容模块，详情见报告', icon='ERROR')

CLASSES = (ANIMATICA_ZH_OT_scan, ANIMATICA_ZH_Preferences)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    install_bootstrap()
    prefs = bpy.context.preferences.addons.get(PACKAGE)
    if prefs:
        # Configuration is read before add-ons start; no dependence on registration order.
        prefs.preferences.enabled = read_enabled()
    if read_enabled():
        core.install()

def unregister():
    core.uninstall()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    # No preference write on shutdown. Bootstrap is inert when this add-on is disabled.
