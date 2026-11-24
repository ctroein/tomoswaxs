"""Intensity-scale steps, low opacity and independent beam visibility."""
import unittest,uuid
from unittest.mock import patch
from trame.app import get_server
from sample_fixture import Demo
from tomoswaxs.app import colour_mapping_step
from tomoswaxs.projects import validate_view


class ViewControlChecks(unittest.TestCase):
    def test_mapping_step_tracks_significant_places(self):
        for high,expected in [(65535,1000),(789,10),(123,5),(17,.5),(2.3,.1),
                              (.00123,.00005),(.000791,.00001),(-.00016,.000005)]:
            with self.subTest(high=high):self.assertAlmostEqual(colour_mapping_step(high)/expected,1)
        self.assertEqual(colour_mapping_step(0,-123),5)
        self.assertEqual(colour_mapping_step(0),1)
        self.assertGreater(colour_mapping_step(5e-324),0)

    def test_negative_mapping_low_opacity_and_beam_toggle(self):
        app=Demo(get_server('view-controls-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        with app.state:
            app.state.opacity=.007
            app.state.contrast_low=-.00015
            app.state.contrast_high=.00123
            app.state.saxs_available=True
        app.update_scene()
        self.assertEqual(app.state.contrast_low,-.00015)
        self.assertAlmostEqual(app.state.contrast_step,.00005)
        self.assertEqual(app.parameters()['opacity'],.007)
        validate_view(dict(opacity=0,contrast_low=-1,contrast_high=1))
        self.assertTrue(app.beam.GetVisibility())
        with patch.object(app,'saxs_from_pose') as saxs:
            with app.state:app.state.beam_visible=False
            app.beam_visibility_changed()
            self.assertFalse(app.beam.GetVisibility())
            saxs.assert_not_called()
        app.update_scene()
        self.assertFalse(app.beam.GetVisibility())
        with app.state:app.state.beam_visible=True
        app.beam_visibility_changed()
        self.assertTrue(app.beam.GetVisibility())
        app.state.saxs_available=False;app.update_scene()
        self.assertFalse(app.beam.GetVisibility())
