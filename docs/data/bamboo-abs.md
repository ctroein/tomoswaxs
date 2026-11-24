# Bamboo/ABS: file and coordinate investigation

Internal working notes, inspected 2026-11-18. This describes the supplied files,
not a general ForMAX file-format contract. Scan-to-sample association comes from
Mira's message and Carl's identification of this directory. Values marked
**observed** come from the files; interpretations and open questions are explicit.
Reconstruction, scientific reduction and simulation are provided by the beamline
scientists using their scripts. These notes support visualization and questions
about their supplied outputs. The companion [storage and rebinning notes](multimodal-storage.md) describe a
possible data model, not an implemented conversion.

## Files and associations

Paths below are relative to `~/src/nim/data/Bamboo/ABS/`.
`Bamboo` currently links to the external drive. There are ten HDF5 files:

| File | Role | Size |
| --- | --- | --- |
| `recon_0091.h5` | Reconstructed absorption CT for scan 91 | 43,235,542,456 bytes; 40.266 GiB |
| `Metadata_CT/Radiographs.h5` | Scan 91 metadata and recorded projection angles | 58,320 bytes |
| `Metadata_CT/Flats.h5` | Flat-field scan 92 metadata | 40,776 bytes |
| `Metadata_CT/Darks.h5` | Dark-field scan 94 metadata | 40,776 bytes |
| `Scattering data/scan-0135_eiger_integrated.h5` | Integrated scattering, scan 135 | 124,387,060,064 bytes; 115.844 GiB |
| `Scattering data/scan-0136_eiger_integrated.h5` | Integrated scattering, scan 136 | Same size |
| `Scattering data/scan-0137_eiger_integrated.h5` | Integrated scattering, scan 137 | Same size |
| `Scattering data/Metadata/scan-0135.h5` | Scan 135 motor and acquisition metadata | 1,247,786 bytes |
| `Scattering data/Metadata/scan-0136.h5` | Scan 136 motor and acquisition metadata | Same size |
| `Scattering data/Metadata/scan-0137.h5` | Scan 137 motor and acquisition metadata | Same size |

The three scattering files are three acquisitions of the same sample, rather
than three independently identified samples. Match each integrated file to the
metadata file with the same scan number. Their frame counts agree; the
integrated files do not supply the per-frame motor coordinates themselves.
Frame-index correspondence is the working association to confirm with ForMAX.

The metadata files contain external links to original camera files, e.g.
`scan-0135_eiger.h5` and `scan-0091_andor3_zyla.h5`. Those target files are absent
from the supplied directory. The integrated intensities and reconstructed CT
are stored locally in their respective files and can be read independently.

## Mira's supplied information

Mira identifies the relevant motors as `tab_x`, `tab_y`, `swaxs_x`, `swaxs_y`,
`tomo_xf`, and `tomo_zf`. CT rotation is recorded at
`/entry/measurement/pandapcap_tomo_ry`. The camera used for tomography also
measured the beam profiles, with 2560 × 2160 pixels (X × Y) and 0.65 µm/pixel.
The unfocused/full-beam centre is (675, 743); the focused-beam centre at the
sample is (1454, 949). Coordinate indexing, image orientation and precise
definitions of those centres have not been established.

The focused-minus-full centre difference is (779, 206) camera pixels, or
(506.35, 133.9) µm at that pixel size. This is an image-coordinate displacement,
not yet a signed laboratory or sample-coordinate translation.

Mira says scattering is normally intended at rotation 0° unless otherwise
agreed, and that adjacent measurements in `swaxs_x` are 5 µm apart with
overlapping beam footprints. **These particular files actually scan 90–270°.**
No numerical beam radius or profile was found in the inspected metadata.

### Motor-stack clarification received 2026-11-23

Mira supplied `data/Motor_stack_combined_formax.jpg` (outside the repository)
and a further explanation. CT was acquired with the sample at the full-beam
centre. SAXS line scans use swaxs_x, with tomo_ry increments between lines.
The sketch places tomo_zf and tomo_xf above tomo_ry, and swaxs_x and swaxs_y
below it. It labels the beam direction Z and the vertical direction Y.
The sketch does not locate tab_x/tab_y within the stack.

Mira explicitly states that tomo_zf is transverse to the beam at 0°/180°,
whereas tomo_xf is transverse at 90°/270°. Thus their horizontal projection
depends on rotation; their names must not be interpreted as fixed laboratory
axes. At intermediate angles, both contribute. The focused/full-beam camera
offset is a translation used for registration, not an extra rotation or an
offset to apply to the SAXS detector's q/azimuth axes. Her wording also mentions
beam centres on different detectors; the earlier two supplied pixel positions
were both described as Zyla measurements. No new detector pixel coordinates
were supplied, so do not reinterpret those two positions as belonging to
different detectors.

For a model using the reconstruction's rotation axis as origin, a candidate
horizontal beam-coordinate relation is:

```text
beam_X(theta) = B_X - s_swaxs_x * delta_swaxs_x - s_tab_x * delta_tab_x
                  - s_zf * delta_tomo_zf * cos(theta)
                  - s_xf * delta_tomo_xf * sin(theta)
```

All deltas here are SAXS minus CT motor positions converted to µm. The signs
and reconstructed-image orientation must be established in one shared
convention. `B_X` includes the registered beam/reference-origin displacement;
do not independently add a second camera-centre correction to it. The upper
stage deltas are used because the CT reconstruction already contains the sample
with its CT alignment settings. This equation assumes tab_x is a fixed
laboratory translation, which the sketch does not establish. It is a proposed
model, not a validated transform. Vertical translations and their signs need
the same explicit beam-relative-to-sample convention.

Before the stack-model update, the implementation used constant user-supplied XY coefficients
for every motor, defaults tomo_xf to fixed laboratory X and tomo_zf to zero.
That could not represent the clarified stack geometry. However, scan 135 differs
from CT by only −0.04 µm in tomo_xf and −16.18 µm in tomo_zf. Correcting the
angle dependence of these deltas cannot alone resolve the approximately
815 µm X profile discrepancy reported below. A justified mapping from the
reconstruction origin to the camera/rotation-axis reference remains necessary.

Mira calls the scan-title counts numbers of points and describes 420
measurements per line. The files contain 421 × 51 measurements, including both
endpoints at 5 µm and 3.6° spacing. Retain the verified file grid; record this
terminology discrepancy rather than dropping a point or changing spacing.
The sketch's “swaxs_y (not used)” does not remove the differing Y snapshots
between scans 135–137; it is consistent with Y remaining fixed within each
X/rotation mesh, but that interpretation has not been explicitly confirmed.

## CT organization and physical metadata

The reconstructed array is `/data/recon_abs`, shape `(1486, 2697, 2697)`,
little-endian float32. Storage is contiguous, uncompressed; the array occupies
43,235,520,696 bytes. Partial reads should select regions rather than loading
the entire array.

The dataset named
`/metadata/reconstructed_vol_dimensions_Z(number-of-slices)_X(width)_Y(height)`
contains the string `(1486, 2697, 2697)`. This declares Z/X/Y terminology, but
there are no dimension scales or axis attributes on the array. Equal second
and third dimensions prevent shape alone from distinguishing their orientation.
The mapping of these axes to the viewer's sample axes remains unresolved.

Selected `/metadata/` values:

| Dataset | Stored value |
| --- | --- |
| `pixel_size_cm` | `6.5e-05` = 0.65 µm |
| `energy_keV` | 20.759 |
| `sample-detector_dist_cm` | 8 |
| `recon_algorithm` / `recon_filter_name` | `gridrec` / `parzen` |
| `phase_retrieval` | string `no` |
| `rotation_center_actual` / `rotation_center_expected` | 1351 / 674 |
| `tomo_xf_proj_mm` / `tomo_zf_proj_mm` | approximately 1.304495 / −0.482420 |
| `flat_scan_number` / `dark_scan_number` | strings `92` / `94` |
| `flats_used_for_ffc` / `darks_used_for_ffc` | strings `50 to 399` |
| `Acquisition_parameters` | `rotaryscan 11.0 0.1 0.5 0.015 0.03` |

If the declared pixel size applies isotropically to this reconstruction, its
voxel-count extents are 965.90 × 1753.05 × 1753.05 µm in stored dimension order.
This does not establish the volume origin or its position in the beamline.
The reconstruction's 2697-pixel transverse dimensions also differ from the
reported 2560-pixel camera width. We need the reconstruction/stitching/cropping
history before translating camera pixels into reconstructed voxel indices.

`Radiographs.h5` has 1800 recorded projection angles, from approximately
11.033363° to 190.933124°, with median increment 0.0999993°. Its start-positioner
snapshot says `tomo_ry ≈ 360°`, so that snapshot is not the projection-angle
array. Projection trigger spacing is approximately 0.045 seconds.
Flat and dark metadata each contain 400 points; their table X positions are
approximately −7.97127, compared with −2.97059 for radiographs.

## Scattering acquisition coordinates

All three metadata files have exactly this `/entry/title`:

```text
mesh swaxs_x -3.1 -1.0 420 tomo_ry 90.0 270.0 50 0.05 False False
```

The observed array lengths and motor trajectories support 420 X intervals
(421 measurements per row), and 50 rotation intervals (51 rows):

```text
n = 421 * row + column
row = 0..50; column = 0..420
nominal swaxs_x = -3.1 + 0.005 * column
nominal tomo_ry = 90 + 3.6 * row
421 * 51 = 21471 measurements per scan
```

Rows traverse X in the same direction, from about −3.1 to −1.0. Interpreting
linear positions as mm makes the nominal step 5 µm and span 2.1 mm, consistent
with Mira's message. **The motor datasets have no units attributes**, so the
motor-unit and sign conventions still need explicit beamline confirmation.
The last title arguments have not been interpreted beyond the observed
`albaem-e01_ti` array being uniformly 0.05.

| Scan | Start timestamp as stored | End timestamp as stored | `swaxs_y` snapshot |
| --- | --- | --- | --- |
| 135 | 2026-04-30 19:20:15.737437 | 2026-04-30 21:53:58.771412 | −2.12355 |
| 136 | 2026-04-30 22:00:34.756129 | 2026-05-01 00:34:20.713147 | −2.04650 |
| 137 | 2026-05-01 00:34:21.519322 | 2026-05-01 03:07:51.495964 | −2.19220 |

The Y offsets from scan 135 are +0.07705 and −0.06865 raw motor units. If mm,
these are +77.05 and −68.65 µm. **Interpretation:** three offset X/rotation
scans, different Y sampling locations, as also discussed with Carl. The physical direction and sample
coverage of those offsets remain unconfirmed. This is not a dense independent
X/Y/rotation grid.

Start-position snapshots at `/entry/instrument/start_positioners/`:

| Motor | CT radiographs | Scan 135 | Scan 136 | Scan 137 |
| --- | ---: | ---: | ---: | ---: |
| `tab_x` | −2.970590 | −2.098675 | −2.098830 | −2.098935 |
| `tab_y` | −36.7157025 | −40.709060 | −40.709015 | −40.7090025 |
| `swaxs_x` | −0.248700 | −0.005000 | −1.000800 | −1.000550 |
| `swaxs_y` | −5.853250 | −2.123550 | −2.046500 | −2.192200 |
| `tomo_xf` | 1.304495 | 1.304455 | 1.304460 | 1.304475 |
| `tomo_zf` | −0.482420 | −0.498600 | −0.498620 | −0.498630 |
| `tomo_ry` | 360.000019 | 90.000019 | 270.000008 | 269.999973 |
| `swaxs_ry` | 180.0001 | 180.0001 | 180.0001 | 180.0001 |

Keep the raw snapshots as well as any derived offsets. For example, scan 135's
`swaxs_x = −0.005` snapshot is outside the actual scan range. A snapshot must
not replace per-frame coordinates or be treated as a universally valid origin.

Per-frame arrays, all length 21471 and float64, under `/entry/measurement/`:

| Dataset | Observed role / limitation |
| --- | --- |
| `swaxs_x` | Recorded motor position; steps jitter around 0.005 |
| `tomo_ry` | Recorded rotation, with a few row-start anomalies below |
| `pcap_fast_axis` | Closely matches `swaxs_x`; likely a separate acquisition/processing representation, precise definition unconfirmed |
| `pcap_ts_trig` | Large second-like timestamps, consistent with Unix epoch interpretation |
| `albaem-e01_ch1`, `albaem-e01_ch3` | Recorded monitor channels; physical roles, units and normalization use unconfirmed |
| `albaem-e01_ti` | Constant 0.05; acquisition-time interpretation to confirm |

These measurement datasets are hard links to corresponding instrument datasets.
There are no per-frame `swaxs_y`, `tab_x/y`, or `tomo_xf/zf` arrays in these files.
The maximum `pcap_fast_axis` versus `swaxs_x` differences are about 0.000150,
0.0000963 and 0.0000552 raw units for scans 135, 136 and 137 respectively.

Compared with the nominal row angle, only these points differ by more than 0.01°
(indices are zero-based):

| Scan | Frame index | Recorded angle | Nominal row angle |
| --- | ---: | ---: | ---: |
| 135 | 6315 | 140.3999895° | 144.0° |
| 135 | 11367 | 183.5999939° | 187.2° |
| 136 | 6315 | 140.4000378° | 144.0° |

Each is the first point of a new 421-point row and retains the preceding row's
angle. Whether this is a stale readback or a real exposure-angle issue needs
confirmation. Preserve the values and flag them; do not silently correct them.

Stored ISO timestamps lack a timezone. Interpreting the first scan-135 trigger
as Unix seconds gives 2026-04-30 17:20:20.516 UTC, consistent with a first exposure
a few seconds after the stored start time if that time is Swedish summer time.
That timezone interpretation is an inference. Median trigger intervals are
about 0.416 seconds, substantially longer than 0.05; retain actual timestamps.

## Integrated scattering arrays

All three integrated files have the same paths, shapes, dtypes and q/azimuth
coordinates. Let `one=/entry/default/data1d/orig/` and
`two=/entry/default/data2d/orig/`:

| Path suffix | Shape | Contents |
| --- | --- | --- |
| `one/I` | `(21471, 2000)` | Stored 1D curve per measurement |
| `one/I_errors` | `(21471, 2000)` | Supplied uncertainties; exact definition to confirm |
| `one/q` | `(2000,)` | q bin centres, units attribute `1/angstrom` |
| `one/norm` | `(2000,)` | Static 1D normalization array |
| `two/cake` | `(21471, 180, 2000)` | Azimuth/q cake per measurement |
| `two/cake_errors` | Same | Supplied cake uncertainties |
| `two/q` | `(2000,)` | Identical to `one/q` |
| `two/azi` | `(180,)` | Azimuth centres 1°, 3°, …, 359°; units `degrees` |
| `two/norm` | `(180, 2000)` | Static 2D normalization array |

All these arrays are little-endian float64. NXdata `axes` attributes are
`[".", "q"]` for 1D and `[".", "azi", "q"]` for cakes: the measurement axis
is unnamed. `/entry` has default `data1d`; resolve the actual nested paths
explicitly rather than assuming that string directly names an NXdata group.

q centres run from 0.00012765875 to approximately 0.51050734125 Å⁻¹ with step
0.0002553175 Å⁻¹. In nm⁻¹ these are 0.0012765875 to 5.1050734125, step
0.002553175. Bin edges are not stored. Half-step boundaries would be a derived
convention, to record explicitly if adopted.

Intensity/error arrays are chunked in five-measurement blocks: `(5,2000)` and
`(5,180,2000)`, without compression. One cake is 2,880,000 bytes (2.747 MiB);
one five-frame cake chunk is 14,400,000 bytes. `cake` and `cake_errors` each
allocate 61,848,000,000 bytes, explaining most of the file size. A curve is
only 16,000 bytes. GUI readers should request selected measurements/chunks.

### Normalization and uncertainty observations

Sampled frames: 0, 210, 10735 and 21470 from each scan. All sampled I/cake values
were finite and nonnegative; this is not an exhaustive data-quality audit.
`one/norm` is zero in q bins 0–35, and `two/norm` is zero in 117827/360000 cells
(32.73%). Those cells require coverage-aware treatment rather than interpreting
every stored zero as a measured zero intensity.
The first q centre with nonzero 1D normalization is 0.00931908875 Å⁻¹.

The cake values are on a very different numerical scale from the stored I(q).
For the middle sampled frame (10735) in each of the three files, the following
empirical relation reproduces I(q) to maximum absolute differences below 5e−14
on bins with nonzero `one/norm`:

```text
I[q] = sum_phi(cake[phi,q] * norm2d[phi,q]) / norm1d[q]
```

In these files `norm1d[q] / sum_phi(norm2d[phi,q])` is approximately
177777777.7777778 on supported bins. A plain angular mean, or a weighted mean
whose denominator is simply `sum(norm2d)`, therefore does not reproduce I(q).
Retain both supplied normalization arrays. Their physical meaning, the scale
factor, and any absolute-intensity units have not been established.

Rechecked on 2026-11-23 using the saved frame 10735 exports from all three
scans: maximum absolute I(q) residuals are 4.97e−14, 3.55e−14 and 4.62e−14.
The ratio is numerically equal to `1 / (75e-6 m)**2`, the inverse area of a
75 µm square pixel. This suggests an area convention in the upstream reduction,
but does not establish that convention or the physical intensity units. The
recorded azint commit could not be found in the public maxiv-science/azint
repository. Current [azint source documentation](https://maxiv-science.github.io/azint/azint-reference/)
normalizes its returned intensity during integration; its current normalization
arrays do not explain the differing 1D/2D conventions in these older files.
Do not divide the stored cake or I(q) by their normalization arrays again, or
silently apply an inferred pixel-area correction. The viewer preserves the
stored values and labels the cake colour scale as stored intensity.
After the original HDF5 files became available again on 2026-11-23, five frames
per scan (0, 210, 10651, 10735 and 21470) were checked directly. Their weighted
cake-to-I(q) relation agrees to relative L2 residuals below 1.6e−15; the largest
absolute residual is 1.37e−12 in a brighter sample frame. All three saved frame
10735 exports match the source arrays exactly. The application reader returns
the source cake and I(q) unchanged in covered bins and masks unsupported bins.
The 15 checked frames include covered zeros, with no covered negative or
non-finite intensities. All three coverage arrays have the same 117827 missing
bins and the same pixel-area scale ratio. This is a sampled consistency check,
not validation of the upstream reduction or absolute intensity calibration.
Numerical details are in `data/inspection/bamboo-abs/normalization-recheck.json`
outside the repository.

Cake display: positive finite values use log10 and the Magma scale. Grey cells
and the “No data” legend identify unavailable/non-finite values, including bins
with no normalization coverage. Covered zero intensity is turquoise, separately
labelled and hoverable. Negative finite values, if encountered, use a third
categorical colour because a real logarithm is undefined there. Missing cells
are not interpolated across.

Applying the usual independent-error quadrature to `cake_errors * norm2d`
does **not** exactly reproduce `I_errors`: middle-frame relative L2 differences
are approximately 4.44%, 4.38% and 4.32%. Error semantics, pixel-splitting
correlations and processing details need investigation before uncertainty rebinning.

### Processing provenance

`/entry/azint/input/` records `program="C++Azint"`, version
`commit 446eba533e22fd6d8dd52286e7a934fa174063dd`, `n_splitting=8`,
`polarization_factor=0.997` and literal `error_model="possion"`.
Processing dates differ: scan 135 on August 18, scans 136 and 137 on August 17,
2026; acquisition was April 30–May 1.

`/entry/eiger/poni` embeds this detector geometry text:

```text
Detector: Eiger2_4M
Detector_config: { }
Distance: 2.51834
Poni1: 0.0895356
Poni2: 0.0815797
Rot1: -0.000468653
Rot2: 0.000225302
Rot3: 1.43338e-11
Wavelength: 5.97255e-11
```

The geometry's filename attribute and `mask_file` reference beamline paths
ending in `saxs-122.poni` and `saxs-mask_2026_122.npy`. The geometry text is
embedded, while the mask content is not. Preserve both the text and original
path references. No intensity units, sample identifier, or explicit CT
registration transform were found in the integrated-file headers.

## Questions for Mira / ForMAX

1. What is the transformation from the listed motor positions and camera
   centres to sample coordinates, including signs, stage order and rotation
   pivot? How do `swaxs_ry=180°` and `tomo_ry` combine physically?
2. Which reconstructed array direction is the physical rotation axis? What
   stitching/cropping/flipping led to the reconstructed dimensions and centres
   1351/674, and how are camera pixel coordinates transferred to this array?
3. Which CT coordinates/regions do the sampled `swaxs_y` locations cover?
   What were the beam footprint and
   positional uncertainties?
4. Does integrated frame n correspond exactly to metadata measurement n?
   Which of `swaxs_x` and `pcap_fast_axis` should locate each exposure? How should
   the three anomalous angle readbacks be treated?
5. What corrections and normalization distinguish `cake`, `I`, and their norm
   arrays? What are the intensity and uncertainty units/definitions? Which
   monitor channel, if any, should be applied to these already processed arrays?
6. Does “rebinning” refer to averaging nearby parallel paths represented by a
   display region at the current zoom? What weights account for the beam profile
   and overlapping footprints? What should the measured and proposed
   single-scattering simulated displays represent, and which scripts/results
   should the viewer consume?

## Inspection record and reproducibility

Source files were opened read-only with installed `h5ls`/`h5dump` 1.14.6 and
small numeric exports analyzed using NumPy. The complete CT and scattering
volumes were not loaded into RAM or scanned. All small motor arrays were read;
the intensity sampling extent is stated above.

Generated inspection material is outside the repository at
`~/src/nim/data/inspection/bamboo-abs/`: full header/storage/attribute dumps for
all ten files, scalar metadata dumps, motor arrays, `summary.json`, `checks.json`,
and one representative frame per scan in `.npz` form. The extraction script is
retained there as `inspect_bamboo_abs.py`; it does not modify source HDF5 files.
`verify_relationships.py` rechecks shapes, shared coordinate/normalization arrays,
the angle exceptions and the sampled cake-to-I relation from the small exports.
The exported arrays are working inspection material, not a new science format.

Example commands, from `Bamboo/ABS`:

```bash
h5ls -r 'Scattering data/scan-0135_eiger_integrated.h5'
h5dump -pH 'Scattering data/scan-0135_eiger_integrated.h5'
h5dump -d /entry/title 'Scattering data/Metadata/scan-0135.h5'
h5dump -d /entry/default/data1d/orig/I -s 10735,0 -c 1,2000 \
  'Scattering data/scan-0135_eiger_integrated.h5'
```

For `h5dump` subsets, put `-s`/`-c` immediately after the corresponding `-d`,
before output-format options. This was required by the installed CLI parser.

## Viewer extent sanity check (2026-11-19)

### Rotation-reference review (2026-11-23)

A further check uses every stored I(q) curve in scans 135 and 136, averaging
over 0.05 < q < 0.2 Å⁻¹. For each of the 51 angle rows, subtract that row's
median, clip negative excess to zero and calculate its weighted centroid in
nominal swaxs_x (µm). Least-squares fits to
`a + b*cos(theta) + c*sin(theta)`, with theta the nominal motor angle, give:

| Scan | a (µm) | b (µm) | c (µm) | RMS residual (µm) |
| --- | ---: | ---: | ---: | ---: |
| 135 | −1922.0291 | 518.5493 | 372.1916 | 2.6386 |
| 136 | −1925.0484 | 512.3310 | 368.8938 | 2.6667 |

This is a modal-intensity centroid, not a direct measurement of the sample's
mass centre. Nevertheless, the consistent roughly 630–640 µm sinusoidal
amplitude strongly supports a significant displacement of the scattering
feature from the physical rotation axis. It cannot be explained by the roughly
16 µm change in the upper alignment motors between CT and SAXS. In CT slice 543,
the positive-intensity centroid is about (8.4, 20.6) µm from the array centre;
visual inspection also places the object near the array centre. CT density and
SAXS centroids need not coincide, but the present evidence does not justify
treating the CT array centre as the physical rotation axis.

Separate three concepts before revising registration: reconstructed array
origin, physical rotation-axis location, and specimen position relative to that
axis. A constant beam shift and rotation-dependent fine-stage deltas alone do
not establish these. The CT-to-viewer rotation currently uses the array centre.

The reconstruction's acquisition timestamps and fine-stage positions exactly
match Radiographs.h5. A mismatched CT scan is not supported by those checks.
However, `rotation_center_expected=674`, `rotation_center_actual=1351`, and
reconstruction width 2697 need their original processing definitions. The
arithmetic `2697 = 2*1349 - 1` suggests investigating padding/cropping conventions,
but does not establish a particular reconstruction procedure. Do not subtract
full-camera beam coordinates from these centres without identifying their
coordinate frames. The original Zyla file containing camera/ROI metadata is an
unavailable external-link target in the supplied metadata bundle.

Clarification needed from the beamline/reconstruction workflow: where is the
physical rotation axis in the final reconstructed XY array, how are original
Zyla coordinates transformed into that array (ROI, padding/cropping, flips and
angular origin), and where do tab_x/tab_y and swaxs_ry sit relative to the sketch?
swaxs_ry is approximately 180° in both CT and SAXS snapshots. Its relevance to
motor direction signs depends on the unprovided stack geometry.

### Provisional sinusoid-derived registration test

At Carl's request, the implemented stack model was tested using all 51 line
profiles in scan 135. Mean I(q) over 0.05–0.2 Å⁻¹ supplies each profile; weights
are positive excess above its row median. Fit even-indexed angle rows to
`A + B*cos(theta) + C*sin(theta)` in the current **beam-coordinate** mapping,
including the rotating fine-stage corrections. The fitted coefficients are
(-296.4534, 500.2100, 372.7972) µm. Odd-indexed rows, excluded from the fit,
have 3.1317 µm RMS and 13.1359 µm maximum absolute centroid residual.

CT slice 543 is retained from the existing Y mapping, at −129.675 µm. The
positive reconstructed intensity has aligned X/Z centroid
(8.4061, −20.6294) µm. Using the implemented transform
`R_y(theta) * (aligned_image - pivot)`, the candidate parameters are:

| Parameter | Candidate (µm) |
| --- | ---: |
| CT offset X | +296.4534 |
| Trajectory correction X (JSON `pivot_x`) | −491.8039 |
| Trajectory correction Z (JSON `pivot_z`) | −393.4266 |

Correction after GUI testing: these coefficients must be applied to beam X as
`pivot_x*cos(view_angle) + pivot_z*sin(view_angle)`, leaving the rendered CT
centred. The initial implementation instead translated the CT by `-R*pivot`.
Although that preserved the relative transverse ray geometry used by the
profile comparison, it made the specimen orbit around a distant point in the
GUI. It was incorrect for the intended centred CT viewer. The fitted sinusoid
does not independently establish a physical axis location in the reconstruction.
The coefficients and constant X offset retain their numerical values; only the
coordinate-frame representation changes. The helper also restores the camera
focal point to the CT centre while retaining view direction and zoom.

All other reference positions, factors, camera shifts, Y mapping and image-axis
orientation remain those of the existing Bamboo starting estimate. The constant
term requires the fitted CT offset X; changing only the rotation axis cannot
remove it. A scattering centroid is not independently a physical axis marker:
this derivation assumes its average location corresponds to the positive CT
centroid in this slice.

CT projection **shapes**, which were not fitted, support the candidate. Positive
CT voxels are projected geometrically into the 5 µm SAXS coordinate bins. Median
Pearson correlation with the measured SAXS profiles over all 51 scan-135 angles
improves from −0.2872 to 0.9299. Relative-amplitude plots at held-out angles
93.6°, 180° and 266.4° show the previously displaced signal regions overlapping.
Fine CT features and SAXS contrast remain different, as expected for distinct
measurements; correlation does not validate absolute intensity normalization.

Without refitting, apply the same registration to scans 136 and 137 at 90°,
126°, 180°, 234° and 270°. Their existing Y coordinates select CT slices 661
and 437 respectively. Centroid residual RMS is 4.6506 and 7.7359 µm; shape
correlations span 0.8425–0.9574 and 0.8328–0.9670. This cross-scan agreement is
evidence for a useful provisional registration, not independent metrology of
the physical axis or proof of the camera-origin convention.

Reproducible scripts and results are in
`data/inspection/bamboo-abs/registration-review/` outside the repository:
`estimate_axis.py`, `check_axis_transfer.py`, `plot_axis_comparison.py`,
`135-axis-estimate.json`, `axis-transfer.json`,
`135-candidate-placement.json` and `axis-alignment-comparison.png`.
The candidate is saved for review; this investigation does not overwrite an
existing project's registration.

### Earlier single-row extent comparison

Implementation update: the ForMAX stack hypothesis now has angle-dependent
upper-stage projections and an editable CT rotation-axis location. The earlier
constant-factor model remains available for custom registrations. Axis position
defaults to zero pending a justified reconstruction reference; no fitted SAXS
centroid offset is applied automatically. Per Carl's working assumptions,
swaxs_y and tomo_ry share the vertical direction, tomo_xf is a centring stage,
and swaxs_ry has no further effect at 180°. A different swaxs_ry snapshot is
flagged for beamline clarification. The table/Y snapshots are retained as data,
including differences between separately acquired Y scans.

The current imported CT has XYZ dimensions 2697 × 2697 × 1486 and 0.65 µm
spacing. Its voxel-edge X/Y bounds are −876.525…876.525 µm and Z bounds are
−482.95…482.95 µm. Each SAXS line spans 2100 µm (421 positions, 420 × 5 µm).
That is 346.95 µm wider than a single image-X interval. Offsets or signs cannot
make that complete interval fit inside image X while retaining those scales.
The comparison also needs the sample rotation: with image Z aligned to lab Y,
the CT box projects to lab-X width 1753.05 × (|cos(theta)|+|sin(theta)|) µm.
An axis-aligned CT box at 90° or 180° is still narrower than the complete scan;
at intermediate angles the projected box may be wider. Scanned background or
reconstruction cropping could explain this, but neither is established by the
available metadata. No coordinate rescaling or filtering of outlying scan
positions is justified just to force agreement with these bounds.

With the current starting estimate, scan 135 maps to X −1473.075…626.925 µm,
Y −129.7575 µm. The offset of that range remains unvalidated. This is a physical
registration uncertainty, not a unit conversion between raw mm and displayed
µm: a raw swaxs_x step of 0.005 is consistent with Mira's stated 5 µm.

A direct profile comparison at the nominal 180° SAXS row adds evidence that the
entire scan range is not a sample-width measurement. For scan 135, mean I(q)
over 0.05 < q < 0.2 Å⁻¹ is near 6.08 for most positions, rising to 15.15 in a
localized region. Positions above median + 20% of peak contrast span columns
87–178 (raw swaxs_x −2665…−2210 µm). The CT slice at index 543 (chosen using the
current Y estimate) has a positive projected-density feature near its centre.
Baseline-subtracted positive profile centroids lie at approximately −815 µm
under the current SAXS mapping and −1 µm in the CT at 180°. This suggests a
substantial X offset error in the starting estimate. These are different
modalities, and the Y estimate and feature correspondence are unconfirmed;
centroid matching is not sufficient evidence for automatically correcting the
registration. The measurements and image scales have not been changed.
