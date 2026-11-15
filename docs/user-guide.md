# TomoSWAXS user guide

TomoSWAXS displays a sample volume together with a SAXS intensity curve and
an intensity map against scattering coordinate q and azimuth φ. The current
demo can use a synthetic specimen or a loaded CT volume. The scattering data
are illustrative.

## Start

With the project virtualenv active, run from the repository directory:

```bash
uv run --active --locked tomoswaxs --server --port 8080 --timeout 0
```

Open http://127.0.0.1:8080/ in a browser. Stop the server with Ctrl+C in its terminal.

## Projects and samples

Use the **Project** menu for **New project**, **Open project**, **Project settings**
and **Close project**.

For **New project**, choose a directory using the folder icon beside the path
field. Navigate to the destination, use **Create folder** if needed, and choose
**Use this directory**. The new project takes its name from that directory.
**Include current sample** adds the displayed sample and its viewing state.

For **Open project**, the folder icon opens the project picker. Select a project
file or directory there, or enter its path directly and press **Open project**.
The picker browses the application host's filesystem.

The header shows the project name and an **Active sample** selector. **Add sample**
opens or imports another CT dataset. **Sample settings** holds the sample name
and axis assignment. Rename the project in **Project → Project settings**. Settings and viewing state
are saved automatically after valid changes settle. Reopening a project restores
its active sample, beam position and size, angle, contrast, opacity and camera.

Existing OME-Zarr datasets are referenced in place. TIFF conversions default to
`data/<sample-id>/ct.ome.zarr` inside the project; choose **External destination**
to write elsewhere. `results/<sample-id>/` and `figures/<sample-id>/` are the
locations for future analysis outputs, created when needed. Stable sample IDs
keep associations intact when names change. Different projects can reference
the same dataset with independent settings and results.

Paths inside the project are relative, so the project and its internal data can
be moved together. If external data have moved, open **Project → Project settings**, select the
**Sample to locate**, and choose **Locate sample data** to update its reference.
A failed or cancelled sample load preserves the displayed volume. Save failures
are reported in the footer and project dialogs. After an external manifest edit,
**Project → Reload saved project** reopens the on-disk version and discards unsaved viewing
changes.

Without a project, the header says **Standalone inspection**. This is read-only
inspection: viewing controls can be adjusted temporarily, without saving sample
settings or analysis results. **Add to project** retains the current sample and
view in a new or existing project. **Project → Close project** returns to standalone
inspection. The explicit import pixel size edit described below updates the
dataset itself. Some future analysis tools will require an active project.

A project can also be opened at startup:

```bash
tomoswaxs --server --port 8080 --timeout 0 --project /path/to/project.json
```

Project name edits in **Project settings** are saved when the dialog closes.
An empty name keeps the dialog open for correction. Opening **Locate sample
data** also saves the edited name before continuing to the file chooser.

## Open and import CT volumes

Choose **Open volume** to browse the application host's filesystem. Select an
OME-Zarr image and press **Open**. Double-click a folder or press Enter to enter
it; **Open** also enters the selected folder. **Parent directory** moves up.
Press Enter in the directory field, or use **Refresh**, to list that path.
Click a column heading to sort by name, size or modification time. A single click
selects an entry and shows its type, file size and full path below the table.

For TIFF samples imported with user-supplied pixel size, **Sample settings →
Pixel size (µm)** lets you revise those sizes. **Preserve XYZ ratio** scales all
three values proportionally; clear it to edit them separately. Closing the dialog
updates the OME-Zarr coordinate metadata at every resolution level and refits the camera. Image values
are preserved. This explicit import pixel size edit also works during standalone
inspection; project-specific settings and analysis results still require a project.

Selecting a TIFF opens import settings. Without an active project, choose
**Create new project** to use a project destination, or choose a new external
**OME-Zarr destination** for standalone inspection. Conversion writes a new
dataset and preserves the TIFF. With an active project, the destination defaults
to its data directory. **Pixel size** is in X, Y, Z order, in µm. Physical
pixel sizes are read from supported OME-TIFF or ImageJ metadata when available;
otherwise they start at 1 µm on each axis. **Preserve XYZ ratio** scales all three
values proportionally when any one field is edited. Clear it to edit sizes
separately. Pixel-size metadata are read afresh for each selected TIFF. The resulting dataset records that spacing and can be reopened directly.

Press **Open** to import and show the volume. Progress is displayed, and
**Cancel** stops the operation and removes the incomplete import. A failed or
cancelled operation keeps the previous scene. Existing destinations are
preserved; choose the existing OME-Zarr image to reopen it.

**Voxel array size limit (MiB)** limits the voxel array loaded into RAM for
volume rendering (64 MiB by default). The viewer picks a suitable pyramid level; a stride preview is used
when the store has no sufficiently small level. The footer shows preview
resolution and physical spacing. Overall process RAM also includes rendering,
I/O buffers and application overhead.

To open an existing image:

```bash
uv run --active --locked tomoswaxs --server --port 8080 --timeout 0 \
  --volume /path/to/image.ome.zarr --preview-mib 64
```

TIFF conversion can also run separately with `--import-tiff FILE --output
DESTINATION --import-only`. Supply `--voxel-size-um` followed by one isotropic
value or three X Y Z values when metadata does not provide physical spacing.
Omit `--import-only` to open the converted image immediately. `--data-dir`
chooses the initial GUI browsing directory.

The bundled demo's downsampled cjd TIFF uses an explicitly supplied test spacing
of 10 µm along each axis. That arbitrary value applies only to that demo.

The importer writes OME-Zarr 0.5 with full-resolution scalar values and a block-
mean pyramid. TIFF coordinates are centred around zero. Existing OME-Zarr scale
and translation metadata are retained. Scalar ZYX images with physical length
units are supported.

Expand **Contrast** to adjust display limits. The initial limits use sampled
preview median and 99.5th percentile, with a sampled minimum/maximum fallback.
Minimum and maximum map intensities to 0–1 for colour and opacity. **Reset
contrast** restores the initial limits for the current sample. Spinbox increments
are scaled to that sample's initial intensity range.
The source's full-resolution values remain available independently of the
preview. SAXS is fabricated and is labelled **SYNTHETIC SAXS**.

## Explore the sample

Drag with the left mouse button to orbit the camera. Use the mouse wheel or
right-button drag to zoom, and middle-button drag to pan. With the left button, hold Shift to pan, Ctrl to roll the view, or Shift+Ctrl to zoom. **Saved views → Default camera** restores
the initial viewpoint. **Beam view** looks along the beam. Zoom-out stops at four
times the fitted view extent to keep the sample visible.

The beam travels along +Z. Its colour fades from light cyan at its origin to
dark blue downstream. **Opacity** adjusts the transparency of the sample.

## Position the beam

Use the X and Y fields or sliders under **Beam position** to position the beam.
Positions are displayed in micrometres (µm).

For direct positioning, hold **Alt+Shift**, then press and drag the left mouse
button in the volume view. Release the mouse button to finish. **Beam view**
is convenient for this operation because it shows the XY positioning plane
face-on. The gesture stays in beam-positioning mode until mouse release.

During scrubbing, the volume follows the controls; the SAXS panels refresh when
the gesture finishes. Rapid input is coalesced to the latest values.

## Rotate the sample

Use the **Sample angle** field or slider to rotate the object around Y relative
to the beam. Angles wrap around ±180° when stepping or entering values beyond
the ends of the range.

Open **Sample settings** in the header. Under **Axis assignment**,
choose **File direction for sample Y** to correct
the assumed TIFF dimension order: X is columns, Y is rows and Z is the stack.
Choose the file direction that should be treated as the sample's Y axis,
about which the sample rotates. The choice is saved in the active project and
restored with the sample. During standalone inspection it applies temporarily. Existing `nim-view.json` axis
settings are read as initial values when adding a dataset; the dataset is kept
unchanged.

The **Play/Pause** button starts rotation and switches to Pause; click it again to hold the current angle. The adjustments
button beside these icons opens **Rotation settings**: choose updates per second
and the angular step per update. The popup shows seconds per full turn. Defaults
are 20 updates/s and 1.5°, giving a 12-second turn. These settings are saved in
this browser. During
playback, the volume and scattering panels follow the selected rotation poses.
Camera orbiting changes the viewpoint; sample rotation changes the object's
orientation relative to the beam.

## Saved views

Use **Saved views → Save current view…** to name the current X/Y position,
sample angle and camera view, including zoom. Choose a name from the menu to
pause playback and restore that pose and camera together. **Manage saved views…**
provides Rename and Delete. **Default camera** restores the standard camera.

Saved views belong to the current sample and persist in its project record.
During standalone inspection they remain in memory for the application session;
adding that sample to a project retains them.

## Beam size

Expand **Beam size** at the left of the row below the coordinate sliders. It
contains **Radius (µm)** with **X** and **Y** prefixes in the two fields, for the
horizontal and vertical semi-axes of the elliptical beam. In this demo these
adjust the displayed beam geometry. The fabricated SAXS signal currently depends
on beam position and sample angle, rather than beam radius.

## Crop and resolution

**Crop** and **Resolution** are movable tabs, initially grouped beside the volume.
Open or close either through **Tabs**, drag them to another position, or use their
pop-out icons to place the controls in a separate window.

Crop has start/end spinboxes and a two-handle slider for each image axis. The
numbers are full-resolution voxel indices. Start is included and end is excluded;
`X 40–120` selects 80 voxels. These image axes precede the sample’s axis assignment
and rotation. Changing resolution preserves the same physical region.

Changes update the displayed region and load the needed OME-Zarr chunks in the
background. New requests replace older ones. **Cancel loading** restores the
previous loaded region. **Reset crop** selects the complete sample, and **Copy
coordinates** copies Python-style `[z_start:z_end, y_start:y_end, x_start:x_end]`.
Enable **3D handles** to resize the crop box directly in the volume viewer.

Resolution offers **Auto** and the available OME-Zarr levels, with cropped
array dimensions, array size and XYZ voxel size. Level 0 is full resolution.
Auto chooses the finest level fitting **Voxel array size limit (MiB)**. Smaller
crops can therefore use finer levels. Levels exceeding the limit are marked
“too large”. If no stored level fits, Auto subsamples the coarsest level and
reports the subsampling factor in **Loaded array**. The loaded-array readout
shows what is currently being rendered while a new request is loading.

The size limit covers the voxel array in RAM. Rendering, decompression and other
application allocations also use memory. There is no additional 512-voxel axis
limit. Set a suitable array limit for the machine running the application.

Projects remember crop and level selection per sample. Standalone selections
last while that sample remains open. Cropping changes the displayed CT region;
the scattering demonstration continues to sample the full source dataset.

## Read the SAXS panels

The left panel shows I(q), the mean intensity over the cake's azimuthal bins.
Enable **Log I** for a logarithmic intensity axis.

The right panel shows I(q, φ) as a heatmap with a fixed logarithmic colour scale.
Plotly's controls provide plot zoom, pan, reset and image export. Double-click a
plot to restore its axis ranges.

## Arrange the interface

Drag a panel tab to an edge to create a horizontal or vertical split. Drop it
onto another tab strip to group the panels as tabs. Drag the dividers to resize.
Shift-drag a tab to create an in-page floating panel; Shift-drag its tab back to a
dock target to reattach it. **Tabs** shows a check beside each open panel. Select an entry to open or close that panel.

The arrow icon beside a tab’s close button opens that panel in a separate browser
window. Move the window to another monitor or desktop as needed. The arrow in
that window returns the panel to the main window. Closing the browser window
also returns its panels; the tab’s × closes the panel. Keep the main application
window open while using detached panels.

Detached panels follow appearance and text-size changes in Settings. If the
browser blocks a new window, allow popups for the application’s address and try
again. Remember panel layout restores detached panels into the main window when
the application page is reloaded.
**View → Restore default layout** restores the volume above the two SAXS views.

**Settings** provides System, Light and Dark appearance; text size from 80–160%;
**Remember panel layout**; and **Show coordinate axes**. The RGB coordinate axes
are hidden by default. Preferences are saved in the current browser.
**Reset preferences** restores the defaults.

**About** contains the project credits, linked infrastructure logos, MIT licence,
and installed dependency versions.
