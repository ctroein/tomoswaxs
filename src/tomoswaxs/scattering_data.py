"""Read-only ForMAX integrated SAXS scans and their acquisition coordinates."""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import shlex

import h5py
import numpy as np


ONE='/entry/default/data1d/orig/'
TWO='/entry/default/data2d/orig/'


def text(value):
    if isinstance(value,np.ndarray) and value.size==1:
        value=value.reshape(-1)[0]
    return value.decode() if isinstance(value,bytes) else str(value)


@dataclass
class MeasurementIndex:
    x_um: np.ndarray
    y_um: np.ndarray
    angle_deg: np.ndarray
    nominal_x_um: np.ndarray
    nominal_angles: np.ndarray

    def __post_init__(self):
        count=len(self.nominal_x_um)*len(self.nominal_angles)
        if not count or any(a.shape!=(count,) or not np.isfinite(a).all()
                            for a in (self.x_um,self.y_um,self.angle_deg)):
            raise ValueError('Motor arrays must be finite and match the scan grid.')
        if any(not np.isfinite(a).all() for a in (self.nominal_x_um,self.nominal_angles)):
            raise ValueError('Invalid nominal scan coordinates.')

    @property
    def shape(self):
        return len(self.nominal_angles),len(self.nominal_x_um)

    def frame(self,row,column):
        if type(row) is not int or type(column) is not int or not (0<=row<self.shape[0] and 0<=column<self.shape[1]):
            raise ValueError('Measurement is outside the acquired scan grid.')
        return row*self.shape[1]+column

    def nearest(self,x_um,angle):
        angular=np.abs((self.nominal_angles-angle+180)%360-180)
        return int(np.argmin(angular)),int(np.argmin(np.abs(self.nominal_x_um-x_um)))

    def details(self,row,column):
        n=self.frame(row,column)
        return dict(frame=n,row=row,column=column,x_um=float(self.x_um[n]),y_um=float(self.y_um[n]),
                    angle=float(self.angle_deg[n]),nominal_angle=float(self.nominal_angles[row]),
                    angle_flag=bool(abs((self.angle_deg[n]-self.nominal_angles[row]+180)%360-180)>.01))


class IntegratedScan:
    def __init__(self,path,metadata=None):
        self.path=Path(path).expanduser().resolve()
        self.metadata=Path(metadata).expanduser().resolve() if metadata else self.path.parent/'Metadata'/self.path.name.replace('_eiger_integrated','')
        with h5py.File(self.metadata,'r') as f:
            self.title=text(f['/entry/title'][()])
            args=shlex.split(self.title)
            if len(args)<9 or args[0:2]!=['mesh','swaxs_x'] or args[5]!='tomo_ry':
                raise ValueError(f'Unsupported SAXS scan layout: {self.title}')
            cols=int(args[4])+1;rows=int(args[8])+1
            if not (1<=cols<=100000 and 1<=rows<=100000):
                raise ValueError('Invalid SAXS scan dimensions.')
            nominal_x=np.linspace(float(args[2]),float(args[3]),cols)*1000
            angles=np.linspace(float(args[6]),float(args[7]),rows)
            motors=f['/entry/measurement']
            x=np.asarray(motors['swaxs_x'],dtype=float)*1000
            theta=np.asarray(motors['tomo_ry'],dtype=float)
            if 'swaxs_y' in motors:
                y=np.asarray(motors['swaxs_y'],dtype=float)*1000;self.y_origin='per-measurement readback'
            else:
                y=np.full(x.shape,float(f['/entry/instrument/start_positioners/swaxs_y'][()])*1000)
                self.y_origin='start-position snapshot'
            self.start_positioners={name:float(ds[()]) for name,ds in f['/entry/instrument/start_positioners'].items()}
        self.index=MeasurementIndex(x,y,theta,nominal_x,angles)
        with h5py.File(self.path,'r') as f:
            self.q=np.asarray(f[ONE+'q'],dtype=float)
            self.phi=np.asarray(f[TWO+'azi'],dtype=float)
            self.q_unit=text(f[ONE+'q'].attrs.get('units','unknown unit'))
            phi_unit=text(f[TWO+'azi'].attrs.get('units',''))
            if phi_unit not in ('degree','degrees'):
                raise ValueError(f'Unsupported scattering azimuth unit: {phi_unit!r}')
            self.norm1=np.asarray(f[ONE+'norm'],dtype=float)
            norm2_shape=f[TWO+'norm'].shape
            expected=(len(x),len(self.phi),len(self.q))
            if f[TWO+'cake'].shape!=expected or f[ONE+'I'].shape!=(len(x),len(self.q)):
                raise ValueError('Integrated SAXS data and motor metadata have different dimensions.')
            if self.norm1.shape!=self.q.shape or norm2_shape!=expected[1:]:
                raise ValueError('SAXS normalization arrays do not match the scattering axes.')
            if not np.array_equal(self.q,np.asarray(f[TWO+'q'])) or not all(np.isfinite(a).all() for a in (self.q,self.phi)):
                raise ValueError('SAXS q/azimuth coordinates are inconsistent or non-finite.')
        self.name=self.path.name.removesuffix('_eiger_integrated.h5')
        self._cache=OrderedDict()
        self._norm2=None

    def clear_cache(self):
        self._cache.clear()
        self._norm2=None

    def read(self,row,column):
        n=self.index.frame(row,column)
        if n in self._cache:
            self._cache.move_to_end(n)
            return self._cache[n]
        with h5py.File(self.path,'r') as f:
            intensity=np.asarray(f[ONE+'I'][n],dtype=float)
            cake=np.asarray(f[TWO+'cake'][n],dtype=float)
            if self._norm2 is None:
                self._norm2=np.asarray(f[TWO+'norm'],dtype=float)
        intensity=np.where(self.norm1>0,intensity,np.nan)
        cake=np.where(self._norm2>0,cake,np.nan)
        result=(self.q,self.phi,cake,intensity)
        # Bound by bytes: future detectors need not have the same cake shape.
        self._cache[n]=result
        while len(self._cache)>1 and sum(v[2].nbytes+v[3].nbytes for v in self._cache.values())>18*1024**2:
            self._cache.popitem(last=False)
        return result


def scan_specs(path):
    path=Path(path).expanduser().resolve()
    paths=sorted(path.glob('*_eiger_integrated.h5')) if path.is_dir() else [path]
    if not paths:
        raise ValueError('No *_eiger_integrated.h5 files found in this directory.')
    return [dict(path=str(p),metadata=str(p.parent/'Metadata'/p.name.replace('_eiger_integrated',''))) for p in paths]


def open_scans(specs):
    scans=[IntegratedScan(spec['path'],spec.get('metadata')) for spec in specs]
    if not scans:
        raise ValueError('Select at least one integrated SAXS scan.')
    return scans
