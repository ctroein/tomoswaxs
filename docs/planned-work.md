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

## Next application changes

- Raise the default voxel-array size limit to suit a computer with a good
  graphics card. The appropriate value is still to be determined.

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

Evaluate the behaviour with beamline users. Loading/rendering individual chunks
could improve memory efficiency for oblique views in a later version.

The existing-path improvements are implemented: separate required/prefetched
coverage, keep useful detail while moving, a bounded decoded-block cache,
bounded parallel reads, one settling delay and coarse-to-fine refinement.

Measured bottlenecks, experiments and progressive-rendering options are recorded
in [Auto detail performance](auto-detail-performance.md).

Next, evaluate brick-based rendering for centre-prioritised chunk display and
mixed-resolution context. Neuroglancer's inspected volume-rendering path chooses
one scale for the view and prioritises visible chunks near its centre. A finer
centre with coarser context additionally needs compatible rendering/compositing.

The [first brick-rendering prototype](brick-rendering-prototype.md) demonstrates
the memory/detail trade-off and smaller local replacement cost, but has slower
orbiting and unresolved beam transparency. Keep the current renderer while
investigating single-ray brick integration with bounded sampler use.

## Possible first-run profiles

Consider light/laptop, medium/desktop and heavy/workstation profiles for the
voxel-array size limit and other resource settings. Defer the profile interface
until several settings justify it. These are proposed profiles, not established
hardware requirements.
