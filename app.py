"""NIM: browser demo with fabricated volume and scattering data."""
from pathlib import Path
import math
import numpy as np
import plotly.graph_objects as go
import vtk
from vtk.util.numpy_support import numpy_to_vtk
from trame.app import get_server
from trame.ui.html import DivLayout
from trame_client.widgets.core import Template
from trame.widgets import html, vtk as vtk_widgets, plotly, quasar
from synthetic_demo import make_volume, scattering
from project_info import NAME, DESCRIPTION, BUILD, LICENSE_NAME, COPYRIGHT, COLLABORATION


class Demo:
    def __init__(self, server=None):
        self.server = server or get_server(client_type='vue3')
        self.state = self.server.state
        self.state.trame__title = NAME
        self.server.enable_module(dict(serve={'nim-assets': str(Path(__file__).parent/'assets')},
                                       styles=['/nim-assets/app.css'], scripts=['/nim-assets/beam.js']))
        self.volume, self.spacing, self.origin = make_volume()
        self.state.update(beam_x=250., beam_y=0., radius_x=60., radius_y=40.,
                          angle=0., opacity=.55, move_beam=False, view_height=66, plot_width=50,
                          status='Ready', log_iq=False, show_about=False)
        self.dragging_beam = False
        self.server.controller.trigger("nim_beam_position")(self.receive_beam_position)
        self.build_scene()
        self.build_ui()
        self.state.change('beam_x', 'beam_y', 'radius_x', 'radius_y', 'angle', 'opacity')(self.update_scene)
        self.state.change('log_iq')(self.update_plots)
        self.server.controller.on_server_ready.add(self.view.update)
        self.update_scene()

    def build_scene(self):
        image = vtk.vtkImageData()
        image.SetDimensions(*self.volume.shape[::-1])
        image.SetSpacing(*([self.spacing]*3))
        image.SetOrigin(*self.origin)
        image.GetPointData().SetScalars(numpy_to_vtk(self.volume.ravel(), deep=True))
        mapper = vtk.vtkSmartVolumeMapper()
        mapper.SetInputData(image)
        colors = vtk.vtkColorTransferFunction()
        for value, color in [(0,(.05,.08,.12)), (10000,(.35,.45,.60)),
                             (24000,(.80,.65,.38)), (50000,(1.,.92,.72))]:
            colors.AddRGBPoint(value,*color)
        self.transfer = vtk.vtkPiecewiseFunction()
        prop = vtk.vtkVolumeProperty()
        prop.SetColor(colors)
        prop.SetScalarOpacity(self.transfer)
        prop.SetScalarOpacityUnitDistance(self.spacing)
        prop.SetAmbient(.4)
        prop.SetDiffuse(.6)
        prop.SetInterpolationTypeToLinear()
        prop.ShadeOn()
        self.sample = vtk.vtkVolume()
        self.sample.SetMapper(mapper)
        self.sample.SetProperty(prop)
        self.renderer = vtk.vtkRenderer()
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
        axes.SetTotalLength(.45,.45,.45)
        axes.AxisLabelsOff()
        axes.SetPosition(-1.3,-1.,-1.3)
        self.renderer.AddActor(axes)
        self.window = vtk.vtkRenderWindow()
        self.window.SetOffScreenRendering(1)
        self.window.SetSize(1000,600)
        self.window.AddRenderer(self.renderer)
        # Keep the illustrative beam legible through the volume. A transparent
        # overlay uses the same camera and intentionally draws it in front.
        self.renderer.RemoveActor(self.beam)
        self.beam_renderer = vtk.vtkRenderer()
        self.beam_renderer.SetLayer(1)
        self.beam_renderer.SetActiveCamera(self.renderer.GetActiveCamera())
        self.beam_renderer.AddActor(self.beam)
        self.beam_renderer.InteractiveOff()
        self.window.SetNumberOfLayers(2)
        self.window.AddRenderer(self.beam_renderer)
        interactor = vtk.vtkRenderWindowInteractor()
        interactor.SetRenderWindow(self.window)
        interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        interactor.Initialize()
        self.interactor = interactor
        self.reset_camera()
        self.renderer.GetActiveCamera().AddObserver("ModifiedEvent", self.update_beam_colors)

    def update_beam_colors(self, *_):
        """Colour the beam by camera distance, independently of sample rotation."""
        points = self.beam_geometry.GetPoints()
        matrix = self.beam.GetMatrix()
        world = np.array([matrix.MultiplyPoint((*points.GetPoint(i), 1))[:3]
                          for i in range(points.GetNumberOfPoints())])
        camera = np.array(self.renderer.GetActiveCamera().GetPosition())
        distance = np.linalg.norm(world-camera, axis=1)
        fraction = (distance-distance.min()) / max(float(np.ptp(distance)), 1e-9)
        near, far = np.array([.35, 1., 1.]), np.array([.12, .22, .65])
        colors = np.uint8(255*((1-fraction[:, None])*near + fraction[:, None]*far))
        scalars = numpy_to_vtk(colors, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        scalars.SetName('Camera distance')
        self.beam_geometry.GetPointData().SetScalars(scalars)

    def scene_bounds(self):
        sample = self.sample.GetBounds()
        beam = self.beam.GetBounds()
        return tuple(min(sample[i],beam[i]) if i%2 == 0 else max(sample[i],beam[i])
                     for i in range(6))

    def reset_camera(self, beam_view=False):
        cam = self.renderer.GetActiveCamera()
        cam.SetPosition(*( (0,0,8) if beam_view else (4,-6,3) ))
        cam.SetFocalPoint(0,0,0)
        cam.SetViewUp(0,1,0)
        self.renderer.ResetCamera(self.sample.GetBounds())
        cam.Zoom(1.05)
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        if hasattr(self,'view'):
            self.view.update()

    def parameters(self):
        specs = {'beam_x':(-1600,1600), 'beam_y':(-1600,1600),
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
        p = self.parameters()
        if p is None:
            self.state.status = 'Enter a number within the displayed limits.'
            return
        self.state.status = 'Ready'
        self.sample.SetOrientation(0,p['angle'],0)
        self.beam.SetPosition(p['beam_x'],p['beam_y'],0)
        self.beam.SetScale(p['radius_x'],p['radius_y'],1)
        self.update_beam_colors()
        self.transfer.RemoveAllPoints()
        for value, alpha in [(0,0),(9000,0),(18000,.025),(35000,.12),(65535,.4)]:
            self.transfer.AddPoint(value,alpha*p['opacity'])
        self.renderer.ResetCameraClippingRange(self.scene_bounds())
        self.view.update()
        # Radius and opacity do not affect scattering: avoid resending both plots.
        key = (p['beam_x'],p['beam_y'],p['angle'])
        if not self.dragging_beam and key != getattr(self,'last_signal_key',None):
            self.last_signal_key = key
            self.signal = scattering(self.volume,self.spacing,self.origin,*key)
            self.update_plots()

    def update_plots(self, **_):
        if not hasattr(self,'signal'):
            return
        q,phi,cake,iq = self.signal
        common = dict(template='plotly_dark', paper_bgcolor='#101722',
                      plot_bgcolor='#101722', margin=dict(l=58,r=20,t=20,b=48),
                      font=dict(family='sans-serif',size=12), autosize=True,
                      uirevision='preserve-user-zoom')
        curve = go.Figure(go.Scatter(x=q.tolist(),y=iq.tolist(),mode='lines',
                                    line=dict(color='#67deeb',width=2)))
        curve.update_layout(**common, xaxis_title='q (invented nm⁻¹)',
                            yaxis_title='Mean I(q) (a.u.)',
                            yaxis_type='log' if self.state.log_iq else 'linear')
        heat = go.Figure(go.Heatmap(x=q.tolist(),y=phi.tolist(),
                                  z=np.log10(cake).tolist(),colorscale='Magma',
                                  zmin=-1.6,zmax=1.3,
                                  colorbar=dict(title='log₁₀ I',thickness=12),
                                  hovertemplate='q=%{x:.3f}<br>φ=%{y:.0f}°<br>log₁₀ I=%{z:.2f}<extra></extra>'))
        heat.update_layout(**common, xaxis_title='q (invented nm⁻¹)',
                           yaxis_title='φ (degrees)')
        self.curve.update(curve)
        self.cake.update(heat)

    def receive_beam_position(self, x, y, finished):
        # Browser awaits this RPC before sending another; intermediate positions
        # replace one pending slot in beam.js. Final release always refreshes SAXS.
        self.dragging_beam = not finished
        self.drag_beam(x, y)
        if finished:
            self.update_scene()

    def drag_beam(self, x, y, buttons=1):
        if not self.state.move_beam or not (int(buttons)&1):
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

    def build_ui(self):
        with DivLayout(self.server) as layout:
            with html.Div(style='height:100dvh;display:flex;flex-direction:column;min-width:720px'):
                with html.Div(style='padding:10px 16px;display:flex;justify-content:space-between;align-items:center;background:#101722'):
                    html.Strong('NIM / µCT + SAXS',style='font-size:18px')
                    with html.Div(style='display:flex;gap:14px;align-items:center'):
                        html.Span('SYNTHETIC DEMO · fabricated specimen and scattering',style='font-size:12px;color:#e8bc75')
                        html.Button('About', click='show_about = true')
                with html.Div(classes='controls'):
                    for name,label,step,lo,hi in [('beam_x','Beam X (µm)',50,-1600,1600),('beam_y','Beam Y (µm)',50,-1600,1600),('radius_x','Radius X (µm)',10,10,500),('radius_y','Radius Y (µm)',10,10,500),('angle','Sample angle (°)',5,-180,180)]:
                        with html.Label():
                            html.Span(label+' ')
                            html.Input(type='number',v_model=(name,),step=step,min=lo,max=hi,title=f'{label}: {lo} to {hi}',aria_label=label)
                    with html.Label():
                        html.Span('Opacity ')
                        html.Input(type='range',v_model=('opacity',),min=.05,max=1,step=.05,style='width:90px',aria_label='Volume opacity')
                    with html.Label():
                        html.Input(type='checkbox',v_model=('move_beam',),aria_label='Move beam')
                        html.Span(' Move beam')
                    html.Button('Reset camera',click=self.reset_camera)
                    html.Button('Beam view',click=lambda: self.reset_camera(True))
                with quasar.QSplitter(v_model=('view_height',), horizontal=True,
                                      limits=('[35, 78]',), before_class='split-panel',
                                      after_class='split-panel', separator_class='nim-divider',
                                      separator_style='height:8px',
                                      style='flex:1;min-height:0;width:100%'):
                    with Template(raw_attrs=['#before']):
                        with html.Div(classes='panel-title'):
                            html.Span('µCT VOLUME · beam along Z · sample rotates about Y')
                            html.Span("{{ move_beam ? 'Drag beam · SAXS updates on release' : 'Drag to orbit · scroll to zoom' }}")
                        with html.Div(style='flex:1;min-height:0;position:relative'):
                            self.view = vtk_widgets.VtkRemoteView(self.window,interactive_ratio=1,interactive_quality=75,still_quality=95,style='width:100%;height:100%')
                            html.Div(v_if=('move_beam',),id='beam-drag-overlay',
                                     style='position:absolute;inset:0;z-index:5;cursor:crosshair;touch-action:none')
                    with Template(raw_attrs=['#separator']):
                        html.Div(classes='divider-grip horizontal', title='Drag to resize volume and SAXS panels')
                    with Template(raw_attrs=['#after']):
                        with quasar.QSplitter(v_model=('plot_width',), limits=('[25, 75]',),
                                              before_class='split-panel', after_class='split-panel',
                                              separator_class='nim-divider', separator_style='width:8px',
                                              style='height:100%;width:100%;min-height:0'):
                            with Template(raw_attrs=['#before']):
                                with html.Div(classes='panel-title'):
                                    html.Span('SAXS 1D · full-azimuth mean')
                                    with html.Label():
                                        html.Input(type='checkbox',v_model=('log_iq',),aria_label='Log intensity')
                                        html.Span(' Log I')
                                self.curve = plotly.Figure(classes='plot',style='width:100%;height:100%',display_logo=False,responsive=True)
                            with Template(raw_attrs=['#separator']):
                                html.Div(classes='divider-grip vertical', title='Drag to resize SAXS plots')
                            with Template(raw_attrs=['#after']):
                                with html.Div(classes='panel-title'):
                                    html.Span('SAXS CAKE · I(q, φ)')
                                    html.Span('Fixed log colour scale')
                                self.cake = plotly.Figure(classes='plot',style='width:100%;height:100%',display_logo=False,responsive=True)
                with html.Div(style='padding:6px 16px;background:#101722;font-size:11px;color:#99afc7;display:flex;justify-content:space-between'):
                    html.Span('Beam: light cyan near / blue far · radii change geometry only')
                    html.Span('{{ status }}')
                with quasar.QDialog(v_model=('show_about',)):
                    with quasar.QCard(dark=True, classes='about-card', raw_attrs=['role="dialog"', 'aria-modal="true"', 'aria-labelledby="about-title"']):
                        with quasar.QCardSection():
                            html.H2(NAME, id='about-title')
                            html.P(DESCRIPTION)
                            html.P(BUILD, classes='about-muted')
                            html.P(COLLABORATION)
                            html.P('The current demo uses a fabricated specimen and synthetic scattering. It is not a scientific scattering simulation.')
                            html.H3('Licence')
                            html.P(LICENSE_NAME)
                            if COPYRIGHT:
                                html.P(COPYRIGHT, classes='about-muted')
                            licence_file = Path(__file__).with_name('LICENSE')
                            if licence_file.exists():
                                with html.Details():
                                    html.Summary('Full licence text')
                                    html.Pre(licence_file.read_text(), classes='licence-text')
                            html.H3('Built with')
                            with html.P(classes='about-links'):
                                for label,url in [('Trame','https://kitware.github.io/trame/'),
                                                  ('VTK','https://vtk.org/'),
                                                  ('Quasar','https://quasar.dev/'),
                                                  ('Plotly','https://plotly.com/python/'),
                                                  ('NumPy','https://numpy.org/')]:
                                    html.A(label, href=url, target='_blank', rel='noopener noreferrer')
                            html.P('Dependencies retain their own licences.', classes='about-muted')
                        with quasar.QCardActions(align='right'):
                            html.Button('Close', click='show_about = false')
        self.layout = layout


if __name__ == '__main__':
    app = Demo()
    app.server.start(host='127.0.0.1')
