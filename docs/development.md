# Development

For initial setup, see the [installation guide](installation.md).
For the web interface, see the [user guide](user-guide.md).
Near-term priorities and investigation topics are in [planned work](planned-work.md).

Startup has no specimen: an invisible 2³ zero buffer only initializes VTK.
`has_sample` identifies an active sample record; `has_volume` identifies a loaded
CT image. Legacy `ct.kind='synthetic'` records remain readable as samples without
CT; new CT-less records use `kind='none'`. No generator or example-data fallback
remains. Tests use an explicit in-memory fixture in `tests/sample_fixture.py`.
Browser-local project history is in `assets/projects.js`, with eight recent
paths and a last-open path under `tomoswaxs.projects.v1`. Server history events
record successful opens/creation and explicit closes. Recovery is accepted only
once per server startup, into an empty workspace, and is suppressed by explicit
CLI project/volume arguments. Existing server state takes precedence when a
second browser connects. Missing projects produce the normal visible error;
storage failures produce a separate notice. History does not store scientific
view state or bypass the project manifest's ownership/concurrent-write checks.

ForMAX registration uses `model='stack'` for new CT-referenced attachments.
Upper-stage deltas contribute `xf_factor * Δxf * sin(motor_angle)` and
`zf_factor * Δzf * cos(motor_angle)` to beam X; the lower-stage factors retain
their explicit signed XY mapping. swaxs_y and tomo_ry share vertical direction;
swaxs_y snapshots still distinguish acquired heights. swaxs_ry is assumed to
have no further effect at 180°; other supplied snapshots produce a warning.
`pivot_x/pivot_z` are retained JSON field names for empirical trajectory
coefficients (µm in the CT frame after image-axis alignment), defaulting to zero.
They add `pivot_x*cos(view_angle) + pivot_z*sin(view_angle)` to beam X.
The shared `sample_pose_matrix()` maps image mm by `R_y(theta) * A * image`.
Volume rendering and crop-handle forward/inverse transforms use that same
matrix with zero translation: the CT stays centred on viewer Y. Mechanical stage
projections use nominal motor angles, independently of CT orientation offsets.
SAXS controls receive per-angle X grids; the browser must select the current
row before interpreting an X value. Pivot and stack parameters persist in the
sample's scattering placement. Original untouched motor-factor estimates
upgrade to this model; custom/manual placements retain their previous model.
The sinusoidal trajectory is an empirical beam-to-CT registration, not an
independently established physical rotation-axis location. The earlier version
translated the CT by `-R*pivot`; that caused the specimen to orbit in the viewer.
Moving the equivalent correction to beam X preserves transverse beam/sample
alignment while keeping CT rotation centred. Do not restore that CT translation.

Internal data investigation: [Bamboo/ABS file and coordinate notes](data/bamboo-abs.md)
and [multimodal storage and rebinning](data/multimodal-storage.md).
See also the [NGFF 0.6 capability investigation](data/ngff-0.6.md).

Run commands from the repository directory. `uv sync --active --locked` installs into the active
project environment. Our local setup uses the shared pyenv `nim` environment. Application code and browser assets live under
`src/tomoswaxs/`; `pyproject.toml` declares the installed `tomoswaxs` command.
Python 3.12 or newer is permitted; verification has covered Python 3.12.13
and 3.13.15. Do not exclude other versions without evidence of incompatibility.
Local verification uses the shared `nim` environment; check its actual patch
version when reporting results.

## Running and testing

Use a second port when testing edits so an existing demo session remains
available:

```bash
uv run --active --locked tomoswaxs --server --port 8081 --timeout 0
uv run --active --locked python -m unittest discover -s tests
```

The server does not reload source edits automatically. Restart it explicitly to
load changes. Announce restarts of a running demo; browser tabs must reconnect
or reload afterward. `--timeout 0` disables Trame's idle shutdown, but does not
make the process survive termination of its shell or execution session.

### Local startup on login

`tools/systemd/tomoswaxs.service` runs the checkout at `~/src/nim/nim` using
the shared pyenv `nim` environment. It starts with a graphical login, stops
with the graphical session, and restarts after a failure. Source code is loaded
directly from the checkout. It opens the demo on port 8080; the file selector
starts in `~/src/nim/data`.

Run this once from Carl's terminal to enable it and start it immediately:

```bash
systemctl --user enable --now "$HOME/src/nim/nim/tools/systemd/tomoswaxs.service"
```

Open http://127.0.0.1:8080/ in a browser. Manage the service with:

```bash
systemctl --user status tomoswaxs.service
journalctl --user -u tomoswaxs.service -f
systemctl --user restart tomoswaxs.service
```

Restart after source edits to load changes. To disable automatic startup and
stop the server, run `systemctl --user disable --now tomoswaxs.service`.
After editing the service unit itself, run `systemctl --user daemon-reload`
before restarting it.

For the dependency-free JavaScript input-queue test, if Node.js is available:

```bash
node tests/beam_input.cjs
node tests/preferences.cjs
node tests/coordinates.cjs
```

Check volume rendering, camera navigation, beam dragging and release, numeric
controls, dock panel resizing, and the About dialog in a browser after relevant
GUI changes. An application startup check alone does not verify these workflows.
The application currently has one shared state, so browser tabs on the same
server affect each other.

## Data and scope

Generated data and screenshots go in the sibling `../data/` directory. Keep
scientific assumptions explicit: the default CT specimen is
fabricated; TIFF scales come from supported metadata or explicit user input. Internal
spatial coordinates are mm and controls display µm. SAXS panels remain empty until measured scans are attached and use their stored I(q). Beam radii affect only the
visual geometry.

OME-Zarr input and TIFF import preserve source scalars and physical metadata.
Validated motor-coordinate registration, measured scattering processing,
rebinning, and remote multi-user deployment have not been implemented. Do not
present these as supported features.

## Project persistence and sample lifecycle

`projects.py` owns the version-1 `nim-ct-saxs-project` manifest, stable sample IDs,
CT/scattering references, axis settings and viewing state. `project_workflow.py`
connects the model to the global Project menu, New/Settings dialogs, the direct
Open project chooser, sample selection and background loading. Header and menu
actions keep stable labels and remain visible when unavailable, with disabled
states. Directory activation navigates even when a project manifest is present;
the chooser's Open button can also open a selected project directory. Chooser
failures must be visible within the chooser, including unexpected exceptions;
unexpected exceptions are logged with tracebacks. New projects derive their
display name from the chosen directory; existing projects can be renamed in
Project settings. Folder icon buttons beside path fields use Exhale's Tabler SVG
and its accompanying MIT licence from `assets/icons/`.
Existing datasets are referenced; internal paths are relative and external paths
absolute. The project directory contains `project.json` and, as needed,
`data/<sample-id>/`, `results/<sample-id>/`, and `figures/<sample-id>/`.

Valid, settled changes are saved automatically with atomic manifest replacement.
Replacement manifests preserve the existing file's permission bits and group.
New manifests use normal file-creation permissions, honouring the process umask
and directory default ACL rather than forcing private temporary-file permissions.
Concurrent disk edits are detected before replacing the manifest. Saved view
values include beam X/Y and radii in µm, angle in degrees, opacity and original
intensity contrast limits; camera coordinates are in the viewer's mm space.
The manifest also identifies the active sample. A sample can be referenced by
several projects with independent settings. Output directories are established
by the model; measured analysis and batch execution remain future work.

Standalone viewing is read-only inspection: changes to sample/view state remain
in memory. Axis assignment is saved only in a project. `legacy_axis()` can read
an old dataset's `nim-view.json` as an initial value; neither standalone viewing
nor project editing writes viewer settings back to the dataset. Browser-local
interface preferences continue to save in browser storage.
Closing Sample settings saves edits to import-supplied pixel size in the dataset metadata,
including all pyramid scales and translations, without rewriting chunks. New
imports record whether source pixel size existed so sources with pixel-size metadata are
excluded. The cached rendering preview is reused, with new physical geometry.

TIFF selection without a project offers project creation or an explicit external
conversion destination. Project imports default to an internal destination and
register a sample only after successful conversion/preview reading. New project
can retain the current standalone sample and view with Include current sample.
Project-free conversion explicitly writes a new dataset while preserving input.

The single Open sample action works with or without a project. `sample_management.py`
owns the Samples dialog, its source list, rename and membership removal. Removing
an active member loads a replacement before removing its record, so a failed
replacement leaves membership intact. Removing the last member clears the view
and invalidates queued input; `has_sample` gates scientific controls and panels.
Removal updates only the manifest. Data files are retained. Sample provenance
belongs in sample information and source columns, rather than toolbar labels.

One project and sample are active per server. Cancellable background reads return
immediately from their initiating RPC. Jobs and queued coordinate/beam events
carry a sample-context token so late completion or input cannot affect a newer
selection. Sample switches preserve the old scene on read failure or cancellation.
Save failure prevents switching away from an unsaved active sample.

The Project dialog is client-only. Server-driven visibility changes must clear
Trame's state-client cache and mark the key dirty so an unchanged Python value
still reaches a browser whose local modal state differs.

Tests cover atomic saves, external edits, malformed manifests, moved projects,
independent references, legacy settings, standalone inspection, both TIFF import
choices, relinking, sample/view/camera restoration, stale input and cancelled
jobs. `tools/browser_check.py` also exercises project creation from TIFF import,
sample settings and switching, close/reopen and modal dismissal.

## Git and releases

Development is local; no GitHub remote or publishing workflow is required.
Leave changes uncommitted for Carl to review unless a commit is requested.
The initial packaging version is `0.1.0.dev0`; the About dialog identifies the
software as a development prototype. `uv build` creates a wheel and source
distribution. Include the matching lockfile or requirements export when
distributing a reproducible environment.

## Browser preferences

`assets/preferences.js` owns a versioned browser-local preference record and a
native Settings dialog. CSS variables in `assets/app.css` implement light/dark
appearance and relative text sizing. Plotly styles are applied locally after
server updates, preserving data and user zoom. The shared VTK viewport stays
dark. Do not put browser appearance preferences in shared Python state.
`workspace_ready`, dialog visibility and appearance values are explicitly
client-only Trame state. Dock layout JSON stays in browser-local preferences. The preference record excludes scientific state.

The browser preference `voxelArrayMib` restores `volume_preview_mib` and is
updated from both Resolution and Settings. The server startup value supplies the
initial default and Reset preferences value. Restoring a different limit with a
CT image loaded submits a bounded rendering request. Invalid partial edits are
not persisted. Active control labels use `--text`; supplementary text uses
`--muted`, and disabled controls retain their disabled styling.

When changing settings, check light/dark/system appearance, text size, browser
zoom, dock layout persistence across reload, reset, and continued local plot styles
after a beam update. Browser storage failure must not stop the app.

## Coordinate interactions

`auto_detail.py` computes a convex camera frustum/slab in image coordinates,
intersects it with the manual crop, and reads the enclosing axis-aligned box.
Its temporary data window never overwrites `crop_bounds` or `_render_spec`, nor
changes the camera focal point. VTK clipping planes are transformed from image
coordinates to world coordinates so Freeze remains attached to the sample.
The Depth slider scales thickness logarithmically relative to view height; its
last position covers the manual crop's full depth. Perspective and orthographic
cameras share the same planning path, including voxel spacing and sample pose.

Automatic requests share `volume_viewing.py`'s cancellable worker. Coverage tests
use the actual visible region; fetched boxes have 12% extra coverage on each
image axis, clamped to manual Crop. Existing useful detail stays resident during
motion. A small coarse array may be retained as fallback (up to 8 MiB, normally
one eighth of the array budget); the main array uses the remaining budget, with
at least 1 MiB per array. At a 1 MiB limit, these two arrays may total 2 MiB.

There is one 100 ms settling policy, bypassing the manual worker's 150 ms
debounce for automatic requests. After each completion the latest view is
replanned. Stable views refine through at most two intermediate pyramid levels
before the target; stages already covered at equal or better spacing are skipped.
Single-scale sources can refine by stride. Results must cover the latest actual
region and satisfy the current size limit; late coarser results cannot overwrite
useful finer detail. Sample/control changes cancel queued work and reject old
generations/contexts. Refinement preserves colour mapping, camera, pose and SAXS.

`volume_cache.py` maintains a byte-bounded decoded-block LRU through public Dask
APIs. Its limit is twice the voxel-array limit, clamped to 8–256 MiB, in addition
to rendered arrays. Hits copy only the selected voxels. Misses use up to four
workers; the largest block and array budget reduce concurrency for large blocks.
Only that bounded number of reads are submitted at once. Completed blocks can
serve later views, including after their original view becomes obsolete.
Clearing the cache advances an epoch so old completions cannot repopulate it.
Automatic reads reuse existing intensity bounds rather than calculating new
percentiles. Manual preview reading retains its original path.

The array limit describes neither total host nor GPU memory. Replacement needs
old/new arrays temporarily; cache, decoding buffers, Dask graphs and GPU textures
are additional allocations. A source block larger than the work budget still
requires one block read. See [Auto detail performance](auto-detail-performance.md)
for the motivating measurements and implementation follow-up.

`view.volume.auto_detail` optionally stores `enabled`, `depth`, and six
`frozen_planes` (or null), validated by `projects.py`. Existing manifests need no
migration. Source/sample changes discard caches and pending requests. A camera
bookmark changes the camera without discarding the active auto-detail mode.

This first version loads an enclosing rectangular array rather than rendering
individual OME-Zarr chunks. Oblique views therefore retain some off-screen data.
Geometry, async refinement, empty regions, restoration and orbit invariants are
covered in `tests/test_auto_detail.py`.

`assets/updates.js` provides the shared bounded RPC queue for pointer gestures
and coordinate controls. It allows one request in flight and one pending update
per source. Pose patches merge the latest X/Y/angle values so simultaneous edits
are committed atomically by `Demo.receive_pose()`. Do not bind high-frequency
sliders directly to server-synchronized state.

`assets/coordinates.js` owns client-only camera-angle drafts, angle wrapping,
and camera playback. Server acknowledgements must not overwrite newer local
drafts. Camera requests use `nim_camera_angle` in the same bounded queue and
never update the sample pose or SAXS plots. Playback uses elapsed time (default
30°/s), pauses when the page becomes hidden or the volume is manipulated, and
retains the final angle on Pause. Acquired sample coordinates are selected in
the SAXS measurements panel.

Beam view is a one-shot camera action. The browser stops playback without
submitting its last angle and replaces the pending `camera` queue entry with
`beam-view`. It runs through `nim_beam_view` after any in-flight request, so an
old queued angle cannot undo the alignment. The server checks sample context;
subsequent manual camera movement works normally.
Beam view uses parallel projection along the beam, centred on the selected
crop rather than an offset beam. Parallel projection keeps both endpoints of
an offset beam at the same screen point; the beam need not be in frame.
Both presets fit a sample-centred bounding sphere with an 8% margin so arbitrary
orbits retain the sample. Cached sample-wide display bounds exclude transparent
margins when available; view-dependent Auto-detail arrays do not replace that
cache. Neither beam position nor length sets the zoom. Beam length is 60% of
the former `max(4.5, diagonal * 1.25)` rule.

`camera.py` owns laboratory-Y camera orbiting, heading synchronization after
mouse interaction, and the visible crop centre. Cropping translates both camera
position and focal point to that centre, preserving direction and distance.
Default camera fits those visible sample bounds around the crop centre. Saved-view recall preserves
the saved camera, including its pan, until a crop/pose change or explicit camera
orbit. Keep camera geometry separate from the CT–SAXS registration transform.

## Dependency-update trials

Runtime dependencies have minimum versions and upper bounds at the next minor
release. Patch releases are admitted within those ranges. `uv.lock` records the
complete tested resolution, including transitive dependencies.

One-time browser setup:

```bash
uv sync --active --locked
uv run --active --locked python -m playwright install chromium
```

Run an update trial and automatically accept it if all checks pass:

```bash
uv run --active --locked python tools/try_dependency_updates.py
```

Use `--check-only` to retain a successful candidate without changing the checkout.
The default test port is 8081; `--port` selects another test port. An occupied
port fails the trial. Port 8080 is reserved for the running demo.

Each trial snapshots the source, removes upper runtime dependency bounds while
preserving minimums and exclusions, builds a wheel, and installs it into an
isolated environment with current stable dependencies. Document any bounds that
must remain in `[tool.dependency-trial.keep]`. Equality and compatible-release
specifiers require a documented exception or conversion to explicit bounds.

The trial runs Python and JavaScript checks, verifies installed dependencies,
and starts the installed application from outside the checkout. Playwright
checks rendering, coordinate fields and sliders, wrapping and playback,
Alt+Shift beam movement, beam radius, dock resizing and tab docking, persisted settings and
About resources. For JavaScript unit tests, the tool uses system Node when
available, otherwise the Node executable bundled with Playwright.

After a successful first pass, bounds expand to the next minor version after
each newly admitted direct dependency. The tool resolves a candidate lockfile,
installs the bounded package as a non-editable installation, and repeats the
checks against that environment. Successful trials replace `pyproject.toml`
and `uv.lock`. Concurrent source edits abort acceptance. A write failure rolls
back both configuration files. The tool leaves changes for review and commit.

Trials and diagnostics stay in `.dependency-trials/<timestamp>/`: `setup.log`,
`installed.json`, `result.json`, source snapshot, built distributions, and the
`latest-checks/` and `locked-checks/` directories. Failed checks retain
`checks.log`, `server.log`, and, for browser failures, `browser-trace.zip` and
`browser-errors.txt`. Open a trace using:

```bash
uv run --active --locked python -m playwright show-trace /path/to/browser-trace.zip
```

Inspect these diagnostics when a trial fails, correct the application or its
requirements, and rerun the trial. Browser executable or system-library errors
require repairing the development browser environment before retrying. Trials
leave the user-facing server running. These synthetic-data checks cover GUI
compatibility; scientific validation requires representative measured data.

Reproducibility covers the resolved Python packages. VTK rendering must also be
verified against the target machine's graphics libraries and drivers.

## OME-Zarr volume access and TIFF import

`volumes.py` uses ngff-zarr 0.52 for native OME-Zarr access. `VolumeSource` exposes
metadata, lazy levels, region reads and point sampling. Its bounded preview is
separate from source data. VTK uses that preview.

TIFF import writes OME-Zarr 0.5 with 64³ chunks and DASK_BIN_SHRINK block-mean
levels. Level zero retains source dtype and values. Supported ImageJ/OME-TIFF
pixel size is read, or the user explicitly supplies XYZ spacing in µm. No
scale is inferred from filenames or other samples. Provenance is stored in
`nim_import` root attributes. TIFF coordinates are centred on the full volume;
ngff-zarr records the per-level centre shifts and spacing changes.

The TIFF adapter copies only requested blocks, honours the on-disk byte order,
and closes each memory mapping. Big-endian float and integer stacks are covered
by round-trip and pyramid tests.
Compressed multipage TIFFs are read page by page. Compressed layouts that
cannot be handled this way fail before conversion. Dask conversion and reads
use a single-threaded scheduler to bound concurrent buffers. Existing OME-Zarr
chunks over 256 MiB are rejected with a rechunking message. Preview arrays are
limited by the requested budget and a maximum axis length of 512; if necessary,
a strided view is computed from the coarsest available level.

Imports are staged in hidden `.NAME.importing-UUID` directories and renamed on
success. Staged directories are rejected by the viewer. Cooperative cancellation
is checked between Dask tasks; failed/cancelled imports remove their staging
output. An abrupt process termination can leave a hidden staging directory for
manual removal. Existing destinations are never intentionally replaced.

The Open RPC starts an asyncio task and returns immediately so the connection
can process Cancel. Reading/conversion runs via `asyncio.to_thread`; VTK changes
stay on the server loop. Progress callbacks are throttled. Test cancellation
through a real browser connection, since an awaited long-running RPC prevents
that same connection from delivering Cancel promptly.

To exercise import/reopen in the browser check, add `--volume /path/to/test.tif
--import-output /path/to/new-visible-name.ome.zarr`. That optional fixture check
uses an TIFF without pixel-size metadata with explicitly entered 10 µm test spacing and tests
positions beyond the seed's ±1600 µm range. Use `--dataset IMAGE.ome.zarr` to
check reopening an existing dataset. The default dependency trial still uses
the generated specimen and needs no external dataset.

The verified full-TIFF benchmark processed 5,942,796,678 bytes in about
74 seconds with a sampled peak process RSS of 165 MiB, including an 11 MiB
preview and independent TIFF/Zarr value checks. This was a conversion-only process, not the VTK server. Test-only
pixel size and converted output were discarded afterward. Performance depends
on data, chunk layout, codecs, filesystem and graphics environment.

## Numeric controls and axis labels

Put X, Y and Z inside their numeric fields as prefixes. Use a shared descriptive
label, such as Beam position or Pixel size, with units in that label or as field
suffixes. Apply this convention to import dialogs, sample settings and viewing
controls. User-entered pixel sizes are described as pixel sizes. Preserve XYZ
ratio scales the current components proportionally, including anisotropic data.
Sample pixel-size edits are validated and saved when Sample settings closes;
invalid values keep the dialog open with an explanation.

## SAXS plot updates

The Python Plotly figures and layouts are created once. Subsequent poses replace
the trace arrays in the existing figures. Keep q, phi, I(q) and the log cake as
NumPy arrays: Plotly serializes these as typed, base64-encoded buffers with shape
metadata, which the bundled Plotly.js decodes. Converting these arrays to nested
Python lists reintroduces expensive per-element validation, copying and JSON
processing. Regression checks decode the transmitted buffers and compare their
values and shapes with the scattering output.

## Measured SAXS adapter and selection

`scattering_data.py` reads integrated ForMAX HDF5 files and accompanying motor
metadata with h5py, always read-only. `MeasurementIndex` keeps per-frame recorded
X/Y/angle arrays separately from nominal title-derived X/rotation axes. The
initial adapter accepts `mesh swaxs_x … tomo_ry …`, validates frame and axis
shapes, and uses X-fastest ordering. It supports any number of matching scans;
there is no three-scan or fixed-Y-count assumption. Y is read per measurement
when present, otherwise from the explicitly labelled start-position snapshot.
Navigation currently selects among X/rotation meshes and their scan Y levels.

`IntegratedScan.read()` retrieves one curve and cake together. It masks bins
whose respective normalization array is nonpositive, preserves stored intensity
values and q units, and lazily caches normalization. It retains at most 18 MiB
of frame arrays (or one frame when larger), plus q/phi and normalization arrays.
The workflow clears inactive scan caches. HDF5 storage chunks may cover more
than the requested frame. Errors and uncertainty in units/placement must remain
visible. The stored I(q) is not a simple cake mean.

`saxs_workflow.py` owns source attachment, sample lifecycle, persisted selection,
parameterized CT registration and a single latest-pending background reader. Blocking
h5py work runs through `asyncio.to_thread`. Generation and sample-context tokens
discard obsolete results. CT-driven reads do not snap the continuous CT pose.
Sources and plots change together; a failed source attachment preserves the
previous source. `saxs_ui.py` defines the detachable `nim_saxs` panel.
`assets/saxs.js` keeps drafts and incomplete numeric edits local and submits full
selection requests through the existing interaction queue. Server revisions must
not replace a newer pending selection or a number being typed.

The client-only `saxs_lock_x` toggle keeps a full-precision X target while
rotation selects its nearest acquired X at each angle. Explicit X edits reset
the target; do not accumulate drift by targeting each rounded nearest value.
Display coordinates with at most four decimal places and accept the displayed
rounded value without changing the source coordinates.

The per-sample `datasets.scattering` record uses `kind: "formax-integrated"`,
`scans: [{path, metadata}]`, `selection: {scan, row, column}`, `placement` (X/Y
motor origins, CT offsets and signs, plus angle offset) and `link_ct`.
The obsolete `restrict_y` flag is ignored when reading existing records.
Paths inside a project are relative; external paths remain absolute.
This stage references HDF5 sources directly. The future multimodal OME-Zarr
representation is described in the internal storage notes, not implemented by
this adapter. Registration and physical averaging rules require beamline input.

Focused checks: `test_scattering_data.py` covers paired frame identity, masks,
nominal/recorded coordinates, persistence, sample switching, visible read errors
and superseded reads. `saxs.cjs` covers browser draft preservation and selection.
Real-data browser checks used Bamboo scans 135–137, including a flagged angle
readback, rapid selection, linked CT positioning and detached-panel return.

## Icon sources

The current icon inventory is in `src/tomoswaxs/assets/icons/README.md`.
Local SVGs use `currentColor` and are embedded by `ApplicationUI.svg_icon()`;
CSS supplies the theme accent. The SVG files contain the colours they use, with
no runtime colour replacement. Play, Pause and view help currently use Quasar’s
Material Icons names through `QIcon` in `ui.py`.

## UI and dock workspace structure

`app.py` coordinates scientific state, VTK rendering and plot data. `ui.py` builds
application controls and dialogs. `workspace.py` owns the three named Trame
panel templates and the Dockview widget. Build these named templates outside the
main layout context so Dockview can host them without duplicate root content.

`assets/workspace.js` manages docking, panel recovery and default arrangements
through the wrapper’s public component methods. The **Tabs** menu toggles open and closed
panels and resets the arrangement. `preferences.js` saves complete Dockview JSON
only when Remember panel layout is enabled. Old splitter percentages are used
as initial proportions. The workspace and preferences scripts signal readiness
explicitly because Trame may load them in either order. Layout remains local to
the browser, separate from project and sample state.

The default renderer keeps hidden tabs mounted. Dockview observes panel sizes;
VTK and Plotly observe their own containers. The installed wrapper supports
Shift-drag floating groups within the page. A `nim_tab` template supplies the
per-panel pop-out/return and close buttons. Dockview passes its native panel and
container APIs through Vue `$attrs.params`, so the custom tab can call
`addPopoutGroup(panel)` without patching the Trame wrapper. Use the panel object,
not its group, to detach only the requested tab. To return a panel, create a
main-grid group with `containerApi.addGroup()` and pass it explicitly to
`panelApi.moveTo({group, position:'center'})`. A position-only call to the panel
API targets its own group; the group API has different defaults. Panel API
facades share one underlying workspace, so bind lifecycle events only once.

`assets/popout.html` is the same-origin host page; the live Vue components and
Trame connection remain owned by the main window. `workspace.js` manages child
window lifecycle, theme/text-size propagation, tab state and resize notifications.
`beam.js` exposes document attachment with cleanup so Alt+Shift beam gestures
share the existing update queue in either window. Window listeners and API
subscriptions are disposed on close/unmount.

`mainWindowLayout()` removes pop-out window records from persisted layouts and
places detached panels back in the main grid. Restoration cannot replay saved
window URLs or create popups. Existing docking and floating positions are kept.
`tests/popouts.cjs` exercises lifecycle and failure handling; `browser_check.py`
includes real child-window rendering, updates, beam gestures and return checks.

## Saved pose and camera views

`saved_views.py` manages named per-sample bookmarks. Each optional `saved_views`
entry in a project sample has a stable ID, a unique name and a `view` containing
`beam_x`, `beam_y`, `angle` and the existing camera representation. Validation
reuses the camera/view checks in `projects.py`. Existing version-1 manifests
without this optional field remain valid. Standalone bookmarks are held in
memory by source path and carried into projects when the sample is added.

The Saved views menu pauses playback. Capture accepts the latest client pose so
an in-flight pose update does not save an older angle. Recall applies pose and
camera under `_applying_pose`, changes the sample-context token to invalidate
queued input, and renders once. Existing opacity, contrast and radii remain in
effect. Project settings applies name edits on dismissal and before opening the
relink chooser; it preserves the selected sample-to-locate.

## Volume crop and resolution

`volume_viewing.py` owns control state, crop-box interaction and a single
background rendering-load worker. `VolumeSource` in `volumes.py` plans crops
at each stored level before computing any array. Crop bounds are XYZ integer
cell indices at full resolution, with exclusive ends. Physical level transforms
(including translated downsampling centres) map these bounds to ZYX chunk reads.
The VTK image receives the selected level’s spacing and the cropped origin.
Cropping planes enforce the exact physical region at coarse levels.

Explicit levels are loaded without additional subsampling and must fit the
voxel-array size limit. Auto chooses the finest fitting level, falling back to
power-of-two stride sampling of the coarsest level when necessary. Array size,
not a hidden axis-length cap, controls this selection. The limit excludes total
process and GPU allocation overhead.

`workspace.py` defines named `nim_crop` and `nim_resolution` panel templates.
`crop.js` keeps numeric/range drafts local and submits complete requests through
the existing bounded queue. Server acknowledgements leave newer drafts intact;
reload and sample changes restore drafts from canonical bounds. The rendering
worker coalesces requests, cancels old chunk reads and checks generation/source/
sample context before installing an array. Crop handles use the same controller
on release; intermediate handle movement clips the loaded volume. Rendering
resolution changes preserve the camera. Crop changes move its orbit centre to
the visible crop. Both preserve sample pose, colour mapping and measured scattering.

Projects save `view.volume = {crop: [[x0,x1],[y0,y1],[z0,z1]], level: "auto" | int}`.
Standalone viewing remains read-only. Layout snapshots carry `nimControlsVersion`
so old three-panel arrangements gain the new controls once, while controls
closed afterwards remain closed. Test coverage is in `test_volume_viewing.py`,
`crop.cjs`, `workspace.cjs` and the installed-browser smoke check.

## Source map and naming

The Python distribution, command and import package are `tomoswaxs`; the displayed
application name is TomoSWAXS. `project_info.py` holds the About identity and
copyright attribution. The root `LICENSE` is included in built packages.

Within `src/tomoswaxs/`, `app.py` coordinates state and rendering, `ui.py` builds
controls and dialogs, and `workspace.py` defines dock panels. `projects.py`
validates and saves project manifests; `project_workflow.py` manages sample and
project operations. `saved_views.py` manages pose/camera bookmarks. `volumes.py`
reads OME-Zarr and imports TIFF; `volume_viewing.py` manages crop and resolution
loads. `orientation.py` defines coordinate transforms and `synthetic_demo.py`
generates the illustrative CT specimen. Browser scripts, styles,
icons and logos are in `assets/`.

Python integration tests and JavaScript checks are in `tests/`.
`tools/browser_check.py` exercises the installed GUI;
`tools/try_dependency_updates.py` tests dependency updates and packaging.
Root `app.py` is a launch wrapper; `preview_demo.py` creates a static preview.

The saved-project format remains `nim-ct-saxs-project` for compatibility with
existing files. Internal `nim` browser keys, asset routes and RPC names also
remain stable; these are implementation identifiers, not the application name.

## Synthetic fixtures and static preview

The app generates its small 160³ uint16 specimen in memory at startup. NumPy
NPZ fixtures and a static preview can also be generated in the sibling `../data/`
directory, outside Git:

```bash
uv run --active python -m tomoswaxs.synthetic_demo --output ../data
uv run --active --group preview python preview_demo.py
```

The static preview additionally needs Matplotlib. It writes `../data/preview.png`.
`specimen.npz` contains Z,Y,X voxels, scalar spacing and XYZ origin.

## HDF5 CT import

`Hdf5Blocks` reads requested hyperslabs through short-lived read-only h5py handles,
permuting the selected stored axis order into ZYX. The GUI lists numeric 3D datasets;
multiple candidates require a choice. A scalar `/metadata/pixel_size_cm` supplies
an isotropic initial spacing, subject to user confirmation. The known ForMAX
Z/X/Y dimension-label metadata initializes ZXY; other inputs default to ZYX.
`import_hdf5` and TIFF import share the atomic, cancellable OME-Zarr pyramid writer.
Provenance includes source format, dataset path and axis order. No full Bamboo
conversion is part of the automated checks; small fixtures cover conversion,
axis permutation, source preservation and cancellation. A bounded block of the
actual Bamboo reconstruction was read separately.

## Coordinate registration model

`registration.py` holds pure coordinate calculations. `initial_placement` can read
the scan bundle’s Metadata_CT/Radiographs.h5 start-position snapshot. The known
Bamboo reference values identify Mira’s camera shift estimate (506.35, 133.9) µm
and image-Z slice-stack rotation-axis hint. These are documented initial
assumptions, not a validated stage calibration. All six motor contributions have
editable X/Y factors; tomo_zf defaults to zero. The model uses fixed transverse
vectors and cannot yet represent angle-dependent stage kinematics.

`placement.model` is `motors` or `manual`. Motor registration stores `motors`
(name, reference in mm, x/y factors), camera_x/y in µm, reference_source, CT offsets
and angle offset. Existing origin/sign fields preserve the manual model. Source
coordinates stay unchanged. Viewer axes, labels, Y coverage and nearest-frame
selection use the same mapping. Rotation differences are circular; plot selection
does not snap a newer continuous pose. Beam-position limits include registered
scan extents, including measured paths outside the CT volume.

SAXS controls always drive pose; the former opt-in linkage checkbox is removed.
Old autogenerated centred mappings migrate to the bundle estimate, while custom
manual mappings survive. Existing modern parameters remain stable when scans are
replaced; saved references do not require reopening the CT metadata file. A
Bamboo image-Z axis hint is applied only on first initialization/migration, not
over an established configuration. Actual registration remains per-sample.

The fake SAXS generator and fallback have been removed. Empty samples clear both
figures and display “No SAXS data loaded”; legacy synthetic scattering records
are treated as unloaded. `synthetic_demo.py` now generates only a CT fixture.

## Compact SAXS navigation and physical crop units

The default right column contains Crop, Resolution and SAXS measurements in that
order. `nimControlsVersion: 2` migrates SAXS below Resolution in older saved
layouts once; later user arrangements are retained. SAXS controls contain no
loading action or coverage grid. The text inputs have spinbutton roles with
explicit keyboard stepping over acquired values; commits reject off-grid values.
Motor readbacks are structured fields in Measurement details.

Crop keeps integer full-resolution XYZ bounds as its canonical representation.
Client-local `crop_units` changes only numeric presentation. `crop_origin_um`
locates the cell edge half a voxel before source.origin (the first voxel centre);
physical fields use edge + index × spacing and commit to the nearest boundary.
The range sliders and copy-as-Python-slice operation retain voxel indices. The
physical coordinate system is the image frame before sample orientation.

Validation note, 2026-11-19: the real-Bamboo project-copy browser check passed
right-column ordering, compact/list-valued SAXS controls, rejection of off-grid
values, and crop µm/voxel edits. The broader browser check passed rendering,
coordinate/playback controls, beam interaction, crop/level changes and layout
reload (comparing proportions when container height changes). It still fails
when closing a popped-out cake window: five main-window tabs remain rather
than six, with repeated ResizeObserver notifications. This failure is retained
in the browser check, not filtered out. Explicit pop-out return worked in the
focused prior checks. Further pop-out lifecycle investigation is outstanding.


Crop and Resolution now share the `nim_crop` panel, titled Crop and resolution.
Dock layout migration version 3 removes the legacy resolution panel, transferring
its space to Crop when adjacent and recovering it as Crop when Crop was closed.
Browser preferences persist `plotScale` (50–200%, default 100) relative to the
14 px interface base and text scale. `ui_plot_scale` is browser-local; plot layout,
axis ticks/titles, legend and colourbar fonts use the resulting size. Text size
and plot font size update immediately and survive reload.

The Plotly presentation adapter in `assets/preferences.js` reshapes binary 2D
heatmap customdata into ordinary browser-side rows, as required by the bundled
Plotly hover code. Binary NumPy transport and figure reuse remain intact. A
WeakMap caches decoded rows, invalidating them when the encoded frame changes.
Do not replace dense scientific arrays with nested Python lists to fix hover text.

## Graphics device selection

`rendering.py` benchmarks the native window and Linux EGL devices in isolated
subprocesses before creating the application window. The probe includes GPU volume
ray casting, shading and volume-aware depth peeling with a translucent beam.
Errors, crashes and timeouts reject a candidate. The fastest working hardware
renderer wins, with a 10% tolerance favouring the earlier/system candidate.
The small benchmark is a heuristic rather than a guarantee for every workload.

Selection is cached outside the checkout in the user's XDG cache. Its fingerprint
includes the boot ID, VTK version and available DRM devices; startup verifies the
cached renderer and OpenGL version. Explicit graphics environment settings and
GPU allocation variables suppress automatic probing. `--render-device system`
and `--render-device egl:N` provide application-level overrides.

Most application tests and `tools/brick_rendering.py` explicitly use `system`:
this avoids benchmark overhead and preserves deliberate per-process GPU choices
when comparing renderers. `tests/test_rendering.py` exercises ranking, cache
invalidation, environment precedence and probe failures with mocked devices.

## Early-development dependency updates

Accept newer stable dependencies when the available checks show that they work.
The lockfile records the current working environment; it is not a reason to
retain old versions indefinitely. Widen dependency bounds as needed for tested
updates. Keep Python compatibility broad unless a specific incompatibility is
found. Verification should be proportionate to early research development.

For the shared local `nim` environment, Carl installs or updates dependencies.
Do not create isolated test environments or download replacement tools without
explicit authorization. The dependency-trial tool described above creates
isolated environments and therefore requires that authorization before use.

Validation, 2026-11-24: Python 3.13.15 with the updated locked dependencies
passed all 122 Python tests, all JavaScript checks and `uv pip check`. Hatchling
built both the wheel and source archive. The browser check passed volume/plot
rendering, camera controls/playback, beam dragging, crop/level changes, reload,
and explicit pop-out return. Closing a popped-out cake window still leaves
four main-window tabs instead of five, reproducing the previously documented
pop-out lifecycle issue with the current combined Crop and resolution panel.
The assertion remains in place. Other browser steps after that assertion were
not reached. The test runner now launches Python tests from the source directory
so tests can import repository tools; its detached-panel count is corrected to
four main-window tabs while one of five panels is in a separate window.
