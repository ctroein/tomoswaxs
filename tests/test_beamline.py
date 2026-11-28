"""Equipment context keeps physical scale and scientific/sample state separate."""
import unittest,uuid
import numpy as np
from trame.app import get_server
from sample_fixture import Demo
from tomoswaxs.projects import validate_view


class BeamlineChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('beamline-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        return app

    def test_scale_stack_order_and_hidden_default(self):
        app=self.app();parts=app.beamline.parts
        bounds=parts['table top'].GetBounds()
        self.assertEqual(bounds[1]-bounds[0],800)
        self.assertEqual(bounds[5]-bounds[4],800)
        self.assertEqual(parts['flight tube'].GetBounds()[4:],(900,2300))
        names=['swaxs_y','swaxs_x','tomo_ry','tomo_xf','tomo_zf']
        for lower,upper in zip(names,names[1:]):
            self.assertLessEqual(parts[lower].GetBounds()[3],parts[upper].GetBounds()[2])
        self.assertTrue(all(not actor.GetVisibility() for actor in parts.values()))
        self.assertEqual(app.state.beamline_level,'sample')

    def test_presets_clipping_zoom_and_unchanged_scientific_pose(self):
        app=self.app();before=app.capture_view();signal=app.signal
        spans={}
        for preset in ('area','station'):
            with app.state:app.select_beamline_level(preset)
            app.window.Render()
            self.assertTrue(app.state.beamline_visible)
            self.assertEqual(app._beamline_scope,preset)
            near,far=app.renderer.GetActiveCamera().GetClippingRange()
            self.assertGreater(near,0);self.assertGreater(far,near)
            app.limit_zoom()
            for key in ('beam_x','beam_y','angle','opacity'):
                self.assertEqual(app.capture_view()[key],before[key])
            self.assertIs(app.signal,signal)
            self.assertGreater(app.zoom_out_limit,app.camera_view_span())
            spans[preset]=app.camera_view_span()
        self.assertLess(spans['area'],spans['station'])
        app.reset_camera()
        cam=app.renderer.GetActiveCamera()
        self.assertGreater(cam.GetPosition()[1],cam.GetFocalPoint()[1])
        with app.state:app.select_beamline_level('sample')
        self.assertFalse(any(actor.GetVisibility() for actor in app.beamline.parts.values()))
        self.assertEqual(app._beamline_scope,'sample')
        self.assertLess(app.camera_view_span(),20)

    def test_equipment_is_stationary_and_camera_bookmark_restores_context(self):
        app=self.app()
        with app.state:app.select_beamline_level('area')
        before={name:actor.GetBounds() for name,actor in app.beamline.parts.items()}
        view=app.capture_view();validate_view(view)
        with app.state:
            app.state.angle=90;app.state.beam_x=500
        self.assertEqual(before,{name:actor.GetBounds() for name,actor in app.beamline.parts.items()})
        with app.state:app.select_beamline_level('sample')
        with app.state:app.restore_view(view)
        self.assertTrue(app.state.beamline_visible)
        self.assertEqual(app._beamline_scope,'area')
        self.assertEqual(app.state.beamline_level,'area')
        np.testing.assert_allclose(app.renderer.GetActiveCamera().GetPosition(),view['camera']['position'])
        view['camera']['beamline']['visible']='yes'
        with self.assertRaises(ValueError):validate_view(view)

    def test_labels_follow_scale_and_marker_yields_to_real_volume(self):
        app=self.app()
        with app.state:app.beamline_camera('station')
        app.sync_beamline()
        self.assertTrue(all(bool(actor.GetVisibility())==(scope in ('station','context')) for actor,scope in app.beamline.labels))
        self.assertFalse(app.beamline.parts['sample marker'].GetVisibility())
        with app.state:app.select_beamline_level('area')
        app.sync_beamline()
        self.assertTrue(all(bool(actor.GetVisibility())==(scope in ('area','context')) for actor,scope in app.beamline.labels))
        app.reset_camera();app.window.Render()
        self.assertTrue(all(bool(actor.GetVisibility())==(scope=='stack') for actor,scope in app.beamline.labels))
        with app.state:app.state.beamline_labels=False
        app.update_beamline()
        self.assertTrue(all(not actor.GetVisibility() for actor,_ in app.beamline.labels))

    def test_levels_control_geometry_independently_of_zoom_and_orbit(self):
        app=self.app();camera=app.renderer.GetActiveCamera()
        position=np.array(camera.GetPosition());focal=np.array(camera.GetFocalPoint())
        self.assertLess(position[1],focal[1])
        app.select_beamline_level('area')
        self.assertFalse(app.beamline.parts['gantry crossbar'].GetVisibility())
        self.assertFalse(app.beamline.parts['table base'].GetVisibility())
        self.assertTrue(app.beamline.parts['tomo_ry'].GetVisibility())
        camera.Azimuth(70);camera.Dolly(3);app.window.Render()
        self.assertEqual(app.state.beamline_level,'area')
        self.assertFalse(app.beamline.parts['gantry crossbar'].GetVisibility())
        # An intentionally saved below-holder camera is restored verbatim.
        camera.SetPosition(*position)
        camera.SetFocalPoint(*focal)
        saved=app.capture_view()
        app.select_beamline_level('sample')
        app.restore_view(saved);app.update_beamline()
        np.testing.assert_allclose(camera.GetPosition(),position)
        np.testing.assert_allclose(camera.GetFocalPoint(),focal)

    def test_legacy_visibility_and_preset_records_migrate(self):
        app=self.app();view=app.capture_view()
        for visible,scope,level in [(False,'sample','sample'),(True,'stack','area'),(True,'station','station'),(True,'sample','station')]:
            view['camera']['beamline']=dict(visible=visible,labels=False,scope=scope)
            validate_view(view);app.restore_view(view)
            self.assertEqual(app.state.beamline_level,level)
            self.assertFalse(app.state.beamline_labels)
            np.testing.assert_allclose(app.renderer.GetActiveCamera().GetPosition(),view['camera']['position'])
            self.assertEqual(app.capture_view()['camera']['beamline']['level'],level)

    def test_adaptive_depth_precision_across_orbit_and_zoom(self):
        app=self.app();camera=app.renderer.GetActiveCamera()
        for preset in ('station','stack','sample'):
            app.beamline_camera('stack' if preset=='sample' else preset)
            if preset=='sample':app.reset_camera()
            position=np.array(camera.GetPosition());focal=np.array(camera.GetFocalPoint())
            for zoom in (.6,1.,4.):
                for angle in range(0,360,45):
                    for elevation in (-30,0,30):
                        camera.SetPosition(*(focal+(position-focal)*zoom))
                        camera.SetFocalPoint(*focal);camera.SetViewUp(0,1,0)
                        camera.Azimuth(angle);camera.Elevation(elevation)
                        app.reset_clipping_range()
                        near,far=camera.GetClippingRange()
                        self.assertTrue(0<near<far,(preset,zoom,angle,elevation,near,far))
                        if preset!='sample':self.assertLess(far/near,10000)
                        depths=(app.camera_sample_points()-camera.GetPosition()) @ np.array(camera.GetDirectionOfProjection())
                        if depths.min()>0:self.assertLessEqual(near,depths.min()*.5+1e-8)
                        self.assertGreater(far,depths.max())
            # Field-of-view zoom and parallel Beam view also retain the sample.
            if preset=='sample':
                app.reset_camera(True)
                for parallel in (False,True):
                    camera.SetParallelProjection(parallel)
                    for fov in (5,30,80):
                        camera.SetViewAngle(fov);app.reset_clipping_range()
                        depths=(app.camera_sample_points()-camera.GetPosition()) @ np.array(camera.GetDirectionOfProjection())
                        self.assertLess(camera.GetClippingRange()[0],depths.min())

    def test_render_repairs_an_interactor_clipping_reset(self):
        app=self.app();app.beamline_camera('stack')
        camera=app.renderer.GetActiveCamera()
        camera.SetClippingRange(.001,5000)
        app.window.Render()
        near,far=camera.GetClippingRange()
        self.assertLess(far/near,10000)
