# Development

Run commands from the repository directory with the `nim` virtualenv active.
The current layout is deliberately small: application code in `app.py`, project
identity in `project_info.py`, synthetic data in `synthetic_demo.py`, browser
assets in `assets/`, and focused checks in `tests/`.

## Running and testing

Use a second port when testing edits so an existing demo session remains
available:

```bash
python app.py --server --port 8081 --timeout 0
python -m unittest discover -s tests
```

The server does not reload source edits automatically. Restart it explicitly to
load changes. Announce restarts of a running demo; browser tabs must reconnect
or reload afterward. `--timeout 0` disables Trame's idle shutdown, but does not
make the process survive termination of its shell or execution session.

For the dependency-free JavaScript input-queue test, if Node.js is available:

```bash
node tests/beam_input.cjs
```

Check volume rendering, camera navigation, beam dragging and release, numeric
controls, splitter resizing, and the About dialog in a browser after relevant
GUI changes. An application startup check alone does not verify these workflows.
The application currently has one shared state, so browser tabs on the same
server affect each other.

## Data and scope

Generated data and screenshots go in the sibling `../data/` directory. Keep
scientific assumptions explicit: the sample and scattering are fabricated,
internal spatial coordinates are mm, the controls display µm, and the 1D signal
is the cake's full-azimuth mean. Beam radii affect only the visual geometry.

OME-NGFF input, motor-coordinate registration, measured scattering processing,
rebinning, and remote multi-user deployment have not been implemented. Do not
present these as supported features.

## Git and releases

Development is local; no GitHub remote or publishing workflow is required.
Leave changes uncommitted for Carl to review unless a commit is requested.
There is no release version or release process yet; the About dialog identifies
the software as a development prototype.
