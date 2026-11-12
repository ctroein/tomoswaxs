# Development

Run commands from the repository directory. `uv sync --active --locked` installs into the active
project environment. Our local setup uses the shared pyenv `nim` environment. Application code and browser assets live under
`src/nim_ct_saxs/`; `pyproject.toml` declares the installed `nim-ct-saxs` command.
Python 3.12 is the initial tested and supported series.

## Running and testing

Use a second port when testing edits so an existing demo session remains
available:

```bash
uv run --active --locked nim-ct-saxs --server --port 8081 --timeout 0
uv run --active --locked python -m unittest discover -s tests
```

The server does not reload source edits automatically. Restart it explicitly to
load changes. Announce restarts of a running demo; browser tabs must reconnect
or reload afterward. `--timeout 0` disables Trame's idle shutdown, but does not
make the process survive termination of its shell or execution session.

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
scientific assumptions explicit: the default specimen and all scattering are
fabricated; loaded TIFF scales are supplied by the user. Internal spatial
coordinates are mm, the controls display µm, and the 1D signal
is the cake's full-azimuth mean. Beam radii affect only the visual geometry.

OME-Zarr input and TIFF import preserve source scalars and physical metadata.
Motor-coordinate registration, measured scattering processing,
rebinning, and remote multi-user deployment have not been implemented. Do not
present these as supported features.

## Project persistence and sample lifecycle

`projects.py` owns the version-1 `nim-ct-saxs-project` manifest, stable sample IDs,
CT/scattering references, axis settings and viewing state. `project_workflow.py`
connects the model to the global Project menu, separate New/Open/Settings
dialogs, sample selection and background loading. New projects derive their
display name from the chosen directory; existing projects can be renamed in
Project settings. Folder icon buttons beside path fields use Exhale's Tabler SVG
and its accompanying MIT licence from `assets/icons/`.
Existing datasets are referenced; internal paths are relative and external paths
absolute. The project directory contains `project.json` and, as needed,
`data/<sample-id>/`, `results/<sample-id>/`, and `figures/<sample-id>/`.

Valid, settled changes are saved automatically with atomic manifest replacement.
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
register a sample only after successful conversion/preview reading. Add to project
can retain the current standalone sample and view in a new or existing project.
Project-free conversion explicitly writes a new dataset while preserving input.

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

When changing settings, check light/dark/system appearance, text size, browser
zoom, dock layout persistence across reload, reset, and continued local plot styles
after a beam update. Browser storage failure must not stop the app.

## Coordinate interactions

`assets/updates.js` provides the shared bounded RPC queue for pointer gestures
and coordinate controls. It allows one request in flight and one pending update
per source. Pose patches merge the latest X/Y/angle values so simultaneous edits
are committed atomically by `Demo.receive_pose()`. Do not bind high-frequency
sliders directly to server-synchronized state.

`assets/coordinates.js` owns client-only numeric/slider drafts, angle wrapping,
and rotation playback. Server acknowledgements must not overwrite newer local
drafts. Scrubbing defers SAXS until release; play selects poses at 5 Hz. Rotation
uses elapsed time at 30°/s, and pauses when the page becomes hidden. Final updates
must survive coalescing so Pause and pointer release leave a complete pose.

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
separate from source data. VTK uses that preview; fabricated SAXS samples a
short ray from the full-resolution source and normalises only those samples.

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

## Icon sources

The current icon inventory is in `src/nim_ct_saxs/assets/icons/README.md`.
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
through the wrapper’s public component methods. The **View** menu reopens closed
panels and resets the arrangement. `preferences.js` saves complete Dockview JSON
only when Remember panel layout is enabled. Old splitter percentages are used
as initial proportions. The workspace and preferences scripts signal readiness
explicitly because Trame may load them in either order. Layout remains local to
the browser, separate from project and sample state.

The default renderer keeps hidden tabs mounted. Dockview observes panel sizes;
VTK and Plotly observe their own containers. The installed wrapper supports
Shift-drag floating groups within the page. Separate browser-window popouts need
additional integration; there is currently no detach-to-window action.
