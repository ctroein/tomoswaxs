"""Prepare the sample-area mesh from editable CAD-coordinate inclusion boxes.

Usage: python tools/prepare_beamline_area.py INPUT.stl PREPARED_MODEL/model.json
Original CAD files and full-station meshes are retained.
Use --rebuild-station to also regenerate the full-station asset.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk
from prepare_beamline_model import read_stl,reduce_mesh


DEFAULT_REGIONS=Path(__file__).with_name('beamline_regions.json')


def load_regions(path=DEFAULT_REGIONS):
    regions=json.loads(Path(path).read_text())['regions_cad_mm']
    if not isinstance(regions,dict) or not regions:
        raise ValueError('Provide at least one inclusion box.')
    for name,box in regions.items():
        bounds=np.asarray(box,dtype=float)
        if not isinstance(name,str) or not name or bounds.shape!=(2,3) or not np.isfinite(bounds).all() or not np.all(bounds[0]<bounds[1]):
            raise ValueError(f'Invalid inclusion box: {name}')
    return regions


REGIONS=load_regions()
# Used only when explicitly rebuilding the whole-station asset. Sample-area
# selection is independent of this existing whole-model cleanup.
STATION_STAGE_EXCLUSION=([-90,810,-740],[110,1000,-300])


def inside(vertices,box):
    return np.all((vertices>=box[0])&(vertices<=box[1]),axis=(1,2))


def area_mask(vertices,regions=None):
    area=np.zeros(len(vertices),dtype=bool)
    for box in (REGIONS if regions is None else regions).values():area|=inside(vertices,box)
    return area


def masks(vertices,regions=None):
    stage=np.any(np.all((vertices>=STATION_STAGE_EXCLUSION[0])&(vertices<=STATION_STAGE_EXCLUSION[1]),axis=2),axis=1)
    return ~stage,area_mask(vertices,regions)


def write_mesh(triangles,default,keep,path,target):
    append=vtk.vtkAppendPolyData();count=int(keep.sum());ratio=min(1.,target/max(1,count))
    colours=triangles['colour']
    for colour in np.unique(colours[keep]):
        selected=keep&(colours==colour)
        mesh=reduce_mesh(triangles['vertices'][selected],ratio)
        rgb=default if int(colour)&32768 else tuple(round(((int(colour)>>s)&31)*255/31) for s in (0,5,10))
        scalars=numpy_to_vtk(np.tile(np.array(rgb,dtype=np.uint8),(mesh.GetNumberOfCells(),1)),deep=True)
        scalars.SetName('RGB');mesh.GetCellData().SetScalars(scalars);append.AddInputData(mesh)
    append.Update()
    output=append.GetOutput()
    writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(path));writer.SetInputData(output)
    writer.SetDataModeToAppended();writer.EncodeAppendedDataOff();writer.SetCompressorTypeToZLib()
    if not writer.Write():raise OSError(f'Could not write {path}')
    return dict(source_triangles=count,triangles=output.GetNumberOfCells())


def prepare(source,manifest_path,regions=None,rebuild_station=False):
    regions=REGIONS if regions is None else regions
    triangles,default=read_stl(source)
    directory=manifest_path.parent
    metadata_path=directory/'sample-area-components.json'
    previous=json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
    statistics={}
    if previous.get('station'):statistics['station']=previous['station']
    if rebuild_station:
        station,_=masks(triangles['vertices'],regions)
        statistics['station']=write_mesh(triangles,default,station,directory/'station.vtp',700000)
        print(f'Station: {statistics["station"]}',flush=True)
    area=area_mask(triangles['vertices'],regions)
    statistics['sample-area']=write_mesh(triangles,default,area,directory/'sample-area.vtp',180000)
    print(f'Sample area: {statistics["sample-area"]}',flush=True)
    manifest=json.loads(manifest_path.read_text())
    manifest['sample_area_geometry']='sample-area.vtp'
    if rebuild_station:
        manifest['geometry']='station.vtp';manifest['triangles']=statistics['station']['triangles']
    metadata=dict(source=source.name,regions_cad_mm=regions,
                  selection_rule='All three triangle vertices inside at least one inclusion box',**statistics)
    metadata_path.write_text(json.dumps(metadata,indent=2)+'\n')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('manifest',type=Path)
    parser.add_argument('--regions',type=Path,default=DEFAULT_REGIONS,help='Exported regions_cad_mm JSON')
    parser.add_argument('--rebuild-station',action='store_true',help='Also regenerate the full-station asset')
    args=parser.parse_args();prepare(args.source,args.manifest,load_regions(args.regions),args.rebuild_station)
