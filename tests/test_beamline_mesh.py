"""CAD placement must preserve the beam frame and remain independent of CT pose."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

import numpy as np
import vtk
from trame.app import get_server

from tomoswaxs.beamline_mesh import CadBeamlineModel,placement
from sample_fixture import Demo


class CadBeamlineChecks(unittest.TestCase):
    def fixture(self,root):
        cube=vtk.vtkCubeSource();cube.SetCenter(100,-100,-700)
        cube.SetXLength(1000);cube.SetYLength(2500);cube.SetZLength(800);cube.Update()
        rgb=vtk.vtkUnsignedCharArray();rgb.SetName('RGB');rgb.SetNumberOfComponents(3)
        for _ in range(cube.GetOutput().GetNumberOfCells()):rgb.InsertNextTuple3(82,120,140)
        cube.GetOutput().GetCellData().SetScalars(rgb)
        writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(root/'geometry.vtp'))
        writer.SetInputData(cube.GetOutput());self.assertEqual(writer.Write(),1)
        manifest=dict(version=1,units='millimeter',geometry='geometry.vtp',sample_position_cad_mm=[120,750,-700],
                      cad_to_lab_rotation=[[1,0,0],[0,0,1],[0,-1,0]],labels=[])
        path=root/'model.json';path.write_text(json.dumps(manifest));return path,manifest

    def test_sample_beam_and_vertical_axes(self):
        with tempfile.TemporaryDirectory() as root:
            path,manifest=self.fixture(Path(root));matrix=placement(manifest)
            np.testing.assert_allclose(matrix@[120,750,-700,1],[0,0,0,1])
            np.testing.assert_allclose(matrix@[120,-250,-700,1],[0,0,1000,1])
            np.testing.assert_allclose(matrix@[120,750,-600,1],[0,100,0,1])
            manifest['sample_position_cad_mm'][1]+=50
            np.testing.assert_allclose((placement(manifest)@np.array([120,750,-700,1]))[:3],[0,0,50])
            manifest['cad_to_lab_rotation'][0][0]=-1
            with self.assertRaises(ValueError):placement(manifest)

    def test_colours_bounds_and_scientific_pose(self):
        with tempfile.TemporaryDirectory() as root:
            path,_=self.fixture(Path(root))
            app=Demo(get_server('cad-'+uuid.uuid4().hex,client_type='vue3'),beamline_model=path)
            self.addCleanup(app.window.Finalize)
            self.assertIsInstance(app.beamline,CadBeamlineModel)
            mesh=app.beamline.parts['ForMAX CAD'].GetMapper().GetInput()
            self.assertEqual(mesh.GetCellData().GetScalars().GetTuple3(0),(82,120,140))
            bounds=app.beamline.parts['ForMAX CAD'].GetBounds()
            np.testing.assert_allclose(bounds,[-520,480,-400,400,-400,2100])
            before=app.capture_view()
            for preset in ('station','stack'):
                app.beamline_camera(preset);app.window.Render()
                for key in ('angle','beam_x','beam_y','opacity'):
                    self.assertEqual(app.capture_view()[key],before[key])
                self.assertEqual(app.beamline.parts['ForMAX CAD'].GetBounds(),bounds)
            self.assertFalse(app.beamline.parts['sample marker'].GetVisibility())
            self.assertIn('tomo_ry',app.beamline.parts)
            app.select_beamline_level('area')
            self.assertFalse(app.beamline.parts['ForMAX CAD'].GetVisibility())
            self.assertTrue(app.beamline.parts['tomo_ry'].GetVisibility())

    def test_compact_stack_and_extended_beam_preserve_measurement_pose(self):
        with tempfile.TemporaryDirectory() as root:
            path,_=self.fixture(Path(root))
            app=Demo(get_server('cad-beam-'+uuid.uuid4().hex,client_type='vue3'),beamline_model=path)
            self.addCleanup(app.window.Finalize)
            with app.state:
                app.state.saxs_available=True
                app.state.beam_x=200;app.state.beam_y=-100
            app.update_scene()
            local=app.beam.GetBounds();pose=app.capture_view()
            self.assertAlmostEqual(app.beamline.parts['swaxs_y'].GetBounds()[2],-140)
            self.assertAlmostEqual(app.beamline.parts['swaxs_y'].GetBounds()[1]-app.beamline.parts['swaxs_y'].GetBounds()[0],91)
            self.assertNotIn('beam path',app.beamline.parts)
            self.assertFalse(any(name.startswith('tube entrance') for name in app.beamline.parts))
            for level in ('area','station'):
                app.select_beamline_level(level);app.window.Render()
                beam=app.beam.GetBounds();bounds=app.beamline.bounds
                self.assertLessEqual(beam[4],bounds[4]+1e-6)
                self.assertGreaterEqual(beam[5],bounds[5]-1e-6)
                np.testing.assert_allclose(beam[:4],local[:4])
                for key in ('angle','beam_x','beam_y'):
                    self.assertEqual(app.capture_view()[key],pose[key])
                app.state.beam_visible=False;app.beam_visibility_changed()
                self.assertFalse(app.beam.GetVisibility())
                app.state.beam_visible=True
            app.select_beamline_level('sample');app.window.Render()
            np.testing.assert_allclose(app.beam.GetBounds(),local)

    def test_missing_geometry_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            path,_=self.fixture(Path(root));(Path(root)/'geometry.vtp').unlink()
            with self.assertRaisesRegex(ValueError,'geometry is missing'):
                CadBeamlineModel(vtk.vtkRenderer(),path)

    def test_prepared_area_mesh_replaces_the_full_actor_at_area_level(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);path,manifest=self.fixture(root)
            cube=vtk.vtkCubeSource();cube.SetCenter(120,600,-700);cube.SetXLength(50)
            writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(root/'area.vtp'))
            writer.SetInputConnection(cube.GetOutputPort());writer.Write()
            manifest['sample_area_geometry']='area.vtp';path.write_text(json.dumps(manifest))
            model=CadBeamlineModel(vtk.vtkRenderer(),path)
            model.show('area')
            self.assertFalse(model.parts['ForMAX CAD'].GetVisibility())
            self.assertTrue(model.parts['Sample area CAD'].GetVisibility())
            self.assertTrue(model.parts['tomo_ry'].GetVisibility())
            model.show('station')
            self.assertTrue(model.parts['ForMAX CAD'].GetVisibility())
            self.assertFalse(model.parts['Sample area CAD'].GetVisibility())
            model.show('sample')
            self.assertFalse(any(actor.GetVisibility() for actor in model.parts.values()))
