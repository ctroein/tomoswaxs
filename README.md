# TomoSWAXS

TomoSWAXS is a browser-based application for exploring µCT images alongside SAXS
measurements, developed with scientists at ForMAX. It supports OME-Zarr CT images,
TIFF/HDF5 import and the integrated ForMAX X/rotation mesh scans supplied with the
Bamboo data. Open a sample or project to begin.

## Documentation

[User guide](docs/user-guide.md): working with samples and projects, exploring the
CT image, and selecting scattering measurements through the web interface.

[Installation guide](docs/installation.md): getting the source, installing the
application, starting it locally and connecting over SSH.

[Development guide](docs/development.md): code organization, checks, dependency
updates and the local login-service setup. Internal investigation notes cover
the [Bamboo data](docs/data/bamboo-abs.md) and
[multimodal storage](docs/data/multimodal-storage.md).

## Project abstract

The NIM pilot project is a collaboration between three nationally funded research infrastructures: NAISS, Infravis, and MAX IV. MAX IV currently generates 3+ PB of experimental data annually, and transforming this data into clear, interpretable results presents a challenge. The collaboration between these infrastructures aims to create cohesive workflows that link experiments, computations, analysis, and visualization. The pilot project’s objective is to demonstrate that the computational infrastructures at MAX IV and NAISS can be integrated in a manner that is technically seamless and completely transparent to the users of MAX IV’s experimental stations.

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
