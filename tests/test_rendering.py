"""Graphics selection policy without depending on a particular installed GPU."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tomoswaxs import rendering as r


def result(device='system', seconds=.03, software=False, renderer='GPU'):
    return dict(device=device,seconds=seconds,software=software,renderer=renderer,version='GL test')


class RenderingChecks(unittest.TestCase):
    def tearDown(self):
        r.automatic_device.cache_clear()

    def test_ranking_prefers_speed_but_keeps_system_for_small_difference(self):
        system=result();fast=result('egl:0',.004)
        self.assertEqual(r.fastest([system,fast]),fast)
        self.assertEqual(r.fastest([system,result('egl:0',.029)]),system)
        self.assertEqual(r.fastest([result(software=True),fast]),fast)
        self.assertIsNone(r.fastest([]))
        self.assertEqual(r.fastest([result('egl:0',software=True)])['device'],'egl:0')

    def test_explicit_environment_and_non_linux_keep_system(self):
        for env in ({'DRI_PRIME':'1'},{'VTK_DEFAULT_EGL_DEVICE_INDEX':'2'},{'SLURM_JOB_GPUS':'0'}):
            with self.subTest(env=env),patch.dict(r.os.environ,env,clear=True),patch.object(r,'run_probe') as probe:
                self.assertEqual(r.automatic_device()['device'],'system');probe.assert_not_called()
            r.automatic_device.cache_clear()
        with patch.dict(r.os.environ,{},clear=True),patch.object(r.sys,'platform','darwin'),patch.object(r,'run_probe') as probe:
            self.assertEqual(r.automatic_device()['device'],'system');probe.assert_not_called()

    def test_selection_cache_and_changed_driver(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(r.os.environ,{},clear=True),patch.object(r.sys,'platform','linux'),patch.object(r,'fingerprint',return_value='hardware'),patch.object(r,'cache_path',return_value=Path(root)/'choice.json'):
            with patch.object(r,'run_probe',side_effect=[result(),{'devices':1},result('egl:0',.004)]) as probe:
                self.assertEqual(r.automatic_device()['device'],'egl:0')
                self.assertEqual(probe.call_count,3)
            r.automatic_device.cache_clear()
            with patch.object(r,'run_probe',return_value=result('egl:0',.004)) as probe:
                self.assertIn('Cached',r.automatic_device()['reason'])
                probe.assert_called_once_with('egl:0',quick=True)
            r.automatic_device.cache_clear()
            changed={**result('egl:0',.004),'version':'new driver'}
            with patch.object(r,'run_probe',side_effect=[changed,result(),{'devices':1},changed]):
                self.assertNotIn('Cached',r.automatic_device()['reason'])
            self.assertEqual(json.loads((Path(root)/'choice.json').read_text())['choice']['version'],'new driver')

    def test_failed_devices_fall_back_and_probe_crashes_are_contained(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(r.os.environ,{},clear=True),patch.object(r.sys,'platform','linux'),patch.object(r,'cache_path',return_value=Path(root)/'missing'),patch.object(r,'fingerprint',return_value='hardware'),patch.object(r,'run_probe',side_effect=[None,{'devices':1},None]):
            self.assertEqual(r.automatic_device()['device'],'system')
        with patch.object(r.subprocess,'run',return_value=type('Exit',(),dict(returncode=-11,stderr='driver crash'))()),self.assertLogs(r.LOG,level='WARNING'):
            self.assertIsNone(r.run_probe('egl:0'))
        with patch.object(r.subprocess,'run',side_effect=r.subprocess.TimeoutExpired('probe',8)),self.assertLogs(r.LOG,level='WARNING'):
            self.assertIsNone(r.run_probe('egl:0'))

    def test_explicit_device_and_validation(self):
        for value in ('auto','system','egl:0','egl:21'):self.assertEqual(r.device_option(value),value)
        for value in ('nvidia','egl:-1','egl:','0'):
            with self.assertRaises(ValueError):r.device_option(value)
        with patch.object(r,'new_window',return_value='window') as window,patch.object(r,'automatic_device') as auto:
            self.assertEqual(r.create_render_window('egl:2')[0],'window')
            window.assert_called_once_with('egl:2');auto.assert_not_called()
