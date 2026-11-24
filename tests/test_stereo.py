"""Anaglyph rendering, view controls and conservative stereo detail coverage."""
import unittest
import uuid

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.auto_detail import region_vertices
from tomoswaxs.volume_viewing import array_source


class StereoChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('stereo-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        self.addCleanup(app.reset_auto_detail)
        z,y,x=np.indices((48,48,48))
        first=(x-18)**2+(y-23)**2+(z-15)**2<9**2
        second=(x-30)**2+(y-27)**2+(z-33)**2<7**2
        values=np.uint16(first*50000+second*30000)
        app.volume=values;app.spacing=np.full(3,.02);app.origin=np.full(3,-.47)
        app._empty_source=array_source(values,app.spacing,app.origin)
        app.sync_volume_controls()
        app.set_image_data();app.reset_camera();app.update_scene()
        app.window.SetSize(240,200)
        return app

    def pixels(self,app):
        app.window.Render()
        image=vtk.vtkWindowToImageFilter();image.SetInput(app.window);image.Update()
        return vtk_to_numpy(image.GetOutput().GetPointData().GetScalars()).copy()

    def test_anaglyph_channels_swap_and_zero_restores_mono_without_moving_sample(self):
        app=self.app()
        mono=self.pixels(app)
        pose=app.capture_view()
        app.state.update(stereo_enabled=True,stereo_strength=3.)
        app.update_stereo();normal=self.pixels(app)
        self.assertGreater(np.count_nonzero(normal!=mono),100)
        app.state.stereo_swap=True
        app.update_stereo();swapped=self.pixels(app)
        self.assertGreater(np.count_nonzero(normal[:,0]!=swapped[:,0]),20)
        # Both eye images are luminance; swapping exchanges their colour channels.
        np.testing.assert_array_equal(normal[:,0],swapped[:,1])
        np.testing.assert_array_equal(normal[:,1],swapped[:,0])
        self.assertEqual(app.capture_view(),pose)
        app.state.stereo_strength=0
        app.update_stereo();zero=self.pixels(app)
        np.testing.assert_array_equal(zero,mono)
        app.state.update(stereo_strength=3.,stereo_enabled=False)
        app.update_stereo()
        np.testing.assert_array_equal(self.pixels(app),mono)

    def test_strength_validation_and_stereo_detail_region_contains_mono(self):
        app=self.app()
        app.state.detail_depth=60
        mono=app.detail_view_planes()
        app.state.update(stereo_enabled=True,stereo_strength=2.)
        app.update_stereo()
        stereo=app.detail_view_planes()
        bounds=app.crop_world_bounds(app.state.crop_bounds)
        vertices=region_vertices(mono,bounds)
        self.assertTrue(np.all(vertices @ stereo[:,:3].T+stereo[:,3]>=-1e-8))
        self.pixels(app)
        camera=app.renderer.GetActiveCamera()
        for eye in (0,1):
            camera.SetLeftEye(eye)
            coefficients=[0.]*24
            camera.GetFrustumPlanes(app.renderer.GetTiledAspectRatio(),coefficients)
            actual=np.asarray(coefficients).reshape(6,4)[:4] @ app.sample_pose_matrix()
            eye_vertices=region_vertices(np.vstack([actual,stereo[-2:]]),bounds)
            self.assertTrue(np.all(eye_vertices @ stereo[:,:3].T+stereo[:,3]>=-1e-8))
        before=app.renderer.GetActiveCamera().GetEyeAngle()
        app.state.stereo_strength=float('nan')
        app.update_stereo()
        self.assertEqual(app.renderer.GetActiveCamera().GetEyeAngle(),before)
        self.assertTrue(app.state.stereo_notice)
