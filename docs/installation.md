# Install and run TomoSWAXS

This guide is for installing and hosting the application. For use through an
existing web interface, see the [user guide](user-guide.md).

## Install from source

You need Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
TomoSWAXS requires Python 3.12 or newer. It has been tested on Python 3.12.13
and 3.13.15. The example below selects 3.13; you can use another compatible
installed version. uv can download Python when creating the environment.

```bash
git clone https://github.com/ctroein/tomoswaxs.git
cd tomoswaxs
uv venv --python 3.13
source .venv/bin/activate
uv sync --active --locked
```

If you already have a Python 3.12 or newer virtual environment, activate it and run
`uv sync --active --locked` from the checkout. The lockfile supplies the tested
dependency versions. The application requires graphics support for VTK rendering
on the machine running it; verify rendering on the intended workstation or
compute node.

### Install with pip

With Python 3.12 or newer available, installation from the checkout can also
use pip:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Pip uses the dependency ranges in `pyproject.toml`, not the exact versions in
`uv.lock`. With this environment active, run `tomoswaxs` directly instead of
`uv run --active --locked tomoswaxs`.

## Start locally

From the checkout, with that environment active:

```bash
uv run --active --locked tomoswaxs --server --port 8080 --timeout 0
```

The interface is at <http://127.0.0.1:8080/>. The process stays in the foreground;
Ctrl+C stops it. `--timeout 0` keeps it running when no browser is connected.
Without `--server`, startup also opens a browser.

The application reopens the last project remembered by this browser when available. Add `--project
/path/to/project.json` to reopen a project, or `--volume /path/to/image.ome.zarr`
to open a CT image. `--data-dir /path/to/data` sets the file chooser’s starting
directory. Samples and projects can also be opened through the interface.

## Graphics selection

On Linux, startup compares the system OpenGL renderer with available VTK EGL
devices using a small volume-rendering benchmark. It selects a working accelerated
renderer with the shortest measured frame time, keeping the system renderer when
the difference is within 10%. This tests a representative workload; relative
performance can vary with the dataset and current GPU load.

The result is cached under `$XDG_CACHE_HOME/tomoswaxs/render-device.json`
(normally `~/.cache/tomoswaxs/`). Later starts verify the cached device; a new boot
or detected graphics change triggers fresh selection. Probes run in separate
processes with timeouts. Other operating systems use platform graphics selection.

Use `--render-device system` to retain VTK's default device, or
`--render-device egl:0` to select a particular VTK EGL device index. Existing
graphics environment overrides and GPU allocation variables take precedence
over automatic probing. Startup prints the actual OpenGL renderer and backend.

## Access over SSH

On a remote machine, start the application as above. From your local computer,
forward a local port to it:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@remote-machine
```

Then use <http://127.0.0.1:8080/> locally. Keep the SSH connection and application
process running. File selection uses paths on the remote machine. This example
assumes direct SSH access to the machine running TomoSWAXS; facility-specific
compute allocations and gateway connections need the facility’s access setup.

One running instance has one shared sample, camera and set of scientific controls.
For independent work, run separate instances on different ports and forward the
corresponding ports.

## Updates and distribution

To update a checkout, review and pull the desired Git revision, then run
`uv sync --active --locked`. A running process loads its code at startup.

To build a wheel and source archive, run `uv build` in the checkout. A wheel can
be installed with `uv pip install /path/to/tomoswaxs-VERSION-py3-none-any.whl`
into an active Python 3.12 or newer environment, then started with `tomoswaxs --server
--port 8080 --timeout 0`. Wheel dependencies follow the ranges in the package;
for exact versions, distribute a requirements export alongside the matching wheel:

```bash
uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file requirements-locked.txt
```

Install those requirements and the wheel together to reproduce that dependency
set. See the [development guide](development.md) for checks, dependency updates
and the local login-service setup.
