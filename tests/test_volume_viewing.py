"""Crop geometry, level selection, bounded loads and project persistence."""
import asyncio
from copy import copy
import tempfile
import threading
import time
import unittest
import uuid

import numpy as np
import tifffile
from trame.app import get_server

from tomoswaxs.app import Demo
from tomoswaxs.projects import Project, validate_view
from tomoswaxs.volume_viewing import array_source
from tomoswaxs.volumes import ImportCancelled, VolumeSource, import_tiff
from tomoswaxs.synthetic_demo import scattering


class CropChecks(unittest.TestCase):
    def source(self):
        data=np.arange(128**3,dtype=np.uint16).reshape(128,128,128)
        source=array_source(data,[.002,.003,.004],[-.1,-.2,-.3])
        coarse=copy(source.images[0]);coarse.data=source.data[1::2,1::2,1::2]
        coarse.scale={axis:float(s*2) for axis,s in zip('xyz',source.spacing)}
        coarse.translation={axis:float(o+s) for axis,o,s in zip('xyz',source.origin,source.spacing)}
        source.images.append(coarse)
        return source,data

    def test_crop_selects_finer_level_and_preserves_values_and_translation(self):
        source,data=self.source()
        self.assertEqual(source.preview(1).level,1)
        crop=[[4,30],[8,40],[12,48]]
        result=source.preview(1,crop=crop)
        self.assertEqual(result.level,0)
        np.testing.assert_array_equal(result.values,data[12:48,8:40,4:30])
        np.testing.assert_allclose(result.origin,source.origin+source.spacing*[4,8,12])
        self.assertEqual(result.crop,tuple(map(tuple,crop)))
        coarse=source.preview(1,crop=crop,level=1)
        np.testing.assert_array_equal(coarse.values,data[11:48:2,7:40:2,3:30:2])
        np.testing.assert_allclose(coarse.origin,source.origin+source.spacing*[3,7,11])
        np.testing.assert_allclose(coarse.spacing,source.spacing*2)

    def test_explicit_level_is_exact_and_limited_but_auto_can_subsample(self):
        source,_=self.source()
        with self.assertRaisesRegex(ValueError,'exceeds'):source.preview(1,level=0)
        del source.images[1:]
        result=source.preview(1)
        self.assertEqual(result.stride,2)
        self.assertLessEqual(result.values.nbytes,1024**2)
        thin=array_source(np.zeros((2,2,600),dtype=np.uint16),1,[0,0,0]).preview(1,level=0)
        self.assertEqual(thin.values.shape,(2,2,600),'No hidden 512-voxel axis cap')
        for crop in ([[0,0],[0,1],[0,1]],[[-1,3],[0,1],[0,1]],[[0,129],[0,1],[0,1]]):
            with self.assertRaises(ValueError):source.preview(1,crop=crop)
        cancelled=threading.Event();cancelled.set()
        with self.assertRaises(ImportCancelled):source.preview(1,cancel=cancelled)

    def app(self):
        app=Demo(get_server('crop-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        return app

    def test_widget_round_trip_uses_image_axes_at_any_sample_orientation(self):
        app=self.app();crop=((20,130),(30,100),(40,120))
        source,_=self.source()
        app.render_source=source
        crop=((15,100),(25,110),(35,120))
        for axis in 'xyz':
            for angle in (0,37,-120):
                app.state.rotation_axis=axis;app.state.angle=angle
                app.update_crop_widget(crop=crop)
                self.assertEqual(app.widget_crop(),crop)

    def test_only_latest_load_commits_and_camera_beam_and_contrast_are_preserved(self):
        app=self.app();source=app.render_source
        original=source.preview;started=threading.Event();release=threading.Event();calls=[]
        def slow(*args,**kwargs):
            calls.append(args[2])
            if len(calls)==1:
                started.set();release.wait(3)
            return original(*args,**kwargs)
        source.preview=slow
        before=app.capture_view();signal=app.signal
        async def scenario():
            context=app.state.sample_context
            def request(stop):
                app.receive_volume_view(dict(crop=[[10,stop],[20,140],[30,130]],level='auto',limit=1),context)
            request(150)
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            for stop in range(140,110,-1):request(stop)
            release.set()
            await app._render_task
        asyncio.run(scenario())
        self.assertEqual(len(calls),2)
        self.assertEqual(app._render_spec['crop'][0],(10,111))
        self.assertEqual(app.volume.shape,(50,60,51))
        self.assertAlmostEqual(app.sample.GetProperty().GetScalarOpacityUnitDistance(),float(min(app._synthetic_source.spacing)))
        after=app.capture_view()
        self.assertEqual(after['camera'],before['camera'])
        for key in ['beam_x','beam_y','angle','contrast_low','contrast_high']:self.assertEqual(after[key],before[key])
        self.assertIs(app.signal,signal,'Display cropping must not recompute scattering')
        self.assertFalse(app.state.render_loading)
        app.receive_pose(dict(beam_x=400,beam_y=100,angle=30),True)
        expected=scattering(app.signal_volume,app._synthetic_source.spacing,app._synthetic_source.origin,.4,.1,30)
        for actual,want in zip(app.signal,expected):np.testing.assert_allclose(actual,want)

    def test_cancel_and_stale_input_keep_the_loaded_array(self):
        app=self.app();source=app.render_source
        original=source.preview;started=threading.Event();release=threading.Event()
        loaded=app.volume
        def slow(*args,**kwargs):
            started.set();release.wait(3)
            return original(*args,**kwargs)
        source.preview=slow
        async def scenario():
            spec=dict(crop=[[10,90],[20,100],[30,110]],level='auto',limit=64)
            app.receive_volume_view(spec,'stale-context')
            self.assertIsNone(app._render_pending)
            app.receive_volume_view(spec,app.state.sample_context)
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            app.cancel_volume_render()
            release.set();await app._render_task
            started.clear();release.clear()
            app.receive_volume_view(spec,app.state.sample_context)
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            app.state.sample_context=uuid.uuid4().hex
            release.set();await app._render_task
            self.assertEqual(app.state.crop_bounds,[[0,160]]*3)
        asyncio.run(scenario())
        self.assertIs(app.volume,loaded)
        self.assertEqual(app.volume_view_state()['crop'],[[0,160]]*3)
        self.assertFalse(app.state.render_loading)

    def test_ome_zarr_project_reopens_the_selected_crop_and_level(self):
        app=self.app()
        with tempfile.TemporaryDirectory() as folder:
            from pathlib import Path
            root=Path(folder)
            values=np.arange(32*48*64,dtype=np.uint16).reshape(32,48,64)
            tifffile.imwrite(root/'input.tif',values)
            store=import_tiff(root/'input.tif',root/'image.ome.zarr',[5,6,7])
            project=Project.create(root/'project','Image')
            identifier=project.add_sample(store,'Sample')
            app.project=project
            async def scenario():
                await app.load_sample(store,project,identifier,project.sample(identifier))
                app.receive_volume_view(dict(crop=[[8,40],[6,30],[4,20]],level='1',limit=1),app.state.sample_context)
                await app._render_task
                saved=Project.load(project.path)
                app.project=saved
                await app.load_sample(store,saved,identifier,saved.sample(identifier))
            asyncio.run(scenario())
            self.assertFalse(app.state.volume_error)
            self.assertEqual(app.volume_view_state(),dict(crop=[[8,40],[6,30],[4,20]],level=1))
            self.assertEqual(app.loaded_volume.level,1)
            self.assertEqual(app.volume_source.shape,values.shape)
            spacing,origin=app.volume_source.geometry(app.volume_source.images[1])
            start=np.asarray([s.start for s in app.loaded_volume.selection][::-1])
            np.testing.assert_allclose(app.origin,origin+start*spacing)

    def test_crop_and_level_round_trip_in_project_sample(self):
        app=self.app()
        with tempfile.TemporaryDirectory() as folder:
            app.project=Project.create(folder,'Crops')
            identifier=app.project.add_sample(None,'Seed')
            app.active_sample_id=identifier
            context=app.state.sample_context
            async def select():
                app.receive_volume_view(dict(crop=[[10,90],[20,100],[30,110]],level='0',limit=64),context)
                await app._render_task
            asyncio.run(select())
            loaded=Project.load(folder)
            saved=loaded.sample(identifier)['view']['volume']
            self.assertEqual(saved,dict(crop=[[10,90],[20,100],[30,110]],level=0))
            app.project=loaded
            asyncio.run(app.load_sample(None,loaded,identifier,loaded.sample(identifier)))
            self.assertEqual(app.volume_view_state(),saved)
            self.assertEqual(app.volume.shape,(80,80,80))
        for spec in [dict(crop=[[0,0],[0,1],[0,1]],level=0),dict(crop=[[0,1]]*3,level=-1)]:
            with self.assertRaises(ValueError):validate_view(dict(volume=spec))


if __name__=='__main__':unittest.main()
