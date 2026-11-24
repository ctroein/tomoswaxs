# NGFF 0.6 for TomoSWAXS

Investigation, 2026-11-18. Scope: metadata and visualization of supplied CT,
scattering and simulation products. Reconstruction and scientific models remain
with the beamline scientists. No application changes or source-data conversions
were made during this investigation.

## What is available

The official [version history](https://ngff.openmicroscopy.org/specifications/0.6/version_history.html)
dates NGFF 0.6 to 2026-09-14 and records adoption of RFC-5. The relevant addition
is a way to name coordinate systems, describe transformations between them,
and group spatially related images in a scene. See the
[specification](https://ngff.openmicroscopy.org/specifications/0.6/).

For this application, the useful model is CT indices → intrinsic CT physical
coordinates → sample coordinates → laboratory coordinates, with named frames
and explicit units. A supplied registration can be applied by the viewer as a
geometric transform; displaying a transformed volume need not require resampling
its voxels. Measured beam paths and acquisition poses can then be interpreted
in the same laboratory frame once the scientists provide the missing mappings.

A scene relates images and can declare the common reference system. It is useful
for CT plus any supplied spatial scattering maps or other registered images.
Static registration metadata, per-measurement acquisition angles, and temporary
camera/viewing state have different roles and should remain distinguishable.

NGFF 0.6 still has image-specific restrictions: multiscales have 2–5 dimensions,
2–3 spatial axes, and prescribed ordering of the optional time and channel/custom
axes. Its coordinate vocabulary therefore does not by itself define an arbitrary
`[theta,y,x,phi,q]` scattering acquisition schema. An acquired cake's phi and q
axes also have meanings different from physical image coordinates. Retain those
meanings explicitly rather than labelling them as spatial image axes.

The [axis-generalization RFC-3](https://ngff.openmicroscopy.org/rfc/3/index.html)
was marked under review in the inspected documentation. The installed library
has an opt-in `0.9.dev1` model associated with that work. This investigation does
not select that development format for project data.

## Installed-library findings

The shared `nim` environment reports `ngff-zarr 0.52.0`. Its installed code and
the [library's RFC-5 guide](https://ngff-zarr.readthedocs.io/en/latest/rfc5.html)
provide concrete support beyond recognizing a version string:

| Capability | Inspected support |
| --- | --- |
| Read/write 0.6 multiscales | `from_ome_zarr`, `to_ome_zarr(..., version='0.6')` |
| Named systems and transforms | `ngff_zarr.v06.zarr_metadata`, including `CoordinateSystem`, `Affine`, `Rotation`, and transform sequences |
| Related-image scenes | `NgffScene`, read with `kind='scene'` |
| Array-backed transform parameters | Scene writer can store affine/rotation matrices outside the JSON document |
| Existing image formats | Reader supports earlier NGFF image versions as well |

## Small capability probe

A disposable 8³ float32 array was written as a two-level NGFF 0.6 image, with
0.65 µm spacing and a known origin. The full-resolution array was read back and
compared exactly. TomoSWAXS's current `VolumeSource` also opened this simple
axis-aligned image correctly: XYZ spacing became 0.00065 mm and origin became
`[0.003, 0.002, 0.001]` mm, as expected from the supplied micrometre coordinates.

The same image was written under `ct` in a 0.6 scene with a named `lab` frame
and a known affine translation. `ngff-zarr` read back the scene, its image name,
coordinate system and affine values. This is a working read/write path in the
installed environment.

The application did **not** open the scene root: its single-image reader raised
an explicit error directing the caller to `kind='scene'`. Opening the `ct` child
read its intrinsic image coordinates; it did not apply the scene's laboratory
transform. That is the practical distinction between library and application
support.

The probe checked array values and metadata round trips. It was not a full
schema-conformance or cross-viewer interoperability test. The probe and result
are retained outside the repository in
`~/src/nim/data/inspection/ngff-0.6/`.

## Application implications

Current code in `volumes.py` reads a single multiscales image, extracting
per-level scale and translation through `NgffImage`. Its geometry path does not
traverse a scene or compose the additional transforms into the viewer's geometry.
The TIFF importer explicitly writes version 0.5.

The import-supplied pixel-size editor also directly accesses 0.5-style
`multiscales.axes` and simple scale/translation dictionaries. In 0.6 the axes
belong to named coordinate systems and transforms carry references. That editor
needs a version-aware adaptation before our own TIFF imports change format.

A focused adoption plan would be:

1. Read a scene and select its CT image while retaining the coordinate graph;
   continue to support existing single-image stores.
2. Resolve a scientist-supplied CT-to-sample/laboratory mapping, including units,
   for rendering and beam/region queries. Preserve image-native crop indices and
   the inverse mapping needed to relate viewer selections back to source data.
3. Adapt import and pixel-size metadata handling to the chosen version while
   preserving existing 0.5 stores and their physical coordinates.
4. Represent scattering acquisitions and coverage alongside the registered
   images, retaining their measured coordinates and source provenance. Define
   viewing aggregation and simulation inputs with the scientists.
5. Check representative data and intended external readers before making 0.6
   the default interchange format.

These are proposed development steps, not implemented migration work.

## Recommendation for the multimodal representation

Use NGFF 0.6 as the target for named image-coordinate relationships and scenes.
Keep raw/integrated scattering as chunked arrays with explicit measurement,
q, phi and position/rotation coordinates. Those arrays can be linked alongside
the scene in an explicitly versioned acquisition schema; scientist-provided
spatial maps can use NGFF image metadata where their axes fit that model.

Prepare for full Y coverage through coordinate arrays and chunked access, rather
than encoding the current three scans as a fixed three-level structure. Preserve
snapshot-derived coordinates separately from future per-exposure readbacks.
The [storage/rebinning notes](multimodal-storage.md) describe proposed Y markers,
range restriction and display-footprint aggregation.

This direction gives the viewer a standard way to carry known geometric
relationships while leaving scientific reconstruction, simulation and the
definition of averaging weights with the beamline experts.
