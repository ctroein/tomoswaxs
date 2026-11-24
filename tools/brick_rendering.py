"""Isolated mixed-resolution rendering experiment; writes results outside the repo.

PYTHONPATH=src python tools/brick_rendering.py IMAGE.ome.zarr --output DIRECTORY
"""
import argparse
from dataclasses import dataclass, replace
from html import escape
import json
from pathlib import Path
import time

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

from tomoswaxs.app import Demo
from tomoswaxs.volumes import VolumeSource
from tomoswaxs.volume_cache import DecodedChunkCache


def partition_boxes(shape, core):
    """Six disjoint slabs and a centre, XYZ cell indices with exclusive ends."""
    x,y,z=shape
    (a,b),(c,d),(e,f)=core
    if not all(0<lo<hi<n for (lo,hi),n in zip(core,shape)):
        raise ValueError('The fine region must be strictly inside the outer region.')
    return [((0,a),(0,y),(0,z)),((b,x),(0,y),(0,z)),
            ((a,b),(0,c),(0,z)),((a,b),(d,y),(0,z)),
            ((a,b),(c,d),(0,e)),((a,b),(c,d),(f,z)),core]


@dataclass
class Brick:
    values: np.ndarray
    spacing: np.ndarray
    edge: np.ndarray
    grid_origin: np.ndarray | None = None

    def image(self, cells=True):
        image=vtk.vtkImageData()
        image.SetDimensions(*(np.array(self.values.shape[::-1])+(1 if cells else 0)))
        image.SetSpacing(*self.spacing)
        image.SetOrigin(*(self.edge if cells else self.edge+self.spacing/2))
        if self.grid_origin is not None:
            # Common lattice extents make touching faces bit-identical. Merely
            # checking them with a tolerance leaves tiny overlaps that confuse
            # VTK's block sorter after independent origin computations.
            offset=np.rint((self.edge-self.grid_origin)/self.spacing).astype(int)
            image.SetExtent(*[int(v) for a,n in zip(offset,self.values.shape[::-1])
                              for v in (a,a+n if cells else a+n-1)])
            image.SetOrigin(*(self.grid_origin if cells else self.grid_origin+self.spacing/2))
        scalars=numpy_to_vtk(self.values.ravel(),deep=False)
        scalars.SetName('intensity')
        (image.GetCellData() if cells else image.GetPointData()).SetScalars(scalars)
        return image


def physical_crop(source, level, box):
    """Require nested cell edges; do not silently invent an NGFF registration."""
    spacing,origin=source.geometry(source.images[level])
    faces=origin[:,None]-spacing[:,None]/2+np.array(box)*spacing[:,None]
    indices=(faces-source.origin[:,None]+source.spacing[:,None]/2)/source.spacing[:,None]
    rounded=np.rint(indices)
    if not np.allclose(indices,rounded,rtol=0,atol=1e-5):
        raise ValueError('This prototype requires pyramid levels with nested voxel edges.')
    return source.crop_bounds(rounded.astype(int).tolist()),faces


def load_brick(source, grid_level, box, level, cache, contrast, limit):
    crop,faces=physical_crop(source,grid_level,box)
    preview=source.preview(limit,crop=crop,level=level,cache=cache,contrast=contrast)
    edge=preview.origin-preview.spacing/2
    high=edge+np.array(preview.values.shape[::-1])*preview.spacing
    if not np.allclose(np.column_stack([edge,high]),faces,rtol=0,atol=1e-8):
        raise ValueError('Requested levels do not share the selected physical boundaries.')
    grid_spacing,grid_origin=source.geometry(source.images[grid_level])
    return Brick(preview.values,preview.spacing,faces[:,0],grid_origin-grid_spacing/2)


def mapper(image, cells=True):
    result=vtk.vtkSmartVolumeMapper()
    result.SetInputData(image)
    if cells:result.SetScalarModeToUseCellData()
    return result


def brick_order(eye, low, high):
    """Back-to-front BSP traversal for partition_boxes' fixed seven regions."""
    def visit(axis):
        if axis==3:return [6]
        middle=visit(axis+1)
        positive=([2*axis+1]+middle if eye[axis]<high[axis] else middle+[2*axis+1])
        return positive+[2*axis] if eye[axis]<low[axis] else [2*axis]+positive
    return visit(0)


class Scene:
    def __init__(self, app, mode, bricks, cells=True):
        self.app,self.mode,self.bricks=app,mode,list(bricks)
        self.cells=cells
        self.images=[b.image(cells) for b in bricks]
        self.actors=[];self.mappers=[]
        if mode=='unified':
            m=vtk.vtkGPUVolumeRayCastMapper()
            if cells:m.SetScalarModeToUseCellData()
            root=vtk.vtkMultiVolume();root.SetMapper(m)
            self.subvolumes=[]
            for i,image in enumerate(self.images):
                m.SetInputDataObject(i,image)
                actor=vtk.vtkVolume();actor.SetProperty(app.sample.GetProperty())
                actor.SetUserMatrix(app.sample.GetMatrix())
                root.SetVolume(actor,i);self.subvolumes.append(actor)
            self.actors=[root];self.mappers=[m]
        elif mode=='multiblock':
            self.blocks=vtk.vtkMultiBlockDataSet()
            for i,image in enumerate(self.images):self.blocks.SetBlock(i,image)
            m=vtk.vtkMultiBlockVolumeMapper()
            m.SetInputDataObject(self.blocks)
            if cells:m.SetScalarModeToUseCellData()
            self.add(m)
        else:
            for image in self.images:self.add(mapper(image,cells))
        self.input_actors=list(self.actors)

    def add(self,m):
        actor=vtk.vtkVolume();actor.SetMapper(m)
        actor.SetProperty(self.app.sample.GetProperty())
        actor.SetUserMatrix(self.app.sample.GetMatrix())
        self.mappers.append(m);self.actors.append(actor)

    def activate(self):
        for actor in list(self.app.renderer.GetVolumes()):self.app.renderer.RemoveVolume(actor)
        for actor in self.actors:self.app.renderer.AddVolume(actor)

    def replace(self,index):
        # Identical voxel values in a fresh buffer: measure replacement cost,
        # without image differences or disk IO obscuring the render comparison.
        self.bricks[index]=replace(self.bricks[index],values=self.bricks[index].values.copy())
        image=self.bricks[index].image(self.cells)
        self.images[index]=image
        if self.mode=='multiblock':self.blocks.SetBlock(index,image)
        elif self.mode=='unified':self.mappers[0].SetInputDataObject(index,image)
        else:self.mappers[index].SetInputData(image)

    def render(self):
        t=time.perf_counter()
        if self.mode=='persistent' and len(self.bricks)==7:
            # Keep textures resident while sorting this explicit BSP partition.
            matrix=np.array([[self.input_actors[0].GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
            eye=(np.linalg.inv(matrix) @ np.r_[self.app.renderer.GetActiveCamera().GetPosition(),1.])[:3]
            core=self.bricks[6]
            order=brick_order(eye,core.edge,core.edge+np.array(core.values.shape[::-1])*core.spacing)
            ordered=[self.input_actors[i] for i in order]
            if ordered!=self.actors:
                for actor in self.actors:self.app.renderer.RemoveVolume(actor)
                self.actors=ordered
                for actor in self.actors:self.app.renderer.AddVolume(actor)
        self.app.window.Render();self.app.window.WaitForCompletion()
        return time.perf_counter()-t

    def pixels(self):
        capture=vtk.vtkWindowToImageFilter();capture.SetInput(self.app.window)
        capture.ReadFrontBufferOff();capture.ShouldRerenderOff();capture.Update()
        image=capture.GetOutput()
        return np.flipud(vtk_to_numpy(image.GetPointData().GetScalars()).reshape(image.GetDimensions()[1],image.GetDimensions()[0],-1)).copy()

    def save(self,path):
        capture=vtk.vtkWindowToImageFilter();capture.SetInput(self.app.window)
        capture.ReadFrontBufferOff();capture.ShouldRerenderOff();capture.Update()
        writer=vtk.vtkPNGWriter();writer.SetFileName(str(path));writer.SetInputConnection(capture.GetOutputPort());writer.Write()


def difference(reference, candidate):
    delta=np.abs(reference.astype(float)-candidate.astype(float))
    foreground=(reference.max(axis=2)>40)|(candidate.max(axis=2)>40)
    return dict(mean_absolute_rgb=float(delta.mean()),
                foreground_mean_absolute_rgb=float(delta[foreground].mean()) if foreground.any() else 0.,
                fraction_pixels_over_10=float((delta.max(axis=2)>10).mean()))


def measure(scene, camera, output, name, frames):
    before=len(vtk.vtkOutputWindow.GetInstance().GetOutput())
    scene.activate()
    first=scene.render()
    scene.render()  # Settle mapper adaptation before measuring orbiting.
    scene.save(output/(name+'.png'))
    saved=vtk.vtkCamera();saved.DeepCopy(camera)
    orbit=[]
    for _ in range(frames):
        camera.Azimuth(3);orbit.append(scene.render())
    camera.DeepCopy(saved)
    updates=[]
    for index in ([0,-1] if len(scene.bricks)>1 else [0]):
        times=[]
        for _ in range(3):
            scene.replace(index if index>=0 else len(scene.bricks)-1)
            times.append(scene.render())
        updates.append(dict(brick=index,array_mib=scene.bricks[index].values.nbytes/2**20,seconds=times))
    print(name,'first',round(first,3),'orbit median',round(float(np.median(orbit)),3),flush=True)
    return dict(first_seconds=first,orbit_seconds=orbit,
                orbit_median_seconds=float(np.median(orbit)),updates=updates,
                array_mib=sum(b.values.nbytes for b in scene.bricks)/2**20,
                vtk_messages=vtk.vtkOutputWindow.GetInstance().GetOutput()[before:])


def correctness(app, output):
    """Same-level splitting must not materially alter the optical integral."""
    shape=(64,64,64);core=((16,48),)*3;boxes=partition_boxes(shape,core)
    values=np.ones(shape,dtype=np.float32)
    spacing=np.full(3,.02);edge=np.full(3,-.64)
    whole=Brick(values,spacing,edge)
    bricks=[Brick(np.ascontiguousarray(values[tuple(slice(a,b) for a,b in box[::-1])]),spacing,
                  edge+np.array([a for a,b in box])*spacing) for box in boxes]
    prop=app.sample.GetProperty();prop.ShadeOff();prop.SetScalarOpacityUnitDistance(.02)
    app.colors.RemoveAllPoints();app.colors.AddRGBPoint(0,.8,.7,.5);app.colors.AddRGBPoint(2,.8,.7,.5)
    scenes={name:Scene(app,mode,items) for name,mode,items in
            [('whole','single',[whole]),('multiblock','multiblock',bricks),('persistent','persistent',bricks),('unified','unified',bricks)]}
    camera=app.renderer.GetActiveCamera();results=[]
    for beam in (False,True):
        app.beam.SetVisibility(beam)
        for opacity in (.005,1.):
            app.transfer.RemoveAllPoints();app.transfer.AddPoint(0,opacity);app.transfer.AddPoint(2,opacity)
            for parallel in (False,True):
                camera.SetParallelProjection(parallel)
                for angle in (0,35,80):
                    camera.SetPosition(0,0,4);camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,1,0)
                    camera.SetParallelScale(1.);camera.Azimuth(angle)
                    app.renderer.ResetCameraClippingRange()
                    images={};messages={}
                    for name,scene in scenes.items():
                        before=len(vtk.vtkOutputWindow.GetInstance().GetOutput())
                        scene.activate();scene.render();scene.render();images[name]=scene.pixels()
                        messages[name]=vtk.vtkOutputWindow.GetInstance().GetOutput()[before:]
                        if not parallel and angle==35:scene.save(output/f'check-beam-{beam}-{opacity}-{name}.png')
                    results.append(dict(beam=beam,opacity=opacity,parallel=parallel,angle=angle,messages=messages,
                        **{name:difference(images['whole'],im) for name,im in images.items() if name!='whole'}))
    return results


def write_html(report, output):
    sections=[]
    labels={'current':'Current Auto detail renderer','multiblock':'VTK multiblock','persistent':'Persistent sorted bricks'}
    for beam in ('False','True'):
        rows=[];pictures=[]
        for name,label in labels.items():
            m=report['metrics'][beam][name]
            updates=', '.join(f"{u['array_mib']:.1f} MiB: {np.median(u['seconds'])*1000:.0f} ms" for u in m['updates'])
            rows.append(f"<tr><td>{label}</td><td>{m['array_mib']:.1f}</td><td>{m['orbit_median_seconds']*1000:.0f}</td><td>{updates}</td></tr>")
            pictures.append(f'<figure><img src="beam-{beam}-{name}.png" alt="{label}"><figcaption>{label}</figcaption></figure>')
        sections.append(f"<h2>Beam {'shown' if beam=='True' else 'hidden'}</h2><table><tr><th>Method</th><th>Voxel arrays (MiB)</th><th>Orbit frame (ms, median)</th><th>Frame after replacement (median)</th></tr>{''.join(rows)}</table><div class='pictures'>{''.join(pictures)}</div>")
    checks=''.join(f'<figure><img src="check-beam-True-0.005-{name}.png" alt="Uniform density: {label}"><figcaption>{label}</figcaption></figure>'
                   for name,label in [('whole','Single volume'),('multiblock','VTK multiblock'),('persistent','Persistent sorted bricks')])
    (output/'comparison.html').write_text('''<!doctype html><meta charset="utf-8"><title>Brick rendering prototype comparison</title>
<style>body{font:16px system-ui;margin:2rem;background:#f4f6f8;color:#18222e}table{border-collapse:collapse}th,td{padding:.5rem 1rem;text-align:left;border-bottom:1px solid #ccd3da}.pictures{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}figure{margin:1rem 0}img{width:100%}figcaption{padding:.4rem}pre{white-space:pre-wrap}@media(max-width:800px){.pictures{grid-template-columns:1fr}}</style>
<h1>Brick rendering prototype</h1><p>Local off-screen GPU measurements. The mixed view keeps coarse context and renders a finer central box. These prototypes fail the transparent-beam correctness test; their timing results do not establish an application upgrade.</p>'''
        +f'<p>Source: {escape(report["source"])}</p><pre>{escape(report["capabilities"])}</pre>'
        +''.join(sections)+f'<h2>Uniform-density check with beam</h2><p>The three images should agree. Visible internal boundaries and opacity changes are rendering errors.</p><div class="pictures">{checks}</div>'
        +'<p>The unified seven-input ray caster encountered shader errors (texture-sampler limit); its performance is excluded. Full diagnostics and all view/projection checks are in <a href="results.json">results.json</a>.</p>')


def run(args):
    output=Path(args.output).expanduser().resolve()
    repo=Path(__file__).resolve().parents[1]
    if output.is_relative_to(repo):raise ValueError('Choose an output directory outside the repository.')
    output.mkdir(parents=True,exist_ok=True)
    if not 0<args.fraction<1 or args.frames<1 or min(args.width,args.height)<64:
        raise ValueError('Choose a fraction between 0 and 1, positive frame count and image dimensions of at least 64.')
    source=VolumeSource(args.source)
    if not 0<=args.fine_level<args.context_level<len(source.images):raise ValueError('Choose fine level < context level.')
    shape=np.array(source.images[args.context_level].data.shape[::-1])
    lo=np.maximum(1,np.floor(shape*(1-args.fraction)/2).astype(int));hi=shape-lo
    core=tuple(zip(map(int,lo),map(int,hi)));boxes=partition_boxes(shape,core)
    outer=tuple((0,int(n)) for n in shape)
    crop,_=physical_crop(source,args.context_level,outer)
    cache=DecodedChunkCache();cache.resize(min(256,args.limit*2)*2**20)
    t=time.perf_counter();preview=source.preview(args.limit,crop=crop)
    loading=dict(initial_setup_seconds=time.perf_counter()-t)
    app=Demo(volume=preview,preview_mib=args.limit,render_device='system')
    app.state.rotation_axis='z';app.update_scene()
    app.window.SetSize(args.width,args.height)
    app.beam.SetVisibility(True)
    app.axes.SetVisibility(False)
    vtk.vtkOutputWindow.SetInstance(vtk.vtkStringOutputWindow())
    try:
        # Store exact production property/camera settings before the controlled test.
        prop=vtk.vtkVolumeProperty();prop.DeepCopy(app.sample.GetProperty())
        colors=vtk.vtkColorTransferFunction();colors.DeepCopy(app.colors)
        transfer=vtk.vtkPiecewiseFunction();transfer.DeepCopy(app.transfer)
        checks=correctness(app,output)
        app.colors.DeepCopy(colors);app.transfer.DeepCopy(transfer)
        app.sample.GetProperty().DeepCopy(prop)
        camera=app.renderer.GetActiveCamera();camera.SetParallelProjection(False)
        camera.SetPosition(-4,-6,3);camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,1,0)
        app.renderer.RemoveAllViewProps();app.renderer.AddVolume(app.sample);app.renderer.AddActor(app.beam)
        app.renderer.ResetCamera(app.visible_crop_bounds());camera.Zoom(1.8)
        app.state.detail_enabled=True
        app.detail_refresh()
        plan=app._detail_plan
        auto_plan=dict(crop=plan['crop'],level=plan['request_level'],budget=plan['budget'])
        app.reset_auto_detail()
        t=time.perf_counter()
        current=source.preview(plan['budget'],crop=plan['crop'],level=plan['request_level'],
                               cache=cache,contrast=preview.contrast)
        loading['current_auto_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        mixed=[load_brick(source,args.context_level,box,args.fine_level if i==6 else args.context_level,
                          cache,preview.contrast,args.limit) for i,box in enumerate(boxes)]
        loading['mixed_seconds']=time.perf_counter()-t
        if sum(b.values.nbytes for b in mixed)>args.limit*2**20:raise ValueError('Mixed bricks exceed the requested combined array limit.')
        baseline=Brick(current.values,current.spacing,current.origin-current.spacing/2)
        scenes={'current':Scene(app,'single',[baseline],cells=False),
                'cell-reference':Scene(app,'single',[baseline]),
                'multiblock':Scene(app,'multiblock',mixed),
                'persistent':Scene(app,'persistent',mixed),
                'unified':Scene(app,'unified',mixed)}
        unified_errors=any('ERROR' in case['messages']['unified'] for case in checks)
        metrics={}
        for beam in (False,True):
            app.beam.SetVisibility(beam)
            metrics[str(beam)]={}
            for name,scene in scenes.items():
                if name=='unified' and unified_errors:
                    metrics[str(beam)][name]=dict(invalid='Shader errors during correctness checks; performance excluded.')
                else:
                    metrics[str(beam)][name]=measure(scene,camera,output,f'beam-{beam}-{name}',args.frames)
        order_difference={}
        for beam in (False,True):
            app.beam.SetVisibility(beam)
            persistent=scenes['persistent'];persistent.activate();persistent.render();reference=persistent.pixels()
            persistent.actors.reverse();persistent.activate();persistent.render()
            order_difference[str(beam)]=difference(reference,persistent.pixels())
            persistent.save(output/f'persistent-reversed-beam-{beam}.png')
            persistent.actors.reverse()
        capabilities='\n'.join(line for line in app.window.ReportCapabilities().splitlines()
                                if any(s in line.lower() for s in ['renderer string','version string']))
        report=dict(source=str(source.path),fine_level=args.fine_level,context_level=args.context_level,
                    baseline_level=current.level,current_auto_plan=auto_plan,limit_mib=args.limit,core_coarse_indices=core,
                    size=[args.width,args.height],capabilities=capabilities,loading=loading,
                    correctness=checks,metrics=metrics,persistent_order_difference=order_difference,
                    messages=vtk.vtkOutputWindow.GetInstance().GetOutput())
        report['voxel_spacing_um']={name:(spacing*1000).tolist() for name,spacing in
                                   [('current',current.spacing),('fine',source.geometry(source.images[args.fine_level])[0]),
                                    ('context',source.geometry(source.images[args.context_level])[0])]}
        (output/'results.json').write_text(json.dumps(report,indent=2,default=lambda v:int(v) if isinstance(v,np.integer) else v))
        write_html(report,output)
        print('Saved',output/'results.json',flush=True)
        if report['messages']:print('VTK diagnostics recorded in results.json:',len(report['messages']),'characters',flush=True)
    finally:app.window.Finalize()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('--output',required=True)
    parser.add_argument('--fine-level',type=int,default=2);parser.add_argument('--context-level',type=int,default=3)
    parser.add_argument('--fraction',type=float,default=.4);parser.add_argument('--limit',type=float,default=128)
    parser.add_argument('--width',type=int,default=960);parser.add_argument('--height',type=int,default=640)
    parser.add_argument('--frames',type=int,default=12)
    run(parser.parse_args())
