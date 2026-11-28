"""Prepare the supplied ForMAX binary STL for the viewer; keep source files intact.

Run from the checkout: python tools/prepare_beamline_model.py INPUT.stl OUTPUT_DIR
The output is a compressed VTP plus an editable model.json placement manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray


STL_TRIANGLE=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('colour','<u2')])


def read_stl(path):
    with path.open('rb') as stream:header=stream.read(84)
    if len(header)!=84:raise ValueError('Expected a binary STL.')
    count=struct.unpack('<I',header[80:84])[0]
    if path.stat().st_size!=84+50*count:raise ValueError('Invalid binary STL length.')
    if b'COLOR=' not in header[:80]:raise ValueError('Expected a Magics colour STL (COLOR= header).')
    start=header.index(b'COLOR=')+6
    return np.memmap(path,mode='r',offset=84,dtype=STL_TRIANGLE),tuple(header[start:start+3])


def tube_centre(triangles):
    """Fit long Y-parallel tube wall faces, excluding the supporting legs."""
    vertices=triangles['vertices']
    selected=(np.ptp(vertices[:,:,1],axis=1)>500)&(vertices[:,:,1].min(1)<-1500)&(abs(triangles['normal'][:,1])<.001)
    points=vertices[selected].reshape(-1,3)[:,[0,2]].astype(float)
    if len(points)<100:raise ValueError('Could not identify the ForMAX tube wall.')
    fit=np.linalg.lstsq(np.c_[2*points,np.ones(len(points))],(points**2).sum(1),rcond=None)[0]
    radius=float(np.sqrt(fit[2]+sum(fit[:2]**2)))
    error=float(np.max(abs(np.linalg.norm(points-fit[:2],axis=1)-radius)))
    if error>.1 or not 450<radius<550:raise ValueError('Tube fit does not match the supplied ForMAX assembly.')
    return fit[:2].tolist(),radius,error


def beam_reference(triangles):
    """Fit the upstream beam pipe, rather than the offset large vessel."""
    vertices=triangles['vertices'];low=vertices[:,:,1].min(1);high=vertices[:,:,1].max(1)
    selected=(low>1150)&(high<1210)&(high-low>40)&(abs(triangles['normal'][:,1])<.001)
    selected&=(abs(vertices[:,:,0]).max(1)<25)&(abs(vertices[:,:,2]+660).max(1)<25)
    points=vertices[selected].reshape(-1,3)[:,[0,2]].astype(float)
    fit=np.linalg.lstsq(np.c_[2*points,np.ones(len(points))],(points**2).sum(1),rcond=None)[0]
    radius=float(np.sqrt(fit[2]+sum(fit[:2]**2)))
    error=float(np.max(abs(np.linalg.norm(points-fit[:2],axis=1)-radius)))
    if len(points)<30 or error>.05 or not 19<radius<21:
        raise ValueError('Could not identify the upstream beam reference pipe.')
    return dict(centre_xz_mm=fit[:2].tolist(),radius_mm=radius,max_residual_mm=error)


def holder_reference(triangles):
    """Find the holder spindle's axial position; retain transverse pipe alignment."""
    vertices=triangles['vertices'];mid=vertices.mean(1)
    low=vertices[:,:,2].min(1);high=vertices[:,:,2].max(1)
    selected=(abs(mid[:,0])<100)&(abs(mid[:,1]-900)<100)&(low>-827)&(low<-826)&(high>-818.5)&(high<-817.8)&(high-low>8)&(abs(triangles['normal'][:,2])<.001)
    points=vertices[selected].reshape(-1,3)[:,:2].astype(float)
    fit=np.linalg.lstsq(np.c_[2*points,np.ones(len(points))],(points**2).sum(1),rcond=None)[0]
    radius=float(np.sqrt(fit[2]+sum(fit[:2]**2)))
    error=float(np.max(abs(np.linalg.norm(points-fit[:2],axis=1)-radius)))
    if len(points)<30 or error>.05 or not 17<radius<19:
        raise ValueError('Could not identify the sample holder spindle.')
    return dict(centre_xy_mm=fit[:2].tolist(),radius_mm=radius,max_residual_mm=error)


def reduce_mesh(vertices,ratio):
    points=vtk.vtkPoints();points.SetData(numpy_to_vtk(np.ascontiguousarray(vertices.reshape(-1,3)),deep=True))
    count=len(vertices)
    cells=vtk.vtkCellArray();cells.SetData(numpy_to_vtkIdTypeArray(np.arange(count+1,dtype=np.int64)*3,deep=True),
                                        numpy_to_vtkIdTypeArray(np.arange(count*3,dtype=np.int64),deep=True))
    mesh=vtk.vtkPolyData();mesh.SetPoints(points);mesh.SetPolys(cells)
    clean=vtk.vtkStaticCleanPolyData();clean.SetInputData(mesh);clean.Update()
    if ratio<1 and count>2000:
        decimate=vtk.vtkQuadricDecimation();decimate.SetInputConnection(clean.GetOutputPort())
        decimate.SetTargetReduction(1-ratio);decimate.VolumePreservationOn()
        decimate.SetBoundaryWeightFactor(10);decimate.Update();result=decimate.GetOutput()
    else:result=clean.GetOutput()
    normals=vtk.vtkPolyDataNormals();normals.SetInputData(result);normals.SetFeatureAngle(40)
    normals.ConsistencyOn();normals.AutoOrientNormalsOff();normals.Update()
    output=vtk.vtkPolyData();output.DeepCopy(normals.GetOutput());return output


def prepare(source,destination,target=700000,sample_y=None):
    destination.mkdir(parents=True,exist_ok=True)
    triangles,default=read_stl(source)
    centre,radius,fit_error=tube_centre(triangles)
    reference=beam_reference(triangles);holder=holder_reference(triangles)
    if sample_y is None:sample_y=holder['centre_xy_mm'][1]
    ratio=min(1.,target/len(triangles));append=vtk.vtkAppendPolyData();statistics=[]
    for colour in np.unique(triangles['colour']):
        before=time.perf_counter();vertices=triangles['vertices'][triangles['colour']==colour]
        rgb=default if int(colour)&32768 else tuple(round(((int(colour)>>s)&31)*255/31) for s in (0,5,10))
        mesh=reduce_mesh(vertices,ratio)
        values=np.tile(np.array(rgb,dtype=np.uint8),(mesh.GetNumberOfCells(),1))
        colours=numpy_to_vtk(values,deep=True);colours.SetName('RGB');mesh.GetCellData().SetScalars(colours)
        append.AddInputData(mesh)
        statistics.append(dict(rgb=rgb,input_triangles=len(vertices),output_triangles=mesh.GetNumberOfCells()))
        print(f'{rgb}: {len(vertices):,} → {mesh.GetNumberOfCells():,} triangles ({time.perf_counter()-before:.1f}s)',flush=True)
    append.Update()
    writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(destination/'geometry.vtp'))
    writer.SetInputConnection(append.GetOutputPort());writer.SetDataModeToAppended();writer.EncodeAppendedDataOff();writer.SetCompressorTypeToZLib()
    if not writer.Write():raise OSError('Could not write reduced geometry.')
    digest=hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    manifest=dict(version=1,name='ForMAX',geometry='geometry.vtp',units='millimeter',
        sample_position_cad_mm=[reference['centre_xz_mm'][0],sample_y,reference['centre_xz_mm'][1]],
        beam_axis_fit=reference,holder_axis_fit=holder,
        # Proper rotation: CAD +Z is up, CAD -Y is downstream.
        cad_to_lab_rotation=[[1,0,0],[0,0,1],[0,-1,0]],
        tube_fit=dict(centre_xz_mm=centre,radius_mm=radius,max_residual_mm=fit_error),
        sample_position_estimated=True,
        source=dict(filename=source.name,sha256=digest.hexdigest(),triangles=len(triangles)),
        triangles=append.GetOutput().GetNumberOfCells(),colours=statistics,
        labels=[dict(text='Experimental table',position_cad_mm=[-400,1150,-1100],offset_px=[-100,-70]),
                dict(text='Detector gantry',position_cad_mm=[850,350,-100],offset_px=[20,60]),
                dict(text='WAXS detector',position_cad_mm=[0,687,-700],offset_px=[20,-65]),
                dict(text='SAXS detector',position_cad_mm=[120,294,-700],offset_px=[110,25]),
                dict(text='Tomography microscope',position_cad_mm=[-740,840,-620],offset_px=[-140,60]),
                dict(text='Flight tube',position_cad_mm=[centre[0]+500,-1200,centre[1]],offset_px=[30,30])])
    (destination/'model.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Total: {manifest["triangles"]:,} triangles; {(destination/"geometry.vtp").stat().st_size/1024**2:.1f} MiB',flush=True)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--triangles',type=int,default=700000)
    parser.add_argument('--sample-cad-y',type=float,default=None,help='Override holder-derived sample position along the CAD beam axis, mm')
    args=parser.parse_args()
    if args.triangles<1000:parser.error('--triangles must be at least 1000')
    prepare(args.source,args.destination,args.triangles,args.sample_cad_y)
