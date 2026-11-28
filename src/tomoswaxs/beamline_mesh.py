"""Prepared beamline CAD assets and their placement in the laboratory frame."""
import json
from pathlib import Path

import numpy as np
import vtk

from .beamline import BeamlineModel


def default_beamline_model(data_directory=None):
    """Find the optional local asset beside a checkout or in its data directory."""
    directories=([Path(data_directory)] if data_directory else [])+[Path.cwd()/'data',Path.cwd().parent/'data']
    for directory in directories:
        path=directory/'3dmodel/formax-reduced/model.json'
        if path.is_file():return path
    return None


def placement(manifest):
    sample=np.asarray(manifest['sample_position_cad_mm'],dtype=float)
    rotation=np.asarray(manifest['cad_to_lab_rotation'],dtype=float)
    if sample.shape!=(3,) or rotation.shape!=(3,3) or not np.isfinite(sample).all() or not np.isfinite(rotation).all():
        raise ValueError('Invalid beamline placement coordinates.')
    if not np.allclose(rotation@rotation.T,np.eye(3)) or not np.isclose(np.linalg.det(rotation),1):
        raise ValueError('Beamline placement must use a proper rotation.')
    matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[:3,3]=-rotation@sample
    return matrix


class CadBeamlineModel(BeamlineModel):
    def __init__(self,renderer,path):
        self.parts={};self.labels=[];self.renderer=renderer
        self.manifest_path=Path(path).expanduser().resolve()
        manifest=json.loads(self.manifest_path.read_text())
        if manifest.get('version')!=1 or manifest.get('units')!='millimeter':
            raise ValueError('Unsupported beamline model manifest.')
        self.placement=placement(manifest)
        self.cad_actor('ForMAX CAD',manifest['geometry'])
        self.motor_stack()
        self.cylinder('sample marker',(0,0,0),.7,2,(.16,.65,.64))
        self.station_parts=set(self.parts)
        self.area_parts={'sample marker','swaxs_y','swaxs_x','tomo_ry','tomo_xf','tomo_zf','sample holder'}
        if manifest.get('sample_area_geometry'):
            self.cad_actor('Sample area CAD',manifest['sample_area_geometry'])
            self.area_parts.add('Sample area CAD')
        else:
            # Older/private assets may only have the complete mesh. Use the
            # schematic detector context until an area asset is prepared.
            for name,point,size in [('WAXS detector',(0,0,150),(240,240,30)),
                                    ('SAXS detector',(0,0,450),(155,162,35))]:
                self.box(name,point,size,(.43,.51,.58));self.area_parts.add(name)
        for label in manifest.get('labels',[]):
            point=(self.placement@np.r_[label['position_cad_mm'],1])[:3]
            scope='context' if label['text'] in ('WAXS detector','SAXS detector') else 'station'
            self.label(label['text'],point,scope,offset=label.get('offset_px',(12,8)))
        self.label('Sample (estimated)',(0,0,0),'station',offset=(-160,-35))
        self.label('Motor stack',(0,-60,0),'context',offset=(-100,-15))
        for name in ('swaxs_y','swaxs_x','tomo_ry','tomo_xf','tomo_zf'):
            self.label(name,self.parts[name].GetCenter(),'stack',offset=(130,8))
        self.label('Sample',(0,0,0),'stack',offset=(30,25))
        self.station_bounds=self.bounds_for(self.station_parts)
        self.area_bounds=self.bounds_for(self.area_parts)
        self.bounds=self.station_bounds
        self.fit_station=True
        self.show(False)

    def cad_actor(self,name,filename):
        geometry=(self.manifest_path.parent/filename).resolve()
        if not geometry.is_file():raise ValueError(f'Beamline geometry is missing: {geometry}')
        reader=vtk.vtkXMLPolyDataReader();reader.SetFileName(str(geometry));reader.Update()
        mesh=reader.GetOutput()
        if not mesh.GetNumberOfCells():raise ValueError(f'Beamline geometry is empty or unreadable: {geometry}')
        mapper=vtk.vtkPolyDataMapper();mapper.SetInputData(mesh)
        mapper.SetScalarModeToUseCellData();mapper.SetColorModeToDirectScalars()
        actor=vtk.vtkActor();actor.SetMapper(mapper);actor.PickableOff()
        actor.GetProperty().SetAmbient(.3);actor.GetProperty().SetDiffuse(.7)
        matrix=vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4):matrix.SetElement(i,j,self.placement[i,j])
        actor.SetUserMatrix(matrix);self.renderer.AddActor(actor);self.parts[name]=actor
        return actor
