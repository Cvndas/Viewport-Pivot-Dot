# Viewport Pivot Dot

A small dot that shows the point the 3D viewport orbits around (the viewport's orbit pivot).

- Shown while orbiting / panning / zooming by default (adjustable hide delay), or always visible.
- Hidden during Fly and Walk navigation, where the pivot is meaningless and would sweep across the screen.
- Size, colour, opacity and an optional dark outline are adjustable in the add-on preferences.
- Toggle it in the viewport Overlays popover (Guides section), or in the preferences.
- Hidden when Overlays are off and in camera view.

The dot shows the pivot as Blender stores it right now. With "Orbit Around Selection", "Auto Depth" or
"Zoom to Mouse Position" on, Blender moves the pivot when an orbit or zoom starts, so the dot updates then.

Blender 4.5 LTS or newer. Install via *Preferences > Get Extensions > Install from Disk*. GPL-3.0-or-later.
