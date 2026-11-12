"""OME-Zarr sources, bounded previews and cancellable TIFF import."""
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version as package_version
from pathlib import Path
import math
import json
import fcntl
import os
import shutil
import threading
import time
import uuid

import dask
import dask.array as da
from dask.callbacks import Callback
import ngff_zarr as ngff
import numpy as np
import tifffile

DEFAULT_PREVIEW_MIB = 64
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
    path: Path
    source: object
    level: int
    stride: int = 1


class VolumeSource:
    """Lazy scalar ZYX OME-Zarr source, independent of the rendering preview."""
    def __init__(self, path, _import_validation=False):
        self.path = Path(path).expanduser().resolve()
        if ".importing-" in self.path.name and not _import_validation:
            raise ValueError('This import is incomplete; open a completed OME-Zarr dataset.')
        multiscales = ngff.from_ngff_zarr(self.path)
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

    def preview(self, budget_mib=DEFAULT_PREVIEW_MIB, cancel=None):
        budget = float(budget_mib)*1024**2
        if not math.isfinite(budget) or budget < 1024**2:
            raise ValueError('Preview budget must be at least 1 MiB.')
        level = len(self.images)-1
        for i,image in enumerate(self.images):
            if np.prod(image.data.shape)*image.data.dtype.itemsize <= budget and max(image.data.shape) <= 512:
                level = i
                break
        image = self.images[level]
        stride = 1
        while (np.prod([(size+stride-1)//stride for size in image.data.shape])*image.data.dtype.itemsize > budget
               or max(image.data.shape)/stride > 512):
            stride *= 2
        class CheckCancel(Callback):
            def _pretask(self,key,graph,state):
                if cancel is not None and cancel.is_set():
                    raise ImportCancelled('Load cancelled.')
        with CheckCancel():
            values = image.data[::stride,::stride,::stride].compute(scheduler='single-threaded')
        values = np.ascontiguousarray(values, dtype=values.dtype.newbyteorder('='))
        finite = values.ravel()[::max(1,values.size//1_000_000)]
        finite = finite[np.isfinite(finite)]
        if not finite.size:
            raise ValueError('The preview contains no finite intensities.')
        low, high = map(float,np.percentile(finite,[50,99.5]))
        if high <= low:
            low,high = float(finite.min()),float(finite.max())
        if high <= low:
            high = low+1
        scale,origin = self.geometry(image)
        return Volume(values,scale*stride,origin,(low,high),self.path,self,level,stride)


def import_tiff(path, destination, voxel_size_um=None, cancel=None, progress=None):
    """Write OME-Zarr 0.5 atomically; level zero preserves source scalar values."""
    path, destination = Path(path).expanduser().resolve(), Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f'Destination already exists: {destination}')
    blocks = TiffBlocks(path)
    supplied = voxel_size_um is not None
    source_spacing = tiff_spacing(path)
    spacing = spacing_xyz(voxel_size_um if supplied else source_spacing)
    cancel = cancel or threading.Event()
    progress = progress or (lambda text: None)
    if cancel.is_set():
        raise ImportCancelled('Import cancelled.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging = destination.with_name('.'+destination.name+'.importing-'+uuid.uuid4().hex)
    try:
        data = da.from_array(blocks,chunks=(CHUNK,)*3,asarray=False,fancy=False,
                             name='tiff-'+uuid.uuid4().hex)
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
            source_size=path.stat().st_size,source_mtime_ns=path.stat().st_mtime_ns,
            voxel_spacing_xyz_um=spacing.tolist(),spacing_origin='user' if supplied else 'metadata',
            source_spacing_available=source_spacing is not None,
            downsampling='block mean (DASK_BIN_SHRINK)',ngff_zarr_version=package_version('ngff-zarr'))}
        class Monitor(Callback):
            def _start(self, graph):
                self.total,self.done = max(1,len(graph)),0
                self.last_report = 0.
            def _pretask(self,key,graph,state):
                if cancel.is_set():
                    raise ImportCancelled('Import cancelled.')
            def _posttask(self,key,result,graph,state,worker_id):
                self.done += 1
                now = time.monotonic()
                if self.done == 1 or (self.done % 32 == 0 and now-self.last_report >= .25):
                    self.last_report = now
                    progress(f'Writing pyramid: {self.done}/{self.total} tasks in current level')
        progress('Converting TIFF to OME-Zarr…')
        with dask.config.set(scheduler='single-threaded'), Monitor():
            ngff.to_ome_zarr(staging,multiscales,version='0.5',overwrite=False,scale_strategy='exact')
        if cancel.is_set():
            raise ImportCancelled('Import cancelled.')
        # Validate metadata/readability before making the result visible.
        VolumeSource(staging, _import_validation=True)
        if destination.exists():
            raise FileExistsError(f'Destination appeared during import: {destination}')
        staging.rename(destination)
        progress('Import complete.')
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def directory_entries(directory,projects=False,directories_only=False):
    directory = Path(directory).expanduser().resolve()
    entries=[]
    for path in sorted(directory.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
        if path.name.startswith('.'):
            continue
        is_directory = path.is_dir()
        is_image = is_ome_zarr(path)
        if directories_only and (not is_directory or is_image):
            continue
        if projects and path.name == 'project.json' and path.is_file():
            kind = 'NIM project'
        elif projects and is_image:
            continue
        elif is_image:
            kind = 'OME-Zarr volume'
        elif is_directory:
            kind = 'Directory'
        elif not projects and path.suffix.lower() in ('.tif','.tiff'):
            kind = 'TIFF volume'
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
