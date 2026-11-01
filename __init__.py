# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport Pivot Dot: a small dot at the point the 3D viewport orbits around.

The orbit pivot is the viewport's ``view_location`` (``RegionView3D.view_location``). It is projected to the
region and drawn as a 2D dot on top of the viewport, so it costs next to nothing per redraw.

Fly / Walk navigation set the view distance to exactly zero (the viewport position becomes the camera), so a
zero distance is how that state is recognised: the dot is hidden then, without inspecting any operator.

Limits: Blender itself moves the pivot when an orbit / zoom starts when "Orbit Around Selection",
"Auto Depth" or "Zoom to Mouse Position" are on, so the dot shows the pivot as it is stored right now.
"""

import math
import time

import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

SEGMENTS = 32
FLY_DIST = 1e-5          # view distance at or below this = Fly / Walk navigation is running

_handle = None
_state = {}              # region pointer -> [last view stamp, time of last view change]
_timer_pending = False


# --- pure helpers (no bpy state, unit-testable) ----------------------------------------------------

def circle_tris(cx, cy, r, segments=SEGMENTS):
    """Vertices and triangle indices of a filled circle (a fan written as plain triangles)."""
    verts = [(cx, cy)] + [(cx + r * math.cos(2.0 * math.pi * k / segments),
                           cy + r * math.sin(2.0 * math.pi * k / segments)) for k in range(segments)]
    tris = [(0, 1 + k, 1 + (k + 1) % segments) for k in range(segments)]
    return verts, tris


def is_flying(view_distance):
    """Fly / Walk navigation zero the view distance (the view position becomes the camera)."""
    return view_distance < FLY_DIST


def update_visibility(state, stamp, now, hold):
    """'While navigating' mode. ``state`` is [last stamp, time of last change] or None for a region seen for
    the first time. Returns (new state, visible, seconds left to stay visible)."""
    if state is None:
        return [stamp, -1e9], False, 0.0
    if state[0] != stamp:
        state = [stamp, now]
    left = hold - (now - state[1])
    return state, left > 0.0, max(left, 0.0)


# --- preferences ----------------------------------------------------------------------------------

def prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except KeyError:
        return None


def _redraw(self=None, context=None):
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class PivotDotPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    enabled: BoolProperty(name="Orbit Pivot Dot", default=True, update=_redraw,
                          description="Show a dot at the point the viewport orbits around")
    show: EnumProperty(
        name="Show", default='NAVIGATING', update=_redraw,
        items=[('ALWAYS', "Always", "Keep the dot visible"),
               ('NAVIGATING', "While Navigating",
                "Show the dot while the view is orbiting, panning or zooming, and hide it shortly after")])
    hold: FloatProperty(name="Hide Delay", min=0.0, max=5.0, default=0.05, subtype='TIME', unit='TIME',
                        description="Seconds the dot stays after the view stops moving", update=_redraw)
    size: FloatProperty(name="Size", min=2.0, max=40.0, default=3.0, subtype='PIXEL', update=_redraw)
    color: FloatVectorProperty(name="Colour", subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
                               default=(1.0, 1.0, 1.0), update=_redraw)
    opacity: FloatProperty(name="Opacity", min=0.0, max=1.0, default=0.7, update=_redraw)
    outline: BoolProperty(name="Dark Outline", default=True, update=_redraw,
                          description="Draw a thin dark ring so the dot stays visible on any background")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "enabled")
        col.prop(self, "show")
        if self.show == 'NAVIGATING':
            col.prop(self, "hold")
        col.separator()
        col.prop(self, "size")
        col.prop(self, "color")
        col.prop(self, "opacity")
        col.prop(self, "outline")


# --- drawing --------------------------------------------------------------------------------------

def _redraw_timer():
    global _timer_pending
    _timer_pending = False
    _redraw()
    return None


def _schedule_redraw(seconds):
    global _timer_pending
    if not _timer_pending:
        _timer_pending = True
        bpy.app.timers.register(_redraw_timer, first_interval=max(seconds, 0.02) + 0.03)


def draw_dot():
    context = bpy.context
    space, region, rv3d = context.space_data, context.region, context.region_data
    p = prefs()
    if p is None or not p.enabled or rv3d is None or region is None or space is None or space.type != 'VIEW_3D':
        return
    if not space.overlay.show_overlays or rv3d.view_perspective == 'CAMERA':
        return
    flying = is_flying(rv3d.view_distance)
    if p.show == 'NAVIGATING':
        key = region.as_pointer()
        stamp = tuple(v for row in rv3d.view_matrix for v in row)
        if flying:      # Fly / Walk: hide, and don't count the flight as a view change when it ends
            _state[key] = [stamp, -1e9]
            return
        state, visible, left = update_visibility(_state.get(key), stamp, time.monotonic(), p.hold)
        _state[key] = state
        if not visible:
            return
        _schedule_redraw(left)          # redraw once more when the delay is over, so the dot can hide
    elif flying:
        return
    pos = view3d_utils.location_3d_to_region_2d(region, rv3d, rv3d.view_location)
    if pos is None:
        return
    scale = context.preferences.system.ui_scale or 1.0
    radius = p.size * 0.5 * scale
    rgb = tuple(p.color)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    try:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('ALPHA')
        if p.outline:
            verts, tris = circle_tris(pos.x, pos.y, radius + 1.5 * scale)
            shader.uniform_float("color", (0.0, 0.0, 0.0, 0.85 * p.opacity))
            batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=tris).draw(shader)
        verts, tris = circle_tris(pos.x, pos.y, radius)
        shader.uniform_float("color", (*rgb, p.opacity))
        batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=tris).draw(shader)
    finally:
        gpu.state.blend_set('NONE')


# --- UI + registration ----------------------------------------------------------------------------

def _guides_draw(self, context):
    p = prefs()
    if p is not None:
        self.layout.prop(p, "enabled", text="Orbit Pivot Dot")


def register():
    global _handle
    bpy.utils.register_class(PivotDotPreferences)
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw_dot, (), 'WINDOW', 'POST_PIXEL')
    try:
        bpy.types.VIEW3D_PT_overlay_guides.append(_guides_draw)
    except AttributeError:
        pass


def unregister():
    global _handle
    try:
        bpy.types.VIEW3D_PT_overlay_guides.remove(_guides_draw)
    except (AttributeError, ValueError):
        pass
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    _state.clear()
    bpy.utils.unregister_class(PivotDotPreferences)
