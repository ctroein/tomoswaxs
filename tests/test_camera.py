"""Camera orbiting changes the view, with no measured-pose or SAXS updates."""
import unittest,uuid
from unittest.mock import patch
import numpy as np
from trame.app import get_server
from sample_fixture import Demo


class CameraChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('camera-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        return app

    def test_camera_angle_preserves_sample_and_scattering(self):
        app=self.app();before=app.capture_view();signal=app.signal
        matrix=np.array([[app.sample.GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
        distance=app.renderer.GetActiveCamera().GetDistance()
        with patch.object(app,'saxs_from_pose') as saxs,patch.object(app,'update_plots') as plots:
            app.receive_camera_angle(90,True,app.state.sample_context)
            saxs.assert_not_called();plots.assert_not_called()
        self.assertEqual(app.state.camera_angle,90)
        after=app.capture_view()
        for key in ('beam_x','beam_y','angle'):self.assertEqual(after[key],before[key])
        self.assertIs(app.signal,signal)
        np.testing.assert_array_equal(matrix,[[app.sample.GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
        self.assertAlmostEqual(app.renderer.GetActiveCamera().GetDistance(),distance)

    def test_crop_controls_and_default_camera_share_the_visible_centre(self):
        app=self.app();crop=[[10,40],[20,60],[30,80]]
        app.publish_crop(dict(crop=crop,level='auto'))
        app.set_crop_planes(crop)
        centre=app.visible_crop_centre()
        cam=app.renderer.GetActiveCamera()
        np.testing.assert_allclose(cam.GetFocalPoint(),centre)
        distance=cam.GetDistance()
        for angle in (0,90,180,-90):
            app.receive_camera_angle(angle,False,app.state.sample_context)
            np.testing.assert_allclose(cam.GetFocalPoint(),centre)
            self.assertAlmostEqual(cam.GetDistance(),distance)
        app.reset_camera()
        np.testing.assert_allclose(cam.GetFocalPoint(),centre,atol=1e-12)

    def test_invalid_or_old_camera_requests_do_not_move_the_camera(self):
        app=self.app();before=app.capture_view()['camera']
        for value,context in [(90,'old'),(float('nan'),app.state.sample_context),('',app.state.sample_context)]:
            app.receive_camera_angle(value,True,context)
        self.assertEqual(app.capture_view()['camera'],before)
        app.renderer.GetActiveCamera().Azimuth(30)
        app.sync_camera_angle()
        self.assertNotEqual(app.state.camera_angle,0)

    def test_beam_view_is_a_single_context_checked_alignment(self):
        app=self.app();app.receive_camera_angle(80)
        before=app.capture_view()
        app.receive_beam_view('old')
        self.assertEqual(app.capture_view(),before)
        app.receive_beam_view(app.state.sample_context)
        cam=app.renderer.GetActiveCamera()
        np.testing.assert_allclose(cam.GetDirectionOfProjection(),[0,0,-1])
        self.assertEqual(app.state.camera_angle,0)
        for key in ('beam_x','beam_y','angle'):
            self.assertEqual(app.capture_view()[key],before[key])
        app.receive_camera_angle(45)
        self.assertAlmostEqual(app.state.camera_angle,45)

    def test_beam_view_projects_offset_beam_end_on(self):
        app=self.app()
        with app.state:
            app.state.beam_x=500.
            app.state.beam_y=-300.
            app.state.angle=60.
        crop=[[10,100],[20,130],[30,150]]
        app.publish_crop(dict(crop=crop,level='auto'))
        app.set_crop_planes(crop)
        app.receive_beam_view(app.state.sample_context)
        cam=app.renderer.GetActiveCamera()
        np.testing.assert_allclose(cam.GetDirectionOfProjection(),[0,0,-1],atol=1e-12)
        pixels=[]
        for z in (-app.beam_length/2,app.beam_length/2):
            app.renderer.SetWorldPoint(.5,-.3,z,1)
            app.renderer.WorldToDisplay()
            pixels.append(app.renderer.GetDisplayPoint()[:2])
        np.testing.assert_allclose(pixels[0],pixels[1],atol=1e-6,
            err_msg='Both ends of an offset beam must project to the same screen point')
        np.testing.assert_allclose(pixels[0],np.array(app.window.GetSize())/2,atol=1e-6)

    def test_beam_view_stays_end_on_when_measurement_moves(self):
        app=self.app()
        app.receive_beam_view(app.state.sample_context)
        cam=app.renderer.GetActiveCamera()
        self.assertTrue(cam.GetParallelProjection())
        for angle,x in [(36,600.),(72,700.),(180,-400.)]:
            app.receive_pose(dict(beam_x=x,beam_y=-300.,angle=angle),True,app.state.sample_context)
            pixels=[]
            for z in (-app.beam_length/2,app.beam_length/2):
                app.renderer.SetWorldPoint(x/1000,-.3,z,1)
                app.renderer.WorldToDisplay()
                pixels.append(app.renderer.GetDisplayPoint()[:2])
            np.testing.assert_allclose(pixels[0],pixels[1],atol=1e-6)
        app.reset_camera()
        self.assertFalse(cam.GetParallelProjection())
