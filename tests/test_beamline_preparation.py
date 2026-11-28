"""CAD references and equipment masks are independent of OBJ grouping."""
from pathlib import Path
import sys
import unittest

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
from prepare_beamline_model import STL_TRIANGLE,beam_reference,holder_reference
from prepare_beamline_area import masks,area_mask,load_regions
from beamline_selection_editor import generate,preview_mesh
sys.path.pop(0)


class PreparationChecks(unittest.TestCase):
    def cylinder(self,radius,height,centre,vertical=False):
        source=vtk.vtkCylinderSource();source.SetRadius(radius);source.SetHeight(height);source.SetResolution(64)
        triangles=vtk.vtkTriangleFilter();triangles.SetInputConnection(source.GetOutputPort());triangles.Update()
        mesh=triangles.GetOutput();p=vtk_to_numpy(mesh.GetPoints().GetData())
        faces=vtk_to_numpy(mesh.GetPolys().GetConnectivityArray()).reshape(-1,3)
        v=p[faces].astype(float)
        if vertical:v=v[:,:,[0,2,1]]
        v+=centre
        normals=np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0]);normals/=np.linalg.norm(normals,axis=1)[:,None]
        result=np.zeros(len(v),dtype=STL_TRIANGLE);result['vertices']=v;result['normal']=normals
        return result

    def test_pipe_and_holder_references(self):
        pipe=self.cylinder(20,47.7,[0,1183.25,-659.912])
        vessel=self.cylinder(507.5,753,[120.886,-2000,-699.743])
        holder=self.cylinder(18,9,[23.186844,899.899384,-822.4],vertical=True)
        data=np.concatenate([pipe,vessel,holder])
        fit=beam_reference(data);position=holder_reference(data)
        np.testing.assert_allclose(fit['centre_xz_mm'],[0,-659.912],atol=1e-4)
        np.testing.assert_allclose(position['centre_xy_mm'],[23.186844,899.899384],atol=1e-4)
        self.assertLess(fit['max_residual_mm'],.001)

    def test_four_boxes_select_equipment(self):
        points=np.array([[0,670,-660],[80,290,-620],[0,1100,-660],
                         [20,900,-780],[0,895,-665],[-740,840,-620],[800,350,-100]])
        vertices=np.repeat(points[:,None,:],3,axis=1).astype(float)
        vertices[:,1,0]+=1;vertices[:,2,2]+=1
        station,area=masks(vertices)
        np.testing.assert_array_equal(station,[True,True,True,True,False,True,True])
        np.testing.assert_array_equal(area,[True,True,True,True,False,False,False])

    def test_area_uses_boxes_without_stage_or_component_exclusion(self):
        vertices=np.array([
            [[0,995,-660],[1,1139,-660],[0,1139,-659]],
            [[0,1190,-660],[1,1207,-660],[0,1190,-659]],
            [[250,325,-450],[251,325,-450],[250,326,-450]],
        ],dtype=float)
        station,area=masks(vertices)
        self.assertFalse(station[0])
        np.testing.assert_array_equal(area,[True,False,True])

    def test_saved_editor_embeds_model_and_exported_regions(self):
        import json
        import tempfile
        regions=load_regions()
        cube=vtk.vtkCubeSource();cube.SetCenter(0,1100,-660)
        triangles=vtk.vtkTriangleFilter();triangles.SetInputConnection(cube.GetOutputPort());triangles.Update()
        with tempfile.TemporaryDirectory() as directory:
            model=Path(directory)/'model.vtp';output=Path(directory)/'editor.html'
            writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(model));writer.SetInputData(triangles.GetOutput());writer.Write()
            self.assertEqual(generate(model,output,regions),12)
            html=output.read_text()
            config=json.loads(html.split('<script id="selection-config" type="application/json">')[1].split('</script>')[0])
            self.assertEqual(dict(zip(config['names'],config['boxes'])),regions)
            self.assertEqual(config['sourceMeshCount'],1)
            self.assertIn('window.selectionPlotReady = Plotly.newPlot(',html)
            self.assertIn('beamline-selection.json',html)
            self.assertNotIn('$plot',html)

    def test_preview_simplifies_context_but_preserves_selected_surfaces(self):
        append=vtk.vtkAppendPolyData()
        for centre in [(0,1100,-660),(1000,1000,1000)]:
            sphere=vtk.vtkSphereSource();sphere.SetCenter(*centre);sphere.SetRadius(10)
            sphere.SetThetaResolution(32);sphere.SetPhiResolution(32);sphere.Update()
            append.AddInputData(sphere.GetOutput())
        append.Update();original=append.GetOutput()
        def selected_count(mesh):
            points=vtk_to_numpy(mesh.GetPoints().GetData())
            faces=vtk_to_numpy(mesh.GetPolys().GetConnectivityArray()).reshape(-1,3)
            return int(area_mask(points[faces]).sum())
        preview=preview_mesh(original,load_regions(),2100)
        self.assertLess(preview.GetNumberOfCells(),original.GetNumberOfCells())
        self.assertEqual(selected_count(preview),selected_count(original))
