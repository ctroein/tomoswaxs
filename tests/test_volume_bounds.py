"""Transparent margins preserve tiny floats, interpolation and physical placement."""
import unittest
import uuid

import numpy as np
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.volume_bounds import transparent_crop


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
