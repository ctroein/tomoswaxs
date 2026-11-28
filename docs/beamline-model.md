# ForMAX beamline context

## Optional model downloads

`model_store.py` verifies and installs versioned ZIP bundles on the application
host. `beamline_download.py` requests the configured release on first selection
of Sample area or Whole beamline when no local CAD model is loaded. Transfer,
cache checks and extraction run in a worker thread; VTK props are constructed on
the render thread in a temporary renderer and replace the previous equipment
only after the full model loads successfully. Progress, Cancel and Retry share a
small dialog. Cancellation and failed acquisition preserve the previous scene.
Restored equipment views also request missing assets, preserving the saved camera.

The catalogue is `src/tomoswaxs/beamline_release.json`. Its `formax` entry is
currently `null` pending the first published bundle; the existing schematic
fallback remains available. Current checkout assets and `--beamline-model` take
precedence over downloads. No download runs at ordinary Sample startup.

A catalogue entry pins the model version, download URL, archive byte size and
SHA-256, plus the byte size and SHA-256 of every installed file. Cache reuse
verifies all files; it works offline. Files live under
`${XDG_DATA_HOME:-~/.local/share}/tomoswaxs/beamline-models/formax/<version>/`.
ZIP filenames must be flat and match the catalogue; both referenced VTP meshes
must be included. Complete verified files are moved atomically, with `model.json`
last. The archive and partial extraction directories are temporary.

When the geometry is ready, prepare a release outside the repository, for example:

```bash
python tools/prepare_beamline_release.py ../data/3dmodel/formax-reduced/model.json ../data/model-release-v1 --version v1 --tag models-v1 --include /path/to/model-credits-and-licence.txt
```

The tool creates `formax-v1.zip`, its `.sha256`, and `beamline_release.json`.
The ZIP contains only the runtime manifest, referenced meshes and explicit extra
files. ZIP metadata is deterministic; the VTP files are already compressed.
Review the ZIP and credits, publish the ZIP/checksum as release assets, then copy
the generated catalogue into `src/tomoswaxs/beamline_release.json`. Keep published
versions immutable; subsequent mesh changes get a new model version. Preparing
an archive does not upload it or modify the application's catalogue.

Automated checks cover HTTP transfer, failed checksums, unexpected archive
members, cancellation, offline cache reuse and corrupted-cache repair. Controller
checks cover first-use loading, retry, scene rollback and saved-camera preservation.
A local HTTP fixture also verified GUI progress, intentional failure, Retry,
Cancel, a fresh request and automatic display of the selected equipment level.

## Supplied CAD assembly, 2026-11-26

The local application uses the supplied assembly when a prepared asset is
available at `data/3dmodel/formax-reduced/model.json`. Startup searches the
`--data-dir` directory and the data directory beside the checkout. An explicit
`--beamline-model /path/to/model.json` selects another prepared asset.
The original CAD and prepared meshes stay in the external data directory.

The input is `New+assembly+_EL.stl`: 6,745,820 triangles, approximately 322 MiB.
Its Magics STL attributes contain 17 colours, usable without the OBJ's missing
MTL file. `tools/prepare_beamline_model.py` welds coincident points and applies
volume-preserving quadric decimation independently within each colour, protecting
colour boundaries. Feature-angle normals are regenerated afterwards. The current
asset has 701,717 triangles and occupies 14.1 MiB as compressed binary VTP.
The viewer reads the prepared asset, rather than simplifying it during startup.

Rebuild from the checkout in the existing environment:

```bash
python tools/prepare_beamline_model.py ../data/3dmodel/New+assembly+_EL.stl ../data/3dmodel/formax-reduced
```

`--triangles` changes the target count; `--sample-cad-y` changes the initial
estimated sample location along the beam. The manifest records input SHA-256,
triangle counts, reduction by colour, tube fit and placement. It can be edited
to correct placement without rebuilding the geometry.

The large flight-vessel wall has a Y-parallel axis at CAD X = 120.886116 mm,
Z = −699.743394 mm, radius 507.5 mm. That axis is offset from the beam.
The beam reference instead comes from the upstream 20 mm-radius pipe, agreeing
with the WAXS opening: CAD X ≈ 0 mm, Z ≈ −659.912 mm. A vertical spindle in the
supplied holder gives CAD Y ≈ 899.899 mm for the sample's position along the beam.
The spindle's transverse position is not substituted for the beam axis.
The current approximate transform is:

```
lab X = CAD X
lab Y = CAD Z + 659.912
lab Z = 899.899 − CAD Y
```

`model.json` records separate `beam_axis_fit`, `holder_axis_fit`, and `tube_fit`
measurements. The last describes the large vessel, not the beam reference.
`sample_position_cad_mm` remains an explicit adjustable estimate. Equipment
placement affects only the CAD; CT registration and scientific coordinates stay
in their existing laboratory frame.

Both machinery levels use our coloured reconstruction from Mira's sketch,
now uniformly scaled to 140 mm total height and about 91 mm maximum width.
Its top remains at the sample; it floats above the table. These are illustrative
stage dimensions, not identified ForMAX hardware dimensions. The retired CAD
rotary platform and spindle are excluded; the black holders and grey handle
below remain. The parked tomography microscope appears only in Whole beamline.
The separate `230390_MAX_IV.STL` is not used in this assembly integration.

`beamline_mesh.py` loads the coloured VTP and applies placement only to the
equipment actor. CT registration, sample rotation and measured beam position
retain their existing laboratory frame. The **Beamline** menu has three exclusive
levels: Sample (default), Sample area and Whole beamline. Each selection fits
the camera to that level; manual camera movement retains the selected geometry.
CAD geometry uses the
existing adaptive clipping, FXAA, visibility and saved-view controls.

### Sample-area selection

`tools/beamline_regions.json` contains the four CAD-coordinate inclusion boxes
chosen in the interactive preview: WAXS and SAXS, upstream beam pipe, holders,
and SAXS housing. A triangle is included when all three vertices lie inside
one box. Selection can cut objects open at the box boundaries. No stage
exclusion or connected-component filter is applied to Sample area.

Rebuild the area mesh from the coloured source STL:

```bash
python tools/prepare_beamline_area.py ../data/3dmodel/New+assembly+_EL.stl ../data/3dmodel/formax-reduced/model.json
```

This updates `sample-area.vtp` and its selection metadata while preserving the
whole-station mesh and model placement. The current area mesh has 175,285
triangles. `sample-area-components.json` records the boxes and triangle counts.
The existing whole-station mesh has 703,061 triangles; its retired-stage cleanup
is separate. Use `--rebuild-station` only when also regenerating that asset.

#### Reusable selection editor

Generate a standalone HTML editor from the original prepared CAD mesh:

```bash
python tools/beamline_selection_editor.py ../data/3dmodel/formax-reduced/geometry.vtp ../data/3dmodel/selection-editor.html
```

Open the resulting HTML file in a browser. Choose a box, adjust its bounds with
the numeric fields or sliders, and use Save JSON to export the coordinates.
The mesh and Plotly are embedded, so the editor works offline. The generator,
HTML template and JavaScript controls live in `tools/beamline_selection_editor.*`;
generated HTML and mesh data stay outside Git.

The preview defaults to a target of 250,000 triangles, preserving the initially
selected surfaces and simplifying surrounding geometry. Use `--max-triangles 0`
for the complete input mesh. Use `--regions /path/to/beamline-selection.json`
with either the editor generator or area-preparation script to reuse an export.
Copy accepted coordinates into `tools/beamline_regions.json` to update the
repository's default selection.

The 2026-11-28 selection was checked through the application CAD loader at three
viewing angles. Focused preparation and placement tests passed, including a
regression for pipe triangles previously removed by the stage exclusion.
Editor checks cover coordinate export, triangle containment, self-contained HTML
generation and retention of selected surfaces during preview simplification.
The regenerated editor has not been exercised in a live browser in this session.

The blue beam extends across the selected equipment bounds and returns to its
sample-scale length in Sample mode. It retains its X/Y position and physical
radii. A blue screen-width core in the same actor keeps the narrow beam visible
at station scale, sharing its directional gradient, depth and visibility.
The yellow context lines have been removed. The existing Show beam control
also applies to equipment views.

Verification of the corrected equipment used Bamboo with NVIDIA EGL: area and
station views at three azimuths each, a sample close-up with the extended beam,
and browser transitions through Sample area, Whole beamline, Default camera,
and back to Sample. The final browser return check reported no JavaScript errors.
All 43 focused tests passed across beamline geometry/preparation, camera,
beam/volume transparency, view controls and startup. Mesh masks, reference fits,
compact stack dimensions, beam extent and restoration of its sample-scale length
have automated coverage. Diagnostics are in
`data/inspection/beamline-review-2026-11-27/`.

Current `camera.beamline` records contain `level` (`sample`, `area`, `station`),
`labels`, and camera `scope` (`sample`, `area`, `station`). Scope tracks camera
fitting separately from geometry level, including when Default camera is used.
Legacy `visible`/`labels`/`scope` records migrate on reading: hidden becomes
Sample, visible old stack views become Sample area, other visible views become
Whole beamline. Restored cameras retain their saved position and orientation.

Verification on 2026-11-27 covered all three choices in the browser with Bamboo,
exactly one checked menu item, independent label visibility, changing camera
angle while retaining Sample area, and returning to Sample. No browser JavaScript
errors appeared. Native checks cover selected actor sets, static equipment
under sample rotation, active clipping bounds, unchanged scientific state,
bookmark restoration and legacy migration. Native level images are under
`data/inspection/beamline-levels-2026-11-27/`.

### Verification

Checked the actual prepared assembly with Bamboo on NVIDIA EGL. Eight browser
checks covered enabling the CAD, station and sample presets, pointer orbit and
zoom, Default camera at CT scale, further close-up zoom, label visibility and
hiding the model. Browser JavaScript and rendering reported no errors. Beam
coordinates, scientific sample angle, radii, opacity and colour mapping were
unchanged. Images and the state comparison are under
`data/inspection/formax-integration-2026-11-26/`.

A deterministic sample of 12,000 original triangle centres had median distance
0.062 mm to the reduced surface, 95th percentile 0.609 mm, 99th percentile
2.59 mm and maximum 38.4 mm. This samples triangles uniformly, rather than surface
area, and is not a geometric error bound. Aggressive reduction removes some small
mechanical features; the asset is for visual context. Source files are retained
for rebuilding with a higher triangle target. Focused tests cover the proper
rotation, sample-origin placement, beam and vertical directions, colours,
equipment bounds and independence from scientific sample pose.

## Original illustrative model

Optional surroundings in the existing µCT viewer, implemented 2026-11-26.
The primitive fallback supplies the same three Beamline levels and label control.
Its coloured motor stack uses the same compact dimensions as the CAD context.
It works before opening a sample; Saved views → Default camera fits the CT sample itself.

## References

The main source is Nygård et al. (2024),
[ForMAX – a beamline for multiscale and multimodal structural characterization
of hierarchical materials](https://doi.org/10.1107/S1600577524001048), sections
2.3–2.4 and figures 3–4. The earlier
[MEDSI design paper](https://proceedings.jacow.org/medsi2020/papers/wepb12.pdf)
provides additional overall mechanical layout. See also the
[MAX IV station description](https://www.maxiv.lu.se/beamlines-accelerators/beamlines/formax/experimental-station/).

Mira's `data/Motor_stack_combined_formax.jpg` and explanation supply the combined
stack: swaxs_y, swaxs_x, tomo_ry, tomo_xf, tomo_zf, sample, bottom to top. The
public paper illustrates several interchangeable stacks; Mira's arrangement
takes precedence here. Published images and the private sketch are not bundled
as application assets; all geometry is constructed from primitives.

## Dimensions and assumptions

Units are millimetres: Y vertical, beam along +Z, nominal sample/rotation-axis
intersection at the origin. Apparatus is fixed in this frame. Dimensions and
table height are independent of the active sample's size and crop.

| Component | Model | Basis |
| --- | --- | --- |
| Table top | 800×800 mm, top Y = −400 mm | Published surface size; relative height estimated within the published approximately 520 mm available space |
| Table base | 620×820×650 mm | Estimated proportions |
| Motor stack | 140 mm tall, approximately 91 mm maximum width; floating below sample | Order from Mira; illustrative compact dimensions, independent of table height |
| Gantry | Approximately 2 m wide/high | Envelope from earlier design; placement and member dimensions estimated |
| BCU II | Upstream housing, centre Z = −720 mm | Arrangement documented; detailed dimensions and placement estimated |
| Microscope | Parked beside beam, X = 570 mm | Translation out of beam documented; parked location and geometry estimated |
| WAXS | Four panels around an opening, Z = 260 mm | Central opening documented; simplified shape and placement estimated |
| Flight tube | 1000 mm diameter, visible Z = 900–2300 mm | Published 9 m length and 1 m diameter; only an estimated entrance section represented |
| SAXS detector/trolley | Face approximately 155×162 mm, Z = 1900 mm | Face based on published pixel count/pitch; distance illustrative, within published travel |
| Nose cone, rails, beamstop | Simple shapes | Arrangement documented; dimensions and placement estimated |

Apparatus shows a fixed SWAXS arrangement with the microscope parked aside.
The nose cone and tube have their upper halves removed to expose the interior.
The tube ends at an open cut, labelled as continuing. The extended blue beam uses the same geometry as the sample view, with a thin
screen-width core for visibility at equipment scales.
The no-sample marker is enlarged for visibility and disappears when a CT volume
is present. The apparatus stays separate from the sample pose; beam position remains in the
existing laboratory frame. No active scan detector distance or
motor position is applied to this first model.

## Implementation

`beamline.py` owns independent named component actors, providing a place to
replace primitives with meshes later. Mechanical poses can be connected to
measurements in a later version. Station labels give way to motor labels below
a 650 mm view span.

The camera presets share the µCT viewer. Context visibility expands zoom limits
and includes equipment in clipping bounds. FXAA is enabled while the equipment
is visible and disabled when hidden. Adaptive clipping is recalculated
before each equipment-context frame and after explicit camera/scene changes.
VTK supplies the scene range; a near-plane floor of 0.5% of camera-to-focal
distance avoids wasting depth precision on nearby empty space when the camera
is inside the station's overall bounds. The near plane is also limited to half
the nearest positive CT-corner depth, protecting sample close-ups. Inside the
CT bounds the distance-scaled floor is used. This replaces the fixed 1e-6
near/far tolerance that produced angle-dependent surface artifacts. The closest
0.5% of the orbit distance can be clipped when approaching equipment surfaces.
Default camera approaches the sample from above while equipment is shown,
keeping the holder below it. Machinery level selections fit their own geometry.
Saved cameras restore their exact viewpoint. The original optional
`camera.beamline` format used `visible`, `labels`, and `scope`
(`sample`, `station`, `stack`); see the current migration above.

`tests/test_beamline.py` covers dimensions, stack order, visibility, camera
presets, stationary equipment during sample rotation, and bookmark recovery.

## Bamboo verification, 2026-11-26

Checked the Bamboo OME-Zarr CT at a 256 MiB array limit using NVIDIA EGL.
Settled browser images covered visibility from the initial sample view, both
equipment presets, Default camera, label visibility, Auto detail with camera
rotation, and hiding the equipment again. Beam position, scientific rotation,
radii, opacity and colour mapping were unchanged. Rendering and browser
JavaScript reported no errors. A startup POST to `/paraview/` returned HTTP 405;
the connection and tested interactions still worked. Diagnostics are retained
with the screenshots and JSON under `data/inspection/beamline-2026-11-26/`.

The check exposed holder occlusion when enabling equipment from the normal
below-sample camera. The first-enable elevation adjustment above fixes that
case. A regression test verifies preserved azimuth/zoom and exact restoration
of intentionally saved below-holder cameras.

## Adaptive clipping verification, 2026-11-26

The fixed small tolerance reproduced the reported contact-edge triangles with
a 0.0044–4418 mm clipping range. Adaptive clipping used 4.4–4418 mm at the same
camera and removed those artifacts. Verified on NVIDIA EGL with Bamboo using
27 rendered views: station, stack and sample views at four orbit angles and two
dolly distances, plus the reproduced intermediate camera, field-of-view zoom
and parallel sample projection. Sample close-ups kept their foreground inside
the clipping range; the field-of-view and parallel examples used near distances
of approximately 1.44 mm and 0.67 mm, respectively.

Automated coverage checks 216 combinations of preset, dolly, azimuth and
elevation, sample bounds under perspective/parallel projection, and repair of
interactor-supplied clipping before a frame renders. Nine Bamboo browser checks
covered presets, mouse orbit, wheel zoom, parallel Beam view and Auto detail.
Inspected frames had clean equipment boundaries and intact sample detail;
browser JavaScript and the render-status field reported no errors. Images and
clipping measurements are in `data/inspection/beamline-depth-2026-11-26/`.
