"""Editable CT/SAXS registration estimates, separate from acquisition readbacks."""
from pathlib import Path
import math
import h5py
import numpy as np

MOTORS=('tab_x','tab_y','swaxs_x','swaxs_y','tomo_xf','tomo_zf')


def motor_rows(reference):
    return [dict(name=name,reference=float(reference.get(name,0)),x=float(name in ('tab_x','swaxs_x','tomo_xf')),
                 y=float(name in ('tab_y','swaxs_y'))) for name in MOTORS]


def stack_rows(reference):
    rows=motor_rows(reference)
    # These are signed beam-coordinate factors. Retain the existing provisional
    # lower-stage signs; upper-stage factors specify the transverse amplitude.
    next(row for row in rows if row['name']=='tomo_zf')['x']=1.
    return rows


def rotation_warning(scan):
    """The current stack hypothesis assumes swaxs_ry remains at 180 degrees."""
    value=scan.start_positioners.get('swaxs_ry')
    if value is not None and abs((value-180+180)%360-180)>.01:
        return f'swaxs_ry is {value:g}°. Confirm its effect on the motor geometry with the beamline scientists.'
    return ''


def initial_placement(scans,discover=True):
    first=scans[0].index
    result=dict(model='manual',x_origin=float(np.mean(first.nominal_x_um[[0,-1]])),y_origin=float(first.y_um[0]),
                x_offset=0.,y_offset=0.,x_sign=1.,y_sign=1.,angle_offset=0.,angle_sign=1.,camera_x=0.,camera_y=0.,
                motors=motor_rows(scans[0].start_positioners),pivot_x=0.,pivot_z=0.,reference_source='No CT motor reference')
    reference=scans[0].path.parent.parent/'Metadata_CT'/'Radiographs.h5'
    if discover and reference.is_file():
        with h5py.File(reference,'r') as f:
            group=f['/entry/instrument/start_positioners']
            positions={name:float(group[name][()]) for name in MOTORS}
        result.update(model='stack',motors=stack_rows(positions),reference_source=str(reference))
        # Identified supplied Bamboo bundle: beam profiles reported by Mira.
        # Camera-to-view signs and CT origin remain editable starting assumptions.
        if math.isclose(positions['swaxs_x'],-.2487,abs_tol=1e-6) and math.isclose(positions['swaxs_y'],-5.85325,abs_tol=1e-6):
            result.update(camera_x=(1454-675)*.65,camera_y=(949-743)*.65,axis_hint='z')
    return result


def positions(scan,mapping):
    """Viewer XY arrays in µm; nominal X grid, recorded/snapshot Y, indexed by frame."""
    index=scan.index
    nominal_x=np.tile(index.nominal_x_um,index.shape[0])
    if mapping.get('model','manual')=='manual':
        return (mapping['x_sign']*(nominal_x-mapping['x_origin'])+mapping['x_offset'],
                mapping['y_sign']*(index.y_um-mapping['y_origin'])+mapping['y_offset'])
    x=np.full(len(nominal_x),mapping['x_offset']+mapping['camera_x'],dtype=float)
    y=np.full(len(nominal_x),mapping['y_offset']+mapping['camera_y'],dtype=float)
    theta=np.deg2rad(np.repeat(index.nominal_angles,index.shape[1]))
    for motor in mapping['motors']:
        name=motor['name']
        if name=='swaxs_x':value=nominal_x/1000
        elif name=='swaxs_y':value=index.y_um/1000
        else:
            if name not in scan.start_positioners:
                if motor['x'] or motor['y']:raise ValueError(f'Missing {name} snapshot in {scan.metadata.name}')
                continue
            value=scan.start_positioners[name]
        delta=(value-motor['reference'])*1000
        if mapping['model']=='stack' and name in ('tomo_xf','tomo_zf'):
            # The alignment stages are above tomo_ry. Mira identifies zf as
            # transverse at 0/180 degrees, xf at 90/270 degrees. Their signs
            # remain explicit parameters; viewer angle offsets do not alter
            # the physical motor projection.
            projection=np.sin(theta) if name=='tomo_xf' else np.cos(theta)
            x+=motor['x']*delta*projection
        else:
            x+=motor['x']*delta;y+=motor['y']*delta
    if mapping['model']=='stack':
        # The viewer keeps the CT centred. Express the fitted orbit as a beam
        # correction in that frame, rather than translating the rendered CT.
        view_theta=np.deg2rad(np.repeat(angles(scan,mapping),index.shape[1]))
        x+=mapping.get('pivot_x',0.)*np.cos(view_theta)+mapping.get('pivot_z',0.)*np.sin(view_theta)
    return x,y


def angles(scan,mapping):
    values=scan.index.nominal_angles*mapping.get('angle_sign',1)+mapping['angle_offset']
    return np.where((values>=-180)&(values<=180),values,(values+180)%360-180)
