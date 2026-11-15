"""TomoSWAXS: CT volume visualization with illustrative SAXS data."""
from pathlib import Path
from dataclasses import replace
import math
import asyncio
import uuid
import numpy as np
import plotly.graph_objects as go
import vtk
from vtk.util.numpy_support import numpy_to_vtk
from trame.app import get_server
from .synthetic_demo import make_volume, scattering
from .orientation import sample_rotation
from .project_info import NAME
from .volumes import VolumeSource, import_tiff, tiff_spacing, is_ome_zarr, directory_entries, import_pixel_size, replace_import_pixel_size, spacing_xyz
from .projects import legacy_axis, VIEW_FIELDS
from .project_workflow import ProjectWorkflow
from .ui import ApplicationUI
from .saved_views import SavedViews
from .volume_viewing import VolumeViewing


class Demo(VolumeViewing, SavedViews, ApplicationUI, ProjectWorkflow):
    def __init__(self, server=None, volume=None, data_directory=None, preview_mib=64):
        self.server = server or get_server(client_type='vue3')
        self.state = self.server.state
        self.state.trame__title = NAME
        self.server.enable_module(dict(serve={'nim-assets': str(Path(__file__).parent/'assets')},
                                       styles=[f"/nim-assets/app.css?v={Path(__file__).parent.joinpath('assets/app.css').stat().st_mtime_ns}"], scripts=[f"/nim-assets/{name}?v={Path(__file__).parent.joinpath('assets',name).stat().st_mtime_ns}" for name in ('updates.js','beam.js','workspace.js','preferences.js','coordinates.js','crop.js')]))
        self.volume, self.spacing, self.origin = make_volume()
        self.signal_volume = self.volume
        self.volume_source = None
        self.contrast = (0., 65535.)
        self.beam_limit_um = 1600
        self.beam_length = 4.5
        self.state.update(beam_x=250., beam_y=0., radius_x=60., radius_y=40.,
                          angle=0., rotation_axis='y', sample_settings_notice='',
                          sample_pixel_size_editable=False,sample_voxel_x=1.,sample_voxel_y=1.,sample_voxel_z=1.,sample_voxel_linked=True, opacity=.55, workspace_ready=False, workspace_tabs=[], workspace_detached=[], workspace_busy=[], workspace_error='',
                          status='Ready', log_iq=False, show_about=False, show_sample_settings=False, ui_theme='dark', ui_text_scale=100,
                          draft_x=250., draft_y=0., draft_angle=0., rotation_playing=False, rotation_fps=20,rotation_step=1.5,rotation_settings_open=False,
                          beam_limit_um=1600, contrast_low=0., contrast_high=65535., contrast_step=100.,
                          data_notice='SYNTHETIC DEMO · fabricated specimen and scattering',
                          volume_summary='Synthetic specimen', show_volume_picker=False,
                          volume_directory=str(data_directory or (volume.path.parent if volume else Path.cwd())),
                          volume_entries=[], volume_selection='', volume_voxel_x=1., volume_voxel_y=1., volume_voxel_z=1.,
                          volume_voxel_linked=True,
                          volume_destination='', volume_prepared_path='', volume_preview_mib=preview_mib, volume_progress='',
                          volume_error='', volume_loading=False)
        self.init_projects()
        self.init_saved_views()
        self.init_volume_viewing()
        if volume is not None:
            self.set_volume_data(volume)
        self.sync_project()
        self.list_volume_directory()
        self.state.client_only('workspace_ready','workspace_tabs','workspace_detached','workspace_busy','workspace_error','show_about','show_sample_settings','show_project','project_menu_open','ui_theme','ui_text_scale','draft_x','draft_y','draft_angle','rotation_playing','rotation_fps','rotation_step','rotation_settings_open')
        self.dragging_beam = False
        self.dragging_controls = False
        self._applying_pose = False
        self.server.controller.trigger("nim_beam_position")(self.receive_beam_position)
        self.server.controller.trigger("nim_pose")(self.receive_pose)
        self.server.controller.trigger('nim_axes_visibility')(self.set_axes_visibility)
        self.build_scene()
        self.build_ui()
        self.state.change('beam_x', 'beam_y', 'radius_x', 'radius_y', 'angle', 'opacity')(self.update_scene)
        self.state.change('log_iq')(self.update_plots)
        self.state.change('contrast_low', 'contrast_high')(self.update_scene)
        self.state.change('volume_selection')(self.volume_selection_changed)
        self.state.change('rotation_axis')(self.rotation_axis_changed)
        self.state.change('sample_choice')(self.select_project_sample)
        self.state.change('volume_import_mode')(self.set_import_destination)
        self.server.controller.on_server_ready.add(self.view.update)
        self.server.controller.on_server_exited.add(self.persist_active)
        self.update_scene()

    def set_volume_data(self, volume, rotation_axis=None):
        self.loaded_volume = volume
        self.volume, self.spacing, self.origin = volume.values, volume.spacing, volume.origin
        self.volume_source, self.contrast = volume.source, volume.contrast
        self.signal_volume = volume.source
        pixel_size = import_pixel_size(volume.path)
        self.state.update(sample_pixel_size_editable=pixel_size is not None,
                          **dict(zip((f'sample_voxel_{axis}' for axis in 'xyz'),map(float,volume.source.spacing*1000))),
                          sample_voxel_linked=True)
        extent = (np.array(volume.source.shape[::-1])-1)*volume.source.spacing
        centre = volume.source.origin+extent/2
        diagonal = 2*float(np.linalg.norm(np.maximum(np.abs(volume.source.origin),np.abs(volume.source.origin+extent))))
        self.beam_limit_um = max(100, math.ceil(diagonal*500/100)*100)
        self.beam_length = max(4.5, diagonal*1.25)
        dimensions = ' × '.join(map(str,volume.source.shape[::-1]))
        preview = ' × '.join(map(str,self.volume.shape[::-1]))
        spacing = ' × '.join(f'{value*1000:g}' for value in volume.spacing)
        source_spacing = ' × '.join(f'{value*1000:g}' for value in volume.source.spacing)
        self.state.update(beam_limit_um=self.beam_limit_um, beam_x=float(centre[0]*1000), beam_y=float(centre[1]*1000), angle=0.,
                          rotation_axis=legacy_axis(volume.path) if rotation_axis is None else rotation_axis, sample_settings_notice='',
                          contrast_low=self.contrast[0], contrast_high=self.contrast[1],
                          contrast_step=10.**math.floor(math.log10((self.contrast[1]-self.contrast[0])/100)),
                          data_notice='CT volume · SYNTHETIC SAXS',
                          volume_summary=f'{volume.path.name} · {dimensions} voxels · XYZ spacing {source_spacing} µm · preview {preview} at {spacing} µm')
        self.sync_volume_controls(volume)

    def apply_import_pixel_size(self):
        if self.state.volume_loading or self.volume_source is None:
            return
        try:
            # Validate the current controls before changing the dataset.
            view = self.capture_view()
            path = self.volume_source.path
            spacing = spacing_xyz([self.state[f'sample_voxel_{axis}'] for axis in 'xyz'])
            if np.allclose(spacing,self.volume_source.spacing*1000,rtol=1e-12,atol=0):
                self.state.sample_settings_notice = ''
                return True
            replace_import_pixel_size(path,spacing)
            source = VolumeSource(path)
            cached = self.loaded_volume
            scale,origin = source.geometry(source.images[cached.level])
            origin=origin+(np.array([s.start for s in cached.selection][::-1])*scale if cached.selection else 0)
            volume = replace(cached,source=source,spacing=scale*cached.stride,origin=origin)
            self._applying_pose = True
            try:
                self.state.sample_context = uuid.uuid4().hex
                self.set_volume_data(volume,rotation_axis=self.state.rotation_axis)
                for key,value in view.items():
                    if key in VIEW_FIELDS:
                        if key in ('beam_x','beam_y'):
                            value = float(np.clip(value,-self.beam_limit_um,self.beam_limit_um))
                        self.state[key] = value
                self.set_image_data()
                self.last_signal_key = None
                self.reset_camera()
            finally:
                self._applying_pose = False
            self.update_scene()
            self.persist_active()
            self.state.sample_settings_notice = ''
            return True
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.state.sample_settings_notice = str(error)
            return False
        finally:
            self.state.flush()

    def close_sample_settings(self, visible=False):
        if visible:
            return
        success = not self.state.sample_pixel_size_editable or self.apply_import_pixel_size()
        self.server.clear_state_client_cache('show_sample_settings')
        self.state.show_sample_settings = not success
        self.state.dirty('show_sample_settings')
        self.state.flush()

    def reset_contrast(self):
        self.state.update(contrast_low=self.contrast[0],contrast_high=self.contrast[1])

    def rotation_axis_changed(self, **_):
        if self._applying_pose:
            return
        axis = self.state.rotation_axis
        if axis not in ('x','y','z'):
            self.state.sample_settings_notice = 'Choose image axis X, Y or Z.'
            return
        self.state.sample_settings_notice = ''
        self.last_signal_key = None
        self.update_scene()

    def volume_selection_changed(self, **_):
        if self.state.picker_mode=='project_directory':
            return
        self.state.update(volume_voxel_x=1.,volume_voxel_y=1.,volume_voxel_z=1.,volume_voxel_linked=True,
                          volume_destination='',volume_prepared_path='')
        self._import_sample_id = uuid.uuid4().hex
        self.state.volume_import_mode = 'project' if self.project else 'external'
        path = Path(self.state.volume_selection)
        if path.suffix.lower() in ('.tif','.tiff') and path.is_file():
            self.state.volume_destination = str(path.with_suffix('.ome.zarr'))
            try:
                spacing = tiff_spacing(path)
                if spacing is not None:
                    self.state.update(**dict(zip(('volume_voxel_x','volume_voxel_y','volume_voxel_z'),map(float,spacing))))

            except (OSError,ValueError) as error:
                self.state.volume_error = str(error)
        self.set_import_destination()
        self.state.volume_prepared_path = self.state.volume_selection

    def cancel_volume_load(self):
        if self.state.picker_mode=='project_directory':
            self.finish_project_directory(choose=False)
            return
        if self.state.volume_loading:
            self._volume_cancel.set()
            self.state.volume_progress = 'Cancelling…'
        else:
            self.state.show_volume_picker = False

    def list_volume_directory(self):
        try:
            directory, entries = directory_entries(self.state.volume_directory,projects=self.state.picker_mode == 'project',
                                                   directories_only=self.state.picker_mode == 'project_directory')
            self.state.update(volume_directory=str(directory), volume_entries=entries,
                              volume_selection='', volume_error='')
        except (OSError, ValueError) as error:
            self.state.volume_error = str(error)

    def parent_volume_directory(self):
        self.state.volume_directory = str(Path(self.state.volume_directory).expanduser().parent)
        self.list_volume_directory()

    def open_selected_volume(self, path=None):
        if self.state.volume_loading:
            return
        if path is not None:
            self.state.volume_selection = path
            self.state.flush()
        task = getattr(self, "_volume_task", None)
        if task is None or task.done():
            self._volume_task = asyncio.create_task(self._load_selected_volume())

    async def _load_selected_volume(self):
        await self.load_volume_selection()

    def set_image_data(self):
        image = vtk.vtkImageData()
        image.SetDimensions(*self.volume.shape[::-1])
        image.SetSpacing(*np.broadcast_to(self.spacing,3))
        image.SetOrigin(*self.origin)
        image.GetPointData().SetScalars(numpy_to_vtk(self.volume.ravel(), deep=False))
        self.mapper.SetInputData(image)
        source=self.volume_source if self.volume_source is not None else self._synthetic_source
        self.sample.GetProperty().SetScalarOpacityUnitDistance(float(np.min(source.spacing)))

    def build_scene(self):
        mapper = vtk.vtkSmartVolumeMapper()
        self.mapper = mapper
        colors = vtk.vtkColorTransferFunction()
        self.colors = colors
        self.transfer = vtk.vtkPiecewiseFunction()
        prop = vtk.vtkVolumeProperty()
        prop.SetColor(colors)
        prop.SetScalarOpacity(self.transfer)
        prop.SetScalarOpacityUnitDistance(float(np.min(self.spacing)))
        prop.SetAmbient(.4)
        prop.SetDiffuse(.6)
        prop.SetInterpolationTypeToLinear()
        prop.ShadeOn()
        self.sample = vtk.vtkVolume()
        self.sample.SetMapper(mapper)
        self.sample.SetProperty(prop)
        self.set_image_data()
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetUseDepthPeeling(True)
        self.renderer.SetUseDepthPeelingForVolumes(True)
        self.renderer.SetMaximumNumberOfPeels(100)
        self.renderer.SetOcclusionRatio(0.)
        self.renderer.SetBackground(.045,.06,.09)
        self.renderer.AddVolume(self.sample)
        # Cylinder's native axis is Y. Rotate its geometry into laboratory Z,
        # then scale along lab X/Y to give precisely the requested semi-axes.
        cylinder = vtk.vtkCylinderSource()
        cylinder.SetRadius(1)
        cylinder.SetHeight(4.5)
        cylinder.SetResolution(64)
        transform = vtk.vtkTransform()
        transform.RotateX(90)
        geometry = vtk.vtkTransformFilter()
        geometry.SetInputConnection(cylinder.GetOutputPort())
        geometry.SetTransform(transform)
        beam_mapper = vtk.vtkPolyDataMapper()
        geometry.Update()
        self.beam_geometry = vtk.vtkPolyData()
        self.beam_geometry.DeepCopy(geometry.GetOutput())
        beam_mapper.SetInputData(self.beam_geometry)
        beam_mapper.SetColorModeToDirectScalars()
        beam_mapper.ScalarVisibilityOn()
        self.beam = vtk.vtkActor()
        self.beam.SetMapper(beam_mapper)
        self.beam.GetProperty().SetColor(.25,.9,1.)
        self.beam.GetProperty().SetOpacity(.4)
        self.beam.GetProperty().LightingOff()
        self.renderer.AddActor(self.beam)
        axes = vtk.vtkAxesActor()
        self.axes = axes
        axes.SetTotalLength(.45,.45,.45)
        axes.AxisLabelsOff()
        axes.SetPosition(-1.3,-1.,-1.3)
        axes.VisibilityOff()
        self.renderer.AddActor(axes)
        self.window = vtk.vtkRenderWindow()
        self.window.SetOffScreenRendering(1)
        self.window.SetAlphaBitPlanes(1)
        self.window.SetMultiSamples(0)
        self.window.SetSize(1000,600)
        self.window.AddRenderer(self.renderer)
        interactor = vtk.vtkRenderWindowInteractor()
        interactor.SetRenderWindow(self.window)
        interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        interactor.Initialize()
        self.interactor = interactor
        self.build_crop_widget()
        self.reset_camera()
        self.renderer.AddObserver(vtk.vtkCommand.StartEvent,self.limit_zoom)
        self.renderer.AddObserver(vtk.vtkCommand.EndEvent,lambda *_: self.schedule_project_save())

    def set_axes_visibility(self, visible):
        visible = visible is True
        if bool(self.axes.GetVisibility()) != visible:
            self.axes.SetVisibility(visible)
            self.view.update()

    def update_beam_colors(self, *_):
        """Light at the -Z source, dark downstream (+Z), independent of camera."""
        points = self.beam_geometry.GetPoints()
        z = np.array([points.GetPoint(i)[2] for i in range(points.GetNumberOfPoints())])
        fraction = (z-z.min()) / max(float(np.ptp(z)), 1e-9)
        source, downstream = np.array([.35, 1., 1.]), np.array([.12, .22, .65])
        colors = np.uint8(255*((1-fraction[:, None])*source + fraction[:, None]*downstream))
        scalars = numpy_to_vtk(colors, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        scalars.SetName('Distance along beam')
        self.beam_geometry.GetPointData().SetScalars(scalars)

    def scene_bounds(self):
        sample = self.sample.GetBounds()
        beam = self.beam.GetBounds()
        return tuple(min(sample[i],beam[i]) if i%2 == 0 else max(sample[i],beam[i])
                     for i in range(6))

    def reset_camera(self, beam_view=False):
        cam = self.renderer.GetActiveCamera()
        cam.SetPosition(*( (0,0,8) if beam_view else (-4,-6,3) ))
        cam.SetFocalPoint(0,0,0)
        cam.SetViewUp(0,1,0)
        self.renderer.ResetCamera(self.sample.GetBounds())
        cam.Zoom(1.05)
        self.zoom_out_limit = 4*self.camera_view_span()
        self._zoom_camera = (cam.GetViewAngle(),cam.GetDistance())
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        if hasattr(self,'view'):
            self.view.update()

    def camera_view_span(self):
        """Vertical extent at the focal plane, in sample coordinates."""
        camera = self.renderer.GetActiveCamera()
        if camera.GetParallelProjection():
            return 2*camera.GetParallelScale()
        return 2*camera.GetDistance()*math.tan(math.radians(camera.GetViewAngle()/2))

    def limit_zoom(self, *_):
        # Wheel zoom changes field of view; right-drag changes camera distance.
        # Constrain both before rendering, retaining the selected viewing direction.
        camera = self.renderer.GetActiveCamera()
        angle,distance = camera.GetViewAngle(),camera.GetDistance()
        if self.camera_view_span() > self.zoom_out_limit:
            if camera.GetParallelProjection():
                camera.SetParallelScale(self.zoom_out_limit/2)
            elif not math.isclose(angle,self._zoom_camera[0],rel_tol=1e-10):
                camera.SetViewAngle(math.degrees(2*math.atan(self.zoom_out_limit/(2*distance))))
            else:
                target = self.zoom_out_limit/(2*math.tan(math.radians(angle/2)))
                focal = np.array(camera.GetFocalPoint())
                direction = (np.array(camera.GetPosition())-focal)/distance
                camera.SetPosition(*(focal+direction*target))
            self.renderer.ResetCameraClippingRange(self.scene_bounds())
        self._zoom_camera = (camera.GetViewAngle(),camera.GetDistance())

    def parameters(self):
        specs = {'beam_x':(-self.beam_limit_um,self.beam_limit_um), 'beam_y':(-self.beam_limit_um,self.beam_limit_um),
                 'radius_x':(10,500), 'radius_y':(10,500),
                 'angle':(-180,180), 'opacity':(.05,1.)}
        result = {}
        for name,(lo,hi) in specs.items():
            try:
                value = float(self.state[name])
            except (TypeError,ValueError):
                return None
            if not math.isfinite(value) or not lo <= value <= hi:
                return None
            result[name] = value/1000 if name in ("beam_x", "beam_y", "radius_x", "radius_y") else value
        return result

    def update_scene(self, **_):
        if self._applying_pose or self.state.volume_loading:
            return
        p = self.parameters()
        if p is None:
            self.state.status = 'Enter a number within the displayed limits.'
            return
        self.state.status = 'Ready'
        matrix = vtk.vtkMatrix4x4()
        rotation = sample_rotation(self.state.rotation_axis,p['angle'])
        for row in range(3):
            for column in range(3):
                matrix.SetElement(row,column,float(rotation[row,column]))
        self.sample.SetUserMatrix(matrix)
        self.beam.SetPosition(p['beam_x'],p['beam_y'],0)
        self.beam.SetScale(p['radius_x'],p['radius_y'],self.beam_length/4.5)
        self.update_beam_colors()
        self.update_crop_widget()
        try:
            low, high = float(self.state.contrast_low), float(self.state.contrast_high)
            if not (math.isfinite(low) and math.isfinite(high) and high > low):
                raise ValueError()
        except (TypeError, ValueError):
            self.state.status = 'Contrast maximum must exceed minimum; both must be finite numbers.'
            return
        self.transfer.RemoveAllPoints()
        scalar = lambda value: low+(high-low)*value/65535
        self.colors.RemoveAllPoints()
        for value,color in [(0,(.05,.08,.12)),(10000,(.35,.45,.60)),(24000,(.80,.65,.38)),(50000,(1.,.92,.72))]:
            self.colors.AddRGBPoint(scalar(value),*color)
        for value, alpha in [(0,0),(9000,0),(18000,.025),(35000,.12),(65535,.4)]:
            self.transfer.AddPoint(scalar(value),alpha*p['opacity'])
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        self.view.update()
        self.schedule_project_save()
        # Radius and opacity do not affect scattering: avoid resending both plots.
        key = (p['beam_x'],p['beam_y'],p['angle'])
        if not self.dragging_beam and not self.dragging_controls and key != getattr(self,'last_signal_key',None):
            self.last_signal_key = key
            source = self.volume_source
            self.signal = scattering(self.signal_volume, source.spacing if source else self._synthetic_source.spacing,
                                     source.origin if source else self._synthetic_source.origin,*key,
                                     intensity_range=self.contrast if source else None,
                                     rotation_axis=self.state.rotation_axis)
            self.update_plots()

    def update_plots(self, **_):
        if not hasattr(self,'signal'):
            return
        q,phi,cake,iq = self.signal
        if not hasattr(self,'curve_figure'):
            common = dict(template='plotly_dark', paper_bgcolor='#101722',
                          plot_bgcolor='#101722', margin=dict(l=58,r=20,t=20,b=48),
                          font=dict(family='sans-serif',size=12), autosize=True,
                          uirevision='preserve-user-zoom')
            self.curve_figure = go.Figure(go.Scatter(mode='lines',line=dict(color='#67deeb',width=2)))
            self.curve_figure.update_layout(**common,xaxis_title='q (invented nm⁻¹)',yaxis_title='Mean I(q) (a.u.)')
            self.cake_figure = go.Figure(go.Heatmap(colorscale='Magma',zmin=-1.6,zmax=1.3,
                colorbar=dict(title='log₁₀ I',thickness=12),
                hovertemplate='q=%{x:.3f}<br>φ=%{y:.0f}°<br>log₁₀ I=%{z:.2f}<extra></extra>'))
            self.cake_figure.update_layout(**common,xaxis_title='q (invented nm⁻¹)',yaxis_title='φ (degrees)')
        # Keep dense arrays as NumPy arrays: Plotly encodes them as typed binary
        # buffers instead of recursively validating/serializing Python lists.
        curve = self.curve_figure.data[0]
        curve.x,curve.y = q,iq
        heat = self.cake_figure.data[0]
        heat.x,heat.y,heat.z = q,phi,np.log10(cake)
        self.curve_figure.layout.yaxis.type = 'log' if self.state.log_iq else 'linear'
        self.curve.update(self.curve_figure)
        self.cake.update(self.cake_figure)

    @staticmethod
    def wrap_angle(value):
        return value if -180 <= value <= 180 else (value+180)%360-180

    def receive_pose(self, values, finished=True, context=None):
        """Apply the latest coordinated controls as one validated scene update."""
        if self.state.volume_loading or (context is not None and context != self.state.sample_context):
            return
        pose = {}
        for field,value in values.items():
            if field not in ('beam_x','beam_y','angle'):
                return
            try:
                value = float(value)
            except (TypeError,ValueError):
                return
            if not math.isfinite(value):
                return
            if field == 'angle':
                value = self.wrap_angle(value)
            elif not -self.beam_limit_um <= value <= self.beam_limit_um:
                return
            pose[field] = value
        self.dragging_controls = not finished
        self._applying_pose = True
        try:
            with self.state:
                for field,value in pose.items():
                    self.state[field] = value
        finally:
            self._applying_pose = False
        self.update_scene()

    def receive_beam_position(self, x, y, finished, shortcut=False, context=None):
        # Browser awaits this RPC before sending another; intermediate positions
        # replace one pending slot in beam.js. Final release always refreshes SAXS.
        if self.state.volume_loading or (context is not None and context != self.state.sample_context):
            return
        if not shortcut:
            return
        self.dragging_beam = not finished
        self.drag_beam(x, y)
        if finished:
            self.update_scene()

    def drag_beam(self, x, y, buttons=1):
        if not (int(buttons)&1):
            return
        width,height = self.window.GetSize()
        points=[]
        for depth in (0,1):
            self.renderer.SetDisplayPoint(float(x)*width,(1-float(y))*height,depth)
            self.renderer.DisplayToWorld()
            world = np.array(self.renderer.GetWorldPoint())
            points.append(world[:3]/world[3])
        direction = points[1]-points[0]
        if abs(direction[2]) < 1e-8:
            self.state.status = 'Use Beam view to position the beam from this camera angle.'
            return
        point = points[0]-points[0][2]/direction[2]*direction
        with self.state:
            self.state.beam_x = round(float(np.clip(point[0],-1.6,1.6))*1000,1)
            self.state.beam_y = round(float(np.clip(point[1],-1.6,1.6))*1000,1)



def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project',type=Path,help='Open a TomoSWAXS project file or directory')
    parser.add_argument('--volume',type=Path,help='OME-Zarr image on the application host')
    parser.add_argument('--import-tiff',type=Path,help='Import TIFF into OME-Zarr, then open it')
    parser.add_argument('--output',type=Path,help='New OME-Zarr import destination')
    parser.add_argument('--import-only',action='store_true',help='Finish after conversion without starting the viewer')
    parser.add_argument('--voxel-size-um',type=float,nargs='+',help='Explicit TIFF voxel spacing: one value or X Y Z, in µm')
    parser.add_argument('--preview-mib',type=float,default=64,help='Maximum loaded voxel array size in MiB (default: 64)')
    parser.add_argument('--data-dir',type=Path,help='Initial directory for the GUI file selector')
    args, remaining = parser.parse_known_args()
    if '-h' in remaining or '--help' in remaining:
        parser.print_help()
    sys.argv[1:] = remaining
    try:
        if not math.isfinite(args.preview_mib) or args.preview_mib < 1:
            raise ValueError('Voxel array size limit must be at least 1 MiB.')
        if args.import_only and not args.import_tiff:
            raise ValueError('--import-only requires --import-tiff.')
        if args.project and (args.volume or args.import_tiff):
            raise ValueError('--project is separate from --volume and --import-tiff.')
        path = args.volume
        if args.import_tiff:
            if path is not None or args.output is None:
                raise ValueError('--import-tiff requires --output and is separate from --volume.')
            path = import_tiff(args.import_tiff,args.output,args.voxel_size_um,
                               progress=lambda text: print(text,flush=True))
            if args.import_only:
                return
        if path and path.suffix.lower() in ('.tif','.tiff'):
            raise ValueError('Import TIFF using --import-tiff FILE --output DESTINATION, or the GUI selector.')
        volume = VolumeSource(path).preview(args.preview_mib) if path else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    app = Demo(volume=volume,data_directory=args.data_dir,preview_mib=args.preview_mib)
    if args.project:
        asyncio.run(app.open_project_path(args.project))
        if app.project is None:
            parser.error(app.state.project_error)
    app.server.start(host='127.0.0.1')


if __name__ == '__main__':
    main()
