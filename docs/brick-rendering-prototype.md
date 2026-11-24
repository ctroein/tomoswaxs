# Brick rendering prototype

2026-11-24. The standalone experiment is in
[`tools/brick_rendering.py`](../tools/brick_rendering.py). It does not change the
application's renderer or project files. Data access is read-only.

The result is **promising for local replacement cost, but not ready to integrate**.
It provides finer central voxels within the array budget, at a lower orbiting
frame rate. The separate-mapper paths fail the translucent-beam correctness test;
the unified seven-input path encounters shader-resource limits on this GPU.

## What was built

A fixed central box at one OME-Zarr level is surrounded by six disjoint coarse
slabs. The fine region replaces the central coarse region. It occupies about
40% of the field along each image axis, centred at the default camera target.
The box remains attached to the sample during camera rotation.

Five paths are compared:

| Path | Purpose |
| --- | --- |
| Current single-array renderer | Baseline using the actual Auto detail planner, decoded cache and read path |
| Single-array cell-data renderer | Control for changing from point-centred VTK scalars to cell scalars |
| `vtkMultiBlockVolumeMapper` | One VTK actor, internally using a mapper per brick |
| Persistent individual mappers | Keep brick mappers/data objects resident; sort their actors with the known partition's BSP tree |
| Unified `vtkMultiVolume` ray caster | One ray integration over seven inputs; excluded from performance comparison after shader errors |

Voxel centres and half-voxel boundaries come from the NGFF transforms. The tool
requires nested cell boundaries and rejects incompatible geometry. Cell scalars
allow neighbouring bricks to meet at their voxel faces. A shared integer lattice
makes matching faces bit-identical; the initial version's independently computed
origins introduced tiny overlaps and VTK sorting warnings. The final run has no
sorting warnings. This is not a general loader for arbitrary multiscale layouts.

The persistent path uses a back-to-front traversal of the six-slab partition.
An initial unsorted version depended on actor submission order. Sorting corrects
that; reversing submission order then produces identical images. It changes the
actor order only when required, retaining the mapper objects and their inputs.

## Bamboo comparison

The final artifacts are under
`data/inspection/brick-prototype-2026-11-24/final/`:
`comparison.html`, `results.json`, and the PNG views. The HTML report presents
paired views and the uniform-density check. Intermediate runs remain in sibling
folders, with diagnostic logs, and are not the reported final measurements.

Same local Intel Arc/Mesa context as the Auto detail investigation. All paths use
960×640 off-screen rendering, the application's transfer functions, lighting,
sample transform and volume-aware depth peeling. The beam uses the application's
geometry and opacity. Camera, source crop and colour mapping are shared.

The 128 MiB array budget lets the current Auto detail plan use level 3 over the
whole visible region. The prototype keeps level 3 for its context and uses level
2 in the centre: **2.6 µm central voxels versus 5.2 µm**. Context quality is
therefore retained in this final comparison. The common outer region is trimmed
to complete coarse-level cells, consistently across methods.

| Path | Voxel arrays | Orbit frame, beam hidden | Orbit frame, beam shown |
| --- | ---: | ---: | ---: |
| Current | 80.15 MiB | 35.0 ms | 42.0 ms |
| Cell-data control | 80.15 MiB | 38.8 ms | 39.0 ms |
| VTK multiblock | 116.65 MiB | 55.6 ms | 75.3 ms |
| Persistent sorted bricks | 116.65 MiB | 51.9 ms | 69.5 ms |

Orbit times are medians of 12 three-degree steps. The mixed representation uses
more of the same allowed budget, rather than the exact same byte count. These
timings include no Trame transport, JPEG encoding or browser work. First-frame
shader/driver effects make initial activation times less useful for comparison;
the raw report retains them.

### Replacing data

Each replacement supplies identical values in a fresh buffer, so IO and changing
image content do not obscure rendering costs. The table measures the median
first synchronized render after replacement, three repeats. NumPy copying and
VTK input construction occur before the timed render.

| Path, beam shown | Replaced data | Updated frame |
| --- | ---: | ---: |
| Current | Whole 80.15 MiB array | 132.6 ms |
| VTK multiblock | One 24.02 MiB context slab | 153.1 ms |
| VTK multiblock | 41.71 MiB central brick | 153.3 ms |
| Persistent sorted bricks | One 24.02 MiB context slab | 89.8 ms |
| Persistent sorted bricks | 41.71 MiB central brick | 105.9 ms |

The persistent version benefits from smaller updates, but pays more on every
orbit frame. These measurements are consistent with retaining unchanged GPU
resources; GPU texture identities and transfer bytes were not directly traced.
VTK's multiblock source explicitly clears and recreates its internal mappers
when reloading changed input, explaining why it is a poor incremental-update
candidate. [VTK implementation](https://github.com/Kitware/VTK/blob/master/Rendering/VolumeOpenGL2/vtkMultiBlockVolumeMapper.cxx)

Preparing the current array took 111 ms and preparing mixed bricks 146 ms in the
final run, using the decoded cache. Filesystem caches were warm and not flushed.
These are short local measurements, not storage throughput or NAISS predictions.
The array counts are neither total process memory nor measured GPU allocation;
the experiment retains several representations simultaneously for comparison.

## Correctness findings

A constant-density cube is rendered whole and split into seven same-resolution
pieces. Splitting it should preserve colour and integrated opacity. Tests cover
low opacity and opaque material, perspective and orthographic cameras, and three
view directions, with and without the beam.

With the beam hidden, the native and persistent paths differ from the whole
volume by about 0.4–0.5 RGB levels on average over foreground pixels (0–255).
With the translucent beam shown, that rises to about **14 RGB levels**, with
visible internal boundaries and darkened material. Opaque checks remain much
closer. The discrepancy appears when volume-aware depth peeling is activated
by translucent geometry. The precise internal cause has not been established;
the prototype has not demonstrated correct multi-mapper compositing with the
beam. These timings must not be presented as measurements of a correct upgrade.

The unified GPU ray caster was investigated because it integrates the brick
contributions together. Some cases produced close images, but the seven-input
shader hit **Too many fragment shader texture samplers** on this Intel GPU,
including depth-peeling cases. Failed shader draws can leave misleading previous
frame contents, so all unified timings are excluded. Diagnostics are retained
in the report and log. This is a real limit of this tested configuration, not
proof that the approach fails on every GPU.

Lighting/interpolation at mixed-resolution boundaries also needs halos and
transition handling. The current exact-face construction is a geometry test,
not a completed seamless multiresolution interpolator. Moving the fine region,
chunk-level priorities/eviction and upload throttling are not implemented here.

## Decision

Keep the existing Auto detail renderer. The prototype demonstrates that a finer
centre with unchanged coarse context fits within 128 MiB, and that persistent
bricks can reduce local replacement pauses. It does not deliver faster orbiting
or satisfactory beam transparency.

A next rendering experiment should establish correct single-ray integration
with a bounded number of texture samplers, for example a brick atlas/page table
with shared transfer-function textures. That is shader/renderer work rather
than a swap to VTK's multiblock mapper. Validate it against the same optical
test before adding camera-following brick management or application controls.

## Reproduce

From the repository with the shared environment active:

```sh
PYTHONPATH=src python tools/brick_rendering.py /path/to/sample.ome.zarr \
  --output /path/to/inspection/brick-comparison \
  --fine-level 2 --context-level 3 --fraction 0.4 --limit 128
```

The output must be outside the repository. The tool writes diagnostic images,
JSON and an HTML comparison. Failed shader cases are explicitly excluded from
the performance table. Geometry and partition-order tests are in
`tests/test_brick_rendering.py`.

## NVIDIA comparison after reboot

Rerun on 2026-11-24 with both GPUs after reboot, using the same source, levels,
crop plan, central region, 128 MiB limit, 960×640 viewport and 12 orbit steps.
The Intel run used Mesa 26.2.7; the NVIDIA run verified an RTX 4070 Laptop GPU
with driver 620.70.06. VTK still selected Intel by default; NVIDIA was selected
for the benchmark process with `__NV_PRIME_RENDER_OFFLOAD=1` and
`__GLX_VENDOR_LIBRARY_NAME=nvidia`. The application's launch configuration was
not changed.

With the beam shown:

| Renderer | Intel frame | NVIDIA frame | Speed-up |
| --- | ---: | ---: | ---: |
| Current Auto detail | 39.0 ms | 6.6 ms | 5.9× |
| VTK multiblock | 79.1 ms | 18.9 ms | 4.2× |
| Persistent sorted bricks | 69.6 ms | 18.7 ms | 3.7× |

The current renderer's first frame after replacing its 80 MiB array fell from
118 ms to 58 ms. The persistent path's context-brick update fell from 92 ms to
36 ms, and its fine-brick update from 95 ms to 45 ms. These measure synchronized
rendering, excluding IO, JPEG encoding and browser transport, rather than total
GUI frame latency. Beam-visible passes followed the beam-hidden passes. These
are short-run measurements, not a controlled clock or thermal study.

Separate-mapper transparency discrepancies remain. The unified shader compiled
on NVIDIA without the Intel shader-link failure, but the full Bamboo run with
the beam produced hardware texture-resource warnings. Those unified timings are
excluded; compilation alone did not establish a valid rendering path.

Artifacts are in `data/inspection/brick-prototype-2026-11-24/nvidia/` and
`intel-after-reboot/`, with derived figures in `gpu-comparison.json` alongside
those folders. Original Intel measurements remain in `final/`.

### Assessment after the NVIDIA comparison

Keep brick rendering experimental and defer further implementation for now.
NVIDIA makes the prototypes interactive, but also makes the existing renderer
fast: approximately 6.6 ms per frame versus 19 ms for the brick paths. The
transparency and full-dataset texture-resource problems remain unresolved.

The reason to return to bricks is finer central detail with coarse context,
rather than faster rendering of equivalent data. A further prototype should
demonstrate a substantial detail advantage at a comparable memory budget and
correct beam/volume transparency before replacing the current Auto detail path.
