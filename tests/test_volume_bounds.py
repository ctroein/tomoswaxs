"""Transparent margins preserve tiny floats, interpolation and physical placement."""
from copy import copy
import asyncio
import unittest
import threading
import uuid
from unittest.mock import patch

import dask.array as da

import numpy as np
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.volume_bounds import transparent_crop
from tomoswaxs.volume_viewing import array_source
from tomoswaxs.volumes import ImportCancelled


class TransparentBoundsChecks(unittest.TestCase):
    def test_float32_subunit_intensities_and_margin(self):
        values=np.zeros((12,14,16),dtype=np.float32)
        values[4:8,5:9,6:10]=1e-20
        selection=transparent_crop(values,1e-21)
        self.assertEqual(selection,(slice(3,9),slice(4,10),slice(5,11)))
        self.assertEqual(values[selection].dtype,np.float32)
        self.assertEqual(transparent_crop(values,2e-20),(slice(0,2),)*3)
        self.assertEqual(transparent_crop(values,0),selection)

    def test_nonfinite_and_isolated_visible_values_are_retained(self):
        values=np.zeros((12,14,16),dtype=np.float32)
        values[0,0,0]=np.nan;values[-1,-1,-1]=1e-20
        self.assertEqual(transparent_crop(values,0),tuple(slice(0,n) for n in values.shape))

    def test_mapping_change_restores_data_and_explicit_level_keeps_full_array(self):
        app=Demo(get_server('bounds-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        values=np.zeros((12,14,16),dtype=np.float32)
        values[4:8,5:9,6:10]=1e-20
        app.volume=values;app.spacing=np.array([.01,.02,.03]);app.origin=np.array([1.,2.,3.])
        app.state.update(render_level='auto',contrast_low=0.,contrast_high=1e-20)
        app.set_image_data()
        self.assertEqual(app.mapper.GetInput().GetDimensions(),(6,6,6))
        np.testing.assert_allclose(app.mapper.GetInput().GetOrigin(),[1.05,2.08,3.09])
        self.assertIs(app.volume,values)
        app.state.update(contrast_low=-1e-20,contrast_high=1e-20)
        app.update_scene()
        self.assertEqual(app.mapper.GetInput().GetDimensions(),(16,14,12))
        app.state.update(render_level='0',contrast_low=0.,contrast_high=1e-20)
        app.set_image_data()
        self.assertEqual(app.mapper.GetInput().GetDimensions(),(16,14,12))


class ContentRefinementChecks(unittest.TestCase):
    def source(self):
        values=np.zeros((128,128,128),dtype=np.float32)
        values[56:72,56:72,56:72]=1e-20
        source=array_source(values,np.array([.01,.02,.03]),np.array([1.,2.,3.]))
        coarse=copy(source.images[0])
        coarse.data=da.coarsen(np.mean,source.data,{0:2,1:2,2:2},trim_excess=True)
        coarse.scale={axis:float(source.spacing[i]*2) for i,axis in enumerate('xyz')}
        coarse.translation={axis:float(source.origin[i]+source.spacing[i]/2) for i,axis in enumerate('xyz')}
        source.images.append(coarse)
        return source

    def test_refinement_rechecks_translated_anisotropic_levels(self):
        source=self.source();manual=source.crop_bounds()
        base=source.preview(1,contrast=(0.,1e-20))
        self.assertEqual(base.level,1)
        with patch('tomoswaxs.volume_bounds.transparent_crop',wraps=transparent_crop) as scan:
            volume=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=1e-21)
            self.assertEqual(scan.call_count,2)
        self.assertEqual(volume.level,0)
        self.assertEqual(volume.refined_from,1)
        self.assertEqual(volume.crop,manual)
        self.assertEqual(volume.values.dtype,np.float32)
        self.assertLessEqual(volume.values.nbytes,1024**2)
        # The one-voxel coarse margin becomes two voxels at the finer scale.
        self.assertTrue(all(s.start<=54 and s.stop>=74 for s in volume.selection))
        np.testing.assert_allclose(volume.origin,source.origin+np.array([s.start for s in volume.selection][::-1])*source.spacing)
        np.testing.assert_array_equal(volume.values,source.data[volume.selection].compute())

    def pyramid(self,width=60):
        values=np.zeros((256,256,256),dtype=np.float32)
        values[100:100+width,100:100+width,100:100+width]=1e-20
        source=array_source(values,np.array([.01,.02,.03]),np.array([1.,2.,3.]))
        for factor in (2,4):
            image=copy(source.images[0])
            image.data=da.coarsen(np.mean,source.data,dict.fromkeys(range(3),factor),trim_excess=True)
            image.scale=dict(zip('xyz',source.spacing*factor))
            image.translation=dict(zip('xyz',source.origin+source.spacing*(factor-1)/2))
            source.images.append(image)
        return source

    def test_second_bounds_check_enables_an_additional_level(self):
        source=self.pyramid();manual=source.crop_bounds()
        base=source.preview(1,contrast=(0.,1e-20))
        self.assertEqual(base.level,2)
        result=source.preview(1,contrast=base.contrast,refine=True,threshold=1e-21)
        self.assertEqual(result.level,0)
        self.assertEqual(result.refinement_history,((2,1),(1,1),(0,1)))
        self.assertEqual(result.refinement_stop,'finest')
        self.assertEqual(result.refined_from,2)
        self.assertEqual(result.crop,manual)
        self.assertEqual(result.refinement_crop,((98,162),)*3)
        self.assertEqual(result.values.shape,(64,)*3)
        self.assertLessEqual(result.values.nbytes,1024**2)
        np.testing.assert_allclose(result.refinement_spacing,base.spacing)
        np.testing.assert_array_equal(result.values,source.data[result.selection].compute())
        app=Demo(get_server('multi-pass-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize);app.render_source=source
        app.update_render_summary(result)
        self.assertEqual(app.state.render_refinement,'Refined from L2 in 2 passes.')
        self.assertIn('L2 → L1 → L0',app.state.render_refinement_detail)
        self.assertIn('Finest stored resolution',app.state.render_refinement_detail)

    def test_refinement_stops_when_the_next_level_still_exceeds_the_limit(self):
        source=self.pyramid(width=76)
        result=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=1e-21)
        self.assertEqual(result.level,1)
        self.assertEqual(result.refinement_history,((2,1),(1,1)))
        self.assertEqual(result.refinement_stop,'limit')
        self.assertLessEqual(result.values.nbytes,1024**2)
        self.assertTrue(all(s.start==1 and s.stop==41 for s in result.display_selection))

    def test_subsampled_single_level_can_reach_full_spacing(self):
        source=self.pyramid(width=52);del source.images[1:]
        result=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=1e-21)
        self.assertEqual(result.refinement_history,((0,4),(0,1)))
        self.assertEqual(result.stride,1)
        np.testing.assert_allclose(result.spacing,source.spacing)
        self.assertEqual(result.refinement_stop,'finest')

    def test_cancel_during_the_second_bounds_check_prevents_further_reads(self):
        source=self.pyramid();cancel=threading.Event();calls=[]
        def scan(values,threshold,**kwargs):
            calls.append(values.shape)
            if len(calls)==2:cancel.set()
            return transparent_crop(values,threshold,**kwargs)
        with patch('tomoswaxs.volume_bounds.transparent_crop',side_effect=scan):
            with self.assertRaises(ImportCancelled):
                source.preview(1,cancel,contrast=(0.,1e-20),refine=True,threshold=1e-21)
        self.assertEqual(calls,[(64,64,64),(34,34,34)])

    def test_render_summary_describes_the_actual_vtk_array_and_refinement(self):
        source=self.source()
        app=Demo(get_server('render-summary-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        for refine in (False,True):
            volume=source.preview(1,contrast=(0.,1e-20),refine=refine,threshold=1e-21)
            app.volume=volume.values;app.spacing=volume.spacing;app.origin=volume.origin
            app.loaded_volume=volume;app.volume_source=source;app.render_source=source
            app.state.update(render_level='auto',contrast_low=0.,contrast_high=1e-20)
            app.set_image_data();app.update_render_summary(volume)
            dimensions='×'.join(map(str,app.mapper.GetInput().GetDimensions()))
            self.assertTrue(app.state.render_display.startswith(f'{dimensions} L{volume.level} voxels,'))
            if refine:
                self.assertEqual(app.state.render_refinement,'Refined from L1 in 1 pass.')
                self.assertEqual(volume.level,0)
            else:
                self.assertFalse(app.state.render_refinement)
                self.assertNotEqual(app._display_values.shape,volume.values.shape)

    def test_lower_threshold_reconsiders_original_coverage_and_explicit_level_does_not_refine(self):
        source=self.source()
        refined=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=1e-21)
        restored=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=-1e-21)
        self.assertEqual(refined.level,0)
        self.assertEqual(restored.level,1)
        self.assertIsNone(restored.refined_from)
        self.assertEqual(restored.values.shape,(64,64,64))
        explicit=source.preview(1,level=1)
        self.assertIsNone(explicit.display_threshold)
        self.assertEqual(explicit.values.shape,(64,64,64))

    def test_mapping_reload_restores_coarse_coverage_without_changing_manual_crop(self):
        app=Demo(get_server('refine-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        source=self.source()
        volume=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=9000/65535*1e-20)
        app.render_source=app.volume_source=source
        app.contrast=(0.,1e-20)
        app.loaded_volume=volume
        app.volume,app.spacing,app.origin=volume.values,volume.spacing,volume.origin
        app._render_spec=dict(crop=source.crop_bounds(),level='auto')
        app.state.update(volume_preview_mib=1,render_level='auto',contrast_low=0.,contrast_high=1e-20)
        app.set_image_data()
        async def run():
            app.state.contrast_low=-1e-20
            app.update_scene()
            await app._render_task
        asyncio.run(run())
        self.assertEqual(app.loaded_volume.level,1)
        self.assertEqual(app.volume.shape,(64,64,64))
        self.assertEqual(app._render_spec['crop'],source.crop_bounds())

    def test_zoom_outside_refined_box_requires_new_data_at_finer_target(self):
        app=Demo(get_server('coverage-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        source=self.source();app.render_source=source
        app.state.update(render_level='auto',contrast_low=0.,contrast_high=1e-20)
        volume=source.preview(1,contrast=(0.,1e-20),refine=True,threshold=app.display_array_key()[2])
        plan=dict(required=((0,8),)*3,spacing=source.spacing,budget=1)
        self.assertFalse(app.detail_sufficient(volume,plan))
        plan['spacing']=source.spacing*2
        self.assertTrue(app.detail_sufficient(volume,plan))
