"""OME-Zarr sources, bounded previews and cancellable TIFF import."""
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version as package_version
from pathlib import Path
from .sources import is_http_url, source_location
import math
import json
import fcntl
import os
import shutil
import threading
import uuid

import dask
import dask.array as da
from dask.callbacks import Callback
import ngff_zarr as ngff
import numpy as np
import tifffile

DEFAULT_PREVIEW_MIB = 256
CHUNK = 64


class ImportCancelled(Exception):
    pass


def spacing_xyz(value):
    if value is None or (isinstance(value,str) and value == ''):
        raise ValueError('Pixel size is missing. Enter X, Y and Z spacing in µm.')
    parts = [value] if np.isscalar(value) else list(value)
    if len(parts) == 1:
        parts *= 3
    if len(parts) != 3:
        raise ValueError('Supply one pixel size or three values in X Y Z order.')
    try:
        values = np.array(parts, dtype=float)
    except (ValueError, TypeError):
        raise ValueError('Enter pixel sizes for X, Y and Z in µm.') from None
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError('Pixel size must contain positive finite values in µm.')
    return values


class TiffBlocks:
    """Read only requested blocks. Close each mapping to bound resident pages."""
    ndim = 3

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        with tifffile.TiffFile(self.path) as image:
            if len(image.series) != 1:
                raise ValueError('Select a TIFF containing one scalar volume.')
            series = image.series[0]
            self.shape, self.dtype = tuple(series.shape), np.dtype(series.dtype)
            if len(self.shape) != 3 or series.axes not in ('ZYX', 'QYX', 'IYX'):
                raise ValueError(f'Expected a scalar ZYX stack; found {series.axes}, {self.shape}.')
            if min(self.shape) < 2 or self.dtype.kind not in 'uif':
                raise ValueError('Expected a non-empty numeric scalar 3D volume.')
            self.pages = len(series.pages) == self.shape[0] and series.pages[0].shape == self.shape[1:]
        try:
            mapped = tifffile.memmap(self.path, mode='r')
            self.offset = mapped.offset
            self.storage_dtype = mapped.dtype
            mapped._mmap.close()
        except ValueError:
            self.offset = None
            if not self.pages:
                raise ValueError('This TIFF layout cannot be read in bounded blocks.')

    def __getitem__(self, key):
        # Dask supplies slice tuples on its chunk grid.
        if self.offset is not None:
            mapped = np.memmap(self.path, mode='r', dtype=self.storage_dtype,
                               offset=self.offset, shape=self.shape)
            try:
                return np.array(mapped[key], dtype=self.dtype, copy=True)
            finally:
                mapped._mmap.close()
        z, y, x = key
        with tifffile.TiffFile(self.path) as image:
            indices = range(*z.indices(self.shape[0]))
            if not len(indices):
                return np.empty((0, len(range(*y.indices(self.shape[1]))),
                                 len(range(*x.indices(self.shape[2])))), dtype=self.dtype)
            return np.stack([image.series[0].pages[i].asarray()[y,x] for i in indices])


def tiff_spacing(path):
    """Read explicit physical ImageJ/OME pixel size; never infer from filenames."""
    with tifffile.TiffFile(path) as image:
        if image.ome_metadata:
            import xml.etree.ElementTree as ET
            pixels = ET.fromstring(image.ome_metadata).find('.//{*}Pixels')
            if pixels is not None:
                result = []
                for axis in 'XYZ':
                    size = pixels.get('PhysicalSize'+axis)
                    if size is None:
                        break
                    unit = pixels.get('PhysicalSize'+axis+'Unit', 'µm')
                    result.append(float(size)*unit_to_mm(unit)*1000)
                if len(result) == 3:
                    return spacing_xyz(result)
        metadata = image.imagej_metadata or {}
        unit = metadata.get('unit')
        if unit and 'spacing' in metadata:
            tags = image.pages[0].tags
            if 'XResolution' in tags and 'YResolution' in tags:
                try:
                    factor = unit_to_mm(unit)*1000
                    x = tags['XResolution'].value
                    y = tags['YResolution'].value
                    return spacing_xyz([x[1]/x[0]*factor, y[1]/y[0]*factor,
                                        float(metadata['spacing'])*factor])
                except (ValueError, ZeroDivisionError):
                    pass
    return None


def unit_to_mm(unit):
    units = {'micrometer':.001, 'µm':.001, 'um':.001, 'micron':.001,
             'millimeter':1., 'mm':1., 'nanometer':.000001, 'nm':.000001,
             'meter':1000., 'm':1000., 'centimeter':10., 'cm':10.}
    try:
        return units[unit]
    except (KeyError, TypeError):
        raise ValueError(f'Unsupported or missing physical length unit: {unit!r}') from None


def is_ome_zarr(path):
    path = Path(path)
    return path.is_dir() and ((path/'zarr.json').exists() or (path/'.zgroup').exists())


def import_pixel_size(path):
    """Return the editable spacing supplied for a TIFF import without pixel-size metadata."""
    if is_http_url(path):return None
    metadata = Path(path)/'zarr.json'
    if not metadata.is_file():
        return None
    attributes = json.loads(metadata.read_text()).get('attributes',{})
    provenance = attributes.get('nim_import',{})
    if provenance.get('spacing_origin') != 'user' or provenance.get('source_spacing_available',False):
        return None
    return spacing_xyz(provenance.get('voxel_spacing_xyz_um'))


def replace_import_pixel_size(path, voxel_size_um):
    """Change import-supplied physical coordinates without touching voxel chunks."""
    spacing = spacing_xyz(voxel_size_um)
    metadata = Path(path)/'zarr.json'
    # Keep the file's ownership and permissions; serialize our metadata writers.
    with metadata.open('r+',encoding='utf-8') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        original = stream.read()
        document = json.loads(original)
        attributes = document['attributes']
        provenance = attributes.get('nim_import',{})
        if provenance.get('spacing_origin') != 'user' or provenance.get('source_spacing_available',False):
            raise ValueError('This sample has no editable import-supplied pixel size.')
        old = spacing_xyz(provenance.get('voxel_spacing_xyz_um'))
        ratio = dict(zip('xyz',spacing/old))
        multiscales = attributes['ome']['multiscales']
        for multiscale in multiscales:
            axes = [axis['name'] for axis in multiscale['axes']]
            if set(axes) != set('xyz') or len(axes) != 3:
                raise ValueError('Expected XYZ spatial axes in the imported image.')
            for dataset in multiscale['datasets']:
                for transform in dataset['coordinateTransformations']:
                    kind = transform['type']
                    if kind not in ('scale','translation') or len(transform[kind]) != len(axes):
                        raise ValueError('Unsupported coordinates in the imported image.')
                    values = [float(value*ratio[axis]) for axis,value in zip(axes,transform[kind])]
                    if not np.all(np.isfinite(values)) or (kind == 'scale' and min(values) <= 0):
                        raise ValueError('Pixel size produces invalid physical coordinates.')
                    transform[kind] = values
        provenance['voxel_spacing_xyz_um'] = spacing.tolist()
        replacement = json.dumps(document,indent=2,allow_nan=False)+'\n'
        try:
            stream.seek(0); stream.write(replacement); stream.truncate()
            stream.flush(); os.fsync(stream.fileno())
        except OSError:
            stream.seek(0); stream.write(original); stream.truncate()
            stream.flush(); os.fsync(stream.fileno())
            raise


@dataclass
class Volume:
    values: np.ndarray                 # bounded rendering preview
    spacing: np.ndarray                # XYZ, mm
    origin: np.ndarray                 # XYZ, mm
    contrast: tuple[float, float]
    path: Path | str
    source: object
    level: int
    stride: int = 1
    crop: tuple | None = None          # XYZ, full-resolution cell indices [start, stop)
    selection: tuple | None = None     # actual ZYX slices at the selected level
    requested_level: str | int = 'auto'
    display_threshold: float | None = None
    display_selection: tuple | None = None
    refined_from: int | None = None
    refinement_history: tuple = ()      # (source level, subsampling stride) per loaded array
    refinement_stop: str = ''          # finest / limit / empty after the final bounds check
    refinement_crop: tuple | None = None
    refinement_spacing: tuple | None = None


class VolumeSource:
    """Lazy scalar ZYX OME-Zarr source, independent of the rendering preview."""
    def __init__(self, path, _import_validation=False):
        self.path = source_location(path)
        remote=is_http_url(self.path)
        if not remote and ".importing-" in self.path.name and not _import_validation:
            raise ValueError('This import is incomplete; open a completed OME-Zarr dataset.')
        try:
            if remote:
                from .http_sources import read_http_multiscales
                multiscales=read_http_multiscales(self.path)
            else:
                multiscales = ngff.from_ngff_zarr(self.path)
        except ImportError as error:
            if remote:
                raise ValueError('Opening OME-Zarr URLs requires the ngff-zarr remote extra (obstore).') from error
            raise
        if not isinstance(multiscales, ngff.NgffMultiscales):
            raise ValueError('Select a scalar multiscale OME-Zarr image.')
        self.images = multiscales.images
        for image in self.images:
            if tuple(image.dims) != ('z','y','x'):
                raise ValueError(f'Expected scalar ZYX OME-Zarr data; found {image.dims}.')
            if image.data.dtype.kind not in 'uif' or (image.data.dtype.kind == 'f' and image.data.dtype.itemsize not in (4,8)):
                raise ValueError(f'Unsupported rendering scalar type: {image.data.dtype}.')
            self.geometry(image)  # require physical pixel size
            if np.prod(image.data.chunksize)*image.data.dtype.itemsize > 256*1024**2:
                raise ValueError('OME-Zarr chunks exceed the 256 MiB read limit; rechunk the dataset before opening.')
        self.data = self.images[0].data
        self.shape, self.dtype = self.data.shape, self.data.dtype
        self.spacing, self.origin = self.geometry(self.images[0])
    @staticmethod
    def geometry(image):
        units = image.axes_units or {}
        factors = np.array([unit_to_mm(units.get(axis)) for axis in 'xyz'])
        scale = np.array([image.scale[axis] for axis in 'xyz'])*factors
        origin = np.array([image.translation.get(axis,0.) for axis in 'xyz'])*factors
        if not np.all(np.isfinite(scale)) or np.any(scale <= 0) or not np.all(np.isfinite(origin)):
            raise ValueError('Invalid physical coordinates in OME-Zarr metadata.')
        return scale, origin

    def read_region(self, selection):
        return self.data[selection].compute(scheduler='single-threaded')

    def __getitem__(self, key):
        # The SAXS mock requests a short list of points, grouped by Dask chunks.
        return self.data.vindex[key].compute(scheduler='single-threaded')

    def crop_bounds(self, crop=None):
        shape=tuple(map(int,self.shape[::-1]))
        if crop is None:
            return tuple((0,n) for n in shape)
        if not isinstance(crop,(list,tuple)) or len(crop)!=3:
            raise ValueError('Crop needs X, Y and Z bounds.')
        result=[]
        for pair,n in zip(crop,shape):
            if (not isinstance(pair,(list,tuple)) or len(pair)!=2 or
                any(type(v) not in (int,np.int64,np.int32) for v in pair) or
                not 0 <= pair[0] < pair[1] <= n):
                raise ValueError('Crop bounds must be whole voxel indices with start < end inside the sample.')
            result.append(tuple(map(int,pair)))
        return tuple(result)

    def region_slices(self, crop, level):
        image=self.images[level]
        spacing,origin=self.geometry(image)
        bounds=np.asarray(crop,dtype=float)
        # Include coarse voxel cells intersecting the full-resolution ROI.
        # NGFF levels may have translated centres (e.g. half-voxel averaging).
        indices=(self.origin-origin)[:,None]/spacing[:,None]+(bounds-.5)*(self.spacing/spacing)[:,None]+.5
        start=np.floor(indices[:,0]+1e-9).astype(int)
        stop=np.ceil(indices[:,1]-1e-9).astype(int)
        shape=np.asarray(image.data.shape[::-1])
        start=np.clip(start,0,shape-1);stop=np.clip(stop,start+1,shape)
        return tuple(slice(int(a),int(b)) for a,b in zip(start[::-1],stop[::-1]))

    def level_options(self, budget_mib=DEFAULT_PREVIEW_MIB, crop=None):
        crop=self.crop_bounds(crop)
        budget=float(budget_mib)*1024**2
        if not math.isfinite(budget) or budget < 1024**2:
            raise ValueError('Voxel array size limit must be at least 1 MiB.')
        options=[]
        for i,image in enumerate(self.images):
            selection=self.region_slices(crop,i)
            shape=tuple(s.stop-s.start for s in selection)
            size=math.prod(shape)*image.data.dtype.itemsize
            spacing,_=self.geometry(image)
            options.append(dict(level=i,shape=shape,bytes=size,spacing=tuple(map(float,spacing)),fits=size<=budget))
        return options

    def preview(self, budget_mib=DEFAULT_PREVIEW_MIB, cancel=None, crop=None, level='auto', *, cache=None, contrast=None, refine=False, threshold=None):
        crop=self.crop_bounds(crop)
        options=self.level_options(budget_mib,crop)
        requested=level
        if level == 'auto':
            level=next((item['level'] for item in options if item['fits']),len(options)-1)
        elif type(level) is not int or not 0 <= level < len(options):
            raise ValueError('Choose an available OME-Zarr level.')
        elif not options[level]['fits']:
            raise ValueError('This level exceeds the voxel array size limit for the crop.')
        image=self.images[level]
        selected=self.region_slices(crop,level)
        stride=1
        while math.prod((s.stop-s.start+stride-1)//stride for s in selected)*image.data.dtype.itemsize > float(budget_mib)*1024**2:
            stride*=2
        selection=tuple(slice(s.start,s.stop,stride) for s in selected)
        class CheckCancel(Callback):
            def _pretask(self,key,graph,state):
                if cancel is not None and cancel.is_set():
                    raise ImportCancelled('Load cancelled.')
        if cancel is not None and cancel.is_set():raise ImportCancelled('Load cancelled.')
        if cache is not None:
            values=cache.read(image.data,selection,(id(self),level),cancel,float(budget_mib)*1024**2)
        else:
            with CheckCancel():
                values = image.data[selection].compute(scheduler='single-threaded')
        values = np.ascontiguousarray(values, dtype=values.dtype.newbyteorder('='))
        if contrast is None:
            finite = values.ravel()[::max(1,values.size//1_000_000)]
            finite = finite[np.isfinite(finite)]
            if not finite.size:
                raise ValueError('The preview contains no finite intensities.')
            low, high = map(float,np.percentile(finite,[50,99.5]))
            if high <= low:
                low,high = float(finite.min()),float(finite.max())
            if high <= low:
                high = low+1
        else:
            low,high=contrast
            if not np.isfinite(values.ravel()[::max(1,values.size//1_000_000)]).any():
                raise ValueError('The preview contains no finite intensities.')
        scale,origin = self.geometry(image)
        origin=origin+np.asarray([s.start for s in selection][::-1])*scale
        volume=Volume(values,scale*stride,origin,(low,high),self.path,self,level,stride,crop,selection,requested)
        if refine:
            from .volume_bounds import refine_preview
            return refine_preview(volume,budget_mib,low+(high-low)*9000/65535 if threshold is None else threshold,cancel,cache)
        return volume


def hdf5_volumes(path):
    import h5py
    entries=[]
    with h5py.File(path,'r') as handle:
        def visit(name,obj):
            if isinstance(obj,h5py.Dataset) and obj.ndim==3 and min(obj.shape)>=2 and obj.dtype.kind in 'uif':
                entries.append(dict(value='/'+name,label=f'/{name} · {obj.shape} · {obj.dtype}'))
        handle.visititems(visit)
    return entries


def hdf5_spacing(path):
    import h5py
    with h5py.File(path,'r') as handle:
        if '/metadata/pixel_size_cm' in handle:
            return spacing_xyz(float(handle['/metadata/pixel_size_cm'][()])*10000)
    return None


def hdf5_axes(path):
    import h5py
    with h5py.File(path,'r') as handle:
        if '/metadata/reconstructed_vol_dimensions_Z(number-of-slices)_X(width)_Y(height)' in handle:
            return 'zxy'
    return 'zyx'


class Hdf5Blocks:
    ndim=3

    def __init__(self,path,dataset,axes='zyx'):
        import h5py
        self.path=Path(path).expanduser().resolve()
        self.dataset=dataset
        if sorted(axes)!=list('xyz'):
            raise ValueError('Select the stored order of X, Y and Z.')
        self.order=tuple(axes.index(axis) for axis in 'zyx')
        with h5py.File(self.path,'r') as handle:
            ds=handle[dataset]
            if not isinstance(ds,h5py.Dataset) or ds.ndim!=3 or min(ds.shape)<2 or ds.dtype.kind not in 'uif':
                raise ValueError('Select a numeric scalar 3D HDF5 dataset.')
            if ds.chunks and math.prod(ds.chunks)*ds.dtype.itemsize>256*1024**2:
                raise ValueError("HDF5 chunks exceed 256 MiB; rechunk the source before importing.")
            self.shape=tuple(ds.shape[i] for i in self.order)
            self.dtype=np.dtype(ds.dtype)

    def __getitem__(self,key):
        import h5py
        stored=[None]*3
        for i,axis in enumerate(self.order):stored[axis]=key[i]
        with h5py.File(self.path,'r') as handle:
            return np.ascontiguousarray(handle[self.dataset][tuple(stored)].transpose(self.order))


def import_hdf5(path,destination,dataset,voxel_size_um=None,cancel=None,progress=None,axes='zyx'):
    return _import_volume(path,destination,voxel_size_um,cancel,progress,
        Hdf5Blocks(path,dataset,axes),hdf5_spacing(path),dict(source_format='hdf5',source_dataset=dataset,source_axes=axes))


def import_tiff(path, destination, voxel_size_um=None, cancel=None, progress=None):
    return _import_volume(path,destination,voxel_size_um,cancel,progress,TiffBlocks(path),tiff_spacing(path),dict(source_format='tiff'))


def _import_volume(path,destination,voxel_size_um,cancel,progress,blocks,source_spacing,extra):
    """Write OME-Zarr 0.5 atomically; level zero preserves source scalar values."""
    path, destination = Path(path).expanduser().resolve(), Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f'Destination already exists: {destination}')
    supplied = voxel_size_um is not None
    spacing = spacing_xyz(voxel_size_um if supplied else source_spacing)
    cancel = cancel or threading.Event()
    progress = progress or (lambda text: None)
    if cancel.is_set():
        raise ImportCancelled('Import cancelled.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = destination.with_name('.'+destination.name+'.importing-'+uuid.uuid4().hex)
    try:
        data = da.from_array(blocks,chunks=(CHUNK,)*3,asarray=False,fancy=False,
                             name='import-'+uuid.uuid4().hex)
        scale = dict(zip('xyz',map(float,spacing)))
        translation = dict(zip('xyz',-(np.array(blocks.shape[::-1])-1)*spacing/2))
        image = ngff.to_ngff_image(data,dims=('z','y','x'),scale=scale,
                    translation=translation,axes_units=dict.fromkeys('xyz','micrometer'),name=path.stem)
        factors = []
        factor = 2
        while min(blocks.shape)//factor >= 2:
            factors.append(factor)
            if max(blocks.shape)//factor <= 128:
                break
            factor *= 2
        multiscales = ngff.to_multiscales(image,scale_factors=factors,
                    method=ngff.Methods.DASK_BIN_SHRINK,chunks=CHUNK,cache=False)
        multiscales.root_attributes = {'nim_import':dict(source=str(path),
            **extra,source_size=path.stat().st_size,source_mtime_ns=path.stat().st_mtime_ns,
            voxel_spacing_xyz_um=spacing.tolist(),spacing_origin='user' if supplied else 'metadata',
            source_spacing_available=source_spacing is not None,
            downsampling='block mean (DASK_BIN_SHRINK)',ngff_zarr_version=package_version('ngff-zarr'))}
        class Monitor(Callback):
            def add_multiscales_task(self,description,scales):
                self.levels=scales

            def update_multiscales_task_completed(self,level):
                # ngff-zarr calls this when beginning each level.
                detail=' (full resolution)' if level==1 else ''
                progress(f'Writing resolution level {level} of {self.levels}{detail}')

            def _pretask(self,key,graph,state):
                if cancel.is_set():
                    raise ImportCancelled('Import cancelled.')

        progress('Preparing OME-Zarr conversion…')
        monitor=Monitor()
        with dask.config.set(scheduler='single-threaded'), monitor:
            ngff.to_ome_zarr(staging,multiscales,version='0.5',overwrite=False,scale_strategy='exact',progress=monitor)
        if cancel.is_set():
            raise ImportCancelled('Import cancelled.')
        # Validate metadata/readability before making the result visible.
        progress('Validating converted image…')
        VolumeSource(staging, _import_validation=True)
        if destination.exists():
            raise FileExistsError(f'Destination appeared during import: {destination}')
        staging.rename(destination)
        progress('Import complete.')
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def logical_path(path):
    """Absolute navigation path retaining symlink components, as in pwd -L."""
    import os
    return Path(os.path.abspath(Path(path).expanduser()))


def directory_entries(directory,projects=False,directories_only=False,scattering=False,all_files=False,name_filter='*'):
    from fnmatch import fnmatchcase
    directory = logical_path(directory)
    entries=[]
    for path in sorted(directory.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
        if path.name.startswith('.'):
            continue
        is_directory = path.is_dir()
        try:
            is_image = is_ome_zarr(path)
        except PermissionError:
            is_image = False  # Keep the directory available; opening it reports access errors.
        if not is_directory and not any(fnmatchcase(path.name,pattern.strip()) for pattern in (name_filter or '*').split(';') if pattern.strip()):
            continue
        if directories_only and (not is_directory or is_image):
            continue
        if projects and path.name == 'project.json' and path.is_file():
            kind = 'NIM project'
        elif projects and is_image and not all_files:
            continue
        elif is_image:
            kind = 'OME-Zarr volume'
        elif is_directory:
            kind = 'Directory'
        elif scattering and path.name.endswith('_eiger_integrated.h5'):
            kind = 'Integrated SAXS scan'
        elif not projects and not scattering and path.suffix.lower() in ('.tif','.tiff'):
            kind = 'TIFF volume'
        elif not projects and not scattering and path.suffix.lower() in ('.h5','.hdf5'):
            kind = 'HDF5 volume (import)'
        elif all_files and not directories_only:
            kind = ('HDF5 file' if path.suffix.lower() in ('.h5','.hdf5') else 'File')+' · unsupported by this operation'
        else:
            continue
        try:
            info = path.stat()
        except FileNotFoundError:
            continue  # A file may disappear while the directory is being listed.
        size = None if is_directory else info.st_size
        size_display = ''
        if size is not None:
            amount = float(size)
            for unit in ('B','KiB','MiB','GiB','TiB'):
                if amount < 1024 or unit == 'TiB':
                    size_display = f'{amount:,.0f} {unit}' if unit == 'B' else f'{amount:,.1f} {unit}'
                    break
                amount /= 1024
        entries.append(dict(path=str(path),name=path.name,kind=kind,
                            size=size,size_display=size_display,
                            modified=info.st_mtime,
                            modified_display=datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M'),
                            size_detail='' if size is None else f'{size:,} bytes'))
    return directory,entries
