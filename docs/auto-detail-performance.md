# Auto detail: performance investigation

Investigated 2026-11-24 against the working tree based on `5050205`.
This records measurements and proposed improvements; the application has not
been changed as part of this investigation.

## Measurement conditions

Bamboo CT store:
`data/Bamboo/project/data/220253298026405399b8317b1bbaeea2/ct.ome.zarr`.
The full-resolution array is ZYX 1486×2697×2697, float32, with six pyramid
levels, 64³ storage chunks, and Zstandard compression. A complete chunk is
1 MiB decoded. These are properties of this store, not requirements for samples.

The local machine reports an Intel Core Ultra 9 185H, 22 logical CPUs, and
30 GiB RAM. The rendering context used Mesa 26.2.6 on Intel Arc integrated
graphics, with VTK's GPU mapper selected. Software: Python 3.12.13,
VTK 9.7.2, ngff-zarr 0.52.0, zarrista 0.1.0, Dask 2026.8.0.

Tests used standalone Python processes, without a web server or changes to the
running application. Storage was read-only. OS caches were not flushed;
these are warm/repeated local measurements, not cold-disk throughput tests.
No browser, network, or NAISS performance was measured.

Scripts, raw JSON and cProfile output are retained outside Git under
`data/inspection/auto-detail-2026-11-24/`. Scripts use the existing shared
environment and `PYTHONPATH=src`. Experiments accessing ngff-zarr's private
adapter are diagnostic, not a proposed production API.

## Where time is spent

The representative ROI is full-resolution XYZ
`[850:1850, 850:1850, 450:1050]`. At level 2 it produces a contiguous
ZYX 151×251×251 array, 36.29 MiB. It intersects 100 storage chunks.

| Operation | Observed elapsed time |
| --- | ---: |
| Current `preview()` for the ROI, repeated | 255–269 ms |
| Dask compute portion, single-threaded, three comparison runs | 228–242 ms |
| Dask compute with 2 workers, median | 152 ms |
| Dask compute with 4 workers, median | 108 ms |
| Dask compute with 8 workers, median | 79 ms |
| One region request through the underlying adapter, median | 23 ms |
| `preview()` with warmed decoded-chunk cache | 66–70 ms |
| Normal view-region planning after a camera change | 1.6–2.2 ms |

The compute comparisons exclude percentile calculation and final preview
metadata preparation. The direct adapter read returned values identical to
the Dask result, including NaNs. The direct read batches the region through
the backend instead of making 100 separate Dask reads; this does not establish
the same gain for remote stores or other layouts.

Reading those 100 encoded chunks individually took about 30 ms; decoding took
165–166 ms and exposing the decoded buffers as NumPy arrays about 3 ms.
Their encoded size was 93.24 MiB, compared with 100 MiB decoded. Compression
therefore saves little space for this particular region. These measurements
support decoding and per-chunk dispatch as substantial costs even when bytes
are already in the filesystem cache. The current crop discards much of each
edge chunk after decoding.

cProfile also found approximately 24 ms in preview percentile calculation and
10 ms in array concatenation. Auto detail preserves the current colour mapping;
its repeated percentile calculation is unnecessary for installing refinements.

The cache experiment retained complete decoded chunks in a bounded 128 MiB LRU,
using 100 MiB for this ROI. Repeated and slightly shifted requests reused all
100 chunks and produced arrays identical to uncached reads. It demonstrates
benefit, not a chosen default cache size. The output remains 36 MiB in addition
to the cache; the current 64 MiB array limit would not cover that combined use.

## Rendering and image delivery

Rendering used the application's mapper, volume property and depth-peeling
configuration in an off-screen 1200×800 window. Frames were synchronized with
`WaitForCompletion()`. An initial frame warmed the renderer before swaps.

| Array | Set up VTK input | First frame after replacement | Subsequent orbit frames |
| --- | ---: | ---: | ---: |
| Level 2 ROI, 36.29 MiB | 0.45 ms | 66 ms | 33 ms |
| Level 1 ROI, 286.10 MiB | 0.44 ms | 417 ms | 65–69 ms |

`numpy_to_vtk(deep=False)` already avoids copying the NumPy buffer into another
host array. The expensive work follows on the first render. Texture upload and
mapper initialization are implicated, but were not timed individually; the
417 ms figure must not be described as a pure GPU-transfer measurement.

Framebuffer readback took about 4 ms for these views; separate JPEG encoding
at quality 75 or 95 took 15–24 ms. Images were approximately 38–42 kB at quality
75 and 85–91 kB at quality 95. These are image-dependent examples. VTK rendering
and the installed Trame image-push path run synchronously on the application
thread; background disk reads do not remove first-frame stalls from that thread.

Halving the window dimensions reduced JPEG encoding to about 5–6 ms. It did
not reliably improve volume rendering in this short experiment, where VTK
also adjusts sampling. Image-size reduction is therefore useful for transport
and encoding, but is not established as a cure for the renderer's stalls.

Trame's [remote view](https://github.com/Kitware/trame-vtk#vtkremoteview)
supports separate interactive/still image quality and size. We currently use
full image size during interaction (`interactive_ratio=1`), with JPEG quality
75 during interaction and 95 when still. These controls refine the delivered
image, not the source voxel resolution. VTK also has
[interactive sampling controls](https://vtk.org/doc/nightly/html/classvtkGPUVolumeRayCastMapper.html)
for trading ray-casting quality against allocated frame time.

## Avoidable latency and coarse fallback

An instrumented run with a 1200×800 view, fourfold camera zoom, Depth 50 and a
64 MiB array limit produced this sequence:

| Time after enabling | Event |
| --- | --- |
| 357 ms | Start reading global overview |
| 373 ms | Start installing/rendering level 5 overview |
| 857 ms | Start reading level 3 detail |
| 1034 ms | Start installing/rendering detail |
| 1136 ms | Detail settled |

The overview read itself took 16 ms; detail reading took 177 ms.
Much of the elapsed time was scheduling: Auto detail waits at least 200 ms,
the shared worker adds another 150 ms, and automatic requests are spaced at
least 500 ms apart. The initial overview and detail are separate requests,
each passing through this mechanism. Simply accelerating storage will leave
this latency in place.

A subsequent **one-degree orbit immediately replaced level 3 with level 5**.
The fallback installation and render took 41 ms. Geometry planning alone was
about 2 ms for subsequent camera changes. This is an explicit policy decision
in `detail_refresh()`, not evidence that the data ceased to fit in memory.

The existing 10% frustum guard band is included both in the loaded request and
the next coverage test. The next padded box can extend beyond the old padded
box after a tiny motion. Separate the region that must be visible from the
larger region fetched in anticipation of motion. Keep useful existing detail
while preparing its replacement, with explicit handling of uncovered areas.

Only the overview and current detail array are retained. Falling back loses
the previous fine array as a reusable application object. Completed in-flight
loads are installed only if their crop contains the latest planned crop;
otherwise their useful overlapping work is discarded. There is no persistent
decoded-chunk cache to recover that work.

## Progressive updates: practical choices

### Improve the existing single-array path

Separate required coverage from prefetched coverage, align requests to chunks,
and add level/region hysteresis. Keep existing detail across small motions.
Use one scheduling policy for interaction and one prompt final refinement after
interaction stops, instead of stacking two settling delays. A modest worker
limit or batched backend reads can reduce the measured read overhead. Avoid
recomputing colour-mapping percentiles for refinements.

Load a coarse version of the **new visible region**, then replace it with finer
versions while the camera remains sufficiently stable. That gives whole-region
progressive refinement using the existing renderer. An intermediate stage is
worthwhile only if it displays useful content substantially sooner; each stage
also incurs installation/rendering cost. Retain resident mapper/data objects
where useful rather than repeatedly uploading the same overview and fine array.

This is the smallest extension of the current design. It can substantially
improve continuity and latency without yet rendering individual storage chunks.

### Prioritize centre chunks and reuse decoded data

Give each request a chunk set and order it by visibility and distance to the
view centre, with the current depth slab included in visibility. Refresh
priorities as the camera rotates. Keep completed overlapping chunks even when
the region request becomes obsolete, and cancel queued work that is no longer
useful. Bound concurrent reads/decodes and memory before starting work.

This follows Neuroglancer's inspected
[volume chunk scheduling](https://github.com/google/neuroglancer/blob/master/src/volume_rendering/backend.ts):
view changes recompute priorities, visible chunks are requested through the
chunk manager, and distance from the current data-space centre affects priority.
Its [scale selection](https://github.com/google/neuroglancer/blob/master/src/volume_rendering/base.ts)
and [rendering code](https://github.com/google/neuroglancer/blob/master/src/volume_rendering/volume_render_layer.ts)
should be considered together. Centre-prioritized loading is distinct from
rendering a fine centre surrounded by coarse data.

Use cache keys including source identity, level and chunk coordinates; retain
original intensities. Budget decoded cache, assembled arrays, in-flight buffers
and GPU resources separately. The filesystem cache holds encoded bytes and
cannot substitute for decoded arrays or resident textures. ngff-zarr's current
zarrista adapter does not add a decoded cache. zarrista's shard-index cache is
not a decoded-voxel cache.

The installed zarrista API has `retrieve_encoded_chunk()`, `decode()` and
`decode_async()`; its installed type documentation says decoding releases the
GIL and asynchronous decoding can use a bounded Rust thread pool. This provides
a useful implementation seam. Integrating it must preserve ngff-zarr's axis and
coordinate interpretation, and provide a supported reader interface instead of
depending on private adapter attributes used in these experiments.

### Display arriving chunks or mixed-resolution regions

Prioritizing chunks alone does not make them visible: our current reader returns
only after assembling a complete array. Displaying partial results requires a
different handoff to the renderer.

One possibility is a coarse-filled target array refined in batches. However,
the current VTK OpenGL mapper
[reloads volume resources when input scalars change](https://github.com/Kitware/VTK/blob/master/Rendering/VolumeOpenGL2/vtkOpenGLGPUVolumeRayCastMapper.cxx).
There is no demonstrated cheap per-chunk update through our existing mapper.
Calling `Modified()` after every arriving chunk could repeatedly incur a large
upload. Test bounded batch updates before adopting this route; initialized
coarse estimates must be distinguished from unavailable data and must not
change any scientific values stored on disk.

For genuinely local texture updates, investigate a brick-aware renderer.
[vtkMultiBlockVolumeMapper](https://vtk.org/doc/nightly/html/classvtkMultiBlockVolumeMapper.html)
is a candidate to prototype: it uses one mapper per image block and renders
blocks in back-to-front order. It is not an OME-Zarr loader or an automatic
LOD/cache manager. Correct seams, block ordering under rotation, transfer-function
opacity, and interaction with our translucent beam need verification.

Coarse context and fine detail must cover disjoint regions, or otherwise use
explicit resolution-selection masks. Simply drawing two overlapping transparent
versions of the same sample counts opacity twice. Existing
[vtkMultiVolume](https://vtk.org/doc/nightly/html/classvtkMultiVolume.html)
supports simultaneous overlapping volumes, but does not supply the policy for
replacing coarse values with fine ones. The AMR mapper is another candidate
for a focused prototype, not an established solution for this viewer.

## Suggested sequence and remaining measurements

Start with coverage reuse and scheduling, then benchmark bounded read concurrency
and decoded caching. Add whole-region coarse-to-fine refinement with a final
quality update after motion stops. These changes reuse the existing rendering
architecture and directly address measured problems.

Next, prototype a small brick-based view in isolation. Compare time to useful
centre detail, first-frame stalls and steady orbiting against the improved
single-array path. Include oblique views, depth changes, opaque and transparent
objects, the beam, and perspective/orthographic cameras. That experiment should
decide whether a fine centre with coarse context warrants the extra renderer
and compositing work.

Still unmeasured: true cold storage and remote filesystems, application end-to-end
browser latency, texture upload versus other mapper initialization, GPU cache
retention, adaptive frame budgets, and exact overlap/coverage thresholds. The
reported timings are evidence for this dataset and machine, not target defaults.

## Implemented follow-up

Implemented after approval on the same date:

- Actual visible coverage is distinct from the fetched box, which adds 12% on
  each image axis. Small motions reuse the larger array. Useful partial coverage
  also stays visible while a replacement loads, rather than immediately falling
  back to the overview.
- A decoded-block LRU uses public Dask block and delayed-task APIs. Region graphs
  are optimized together rather than separately for every block. Up to four
  bounded workers read missing blocks; hits only copy the needed voxels. The
  cache limit is twice the array limit, clamped to 8–256 MiB. It is cleared on
  disabling Auto detail or replacing the source, with an epoch guard for late
  completions. This cache is additional to the array limit.
- One 100 ms settling policy replaces the stacked automatic/manual waits.
  Stable views continue refinement immediately after each completed stage.
- Refinement uses up to two intermediate pyramid levels followed by the target,
  skipping stages already covered by useful equal-or-better data. Single-scale
  sources can refine through subsampling strides. Current-view coverage, size,
  cancellation and sample-context checks gate installation. Late coarser results
  cannot overwrite useful sharper data. Automatic loads skip repeated percentile
  calculations while retaining finite-data validation.

The instrumented enable/zoom run above settled in about **387 ms**, compared with
1136 ms before. It loaded a larger padded level-3 array (47.63 MiB versus
34.87 MiB), reading it in 156 ms and installing/rendering in 125 ms. Subsequent
small orbit steps retained level 3. The 36.29 MiB ROI test took 153–163 ms on its
first cache read and 20–28 ms for warmed repeats; a shifted request requiring
additional chunks took 83 ms. These short runs are comparisons, not latency
guarantees.

Cached and uncached Bamboo reads were compared exactly at levels 0 and 2,
including voxel values, spacing and origin. Automated coverage includes decoded
reuse, stride/edge selection, byte limits, eviction, cancellation, cache clearing,
stale contexts, level order, small orbits and frozen regions. Browser checks with
Bamboo covered zoom refinement, small orbits, freeze/unfreeze, playback, Beam
view, SAXS rotation and disabling with cache cleanup. Large first-frame GPU
stalls remain a limitation of this renderer.

Follow-up probe and browser results are retained in
`data/inspection/auto-detail-2026-11-24/implemented/`.
