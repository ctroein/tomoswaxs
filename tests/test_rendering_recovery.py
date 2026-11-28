"""Rebuilding GPU resources retains the CPU scene and scientific/viewing state."""
import asyncio
import unittest
import uuid
from unittest.mock import patch

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.app import Demo as Application
from tomoswaxs.volume_viewing import array_source


class RenderingRecoveryChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('recovery-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        z,y,x=np.indices((48,48,48))
        values=np.uint16(((x-24)**2+(y-24)**2+(z-24)**2<16**2)*50000)
        app.volume=values;app.spacing=np.full(3,.02);app.origin=np.full(3,-.47)
        app._empty_source=array_source(values,app.spacing,app.origin)
        app.sync_volume_controls();app.set_image_data();app.reset_camera();app.update_scene()
        app.window.SetSize(320,240)
        return app

    def pixels(self,app):
        app.window.Render();app.window.WaitForCompletion()
        capture=vtk.vtkWindowToImageFilter();capture.SetInput(app.window);capture.ShouldRerenderOff();capture.Update()
        return vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).copy()

    def test_repeated_resource_rebuild_retains_volume_camera_and_pixels(self):
        app=self.app();before=self.pixels(app)
        view=app.capture_view();values=app.volume;image=app.mapper.GetInput();mapper=app.mapper;window=app.window
        for _ in range(2):
            asyncio.run(app.reinitialise_rendering())
            self.assertFalse(app.state.render_reinitialising)
            self.assertEqual(app.state.render_reinitialise_error,'')
            self.assertEqual(app.capture_view(),view)
            self.assertIs(app.volume,values);self.assertIs(app.mapper.GetInput(),image)
            self.assertIs(app.mapper,mapper);self.assertIs(app.window,window)
            after=self.pixels(app)
            self.assertGreater(np.count_nonzero(after.max(axis=1)>100),1000)
            self.assertLess(np.abs(after.astype(float)-before).mean(),2.)

    def test_failure_is_visible_and_does_not_leave_the_action_busy(self):
        app=self.app();view=app.capture_view()
        with patch('tomoswaxs.app.reinitialise_graphics',side_effect=RuntimeError('GPU reset failed')),self.assertLogs('tomoswaxs.app',level='ERROR'):
            asyncio.run(app.reinitialise_rendering())
        self.assertIn('GPU reset failed',app.state.render_reinitialise_error)
        self.assertFalse(app.state.render_reinitialising)
        self.assertEqual(app.capture_view(),view)

    def test_reset_is_guarded_during_sample_loading_and_another_reset(self):
        app=self.app()
        with patch('tomoswaxs.app.reinitialise_graphics') as rebuild:
            app.state.volume_loading=True;asyncio.run(app.reinitialise_rendering())
            app.state.volume_loading=False;app.state.render_reinitialising=True
            asyncio.run(app.reinitialise_rendering());rebuild.assert_not_called()

    def test_empty_startup_can_reinitialise_before_the_first_frame(self):
        app=Application(get_server('empty-recovery-'+uuid.uuid4().hex,client_type='vue3'),render_device='system')
        self.addCleanup(app.window.Finalize)
        asyncio.run(app.reinitialise_rendering())
        self.assertFalse(app.state.render_reinitialising)
        self.assertEqual(app.state.render_reinitialise_error,'')
        self.assertFalse(app.state.has_sample)
