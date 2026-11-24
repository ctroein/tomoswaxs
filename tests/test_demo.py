"""Integration checks for coordinate conventions and displayed scattering."""
import unittest
import base64
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from trame.app import get_server
from sample_fixture import Demo
from tomoswaxs.orientation import sample_rotation


class OrientationChecks(unittest.TestCase):
    def test_selected_image_axis_stays_on_lab_y(self):
        for axis in 'xyz':
            for angle in (0,37,90,-120):
                rotation=sample_rotation(axis,angle)
                np.testing.assert_allclose(rotation @ np.eye(3)[:, 'xyz'.index(axis)],[0,1,0],atol=1e-12)
                np.testing.assert_allclose(rotation.T @ rotation,np.eye(3),atol=1e-12)

    def test_volume_occludes_rear_beam_and_transmits_it_when_transparent(self):
        app=Demo(get_server('test-beam-occlusion',client_type='vue3'))
        app.window.SetSize(160,160)
        image=vtk.vtkImageData()
        image.SetDimensions(16,16,16)
        image.SetSpacing(.1,.1,.1)
        image.SetOrigin(-.75,-.75,-.75)
        image.GetPointData().SetScalars(numpy_to_vtk(np.full(16**3,65535,dtype=np.uint16),deep=True))
        app.mapper.SetInputData(image)
        app.sample.GetProperty().ShadeOff()
        app.sample.SetUserMatrix(vtk.vtkMatrix4x4())
        app.beam.SetPosition(0,0,2.25)  # Entire beam behind the slab, viewed from -Z.
        app.beam.SetScale(.2,.2,1)
        camera=app.renderer.GetActiveCamera()
        camera.SetPosition(0,0,-8)
        camera.SetFocalPoint(0,0,0)
        camera.SetViewUp(0,1,0)
        camera.ParallelProjectionOn()
        camera.SetParallelScale(1)
        app.renderer.ResetCameraClippingRange(app.scene_bounds())
        def picture(alpha,visible):
            app.transfer.RemoveAllPoints()
            app.transfer.AddPoint(0,alpha)
            app.transfer.AddPoint(65535,alpha)
            app.beam.SetVisibility(visible)
            app.window.Render()
            capture=vtk.vtkWindowToImageFilter()
            capture.SetInput(app.window)
            capture.ReadFrontBufferOff()
            capture.Update()
            return vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).astype(float)
        opaque_without=picture(1,False)
        opaque_with=picture(1,True)
        np.testing.assert_allclose(opaque_with,opaque_without,atol=1)
        transparent_without=picture(.002,False)
        transparent_with=picture(.002,True)
        self.assertGreater(np.abs(transparent_with-transparent_without).max(),10)
        self.assertTrue(app.renderer.GetLastRenderingUsedDepthPeeling())
        app.window.Finalize()


class DemoChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Demo(get_server('test-demo', client_type='vue3'))

    def setUp(self):
        self.app.signal_kind='none'
        self.app.signal=(np.empty(0),np.empty(0),np.empty((0,0)),np.empty(0))
        self.app.update_plots()

    def test_pose_changes_leave_scattering_empty_until_loaded(self):
        app=self.app
        app.receive_pose(dict(beam_x=-400,beam_y=200,angle=60),True)
        self.assertEqual(app.signal[2].size,0)
        self.assertEqual(app.curve_figure.layout.annotations[0].text,'No SAXS data loaded')
        np.testing.assert_allclose(np.array([app.sample.GetMatrix().GetElement(i,j)
                                            for i in range(3) for j in range(3)]).reshape(3,3),
                                   sample_rotation('y',60))
        # VTK forward rotation and the sampling inverse rotation must agree.
        local = np.array([.3,.2,.4,1.])
        world = np.array(app.sample.GetMatrix().MultiplyPoint(local))
        t = np.deg2rad(60)
        inverse_x = np.cos(t)*world[0]-np.sin(t)*world[2]
        inverse_z = np.sin(t)*world[0]+np.cos(t)*world[2]
        np.testing.assert_allclose([inverse_x,world[1],inverse_z],local[:3])

    def test_plot_updates_reuse_figures_and_preserve_binary_array_values(self):
        app=self.app
        app.signal_kind='measured'
        app.signal=(np.array([.1,.2,.3]),np.array([1.,3.]),np.array([[1.,2.,3.],[4.,5.,6.]]),np.array([2.,3.,4.]))
        app.update_plots()
        figures=(app.curve_figure,app.cake_figure)
        traces=(app.curve_figure.data[0],app.cake_figure.data[0])
        app.receive_pose({'angle':41},True)
        self.assertIs(app.curve_figure,figures[0])
        self.assertIs(app.cake_figure,figures[1])
        self.assertIs(app.curve_figure.data[0],traces[0])
        self.assertIs(app.cake_figure.data[0],traces[1])
        def decode(encoded):
            self.assertIsInstance(encoded,dict)
            array=np.frombuffer(base64.b64decode(encoded['bdata']),dtype=encoded['dtype'])
            if 'shape' in encoded:
                array=array.reshape(tuple(int(n) for n in encoded['shape'].split(',')))
            return array
        q,phi,cake,iq=app.signal
        curve=app.state[app.curve.key]['data'][0]
        heat=app.state[app.cake.key]['data'][0]
        np.testing.assert_array_equal(decode(curve['x']),q)
        np.testing.assert_array_equal(decode(curve['y']),iq)
        np.testing.assert_array_equal(decode(heat['x']),q)
        np.testing.assert_array_equal(decode(heat['y']),phi)
        np.testing.assert_array_equal(decode(heat['z']),np.log10(cake))
        np.testing.assert_array_equal(decode(heat['customdata']),cake)
        self.assertEqual(app.state[app.cake.key]['layout']['uirevision'],'preserve-user-zoom')
        app.state.log_iq=True
        app.update_plots()
        self.assertEqual(app.state[app.curve.key]['layout']['yaxis']['type'],'log')
        app.state.log_iq=False
        app.update_plots()

    def test_cake_separates_missing_zero_negative_and_positive_intensity(self):
        app=self.app
        app.signal_kind='measured'
        cake=np.array([[np.nan,0.,1.],[-2.,10.,np.inf]])
        app.signal=(np.array([.1,.2,.3]),np.array([1.,3.]),cake,np.ones(3))
        app.update_plots()
        positive,missing,zero,negative=app.cake_figure.data
        np.testing.assert_allclose(positive.z,[[np.nan,np.nan,0.],[np.nan,1.,np.nan]],equal_nan=True)
        for trace,expected in ((missing,~np.isfinite(cake)),
                               (zero,np.isfinite(cake)&(cake==0)),
                               (negative,np.isfinite(cake)&(cake<0))):
            np.testing.assert_array_equal(np.isfinite(trace.z),expected)
            self.assertTrue(trace.showlegend)
            self.assertFalse(trace.hoverongaps)
            self.assertFalse(trace.connectgaps)
        np.testing.assert_array_equal(positive.customdata,cake)

    def test_beam_radii_do_not_change_scattering(self):
        app = self.app
        app.update_scene()
        before = app.signal[2].copy()
        with app.state:
            app.state.radius_x = 200
            app.state.radius_y = 80
        app.update_scene()
        np.testing.assert_array_equal(before,app.signal[2])
        bounds = app.beam.GetBounds()
        self.assertAlmostEqual(bounds[1]-bounds[0],.4,places=5)
        self.assertAlmostEqual(bounds[3]-bounds[2],.16,places=5)
        self.assertAlmostEqual(bounds[5]-bounds[4],4.5,places=5)

    def test_drag_projects_to_lab_xy(self):
        app = self.app
        app.reset_camera(True)
        app.window.Render()
        target = (.31,-.22,0)
        app.renderer.SetWorldPoint(*target,1)
        app.renderer.WorldToDisplay()
        x,y,_ = app.renderer.GetDisplayPoint()
        width,height = app.window.GetSize()
        app.drag_beam(x/width,1-y/height,1)
        self.assertAlmostEqual(float(app.state.beam_x),target[0]*1000,places=1)
        self.assertAlmostEqual(float(app.state.beam_y),target[1]*1000,places=1)

    def test_drag_defers_scattering_until_release(self):
        app = self.app
        app.reset_camera(True)
        before = app.signal[2].copy()
        app.receive_beam_position(.4,.4,False,True)
        app.update_scene()
        np.testing.assert_array_equal(app.signal[2],before)
        app.receive_beam_position(.52,.48,True,True)
        self.assertFalse(app.dragging_beam)
        self.assertEqual(app.signal[2].size,0)

    def test_beam_colors_follow_source_not_camera(self):
        app = self.app
        geometry = app.beam_geometry
        z = np.array([geometry.GetPoint(i)[2] for i in range(geometry.GetNumberOfPoints())])
        source,downstream = int(z.argmin()),int(z.argmax())
        colors = geometry.GetPointData().GetScalars()
        before = np.array([colors.GetTuple(i) for i in range(colors.GetNumberOfTuples())])
        self.assertGreater(before[source,0],before[downstream,0])
        self.assertGreater(before[source,1],before[downstream,1])
        cam = app.renderer.GetActiveCamera()
        for position in [(0,0,8),(0,0,-8),(4,-6,3)]:
            cam.SetPosition(*position)
            app.update_beam_colors()
            colors = geometry.GetPointData().GetScalars()
            after = np.array([colors.GetTuple(i) for i in range(colors.GetNumberOfTuples())])
            np.testing.assert_array_equal(after,before)

    def test_shortcut_finalises_beam_position(self):
        app = self.app
        app.reset_camera(True)
        app.window.Render()
        target = (.2,.1,0)
        app.renderer.SetWorldPoint(*target,1)
        app.renderer.WorldToDisplay()
        x,y,_ = app.renderer.GetDisplayPoint()
        width,height = app.window.GetSize()
        app.receive_beam_position(x/width,1-y/height,False,True)
        app.receive_beam_position(x/width,1-y/height,True,True)
        self.assertFalse(app.dragging_beam)
        self.assertAlmostEqual(float(app.state.beam_x),200,places=1)
        self.assertAlmostEqual(float(app.state.beam_y),100,places=1)

    def test_coordinated_pose_wraps_and_finalises(self):
        app = self.app
        app.receive_pose({'beam_x':300,'beam_y':-200,'angle':185},False)
        self.assertEqual(app.state.angle,-175)
        np.testing.assert_allclose(app.beam.GetPosition(),[.3,-.2,0])
        before = app.signal[2].copy()
        app.receive_pose({'angle':-185},False)
        self.assertEqual(app.state.angle,175)
        np.testing.assert_array_equal(before,app.signal[2])
        app.receive_pose({},True)
        self.assertFalse(app.dragging_controls)
        self.assertEqual(app.signal[2].size,0)
        app.receive_pose({'beam_x':800,'angle':float('nan')},True)
        self.assertEqual(app.state.beam_x,300,'Reject invalid batches atomically')

    def test_invalid_input_keeps_last_valid_scene(self):
        app = self.app
        app.update_scene()
        before = app.beam.GetPosition()
        with app.state:
            app.state.beam_x = ''
        app.update_scene()
        self.assertEqual(app.beam.GetPosition(),before)
        self.assertIn('Enter a number',app.state.status)
        with app.state:
            app.state.beam_x = 250
        app.update_scene()

    def test_zoom_out_limits_wheel_drag_and_parallel_views(self):
        app=self.app
        camera=app.renderer.GetActiveCamera()
        for operation in ('wheel','drag','parallel'):
            camera.ParallelProjectionOff()
            app.reset_camera()
            focal=camera.GetFocalPoint()
            direction=np.array(camera.GetDirectionOfProjection())
            limit=app.zoom_out_limit
            if operation=='wheel':
                camera.Zoom(.1)
            elif operation=='drag':
                camera.Dolly(.01)
            else:
                camera.ParallelProjectionOn()
                camera.SetParallelScale(limit*10)
            app.window.Render()
            self.assertAlmostEqual(app.camera_view_span(),limit,places=7)
            np.testing.assert_allclose(camera.GetFocalPoint(),focal)
            np.testing.assert_allclose(camera.GetDirectionOfProjection(),direction,atol=1e-12)
            camera.Zoom(2)
            app.window.Render()
            self.assertLess(app.camera_view_span(),limit)
        camera.ParallelProjectionOff()
        app.reset_camera()


if __name__ == '__main__':
    unittest.main()
