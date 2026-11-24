"""Automatic regions, frozen sample geometry and asynchronous refinement."""
import asyncio
from copy import copy
import time
import unittest
import uuid
import threading
from unittest.mock import patch

import numpy as np
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.auto_detail import box_planes,region_vertices,enclosing_crop
from tomoswaxs.projects import validate_view


class AutoDetailChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('detail-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        self.addCleanup(app.reset_auto_detail)
        source=app.render_source
        for step in (2,4,8):
            image=copy(source.images[0]);image.data=source.data[::step,::step,::step]
            image.scale={axis:float(source.spacing[i]*step) for i,axis in enumerate('xyz')}
            source.images.append(image)
        app.loaded_volume=source.preview(2)
        app.volume=app.loaded_volume.values
        app.spacing=app.loaded_volume.spacing;app.origin=app.loaded_volume.origin
        app.set_image_data();app.update_scene()
        return app

    async def settled(self,app):
        until=time.monotonic()+6
        while time.monotonic()<until:
            await asyncio.sleep(.05)
            if app._detail_timer is None and not app.state.render_loading and not app._detail_busy:return
        self.fail('Automatic rendering did not settle: '+str(app.state.render_error))

    def test_convex_region_intersection_and_empty_view(self):
        bounds=np.array([[-1,1],[-2,2],[-3,3]])
        planes=box_planes([[-.5,.5],[-1,1],[-2,2]])
        points=region_vertices(planes,bounds)
        np.testing.assert_allclose(points.min(axis=0),[-.5,-1,-2])
        np.testing.assert_allclose(points.max(axis=0),[.5,1,2])
        self.assertEqual(len(region_vertices(box_planes([[4,5],[4,5],[4,5]]),bounds)),0)

    def test_zoom_depth_freeze_and_orbit_preserve_manual_crop_and_focus(self):
        app=self.app();camera=app.renderer.GetActiveCamera()
        manual=[p[:] for p in app.state.crop_bounds];focus=camera.GetFocalPoint()
        app.receive_auto_detail(dict(enabled=True,depth=50),app.state.sample_context)
        wide=app._detail_plan['crop']
        camera.Zoom(4);app.detail_refresh()
        close=app._detail_plan['crop']
        self.assertLess(np.prod(np.diff(close,axis=1)),np.prod(np.diff(wide,axis=1)))
        app.receive_auto_detail(dict(enabled=True,depth=15),app.state.sample_context)
        thin=app._detail_plan['crop']
        self.assertLess(np.prod(np.diff(thin,axis=1)),np.prod(np.diff(close,axis=1)))
        app.receive_auto_detail(dict(enabled=True,depth=15,freeze=True),app.state.sample_context)
        frozen=app._detail_frozen.copy();region=app._detail_plan['crop']
        app.receive_camera_angle(80);app.detail_refresh()
        np.testing.assert_allclose(app._detail_planes,frozen)
        self.assertEqual(region,app._detail_plan['crop'])
        self.assertEqual(app.state.crop_bounds,manual)
        np.testing.assert_allclose(camera.GetFocalPoint(),focus)
        view=app.capture_view();validate_view(view)
        self.assertEqual(view['volume']['auto_detail']['frozen_planes'],frozen.tolist())
        app.reset_auto_detail();app.restore_view(view);app.detail_refresh()
        np.testing.assert_allclose(app._detail_frozen,frozen)
        app.receive_auto_detail(dict(enabled=True,depth=15,freeze=False),app.state.sample_context)
        self.assertFalse(app.state.detail_frozen)
        self.assertFalse(np.allclose(app._detail_planes,frozen))
        # Empty views stay empty and can be navigated back into the sample.
        position=np.asarray(camera.GetPosition());focal=np.asarray(camera.GetFocalPoint())
        camera.SetPosition(*(position+[100,0,0]));camera.SetFocalPoint(*(focal+[100,0,0]))
        app.detail_refresh()
        self.assertIsNone(app._detail_plan)
        self.assertEqual(app.state.detail_notice,'No sample in view')
        camera.SetPosition(*position);camera.SetFocalPoint(*focal);app.detail_refresh()
        self.assertIsNotNone(app._detail_plan)

    def test_single_level_budget_fallback_can_refine_again(self):
        app=self.app();del app.render_source.images[1:]
        app.install_detail_volume(app.render_source.preview(2),render=False)
        app.state.volume_preview_mib=2
        async def run():
            app.receive_auto_detail(dict(enabled=True,depth=100),app.state.sample_context)
            await self.settled(app)
            self.assertGreater(app.loaded_volume.stride,1)
            app.renderer.GetActiveCamera().Zoom(8)
            app.receive_auto_detail(dict(enabled=True,depth=20),app.state.sample_context)
            await self.settled(app)
            self.assertEqual(app.loaded_volume.stride,1)
            self.assertFalse(app.state.render_error)
        asyncio.run(run())

    def test_refinement_fallback_disable_and_colour_mapping(self):
        app=self.app()
        async def run():
            app.state.volume_preview_mib=2
            camera=app.renderer.GetActiveCamera();camera.Zoom(6)
            before=app.capture_view();signal=app.signal
            app.receive_auto_detail(dict(enabled=True,depth=30),app.state.sample_context)
            await self.settled(app)
            self.assertFalse(app.state.render_error)
            self.assertIsNotNone(app._detail_overview)
            self.assertLess(app.loaded_volume.level,2)
            self.assertLessEqual(app.volume.nbytes,2*1024**2)
            self.assertEqual(app.capture_view()['camera'],before['camera'])
            for key in ('contrast_low','contrast_high','beam_x','beam_y','angle'):
                self.assertEqual(app.capture_view()[key],before[key])
            self.assertIs(app.signal,signal)
            camera.Azimuth(90);app.detail_refresh()
            await self.settled(app)
            self.assertTrue(app.detail_sufficient(app.loaded_volume,app._detail_plan))
            camera.Zoom(.05);app.detail_refresh()
            await self.settled(app)
            self.assertGreaterEqual(app.loaded_volume.level,1)
            app.receive_auto_detail(dict(enabled=False,depth=30),app.state.sample_context)
            await self.settled(app)
            self.assertEqual(app.mapper.GetNumberOfClippingPlanes(),0)
            self.assertEqual(app.loaded_volume.crop,tuple(map(tuple,app.state.crop_bounds)))
        asyncio.run(run())

    def test_progressive_levels_and_small_orbits_reuse_detail(self):
        app=self.app()
        app.install_detail_volume(app.render_source.preview(2,level=3),render=False)
        app.state.volume_preview_mib=8
        camera=app.renderer.GetActiveCamera();camera.Zoom(10)
        installed=[]
        install=app.install_detail_volume
        def record(volume,render=True):
            installed.append(volume.level)
            install(volume,render)
        app.install_detail_volume=record
        async def run():
            app.receive_auto_detail(dict(enabled=True,depth=15),app.state.sample_context)
            await self.settled(app)
            self.assertEqual(installed,[2,1,0])
            detail=app.loaded_volume
            for _ in range(8):
                camera.Azimuth(.25);app.detail_refresh()
                self.assertIs(app.loaded_volume,detail)
            await self.settled(app)
            self.assertIs(app.loaded_volume,detail,'Motion within prefetched coverage must not reload')
            self.assertTrue(app.detail_sufficient(detail,app._detail_plan))
            app.receive_auto_detail(dict(enabled=True,depth=15,freeze=True),app.state.sample_context)
            await self.settled(app)
            detail=app.loaded_volume
            camera.Azimuth(90);app.detail_refresh()
            await self.settled(app)
            self.assertIs(app.loaded_volume,detail)
        asyncio.run(run())

    def test_stale_refinement_cannot_install_after_sample_context_changes(self):
        app=self.app();started=threading.Event();release=threading.Event()
        original=app.render_source.preview
        def slow(*args,**kwargs):
            started.set();release.wait(3)
            return original(*args,**kwargs)
        app.render_source.preview=slow
        async def run():
            app.renderer.GetActiveCamera().Zoom(8)
            app.receive_auto_detail(dict(enabled=True,depth=15),app.state.sample_context)
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            old=app.loaded_volume
            app.state.sample_context='replacement'
            app.reset_auto_detail();app.cancel_render_load()
            release.set();await app._render_task
            self.assertIs(app.loaded_volume,old)
            self.assertFalse(app._detail_busy)
            self.assertEqual(app._detail_cache.nbytes,0)
        asyncio.run(run())

    def test_refinement_reuses_colour_mapping_without_recomputing_percentiles(self):
        app=self.app()
        async def run():
            app.renderer.GetActiveCamera().Zoom(8)
            with patch('tomoswaxs.volumes.np.percentile',side_effect=AssertionError('Unexpected percentile')):
                app.receive_auto_detail(dict(enabled=True,depth=20),app.state.sample_context)
                await self.settled(app)
            self.assertFalse(app.state.render_error)
        asyncio.run(run())

    def test_late_coarse_result_does_not_replace_useful_finer_array(self):
        app=self.app();fine=app.loaded_volume
        fine.spacing=np.full(3,1e-10)
        coarse=copy(fine);coarse.spacing=fine.spacing*2
        app.state.detail_enabled=True
        app._detail_plan=dict(required=fine.crop,spacing=fine.spacing/2,budget=2)
        with patch.object(app,'install_detail_volume') as install:
            app.detail_loaded(coarse,('detail',))
            install.assert_not_called()

    def test_stale_controls_and_sample_change_discard_frozen_region(self):
        app=self.app()
        app.receive_auto_detail(dict(enabled=True,depth=20), 'old')
        self.assertFalse(app.state.detail_enabled)
        app.receive_auto_detail(dict(enabled=True,depth=20,freeze=True),app.state.sample_context)
        self.assertTrue(app.state.detail_frozen)
        app.sync_volume_controls()
        self.assertFalse(app.state.detail_enabled)
        self.assertIsNone(app._detail_frozen)
        self.assertEqual(app.mapper.GetNumberOfClippingPlanes(),0)
