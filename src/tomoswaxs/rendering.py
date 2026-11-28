"""Select a working off-screen renderer using isolated, bounded probes."""
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time


LOG=logging.getLogger(__name__)
MARKER='TOMOSWAXS_RENDER_PROBE '
OVERRIDES=('VTK_DEFAULT_OPENGL_WINDOW','VTK_DEFAULT_EGL_DEVICE_INDEX',
           '__NV_PRIME_RENDER_OFFLOAD','__NV_PRIME_RENDER_OFFLOAD_PROVIDER',
           '__GLX_VENDOR_LIBRARY_NAME','DRI_PRIME','LIBGL_ALWAYS_SOFTWARE',
           'MESA_LOADER_DRIVER_OVERRIDE','GALLIUM_DRIVER',
           'CUDA_VISIBLE_DEVICES','NVIDIA_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES',
           'HIP_VISIBLE_DEVICES','GPU_DEVICE_ORDINAL','SLURM_JOB_GPUS','SLURM_STEP_GPUS')


def reinitialise_graphics(window):
    """Rebuild window, framebuffer, mapper and shader resources from CPU data.

    Run on the rendering thread. Keep the VTK scene and OpenGL context; this is
    intended for lost GPU contents, rather than a destroyed graphics context.
    """
    import vtk
    errors=[]
    @vtk.calldata_type(vtk.VTK_STRING)
    def error(_obj,_event,message):errors.append(message or 'VTK graphics error.')
    objects=[window]
    for renderer in window.GetRenderers():
        objects.append(renderer)
        for prop in renderer.GetViewProps():
            if hasattr(prop,'GetMapper') and prop.GetMapper() is not None:objects.append(prop.GetMapper())
    observers=[(obj,obj.AddObserver(vtk.vtkCommand.ErrorEvent,error)) for obj in objects]
    try:
        window.Initialize()
        window.MakeCurrent()
        window.ReleaseGraphicsResources(window)
        window.OpenGLInit()
        window.Render()
        window.WaitForCompletion()
        if errors:raise RuntimeError('\n'.join(errors))
    finally:
        for obj,tag in observers:obj.RemoveObserver(tag)


def new_window(device):
    import vtk
    if device=='system':return vtk.vtkRenderWindow()
    if device.startswith('egl:') and device[4:].isdigit():
        window=vtk.vtkEGLRenderWindow();window.SetDeviceIndex(int(device[4:]))
        return window
    raise ValueError('Render device must be auto, system or egl:N (a VTK EGL device index).')


def device_option(value):
    """Validate the command-line spelling without initializing graphics."""
    if value in ('auto','system') or (value.startswith('egl:') and value[4:].isdigit()):return value
    raise ValueError('Render device must be auto, system or egl:N (a VTK EGL device index).')


def renderer_name(window):
    for line in window.ReportCapabilities().splitlines():
        if line.lower().startswith('opengl renderer string:'):return line.split(':',1)[1].strip()
    return 'Unknown OpenGL renderer'


def probe(device, quick=False):
    """Executed only in a child process: a driver crash cannot kill the app."""
    import numpy as np
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk
    errors=vtk.vtkStringOutputWindow();vtk.vtkOutputWindow.SetInstance(errors)
    if device=='devices':
        return dict(devices=vtk.vtkEGLRenderWindow().GetNumberOfDevices()) if hasattr(vtk,'vtkEGLRenderWindow') else dict(devices=0)
    window=new_window(device);window.SetOffScreenRendering(1);window.SetSize(480,360)
    window.SetMultiSamples(0);window.SetAlphaBitPlanes(1)
    renderer=vtk.vtkRenderer();window.AddRenderer(renderer)
    try:
        window.Render();window.WaitForCompletion()
        name=renderer_name(window)
        software=any(s in name.lower() for s in ('llvmpipe','softpipe','software rasterizer','swrast','openswr'))
        version=next((line for line in window.ReportCapabilities().splitlines() if line.lower().startswith('opengl version string:')),'')
        result=dict(device=device,renderer=name,version=version,backend=window.GetClassName(),software=software)
        if quick or software:return result
        # Fixed sampling makes device comparisons independent of mapper adaptation.
        z,y,x=np.indices((96,96,96),dtype=np.float32)
        values=np.ascontiguousarray(65535*np.exp(-((x-48)**2+(y-48)**2+(z-48)**2)/650),dtype=np.float32)
        image=vtk.vtkImageData();image.SetDimensions(96,96,96);image.SetOrigin(-48,-48,-48)
        image.GetPointData().SetScalars(numpy_to_vtk(values.ravel(),deep=False))
        mapper=vtk.vtkGPUVolumeRayCastMapper();mapper.SetInputData(image)
        mapper.SetAutoAdjustSampleDistances(False);mapper.SetSampleDistance(.7)
        prop=vtk.vtkVolumeProperty();prop.ShadeOn();prop.SetInterpolationTypeToLinear()
        color=vtk.vtkColorTransferFunction();color.AddRGBPoint(0,.05,.08,.12);color.AddRGBPoint(65535,1.,.92,.72)
        opacity=vtk.vtkPiecewiseFunction();opacity.AddPoint(0,0);opacity.AddPoint(18000,.025);opacity.AddPoint(65535,.4)
        prop.SetColor(color);prop.SetScalarOpacity(opacity);prop.SetScalarOpacityUnitDistance(1.)
        volume=vtk.vtkVolume();volume.SetMapper(mapper);volume.SetProperty(prop);renderer.AddVolume(volume)
        cylinder=vtk.vtkCylinderSource();cylinder.SetRadius(2);cylinder.SetHeight(180);cylinder.SetResolution(24)
        beam_mapper=vtk.vtkPolyDataMapper();beam_mapper.SetInputConnection(cylinder.GetOutputPort())
        beam=vtk.vtkActor();beam.SetMapper(beam_mapper);beam.RotateX(90)
        beam.GetProperty().SetOpacity(.4);beam.GetProperty().SetColor(.2,.9,1);renderer.AddActor(beam)
        renderer.SetUseDepthPeeling(True);renderer.SetUseDepthPeelingForVolumes(True)
        renderer.SetMaximumNumberOfPeels(100);renderer.SetOcclusionRatio(0.)
        camera=renderer.GetActiveCamera();camera.SetPosition(140,160,140);camera.SetViewUp(0,1,0)
        renderer.ResetCamera()
        for _ in range(4):window.Render();window.WaitForCompletion()
        if not mapper.IsRenderSupported(window,prop):raise RuntimeError('GPU volume rendering is unsupported.')
        times=[]
        for _ in range(7):
            camera.Azimuth(4)
            start=time.perf_counter();window.Render();window.WaitForCompletion()
            times.append(time.perf_counter()-start)
        result['seconds']=statistics.median(times)
        # Validate the volume alone, so a beam cannot disguise a failed volume draw.
        beam.VisibilityOff();window.Render();window.WaitForCompletion()
        capture=vtk.vtkWindowToImageFilter();capture.SetInput(window);capture.ShouldRerenderOff();capture.Update()
        from vtk.util.numpy_support import vtk_to_numpy
        if np.count_nonzero(vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).max(axis=1)>40)<1000:
            raise RuntimeError('Volume rendering produced an empty image.')
        if 'ERROR' in errors.GetOutput() or 'does not support' in errors.GetOutput():
            raise RuntimeError(errors.GetOutput()[-1000:])
        return result
    finally:window.Finalize()


def run_probe(device, quick=False, timeout=8):
    command=[sys.executable,'-m','tomoswaxs.rendering',device]
    if quick:command.append('--quick')
    try:
        process=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        if process.returncode:raise RuntimeError(f'probe exited with status {process.returncode}: {process.stderr[-500:]}')
        for line in reversed(process.stdout.splitlines()):
            if line.startswith(MARKER):
                result=json.loads(line[len(MARKER):])
                if 'error' in result:raise RuntimeError(result['error'])
                return result
        raise RuntimeError('probe returned no result')
    except (OSError,subprocess.TimeoutExpired,ValueError,RuntimeError) as error:
        LOG.warning('Graphics probe %s failed: %s',device,error)
        return None


def fastest(results):
    accelerated=[r for r in results if not r['software'] and r.get('seconds',0)>0]
    if not accelerated:return next((r for r in results if r['device']=='system'),results[0] if results else None)
    best=min(r['seconds'] for r in accelerated)
    # Avoid switching backends/devices on insignificant short-benchmark noise.
    return next(r for r in accelerated if r['seconds']<=best*1.1)


def fingerprint():
    import vtk
    pieces=[platform.platform(),vtk.vtkVersion.GetVTKVersion(),os.environ.get('DISPLAY',''),
            os.environ.get('WAYLAND_DISPLAY',''),'probe-v3']
    for path in [Path('/proc/sys/kernel/random/boot_id'),Path('/sys/module/nvidia/version'),
                 *sorted(Path('/sys/class/drm').glob('card[0-9]*/device/uevent'))]:
        try:pieces.extend([str(path.resolve()),path.read_text()])
        except OSError:pass
    return hashlib.sha256('\n'.join(pieces).encode()).hexdigest()


def cache_path():
    return Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'tomoswaxs'/'render-device.json'


@lru_cache(maxsize=1)
def automatic_device():
    explicit=[key for key in OVERRIDES if key in os.environ]
    if explicit:
        return dict(device='system',reason='Preserving '+', '.join(explicit))
    if sys.platform!='linux':return dict(device='system',reason='Using platform graphics selection')
    key=fingerprint();path=cache_path()
    try:
        cached=json.loads(path.read_text())
        if cached['fingerprint']==key:
            result=run_probe(cached['choice']['device'],quick=True)
            if result and all(result.get(k)==cached['choice'].get(k) for k in ('renderer','version','software')):
                return {**cached['choice'], 'reason':'Cached graphics selection, verified'}
    except (OSError,ValueError,KeyError,TypeError):pass
    results=[];start=time.monotonic()
    default=run_probe('system')
    if default:results.append(default)
    devices=run_probe('devices') or {}
    for index in range(int(devices.get('devices',0))):
        remaining=20-(time.monotonic()-start)
        if remaining<1:
            LOG.warning('Graphics selection time limit reached; choosing among completed probes.')
            break
        result=run_probe(f'egl:{index}',timeout=min(8,remaining))
        if result:results.append(result)
    choice=fastest(results)
    if choice is None:return dict(device='system',reason='Graphics probes failed; using VTK fallback')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(f'.render-device-{os.getpid()}.json')
        temporary.write_text(json.dumps(dict(fingerprint=key,choice=choice,probes=results),indent=2))
        temporary.replace(path)
    except OSError as error:
        LOG.warning('Could not cache graphics selection: %s',error)
    return {**choice,'reason':'Fastest working volume-rendering probe'}


def create_render_window(device='auto'):
    choice=automatic_device() if device=='auto' else dict(device=device,reason='Explicit selection')
    LOG.info('Graphics: %s (%s): %s',choice.get('renderer','system default'),choice['device'],choice['reason'])
    return new_window(choice['device']),choice


if __name__=='__main__':
    try:result=probe(sys.argv[1],quick='--quick' in sys.argv[2:])
    except Exception as error:result=dict(error=f'{type(error).__name__}: {error}')
    print(MARKER+json.dumps(result),flush=True)
