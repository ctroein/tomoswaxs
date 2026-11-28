# Planned work

Priorities recorded on 2026-11-23. Address Mira's new coordinate information
first, comparing it with the current CT–SAXS registration assumptions in
[Bamboo/ABS notes](data/bamboo-abs.md). Mira's motor-stack clarification and
sketch were received on 2026-11-23. The motor-stack hypothesis is implemented,
including rotating fine stages and an editable angular beam correction in the
centred CT frame. The sinusoidal estimate is not an independently measured
physical rotation-axis location.
Confirming the absolute CT–SAXS registration remains the current priority.

## Completed startup changes

- Removed the generated CT specimen, generator, preview script and example
  files. Startup is empty; legacy generated-sample records have no CT image.
- Added browser-local last-project recovery and an eight-project recent list.
  Explicit startup arguments take precedence, and closing a project suppresses
  automatic reopening. Errors opening unavailable projects remain visible.
- The beam is hidden without attached SAXS data.

## Voxel-array limit

The application default is 256 MiB, shared by the command-line launcher and
volume reader. A browser-saved preference overrides that default. Raising the
default is no longer an outstanding task.

## Completed UI follow-up, 2026-11-24

- Removed repeated dataset-name and voxel information from the status row;
  status and error messages remain there.
- Fixed cake intensity hover values by adapting binary customdata to ordinary
  rows in the browser. NumPy binary transport is preserved.
- Removed the standalone Resolution heading inside Crop and resolution.
- Moved the resolution chooser beside its label and abbreviated levels as
  L0, L1, etc., preserving their numbering.
- Paired the voxel-array-limit label with its field at the right of the row;
  numeric contents are right-aligned too.

## Completed viewer controls and panel layout

- Camera angle, slider and Play/Pause are in the viewing toolbar. Acquired
  beam position and sample rotation are selected in SAXS measurements.
- Camera orbiting follows the visible crop centre, preserving direction and
  distance when cropping. Default camera fits that cropped region.
- Expandable sections show disclosure triangles; measurement details explain
  Y recorded at scan start.
- Colour mapping bounds are always visible with a Reset button.
- Crop uses one axis label per row and a concise voxel-dimensions summary.
- Resolution puts the array limit beside its input and reports loaded level,
  dimensions and array size on short lines.

## Automatic detail

Auto detail follows the camera within manual Crop. Depth selects a zoom-linked
slab or full depth; Freeze region keeps the current region in sample coordinates
while orbiting. Useful detail stays visible during motion. Bounded asynchronous
loads refine the enclosing image-aligned array from coarse to fine, reusing a
decoded-block cache. Project samples
retain the mode, depth and frozen region. The design follows Neuroglancer's
view-dependent selection and depth controls; AGAVE and ChimeraX provided manual
crop/refinement comparisons. See the user guide and development notes.

Carl is satisfied with Auto detail (2026-11-26); treat further evaluation as
normal application feedback rather than a separate outstanding task.

The existing-path improvements are implemented: separate required/prefetched
coverage, keep useful detail while moving, a bounded decoded-block cache,
bounded parallel reads, one settling delay and coarse-to-fine refinement.

Measured bottlenecks, experiments and progressive-rendering options are recorded
in [Auto detail performance](auto-detail-performance.md).

Brick-based rendering was evaluated for centre-prioritised chunk display and
mixed-resolution context. Neuroglancer's inspected volume-rendering path chooses
one scale for the view and prioritises visible chunks near its centre. A finer
centre with coarser context additionally needs compatible rendering/compositing.

The [first brick-rendering prototype](brick-rendering-prototype.md) demonstrates
the memory/detail trade-off and smaller local replacement cost, but has slower
orbiting and unresolved beam transparency. Further brick work is deferred;
keep the current renderer. See the NVIDIA assessment in the prototype notes
for the conditions that would justify revisiting it.

## Pop-out windows

Carl reports that opening and closing pop-outs now works well (2026-11-26).
The old window-close failure is no longer an active to-do.

## Illustrative beamline context

The first ForMAX model is implemented in the existing µCT viewer, with optional
visibility and labels, Station overview and Sample close-up. It includes the
combined motor stack and a truncated, cutaway flight-tube entrance. Published
dimensions and illustrative assumptions are recorded in the
[model notes](beamline-model.md). CAD replacements and mechanical animation
remain later possibilities.

## Possible first-run profiles

Consider light/laptop, medium/desktop and heavy/workstation profiles for the
voxel-array size limit and other resource settings. Defer the profile interface
until several settings justify it. These are proposed profiles, not established
hardware requirements.
