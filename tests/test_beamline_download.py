"""First-use acquisition, transactional scene replacement and saved-camera recovery."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

import numpy as np
import vtk
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.beamline_mesh import CadBeamlineModel
from tomoswaxs.model_store import ModelDownloadError


class BeamlineDownloadChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        cube=vtk.vtkCubeSource();cube.SetXLength(300);cube.SetYLength(500);cube.SetZLength(300)
        writer=vtk.vtkXMLPolyDataWriter();writer.SetFileName(str(self.root/'geometry.vtp'))
        writer.SetInputConnection(cube.GetOutputPort());writer.Write()
        self.manifest=self.root/'model.json'
        self.manifest.write_text(json.dumps(dict(version=1,units='millimeter',geometry='geometry.vtp',
                             sample_area_geometry='geometry.vtp',sample_position_cad_mm=[0,0,0],
                             cad_to_lab_rotation=[[1,0,0],[0,1,0],[0,0,1]],labels=[])))

    def app(self):
        app=Demo(get_server('download-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        app._beamline_release=object()
        return app

    async def test_download_is_lazy_and_reused_across_levels(self):
        with patch('tomoswaxs.beamline_download.ensure_model',return_value=self.manifest) as ensure:
            app=self.app();before=app.capture_view();ensure.assert_not_called()
            app.select_beamline_level('area')
            self.assertTrue(app.state.beamline_model_loading)
            self.assertEqual(app.state.beamline_level,'sample')
            await app._beamline_download_task
            self.assertIsInstance(app.beamline,CadBeamlineModel)
            self.assertEqual(app.state.beamline_level,'area')
            self.assertFalse(app.state.show_beamline_download)
            self.assertFalse(app.state.beamline_model_loading)
            for key in ('angle','beam_x','beam_y','opacity'):
                self.assertEqual(app.capture_view()[key],before[key])
            app.select_beamline_level('station');app.select_beamline_level('sample')
            ensure.assert_called_once()

    async def test_saved_camera_is_preserved_when_a_model_arrives(self):
        app=self.app();app._beamline_release=None;app.select_beamline_level('area')
        saved=app.capture_view();app.select_beamline_level('sample')
        app._beamline_release=object();app._beamline_download_ready=True
        with patch('tomoswaxs.beamline_download.ensure_model',return_value=self.manifest):
            app.restore_view(saved);await app._beamline_download_task
        self.assertIsInstance(app.beamline,CadBeamlineModel)
        for key in ('position','focal_point','view_up','view_angle','parallel_scale','parallel_projection'):
            np.testing.assert_allclose(app.capture_view()['camera'][key],saved['camera'][key],rtol=0,atol=1e-12)

    async def test_failure_preserves_scene_and_retry_works(self):
        app=self.app();original=app.beamline;actors=app.renderer.GetActors().GetNumberOfItems()
        # Model validation fails after several props have been created. None
        # may leak into the live renderer or replace the previous equipment.
        document=json.loads(self.manifest.read_text());document['sample_area_geometry']='missing.vtp'
        self.manifest.write_text(json.dumps(document))
        with patch('tomoswaxs.beamline_download.ensure_model',return_value=self.manifest),self.assertLogs('tomoswaxs.beamline_download',level='ERROR'):
            app.select_beamline_level('area');await app._beamline_download_task
        self.assertIs(app.beamline,original)
        self.assertEqual(app.renderer.GetActors().GetNumberOfItems(),actors)
        self.assertEqual(app.state.beamline_level,'sample')
        self.assertIn('missing',app.state.beamline_download_error)
        self.assertTrue(app.state.show_beamline_download)
        document['sample_area_geometry']='geometry.vtp';self.manifest.write_text(json.dumps(document))
        with patch('tomoswaxs.beamline_download.ensure_model',return_value=self.manifest):
            app.retry_beamline_download();await app._beamline_download_task
        self.assertIsInstance(app.beamline,CadBeamlineModel)
        self.assertFalse(app.state.beamline_download_error)

    async def test_cancel_and_late_network_failure_do_not_change_the_view(self):
        app=self.app();original=app.beamline;entered=threading.Event()
        def slow(release,*,progress,cancelled):
            entered.set()
            while not cancelled():time.sleep(.005)
            raise ModelDownloadError('Network stopped after cancellation')
        with patch('tomoswaxs.beamline_download.ensure_model',side_effect=slow):
            app.select_beamline_level('area')
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            app.select_beamline_level('sample');await app._beamline_download_task
        self.assertIs(app.beamline,original);self.assertEqual(app.state.beamline_level,'sample')
        self.assertFalse(app.state.show_beamline_download)
        self.assertFalse(app.state.beamline_download_error)
        self.assertFalse(app.state.beamline_model_loading)
