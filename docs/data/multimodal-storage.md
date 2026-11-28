# CT and scattering: coordinates, storage and rebinning

Internal design notes, 2026-11-18. This is a proposal for discussion, not a
conversion specification. The current viewer has a parameterized transverse
registration estimate; see the user guide and development notes. The factual basis is the
[Bamboo/ABS inspection](bamboo-abs.md). Registration and scientific reduction
choices require beamline input. The beamline scientists own reconstruction,
scientific reduction and simulation methods, using their existing scripts.
TomoSWAXS focuses on loading their outputs and metadata, coordinating views,
and applying explicitly agreed display/selection operations.

## Keep the measurement spaces explicit

The CT reconstruction is indexed by three image coordinates. After its axis
assignment, pixel size and origin are established, each voxel has a location in
a sample coordinate system. The specimen's pose then maps sample coordinates
to laboratory coordinates.

A supplied scattering frame is indexed by measurement number, q, and detector
azimuth. Measurement number joins it to the scan's motor positions and rotation.
There are two different angles: **sample rotation** `theta` (`tomo_ry`) and
**scattering azimuth** `phi` (`azi`). One changes the specimen's pose; the other
locates intensity around the detector. Preserve their names, units and frames.

The working relationship is:

```text
CT voxel indices -> CT physical coordinates -> sample coordinates -> laboratory
scattering measurement n -> motors + sample rotation -> laboratory beam path
scattering bins (q, phi) -> intensity and uncertainty for measurement n
```

We have CT pixel size and acquisition coordinates. We do not yet have the
complete transformations joining those chains: stage geometry, rotation-zero
conventions, reconstruction origin and axis directions are still missing.
Store those relationships as unresolved, with provenance, until established.

A measured pattern is associated with a beam path and sample pose. The viewer
can show that path in the CT and retrieve the corresponding supplied pattern.
Any reconstructed local-scattering products or simulated patterns should come
from the scientists' methods, with the metadata needed to display them.

## What rebinning could mean here

The leading working interpretation from Carl is **display-dependent aggregation
of nearby parallel beam paths**. When zoomed out, a selected screen region may
span several acquired beam positions. The displayed pattern could aggregate
those measurements at the selected sample angle. This is a hypothesis about the
intended feature, to confirm with the scientists, rather than an established
meaning of their term “rebinning”.

The finite physical beam already overlaps adjacent paths. A display footprint
and the physical beam profile are separate inputs to a selection/averaging rule;
the width of one cannot simply be substituted for the other. The scientists
need to specify the weights and what displayed intensity should mean.

A simulated-scattering display under a single-scattering assumption has also
been discussed. We should obtain the simulation/combination rule and its inputs
from the scientists. Keep that product identifiable alongside measured patterns.
Averaging several paths may be appropriate for that display, under their rule.

Other uses of the same term are worth distinguishing when asking what is intended:

| Operation | Concrete example | Consequence |
| --- | --- | --- |
| Detector integration | Map detector pixels into q/phi bins | Produces cakes and 1D curves; already performed for the supplied integrated files |
| q rebinning | Combine neighbouring q bins, e.g. 2000 into 1000 bins | Coarser q sampling; requires appropriate weighting and uncertainty propagation |
| Azimuth rebinning/integration | Combine 2° azimuth bins into 10° bins, or integrate selected sectors | Changes angular resolution or extracts directional features |
| Scan-coordinate gridding | Group/interpolate irregular motor positions onto a chosen position/rotation grid | Creates a derived sampling grid and a coverage map |
| CT downsampling | Combine neighbouring voxels to make a coarser level | Reduces spatial resolution and rendering/storage cost; this is the familiar multiscale pyramid operation |

These operations affect different coordinates and can be useful independently.
There is no requirement to give the CT voxel grid and SAXS measurement grid the
same spacing merely to display them together.

For these files, a nominal SAXS X step is 5 µm while the CT declares 0.65 µm
pixels. Combining CT voxels into roughly 5 µm regions would reduce CT detail;
interpolating SAXS onto every 0.65 µm CT pixel would add samples to the display
without creating measured SAXS resolution. The beam footprint and acquisition
coverage also matter. A specimen rotation changes which path traverses the CT.

## SAXS coverage in Y

Carl confirms that the sampled Y locations are relevant to navigation, and that
future data may cover a fuller set of Y values. Represent coverage from coordinate
arrays and scan metadata, rather than fixing the format to three Y planes or
assuming that each file must correspond to one Y value.

For the current files, the sorted `swaxs_y` snapshots are −2.19220 (137),
−2.12355 (135), and −2.04650 (136). The extent is 0.14570 raw motor units,
provisionally 145.70 µm if those units are mm. These still need the confirmed
mapping into the viewer's physical Y coordinate.

The current SAXS measurements panel selects an acquired Scan / Y, X position and
rotation, and drives the beam and sample pose. The former proposal for a
Restrict Y to SAXS range checkbox is superseded by navigation among acquired
measurements. Marks in the CT view remain a possible coverage display. The beam
footprint may determine how much neighbourhood around each level has useful
support; the scientists should define that interpretation.

Retain a source indication for each coordinate: these three Y values are
start-position snapshots, whereas future files may contain per-measurement Y
readbacks. Use the same coverage model for sparse and dense acquisitions.
Coverage and display aggregation should be queryable from metadata without
reading every cake. Scan selection and source indications are implemented in
the HDF5 viewer; the common NGFF coverage representation and display aggregation
remain proposed work.

### Weights, masks and uncertainties

The ABS files already demonstrate why the reduction rule matters: a plain mean
of the stored cake does not equal the supplied I(q). The normalization arrays
have a large scale difference, and many cake cells have zero normalization.
The empirical relation and sampled checks are recorded in the inspection notes.
Use the supplied I(q) as a separately provided result while its exact processing
is clarified.

Before defining a rebinning operation, establish whether stored values represent
counts, averages, densities, or corrected intensities; what normalization has
already been applied; and how fractional overlap with new bin edges is handled.
Preserve support/coverage separately from intensity. Zero support and measured
zero intensity have different meanings.

For independent input estimates combined as a weighted mean, the familiar
variance formula is `sum(w_i**2 * variance_i) / sum(w_i)**2`. Applying that formula
requires knowing the uncertainty definition and whether inputs are independent.
The supplied error arrays do not exactly match simple cake-to-I quadrature;
the scientists should supply the applicable uncertainty treatment for any aggregation.

## Proposed storage organization

Keep acquisition coordinates and supplied data intact in an authoritative
layer. Store registration estimates and rebinned/reconstructed products as
derived objects with their source references and processing provenance. Scientific
products remain outputs of the beamline's processing methods.

OME-Zarr is a good fit for CT image pyramids and physical pixel coordinates.
Our current CT writer uses NGFF 0.5, whose image metadata describe axes and
per-level scale/translation. The [0.5 specification](https://ngff.openmicroscopy.org/0.5/)
is the baseline for that existing representation.

The [NGFF 0.6 documentation](https://ngff.openmicroscopy.org/specifications/0.6/)
adds named coordinate systems and richer transforms, including affine maps.
That is relevant to CT-index/sample/laboratory relationships. The
[NGFF 0.6 investigation](ngff-0.6.md) records the specification findings, installed
library support and a small round-trip probe; library support is ahead of our
current application geometry handling.

The complete multimodal bundle also needs explicit acquisition/scattering
semantics. A Zarr group containing a cake array is not automatically a standard
OME-Zarr description of scattering. We should distinguish NGFF image metadata
from a versioned TomoSWAXS extension, and check existing scattering conventions
before defining that extension. [NXcanSAS](https://manual.nexusformat.org/classes/applications/NXcanSAS.html)
provides relevant conventions for Q/I coordinates, units, axes and uncertainty
references; the supplied HDF5 hierarchy is not claimed to conform to NXcanSAS.

One possible logical organization, retaining the existing project's stable
sample ID, is:

```text
sample/
  ct.ome.zarr/                 # NGFF image, multiscales and physical metadata
  scattering.zarr/            # proposed acquisition schema, when conversion is useful
    scans/0135/
      I                       # [measurement, q]
      I_errors
      cake                    # [measurement, phi, q]
      cake_errors
      q                       # exact original coordinates + units
      phi
      norm1d
      norm2d
      measurement/
        index                 # original frame index
        swaxs_x
        y                     # from snapshot now, per-measurement if provided later
        tomo_ry
        pcap_fast_axis
        pcap_ts_trig
        albaem-e01_ch1
        albaem-e01_ch3
        albaem-e01_ti
      ...metadata for snapshots, geometry, processing, source paths and flags...
    scans/0136/
    scans/0137/
  registration/               # versioned coordinate mappings and their provenance
  derived/                    # explicitly specified rebinning/reconstruction products
```

The first acquisition layer could reference the existing HDF5 datasets and
carry the same metadata model. A later Zarr conversion should
retain original values, errors, masks/normalization and coordinates, with chunks
chosen for the viewer's per-measurement reads. Compression and numerical
precision changes are separate decisions from rebinning.

For each scan retain the original scan number, file/dataset references,
acquisition timestamps, original units, integration version and parameters,
embedded PONI text, mask reference, full start-position snapshots and framewise
coordinates. Store nominal grid coordinates separately from measured readbacks.
The three questionable angle samples need quality flags and original values.

For registration retain the input/output coordinate systems, axis meanings,
units, rotation pivot, transformation order, origin/crop offsets, beam direction
and footprint, source evidence, and confidence/status. A set of motor snapshots
alone is insufficient to infer a signed transform by adding all motor deltas.

For derived products retain source scan/frame identities, coordinate transforms,
bin edges, weighting/coverage rules, uncertainty treatment, and software/version
information. This allows reduction choices to change while the acquired data
remain traceable.

## Next decisions to resolve with the scientists

Establish the coordinate chain and the supplied product definitions. Confirm
whether rebinning means aggregation over paths represented by a display region,
and how beam overlap, weights and uncertainty should be handled. Obtain the
scientists' interface for any single-scattering simulation or precomputed
simulation products intended for display.

With that information, define measured/simulated display selection and the Y
coverage controls. NGFF 0.6 is a promising basis for image-coordinate relations;
retain the full acquisition coordinates and provenance alongside those images.
