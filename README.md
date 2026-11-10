# NIM — µCT and SAXS visualization

NIM is a Python/Trame GUI project for visualizing µCT and scattering data at
a beamline, motivated by discussions with scientists at ForMAX. The current
prototype has a semitransparent volume, movable elliptical beam,
SAXS cake and its full-azimuth mean I(q). All geometry, physical dimensions,
intensities and scattering are fabricated. This is a GUI demonstration, not
measured data or a scattering simulation.

## Setup

Development currently uses Python 3.12. Create or activate a virtualenv, then
install the application dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run

From the repository directory, with the `nim` virtualenv active:

```bash
python app.py
```

The application opens in a browser at http://127.0.0.1:8080. To start without
opening a browser, or use another port:

```bash
python app.py --server --port 8081
```

Stop with Ctrl+C. Required packages are listed in `requirements.txt`;
`python -m pip install -r requirements.txt` installs them in an active virtualenv.
Rendering is performed by VTK on the application host, and images are sent to
the browser. No ParaView installation is needed. This initial demo has one shared
application state and is intended for a single user. Remote facility deployment,
authentication and per-user sessions remain future work.

## Controls

Beam X/Y position and horizontal/vertical ellipse radii are displayed in µm
(initially 250, 0, 60 and 40). Internal geometry remains in invented mm.
The beam travels along laboratory +Z; sample angle rotates the object around
laboratory Y. Changing the sample angle is separate from orbiting the camera.

Drag in the volume to orbit, right-drag to zoom or middle-drag to pan; scroll
zooms. Reset camera restores the initial viewpoint. Beam view looks along Z.
Enable **Move beam** to click or drag the beam in the Z=0 plane. Pointer input
keeps only the latest pending position, allows one request in flight, and limits
intermediate updates to at most 10 per second. Releasing the pointer preserves
the final position and refreshes the SAXS panels; SAXS is held while dragging. This mode
intercepts camera gestures; disable it to orbit again. Beam view is particularly
useful for positioning, since a camera looking along the XY plane cannot provide
a well-conditioned intersection with that plane.

The beam is drawn as a translucent overlay so its path remains visible through
the volume; light cyan marks the portion nearer the camera and dark blue marks
the farther portion. Colours follow camera changes. This is an illustration,
not an occlusion or attenuation model.
Opacity adjusts the volume independently of the data. Beam radii change the
geometry only. X/Y and sample angle change the illustrative scattering pattern.
The 1D curve is the arithmetic mean over all equal-width azimuth bins of the
cake, before its logarithmic colour display. Log I toggles the curve's vertical
axis. Plotly provides plot zoom, pan, reset and image export controls.

Drag the horizontal QSplitter divider between the volume and plots to change
heights; drag the vertical divider between the SAXS panels to change widths.
The grip at the centre of each divider indicates the draggable area. The volume
is limited to 35–78% of the available height and the left plot to 25–75% of width.
Plot zoom is retained when beam parameters change; double-click
a plot to restore its axis ranges. Cake colours use a fixed log scale.

## Synthetic fixtures and static preview

The app generates its small 160³ uint16 specimen in memory at startup. NumPy
NPZ fixtures and a static preview can also be generated in the sibling `../data/`
directory, outside Git:

```bash
python synthetic_demo.py
python preview_demo.py
```

The static preview additionally needs Matplotlib. It writes `../data/preview.png`.
`specimen.npz` contains Z,Y,X voxels, scalar spacing and XYZ origin.
`scattering.npz` contains a 180×256 cake in phi,q order, its axes and mean I(q).
Load with `np.load(path)`; no pickled objects are required. This temporary format
is not OME-NGFF. General file loading, registration, rebinning and export are not
implemented.

`synthetic_demo.scattering()` samples a centre ray through the rotated volume to
control invented peak amplitudes; cosine modulation produces angular variation.
These relationships have no scientific interpretation.

## Verification

```bash
python -m unittest discover -s tests
```

The tests check the displayed rotation/beam geometry against the coordinates
used for synthetic sampling, ray-to-plane positioning and the cake/curve
relationship, deferred SAXS updates during dragging, and camera-relative beam
colours. `tests/beam_input.cjs` can additionally run with Node.js; it checks that
a burst of 1000 pointer moves produces no backlog and retains the final release.
Node.js is not needed to run the application. Browser interaction and rendering should also be checked on the
actual beamline workstation; representative measured data are not supported yet.

## Project files

`app.py` builds the application and its About dialog. `project_info.py` holds
project identity and licence information. `synthetic_demo.py` generates fixtures
and illustrative scattering; `preview_demo.py` renders a static overview.
`assets/` contains styling and beam pointer handling, and `tests/` contains the
coordinate, signal and interaction checks. Generated datasets and screenshots
belong in the sibling `../data/` directory, outside the repository.

See [development notes](docs/development.md) for the development workflow.

## Acknowledgements

A collaboration between InfraVis, MAX IV and NAISS.

NIM uses [Trame](https://kitware.github.io/trame/), [VTK](https://vtk.org/),
[Quasar](https://quasar.dev/), [Plotly](https://plotly.com/python/) and
[NumPy](https://numpy.org/). The optional static preview uses Matplotlib.
Each dependency retains its own licence.

## Licence

NIM is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Carl Troein, Emanuel Larsson, Mira Viljanen, Daniel White, Stuart Ansell.
