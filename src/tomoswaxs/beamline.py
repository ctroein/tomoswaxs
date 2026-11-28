"""Illustrative ForMAX endstation, in millimetres in the viewer's lab frame.

Component dimensions and provenance: docs/beamline-model.md. Geometry stays
separate from sample transforms and can be replaced component by component.
"""
import math
import numpy as np
import vtk


class BeamlineModel:
    def __init__(self, renderer):
        self.parts={};self.labels=[]
        self.renderer=renderer
        steel=(.43,.51,.58);granite=(.29,.33,.37);teal=(.16,.65,.64)
        self.box('table base',(0,-850,0),(620,820,650),granite)
        self.box('table top',(0,-420,0),(800,40,800),steel)
        self.motor_stack()
        self.cylinder('sample marker',(0,0,0),.7,2,teal)
        # A fixed SWAXS arrangement: microscope parked to the side.
        for x in (-900,900):self.box(f'gantry pillar {x}',(x,-250,510),(160,2000,240),granite)
        self.box('gantry crossbar',(0,670,510),(1960,160,240),granite)
        for x in (-900,900):self.box(f'gantry foot {x}',(x,-1220,750),(260,100,1000),steel)
        self.box('microscope carriage',(570,80,490),(340,270,160),steel)
        self.box('tomography camera',(570,40,250),(180,180,300),(.62,.66,.70))
        self.cylinder('microscope objective',(570,40,65),40,100,steel,axis='z')
        # Four panels leave an opening for SAXS and the transmitted beam.
        for x in (-90,90):self.box(f'WAXS side {x}',(x,0,260),(100,280,30),teal)
        for y in (-90,90):self.box(f'WAXS end {y}',(0,y,260),(80,100,30),teal)
        self.shell('nose cone',340,900,45,500,steel)
        self.shell('flight tube',900,2300,500,500,steel)
        self.box('SAXS detector',(0,0,1900),(155,162,35),(.17,.52,.67))
        self.box('SAXS trolley',(0,-310,1900),(330,100,280),steel)
        for x in (-230,230):self.box(f'detector rail {x}',(x,-410,1600),(18,25,1400),steel)
        self.cylinder('beamstop',(0,0,1865),3,10,(.8,.55,.18),axis='z')
        self.box('BCU II support',(0,-730,-720),(380,1000,440),granite)
        self.box('BCU II',(0,0,-720),(260,230,400),steel)
        self.cylinder('BCU exit',(0,0,-420),45,200,steel,axis='z')
        for text,point in [('BCU II',(-210,190,-720)),('Experimental table',(-430,-430,-150)),
                           ('Detector gantry',(650,820,510)),('Tomography microscope',(570,210,140)),
                           ('WAXS detector',(-240,180,260)),('SAXS detector',(160,150,1900)),
                           ('Flight tube (continues)',(450,150,2290))]:
            self.label(text,point,'context' if text in ('WAXS detector','SAXS detector') else 'station')
        for name in ('swaxs_y','swaxs_x','tomo_ry','tomo_xf','tomo_zf'):
            self.label(name,self.parts[name].GetCenter(),'stack',offset=(130,8))
        self.label('Sample',(0,0,0),'stack',offset=(30,25))
        self.label('Motor stack',(0,-60,0),'context',offset=(-110,-20))
        self.station_parts=set(self.parts)
        self.area_parts={'table top','swaxs_y','swaxs_x','tomo_ry','tomo_xf','tomo_zf','sample holder','sample marker',
                         'SAXS detector','beamstop','BCU exit'}
        self.area_parts.update(name for name in self.parts if name.startswith('WAXS '))
        self.station_bounds=self.bounds_for(self.station_parts)
        self.area_bounds=self.bounds_for(self.area_parts)
        self.bounds=self.station_bounds
        self.show(False)

    def motor_stack(self,height=140.):
        """Schematic stack from Mira's drawing; top/sample stays at lab Y=0."""
        before=set(self.parts)
        self.box('swaxs_y',(0,-330,0),(260,140,240),(.43,.36,.63))
        self.box('swaxs_x',(0,-230,0),(245,60,210),(.78,.47,.20))
        self.cylinder('tomo_ry',(0,-140,0),95,120,(.30,.60,.39))
        self.box('tomo_xf',(0,-69,0),(150,22,140),(.72,.28,.28))
        self.box('tomo_zf',(0,-47,0),(140,22,130),(.25,.43,.73))
        self.cylinder('sample holder',(0,-19,0),3,34,(.43,.51,.58))
        transform=vtk.vtkTransform();transform.Scale(height/400,height/400,height/400)
        for name in set(self.parts)-before:self.parts[name].SetUserTransform(transform)

    def actor(self,name,source,color):
        mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(source.GetOutputPort())
        actor=vtk.vtkActor();actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color);actor.GetProperty().SetAmbient(.35)
        actor.GetProperty().SetDiffuse(.65);actor.PickableOff()
        self.parts[name]=actor;self.renderer.AddActor(actor)
        return actor

    def box(self,name,center,size,color):
        source=vtk.vtkCubeSource();source.SetCenter(*center)
        source.SetXLength(size[0]);source.SetYLength(size[1]);source.SetZLength(size[2])
        return self.actor(name,source,color)

    def cylinder(self,name,center,radius,length,color,axis='y'):
        source=vtk.vtkCylinderSource();source.SetRadius(radius);source.SetHeight(length);source.SetResolution(48)
        actor=self.actor(name,source,color)
        if axis=='z':actor.RotateX(90)
        actor.SetPosition(*center)
        return actor

    def shell(self,name,z0,z1,r0,r1,color):
        # Lower half only, with exposed rim: both interior and continuation show.
        points=vtk.vtkPoints();faces=vtk.vtkCellArray();count=49
        for z,r in ((z0,r0),(z1,r1)):
            for angle in np.linspace(math.pi,2*math.pi,count):points.InsertNextPoint(r*math.cos(angle),r*math.sin(angle),z)
        for i in range(count-1):
            faces.InsertNextCell(4)
            for j in (i,i+1,count+i+1,count+i):faces.InsertCellPoint(j)
        mesh=vtk.vtkPolyData();mesh.SetPoints(points);mesh.SetPolys(faces)
        source=vtk.vtkTrivialProducer();source.SetOutput(mesh)
        self.actor(name,source,color)
        for ring in range(2):
            line=vtk.vtkCellArray();line.InsertNextCell(count)
            for i in range(count):line.InsertCellPoint(ring*count+i)
            rim=vtk.vtkPolyData();rim.SetPoints(points);rim.SetLines(line)
            tube=vtk.vtkTubeFilter();tube.SetInputData(rim);tube.SetRadius(7);tube.SetNumberOfSides(8)
            self.actor(f'{name} rim {ring}',tube,(.68,.74,.78))

    def label(self,text,point,scope,offset=(12,8)):
        label=vtk.vtkCaptionActor2D();label.SetCaption(text);label.SetAttachmentPoint(*point)
        label.BorderOff();label.ThreeDimensionalLeaderOff();label.SetPosition(*offset)
        label.GetTextActor().SetTextScaleModeToNone()
        prop=label.GetCaptionTextProperty();prop.SetFontSize(15);prop.BoldOff();prop.ItalicOff();prop.ShadowOff()
        prop.SetColor(.9,.95,1);prop.SetBackgroundColor(.035,.05,.075);prop.SetBackgroundOpacity(.75)
        label.GetProperty().SetColor(.65,.75,.8)
        label.PickableOff();self.renderer.AddViewProp(label);self.labels.append((label,scope))

    def combined_bounds(self):
        return self.bounds_for(self.parts)

    def bounds_for(self,names):
        boxes=np.array([self.parts[name].GetBounds() for name in names]).reshape(-1,3,2)
        return np.column_stack([boxes[:,:,0].min(axis=0),boxes[:,:,1].max(axis=0)]).ravel()

    def show(self,level,labels=True,span=3000,has_sample=False):
        if isinstance(level,bool):level='station' if level else 'sample'
        visible=level!='sample';members=self.area_parts if level=='area' else self.station_parts
        self.bounds=self.area_bounds if level=='area' else self.station_bounds
        for name,actor in self.parts.items():
            show=visible and name in members and (name!='sample marker' or not has_sample)
            actor.SetVisibility(show)
        for actor,scope in self.labels:
            relevant=scope=='stack' if span<650 else scope in ('context',level)
            actor.SetVisibility(visible and labels and relevant)


def beamline_view(context):
    """Migrate the old visibility/camera-preset record to explicit scene levels."""
    if 'level' in context:return context.copy()
    level=('area' if context.get('scope')=='stack' else 'station') if context.get('visible') else 'sample'
    scope='area' if context.get('scope')=='stack' else context.get('scope','sample')
    return dict(level=level,labels=context.get('labels',True),scope=scope)


class BeamlineContext:
    def build_beamline(self):
        self.state.update(beamline_level='sample',beamline_visible=False,beamline_labels=True)
        if self._beamline_model_path is not None:
            from .beamline_mesh import CadBeamlineModel
            self.beamline=CadBeamlineModel(self.renderer,self._beamline_model_path)
        else:
            self.beamline=BeamlineModel(self.renderer)
        self._beamline_was_visible=False;self._beamline_scope='sample'
        self.init_beamline_download()
        self.server.controller.trigger('nim_beamline_level')(self.select_beamline_level)
        self.server.controller.trigger('nim_beamline_camera')(self.beamline_camera)

    def update_beamline(self,**_):
        visible=self.state.beamline_level!='sample'
        enabling=visible and not self._beamline_was_visible
        disabling=not visible and self._beamline_was_visible
        self._beamline_was_visible=visible
        self.state.beamline_visible=visible
        if enabling:
            self._beamline_sample_zoom=self.zoom_out_limit
            self.zoom_out_limit=max(self.zoom_out_limit,16000.)
        if disabling:self.zoom_out_limit=self._beamline_sample_zoom
        self.sync_beamline()
        self.sync_beam_geometry()
        if not self._applying_pose:
            self.reset_clipping_range();self.view.update();self.schedule_project_save()

    def sync_beamline(self,*_):
        self.renderer.SetUseFXAA(self.state.beamline_level!='sample')
        self.beamline.show(self.state.beamline_level,bool(self.state.beamline_labels),
                           self.camera_view_span(),bool(self.state.has_volume))

    def select_beamline_level(self,level):
        if level not in ('sample','area','station') or self.state.volume_loading:return
        if self.request_beamline_model(level,fit_camera=True):return
        self.state.beamline_level=level
        self.update_beamline()
        if level=='sample':
            self.reset_camera()
        else:
            self._beamline_scope=level
            camera=self.renderer.GetActiveCamera();camera.SetParallelProjection(False)
            direction=np.array([-1.3,.8,-1.6])
            direction/=np.linalg.norm(direction)
            centre=np.array(self.beamline.bounds).reshape(3,2).mean(axis=1)
            camera.SetViewAngle(30);camera.SetViewUp(0,1,0);camera.SetFocalPoint(*centre)
            bounds=np.asarray(self.beamline.bounds).reshape(3,2)
            corners=np.array(np.meshgrid(*bounds,indexing='ij')).reshape(3,-1).T-centre
            right=np.cross([0,1,0],direction);right/=np.linalg.norm(right)
            up=np.cross(direction,right)
            tangent=math.tan(math.radians(15))
            depth=corners@direction
            distance=1.1*max(np.max(depth+abs(corners@up)/tangent),
                             np.max(depth+abs(corners@right)/(tangent*self.renderer.GetTiledAspectRatio())))
            camera.SetPosition(*(centre+direction*distance))
            camera.OrthogonalizeViewUp()
            self.zoom_out_limit=max(16000.,self.camera_view_span()*4)
            self._zoom_camera=(camera.GetViewAngle(),camera.GetDistance())
            self.reset_clipping_range();self.sync_camera_angle();self.view.update()
        self.schedule_project_save()

    def beamline_camera(self,preset):
        # Compatibility for existing developer scripts using the old presets.
        self.select_beamline_level({'stack':'area'}.get(preset,preset))
