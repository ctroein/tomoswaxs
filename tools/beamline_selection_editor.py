"""Create an offline 3D editor for CAD-coordinate inclusion boxes.

Usage: python tools/beamline_selection_editor.py MODEL.vtp OUTPUT.html --regions BOXES.json
The output embeds the mesh, Plotly and controls. No web server is required.
"""
import argparse
import json
from pathlib import Path
import re
from string import Template

import numpy as np
import plotly.graph_objects as go
import vtk
from vtk.util.numpy_support import vtk_to_numpy,numpy_to_vtk,numpy_to_vtkIdTypeArray

from prepare_beamline_area import DEFAULT_REGIONS,load_regions,area_mask


COLOURS=['#28cdd0','#f5b642','#bf88ff','#ff8274','#6fd897','#6ca9ff']


def _polydata(points,faces):
    mesh=vtk.vtkPolyData();vertices=vtk.vtkPoints();vertices.SetData(numpy_to_vtk(points,deep=True));mesh.SetPoints(vertices)
    cells=vtk.vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(len(faces)+1,dtype=np.int64)*3,deep=True),
                  numpy_to_vtkIdTypeArray(np.ascontiguousarray(faces.reshape(-1),dtype=np.int64),deep=True))
    mesh.SetPolys(cells)
    clean=vtk.vtkStaticCleanPolyData();clean.SetInputData(mesh);clean.Update()
    output=vtk.vtkPolyData();output.DeepCopy(clean.GetOutput());return output


def preview_mesh(mesh,regions,max_triangles):
    """Keep initially selected triangles; simplify only surrounding context."""
    triangles=vtk.vtkTriangleFilter();triangles.SetInputData(mesh);triangles.Update();mesh=triangles.GetOutput()
    points=vtk_to_numpy(mesh.GetPoints().GetData());faces=vtk_to_numpy(mesh.GetPolys().GetConnectivityArray()).reshape(-1,3)
    if not len(faces):raise ValueError('The model contains no triangles.')
    if max_triangles<=0 or len(faces)<=max_triangles:return mesh
    included=area_mask(points[faces],regions)
    context=_polydata(points,faces[~included]);target=max(1000,max_triangles-int(included.sum()))
    if context.GetNumberOfCells()>target:
        reduce=vtk.vtkQuadricDecimation();reduce.SetInputData(context)
        reduce.SetTargetReduction(1-target/context.GetNumberOfCells());reduce.VolumePreservationOn();reduce.Update()
        context=reduce.GetOutput()
    append=vtk.vtkAppendPolyData();append.AddInputData(context)
    if included.any():append.AddInputData(_polydata(points,faces[included]))
    append.Update()
    normals=vtk.vtkPolyDataNormals();normals.SetInputConnection(append.GetOutputPort());normals.SetFeatureAngle(40);normals.Update()
    output=vtk.vtkPolyData();output.DeepCopy(normals.GetOutput());return output


def outline(box):
    corners=np.array([[x,y,z] for x in (box[0][0],box[1][0]) for y in (box[0][1],box[1][1]) for z in (box[0][2],box[1][2])])
    points=[]
    for a in range(8):
        for b in range(a+1,8):
            if (a^b) in (1,2,4):points.extend([corners[a].tolist(),corners[b].tolist(),[None]*3])
    return {key:[point[axis] for point in points] for axis,key in enumerate('xyz')}


def generate(model_path,output_path,regions,max_triangles=250000):
    reader=vtk.vtkXMLPolyDataReader();reader.SetFileName(str(model_path));reader.Update()
    if not reader.GetOutput().GetNumberOfCells():raise ValueError(f'Empty or unreadable model: {model_path}')
    mesh=preview_mesh(reader.GetOutput(),regions,max_triangles)
    points=vtk_to_numpy(mesh.GetPoints().GetData()).astype(np.float32)
    faces=vtk_to_numpy(mesh.GetPolys().GetConnectivityArray()).reshape(-1,3).astype(np.int32)
    common=dict(type='mesh3d',showlegend=True,flatshading=False,
                lighting=dict(ambient=.55,diffuse=.75,specular=.08,roughness=.8),hoverinfo='name')
    data=[go.Mesh3d(**common,name='Other geometry',legendgroup='other',color='#7c8793',
                   x=points[:,0],y=points[:,1],z=points[:,2],i=faces[:,0],j=faces[:,1],k=faces[:,2])]
    colours=[COLOURS[n%len(COLOURS)] for n in range(len(regions))]
    for (name,box),colour in zip(regions.items(),colours):
        data.append(go.Mesh3d(**common,name=name,legendgroup=name,color=colour,x=[],y=[],z=[],i=[],j=[],k=[]))
    for (name,box),colour in zip(regions.items(),colours):
        data.append(go.Scatter3d(**outline(box),mode='lines',line=dict(color=colour,width=3),name=name+' box',legendgroup=name,showlegend=False,hoverinfo='skip'))
    figure=go.Figure(data)
    figure.update_layout(paper_bgcolor='#0d1420',font=dict(color='#e8eef6',size=14),margin=dict(l=0,r=0,b=0,t=0),
                         scene=dict(aspectmode='data',bgcolor='#0d1420',camera=dict(eye=dict(x=-1.4,y=1.6,z=.9),up=dict(x=0,y=0,z=1)),
                                    **{axis+'axis':dict(title=f'CAD {axis.upper()} (mm)',showbackground=False,showgrid=False,zeroline=False) for axis in 'xyz'}),
                         legend=dict(x=.01,y=.99,bgcolor='rgba(13,20,32,.85)',groupclick='togglegroup'),uirevision='selection-editor')
    plot=figure.to_html(full_html=False,include_plotlyjs=True,div_id='model',config=dict(scrollZoom=True,displaylogo=False,responsive=True))
    plot,count=re.subn(r'Plotly\.newPlot\(\s*"model",','window.selectionPlotReady = Plotly.newPlot("model",',plot,count=1)
    if count!=1:raise ValueError('Could not initialise the Plotly editor.')
    config=dict(names=list(regions),boxes=list(regions.values()),labels=list(regions),colours=colours,
                sourceMeshCount=1,sample=[0,0,0],rotation=[[1,0,0],[0,1,0],[0,0,1]])
    folder=Path(__file__).parent
    html=Template((folder/'beamline_selection_editor.html').read_text()).substitute(
        plot=plot,config=json.dumps(config).replace('<','\\u003c'),script=(folder/'beamline_selection_editor.js').read_text())
    output_path.parent.mkdir(parents=True,exist_ok=True);output_path.write_text(html)
    return len(faces)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--regions',type=Path,default=DEFAULT_REGIONS,help='Editor-exported regions_cad_mm JSON')
    parser.add_argument('--max-triangles',type=int,default=250000,help='Preview target; selected surfaces are retained. Use 0 for the full mesh.')
    args=parser.parse_args()
    count=generate(args.model,args.output,load_regions(args.regions),args.max_triangles)
    print(f'{args.output} ({count:,} triangles)')
