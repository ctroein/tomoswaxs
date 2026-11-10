"""Integration checks for coordinate conventions and displayed scattering."""
import unittest
import numpy as np
from trame.app import get_server
from app import Demo


class DemoChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Demo(get_server('test-demo', client_type='vue3'))

    def test_cake_and_curve_share_data(self):
        app = self.app
        with app.state:
            app.state.beam_x = -400
            app.state.beam_y = 200
            app.state.angle = 60
        app.update_scene()
        q, phi, cake, iq = app.signal
        np.testing.assert_allclose(iq, cake.mean(axis=0))
        self.assertEqual(cake.shape, (len(phi),len(q)))
        np.testing.assert_allclose(app.sample.GetOrientation(), [0,60,0])
        # VTK forward rotation and the sampling inverse rotation must agree.
        local = np.array([.3,.2,.4,1.])
        world = np.array(app.sample.GetMatrix().MultiplyPoint(local))
        t = np.deg2rad(60)
        inverse_x = np.cos(t)*world[0]-np.sin(t)*world[2]
        inverse_z = np.sin(t)*world[0]+np.cos(t)*world[2]
        np.testing.assert_allclose([inverse_x,world[1],inverse_z],local[:3])

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
        with app.state:
            app.state.move_beam = True
        app.drag_beam(x/width,1-y/height,1)
        self.assertAlmostEqual(float(app.state.beam_x),target[0]*1000,places=1)
        self.assertAlmostEqual(float(app.state.beam_y),target[1]*1000,places=1)

    def test_drag_defers_scattering_until_release(self):
        app = self.app
        app.reset_camera(True)
        with app.state:
            app.state.move_beam = True
        before = app.signal[2].copy()
        app.receive_beam_position(.4,.4,False)
        app.update_scene()
        np.testing.assert_array_equal(app.signal[2],before)
        app.receive_beam_position(.52,.48,True)
        self.assertFalse(app.dragging_beam)
        self.assertFalse(np.array_equal(app.signal[2],before))
        np.testing.assert_allclose(app.signal[3],app.signal[2].mean(axis=0))

    def test_depth_colors_reverse_with_camera(self):
        app = self.app
        geometry = app.beam_geometry
        z = np.array([geometry.GetPoint(i)[2] for i in range(geometry.GetNumberOfPoints())])
        front,back = int(z.argmax()),int(z.argmin())
        cam = app.renderer.GetActiveCamera()
        cam.SetPosition(0,0,8)
        colors = geometry.GetPointData().GetScalars()
        self.assertGreater(colors.GetTuple(front)[0],colors.GetTuple(back)[0])
        cam.SetPosition(0,0,-8)
        colors = geometry.GetPointData().GetScalars()
        self.assertLess(colors.GetTuple(front)[0],colors.GetTuple(back)[0])

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


if __name__ == '__main__':
    unittest.main()
