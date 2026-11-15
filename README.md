# TomoSWAXS

TomoSWAXS is a Python/Trame GUI project for visualizing µCT and scattering data at
a beamline, motivated by discussions with scientists at ForMAX. The current
prototype has a semitransparent volume, movable elliptical beam,
SAXS cake and its full-azimuth mean I(q). The default specimen and its dimensions are fabricated. An OME-Zarr image
can replace it using `--volume IMAGE.ome.zarr` or **Open volume**. TIFF input is
converted once into a reusable multiscale OME-Zarr image.
The SAXS data remain fabricated. This is a GUI demonstration.

## Project abstract

The NIM pilot project is a collaboration between three nationally funded research infrastructures: NAISS, Infravis, and MAX IV. MAX IV currently generates 3+ PB of experimental data annually, and transforming this data into clear, interpretable results presents a challenge. The collaboration between these infrastructures aims to create cohesive workflows that link experiments, computations, analysis, and visualization. The pilot project’s objective is to demonstrate that the computational infrastructures at MAX IV and NAISS can be integrated in a manner that is technically seamless and completely transparent to the users of MAX IV’s experimental stations.

## Setup and run

The current supported Python series is 3.12. Activate your project virtualenv,
then run from the checkout with uv installed:

```bash
uv sync --active --locked
uv run --active --locked tomoswaxs --server --port 8080 --timeout 0
```

Open http://127.0.0.1:8080/ in a browser. Stop the server with Ctrl+C.
Omit `--server` to open the browser automatically. Development checks use port
8081. VTK renders on the application host and sends images to the browser.
The demo has one shared application state and is intended for a single user.

See [the user guide](docs/user-guide.md#open-and-import-ct-volumes) for file selection,
TIFF import, physical pixel size, preview budgets and contrast controls.

## Projects

Use **Project** to create or open a project, then **Add sample** and the sample
selector to work with its volumes. Projects save sample settings and viewing
state in `project.json`. Existing datasets are referenced; TIFF conversions can
be stored inside the project. Open a project directly with
`tomoswaxs --project /path/to/project.json --server --port 8080 --timeout 0`.

Opening a volume without a project is read-only inspection. **Add to project**
retains the current sample and view. TIFF import offers project creation or an
external conversion destination. Import-supplied voxel spacing can be revised
explicitly in Sample settings, which updates the imported dataset.
See the [project workflow](docs/user-guide.md#projects-and-samples).

## Building and installing

```bash
uv build
uv tool install dist/tomoswaxs-0.1.0.dev0-py3-none-any.whl
tomoswaxs --server --port 8080 --timeout 0
```

The wheel includes browser assets, logos and the MIT licence. Its dependency
ranges admit patch releases in the supported minor series. The checkout's
`uv.lock` records the exact tested environment; `uv sync --active --locked` installs it.
For a release-specific requirements export:

```bash
uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file requirements-locked.txt
```

Install that export and the matching wheel into the same virtualenv to reproduce
the runtime dependencies. Development and dependency-update instructions are in
[docs/development.md](docs/development.md).

## Controls

Beam X/Y position and horizontal/vertical ellipse radii are displayed in µm
(initially 250, 0, 60 and 40). Internal geometry remains in invented mm.
Each coordinate has a numeric field and a slider. Angle stepping wraps at
±180°. Play rotates at 30°/s; Pause holds the current angle. Playback uses elapsed
time, with adjustable update frequency and angular step. Beam X/Y and angle are applied
together, with only the latest pending control values retained while rendering.
During slider scrubbing, the volume follows the slider and SAXS refreshes on
release. During playback, SAXS follows the selected poses.

Beam radii are available in the folded **Beam size** section.
The beam travels along laboratory +Z; sample angle rotates the object around
laboratory Y. Changing the sample angle is separate from orbiting the camera.

See the [user guide](docs/user-guide.md) for the controls and viewing workflow.
Hold **Alt+Shift** while starting a left-button drag in the volume to position
the beam in the XY plane. Beam view provides a view along the beam for positioning.

The beam is drawn translucently with volume-aware depth ordering. Light cyan
marks the beam origin at −Z, fading to dark blue downstream toward +Z. Colours
remain fixed when the camera moves. Its visibility follows the volume opacity;
its colour gradient is illustrative.
Opacity adjusts the volume independently of the data. Beam radii change the
geometry only. X/Y and sample angle change the illustrative scattering pattern.
The 1D curve is the arithmetic mean over all equal-width azimuth bins of the
cake, before its logarithmic colour display. Log I toggles the curve's vertical
axis. Plotly provides plot zoom, pan, reset and image export controls.

Drag panel tabs onto an edge to create a new split, or onto another tab strip to
group panels as tabs. Drag dividers to resize. Shift-drag a tab to float its panel
inside the workspace. **View** reopens closed panels and restores the default
arrangement. **Remember panel layout** saves the dock arrangement in this browser.
Plot zoom is retained when beam parameters change; double-click
a plot to restore its axis ranges. Cake colours use a fixed log scale.

## Settings

Settings applies immediately and saves interface preferences in browser-local
storage: System/Light/Dark appearance, text size from 80–160% in 5% steps, and
optional panel layout persistence. Reset preferences restores System, 100%, and
the default panel arrangement. Corrupt or unsupported saved settings fall back to
defaults; unavailable browser storage does not prevent temporary changes.

Theme and text size are applied locally to controls, dialogs and Plotly graphs.
The remotely rendered 3D canvas keeps a neutral dark background in either theme.
Panel positions, tab groups and floating panels are remembered when enabled;
scientific state, camera, beam position and sample angle are not preferences.

Preferences belong to the browser profile and site origin. The test port 8081
has separate storage from the main demo on 8080. They do not follow a user to a
different computer. Appearance and panel layout are not synchronized through
Python; the scientific state and VTK scene remain shared by connected tabs.

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
`scattering.npz` contains a 180×256 cake in phi,q order, its axes and mean I(q).
Load with `np.load(path)`; no pickled objects are required. This temporary format
is not OME-NGFF. OME-Zarr volume opening and TIFF import are available; registration, rebinning
and scientific export remain future work.

`tomoswaxs.synthetic_demo.scattering()` samples a centre ray through the rotated volume to
control invented peak amplitudes; cosine modulation produces angular variation.
These relationships have no scientific interpretation.

## Verification

```bash
uv run --active python -m unittest discover -s tests
```

The tests check the displayed rotation/beam geometry against the coordinates
used for synthetic sampling, ray-to-plane positioning and the cake/curve
relationship, deferred SAXS updates during dragging, and source-relative beam
colours. `tests/beam_input.cjs` can additionally run with Node.js; it checks that
a burst of 1000 pointer moves produces no backlog and retains the final release.
Node.js is not needed to run the application. Browser interaction and rendering should also be checked on the
actual beamline workstation; physical pixel size should be checked against the scan metadata.

## Project files

`src/tomoswaxs/app.py` coordinates the application; `ui.py` builds its controls and About dialog.
`project_info.py` in that package holds project identity and licence information;
`synthetic_demo.py` generates fixtures. Browser assets live in the package's
`assets/` directory, focused checks in `tests/`, and development tools in `tools/`.
Generated datasets and screenshots belong in the sibling `../data/` directory,
outside the repository.

See [development notes](docs/development.md) for the development workflow and source map,
and [GitHub publication](docs/publishing.md) for connecting this checkout to the public repository.

## Acknowledgements

The software is developed within NIM, a collaboration between InfraVis, MAX IV
and NAISS. NIM names the collaboration; TomoSWAXS is the software name.

TomoSWAXS uses [Trame](https://kitware.github.io/trame/), [VTK](https://vtk.org/),
[Quasar](https://quasar.dev/), [Plotly](https://plotly.com/python/) and
[NumPy](https://numpy.org/). The optional static preview uses Matplotlib.
Each dependency retains its own licence.

## Licence

TomoSWAXS is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Carl Troein, Emanuel Larsson, Mira Viljanen, Daniel White, Stuart Ansell.
