# TomoSWAXS user guide

TomoSWAXS lets you explore a sample’s 3D CT image alongside its SAXS measurements.

The interface reopens the last project used in this browser when it is available.
Recent projects appear in the Project menu. Closing a project clears automatic
reopening while keeping it in the recent list. If a project is unavailable, the
interface shows the error so you can choose another project or sample.
A **sample** brings those datasets together. A **project** groups samples and
remembers how you were viewing each one.

This guide covers the web interface. For installation and starting the
application, see the [installation guide](installation.md).

## Begin with a sample

If a sample is already open, you can begin [exploring it](#explore-the-sample).
To return to saved work, choose **Project → Open project** and select the project
directory or its `project.json` file. The **Sample** selector beside **Open sample…**
switches between its samples.

For new work, create a project through **Project → New project**, choosing a
folder for it, then use **Open sample…** to add your CT image. Supported inputs
are OME-Zarr images, HDF5 volumes and [3D TIFF files](#open-and-import-ct-volumes). Scattering
measurements are attached [separately](#browse-measured-saxs).

The file chooser shows files on the computer running TomoSWAXS. When you access
a remotely hosted application, your data must be accessible on that computer.
The chooser retains symlink paths while you navigate. **Filter** lists names and
patterns together, such as **Projects (project.json)** or **TIFF (*.tif, *.tiff)**.
Opening a project, CT image or SAXS scan selects the corresponding filter.
Choose **All files (*)** to show other files, or **Custom pattern…** to enter a
pattern such as `recon*`. Separate multiple custom patterns with semicolons.
Directories remain visible for navigation.

You can also open a sample without a project for temporary inspection. A project
is needed to retain sample settings and saved views between sessions. To keep
work begun this way, choose **Project → New project → Include current sample**.

## Explore the sample

The **µCT volume** panel shows the sample, with a beam when SAXS data are attached.
Click and drag to turn the view, scroll to zoom, and hold Shift while dragging
to pan. Ctrl-drag rolls the view; Shift+Ctrl-drag zooms. These gestures change
your viewpoint. Turning the view or playing camera rotation keeps the selected
scattering measurement.

**Beam view** stops camera playback and sets an orthographic camera view along the beam.
This is useful for choosing where it passes through the sample.
The help button in the volume panel’s header provides a
reminder of the mouse controls.

Use **Opacity** to see through the sample. The **Colour mapping** minimum and
maximum set the intensity interval mapped to the display’s colour and opacity
range. The arrow step follows the scale of the upper value. **Reset** beside
these values restores the initial limits for that sample.

### Turn the camera and select a measurement

**Camera angle** turns the viewpoint around the visible cropped region. Angles
wrap around at ±180°. The play button starts continuous camera rotation; the
same button pauses it. The adjustments button beside it sets the update
frequency and angular step, and shows the resulting time per revolution.

Choose the beam position and sample rotation in **SAXS measurements** to browse
the acquired data. The lock button beside X keeps the approximate X coordinate
as rotation changes, selecting the nearest acquired position at each angle.
With the lock off, rotation changes keep the measurement index.
You can also hold **Alt+Shift** and drag with the left mouse
button in the volume to position the beam. Its colour fades from light at the
origin to dark downstream.

In **SAXS measurements**, **Show beam** controls beam visibility.
**Beam size → Radius (µm)** sets the displayed beam’s horizontal and vertical
radii.

### Return to a useful view

**Saved views → Save current view…** records the beam position, sample angle and
camera view together. Selecting a saved name restores that combination and
pauses rotation. Saved views belong to the sample and are retained in its
project. **Saved views → Default camera** restores the initial viewpoint.

## Read the SAXS panels

**SAXS 1D** shows intensity I(q) against scattering coordinate q. **SAXS cake**
shows intensity against q and azimuth φ. With measured data attached, both plots
come from the same selected measurement; I(q) is the supplied integrated curve.
Grey cake bins indicate missing data, including regions without detector
coverage. Turquoise indicates measured zero intensity. The legend and hover
labels identify these colours. Negative intensities, if present, appear blue.
The q axis uses the units recorded in the file.

**Log I** changes the curve’s intensity axis to a logarithmic scale. The cake
uses logarithmic colours and an automatic colour range.
Use the plot toolbar to zoom or export an image; double-click a plot to restore
its axis ranges.

The plots remain empty until scattering data are attached. **Sample settings**
identifies the current data sources.

## Browse measured SAXS

Choose **Sample settings → Load SAXS scans…**.
Select an integrated `scan-XXXX_eiger_integrated.h5` file, or choose **Load scans
in this directory** to attach the scans together. The corresponding motor
metadata must be in `Metadata/scan-XXXX.h5` beside the integrated files. The
current reader supports the ForMAX X/rotation mesh scans supplied with the
Bamboo data.

The **SAXS measurements** panel is below **Crop and resolution** on the right. Select a
scan under **Scan / Y**, then choose X and rotation with the list spinboxes or
sliders. Arrow keys and the −/+ buttons step between acquired values. Typed
values are accepted only when present in the selected scan. Both plots follow
the selection. **Measurement details** contains the original motor readbacks.

The fields show the beam position and sample angle in the CT viewer’s coordinates.
Selecting a measurement moves the beam and rotates the sample. Moving the CT
controls selects the nearest acquired measurement; its position can differ from
the continuously positioned beam. **Measurement details** shows the original
motor readbacks and flags discrepant rotation readbacks. Y may come from a
start-of-scan snapshot, as indicated there.

### Relate measurements to the CT image

**CT registration** saves the coordinate model with the sample. When a CT
motor reference accompanies the scans, **ForMAX motor stack** is the starting
model. It treats tomo_ry and swaxs_y as sharing the vertical direction. The
alignment stages tomo_xf/tomo_zf rotate with tomo_ry: tomo_zf contributes
horizontally at 0°/180°, and tomo_xf at 90°/270°.

The table gives each motor's CT reference position in mm and signed factors
mapping motor differences into beam coordinates. Positive factors increase the
beam coordinate; negative factors reverse that direction. For the two rotating
fine stages, the X factor is their transverse amplitude; their Y contribution
is zero. swaxs_x uses the acquired nominal grid, swaxs_y uses recorded positions
or its scan snapshot, and other motors use snapshots.

**Trajectory correction (µm)** gives X and Z coefficients for the angular
beam-position correction. It adds X × cos(angle) + Z × sin(angle) to beam X
in the centred CT frame. The CT rotates about its central Y axis, after
**Sample Y from image** aligns the image. The trajectory correction,
**CT offset** and **Beam-centre shift** are separate registration parameters.

**Rotation direction** and **Rotation offset** relate the motor angle to the
CT orientation. The mechanical fine-stage projection uses the original motor
angle. For Bamboo, the initial camera displacement is X 506.35 µm and Y
133.9 µm, and image Z is initially aligned with sample Y. These values and the
motor directions remain provisional until the reconstruction reference is
confirmed. The current hypothesis assumes swaxs_ry is 180°; measurements with
a different snapshot show a request for beamline confirmation.

**Motor differences from CT reference** maps each motor displacement to X and Y
using constant factors. It supports simpler stage arrangements with fixed motor
directions. **ForMAX motor stack** also accounts for the fine stages rotating
with the sample. **Manual scan origin** supports direct coordinate mapping. Custom
registrations are retained. An untouched original motor estimate upgrades to
the stack model. Parameters persist with the sample when scans are changed.

Scattering may exist at only a few Y levels. Choose an acquired level under
**Scan / Y**. The project remembers the attached scans, selected measurement and
registration.

## See detail in a large image

**Crop** chooses the part of the CT image to display. Its coordinates are voxel
indices in the original image, before the sample’s axis assignment and rotation.
**Units** switches the fields between voxels and µm. Physical values describe
voxel boundaries in image coordinates; edits snap to the nearest voxel boundary.
Switching units preserves the crop.
The end index is exclusive: X from 40 to 120 selects 80 voxels. Use the paired
slider handles or enable **3D handles** to adjust the box in the volume view.

Enable **Auto detail** in Crop to concentrate the loaded data on the current
view. Zooming in can then reveal finer OME-Zarr levels. Manual Crop remains the
outer boundary. Existing detail stays visible during movement; newly exposed
regions load progressively from coarse to fine.

**Depth** controls the thickness shown around the camera's focal point. Move
left for a thinner region; the thickness in µm follows zoom. **Full** includes
the entire manual crop along the viewing direction. While orbiting, a thin
region turns with the camera and reveals different sections through its centre.
Use **Freeze region** to hold the current region on the sample and examine that
same material from other directions. **Unfreeze region** resumes following the
camera. Panning moves the viewing centre.

**Resolution** chooses how much image detail to load. OME-Zarr images can contain
several resolutions: level 0 is full resolution, and higher levels contain
progressively fewer voxels. **Auto** chooses the finest detail that fits the
**Voxel array limit (MiB)** for the selected crop. Reducing the crop can
therefore make finer detail available.

The size limit is the memory occupied by the loaded voxel array. Total
application memory also includes cached image chunks, rendering and temporary
arrays during loading. **Loaded**
reports the resolution actually being displayed, including any further
subsampling needed to fit the limit.

Changing resolution preserves the crop’s physical region. Changing the crop
centres camera rotation on the cropped region while keeping the viewing
direction and zoom. The project remembers crop and resolution choices per sample.
Auto detail, depth and a frozen region are also remembered with the sample.

## Open and import CT volumes

An OME-Zarr image opens directly through **Open sample…**. TIFF and HDF5 inputs must first be
converted to an OME-Zarr image; the import dialog asks where to save it. Within a
project, the destination defaults to its data folder. For an external destination,
use the folder button to choose the directory and edit the destination name as
needed. For standalone inspection,
you can create a project or choose an external destination. Conversion preserves
the source file and produces an image you can reopen without converting again.
Progress identifies the resolution level being written and the total number of
levels. The first is full resolution; subsequent levels are progressively coarser.

Check **Pixel size (µm)** before importing. Supported TIFF pixel-size metadata
supply the values when available; otherwise the fields start at 1 µm. Enter the
sizes for X, Y and Z. **Preserve XYZ ratio** changes the values proportionally
when you edit one; clear it to enter each size independently.

### Import an HDF5 volume

Select the HDF5 file through **Open sample…**. **HDF5 volume dataset** lists its
numeric 3D arrays with their dimensions and data types. Select the CT array;
a file containing a single candidate selects it automatically.

**Stored dimension order** assigns axes to the dataset’s first, second and third
dimensions. ZYX is the fallback assumption. The supplied ForMAX reconstruction’s
Z/X/Y metadata supplies ZXY instead; confirm its physical orientation for your
sample. Recognized `/metadata/pixel_size_cm` supplies an isotropic starting pixel
size in µm. Otherwise enter the pixel sizes, which initially show 1 µm.

Choose an OME-Zarr destination and import. Conversion reads blocks, preserves
scalar values at full resolution and creates coarser levels for viewing. The
result can subsequently be opened directly. For Bamboo, select `/data/recon_abs`;
the file supplies 0.65 µm pixel size. CT/scattering registration is separate from
this import.

### Correct image geometry

If you supplied the pixel size during import, it can be revised under
**Sample settings → Pixel size (µm)**. Closing that dialog saves the new sizes to
the imported OME-Zarr image itself. This also changes the sizes seen by other
projects referencing that image.

**Sample settings → Axis assignment → File direction for sample Y** corrects
the orientation when a TIFF’s dimension order was assumed incorrectly. Here,
file X means columns, Y means rows and Z means the stack. Choose the file
direction corresponding to the sample’s rotation axis. That assignment is saved
with the sample in the project.

## Keep work in a project

A project saves its samples, viewing settings, CT/scattering associations and
saved views automatically. **Samples…** lists its members and their sources and allows renaming without loading;
**Show sample** displays the selected member. Data paths are also listed under
**Sample settings → Data sources**.
**Remove from project** removes a sample’s membership and saved settings while
keeping the data files.

Existing datasets are referenced where they are. TIFF imports normally go inside
the project folder. When moving a project, keep its internal directory structure
together. External datasets must remain accessible; if a CT dataset has moved,
use **Project → Project settings → Locate sample data** to find it again.

Standalone inspection keeps viewing adjustments temporarily. The explicit pixel
size edit described above still changes the imported dataset. Some future
analysis tools will require an active project.

## Arrange the interface

Drag panel tabs to an edge to split the workspace, or onto another tab strip to
group panels. **Tabs** opens closed panels and can restore the default layout.
Shift-drag creates a floating panel inside the page.

The arrow beside a tab’s close button opens the panel in a separate browser
window. The arrow in that window returns it; closing the window also returns
its panels. Keep the main application window open while using these windows.

The **Settings** gear provides theme, text size, plot font size, the voxel array limit and
**Remember panel layout and sizes**. This remembers splitter proportions as well
as panel arrangement. Changes to the limit in Crop and resolution are remembered too.
Plot font size is a percentage of interface text size; 100% uses matching sizes.
These preferences are saved in the browser. A remembered layout restores detached
panels inside the main window when the page is reloaded.
