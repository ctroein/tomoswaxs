"""Measured scattering identity, acquisition coordinates and bounded asynchronous selection."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import h5py
import numpy as np
from trame.app import get_server

from tomoswaxs.scattering_data import IntegratedScan,scan_specs
from sample_fixture import Demo
from tomoswaxs.projects import Project


def fixture(root,number=135,y=-2.):
    root=Path(root);(root/'Metadata').mkdir(exist_ok=True)
    path=root/f'scan-{number:04}_eiger_integrated.h5'
    metadata=root/'Metadata'/f'scan-{number:04}.h5'
    with h5py.File(metadata,'w') as f:
        f['entry/title']='mesh swaxs_x -0.01 0.005 3 tomo_ry 90 110 2 0.05 False False'
        f['entry/measurement/swaxs_x']=np.tile(np.linspace(-.01,.005,4),3)+.00001
        angles=np.repeat([90.,100.,110.],4);angles[4]=90.
        f['entry/measurement/tomo_ry']=angles
        f['entry/instrument/start_positioners/swaxs_y']=y
    with h5py.File(path,'w') as f:
        for base in ('entry/default/data1d/orig','entry/default/data2d/orig'):
            f[base+'/q']=[.1,.2,.3];f[base+'/q'].attrs['units']='1/angstrom'
        f['entry/default/data1d/orig/I']=100+np.arange(36,dtype=float).reshape(12,3)
        f['entry/default/data1d/orig/norm']=[0.,1.,1.]
        f['entry/default/data2d/orig/azi']=[1.,3.];f['entry/default/data2d/orig/azi'].attrs['units']='degrees'
        f['entry/default/data2d/orig/cake']=1+np.arange(72,dtype=float).reshape(12,2,3)
        f['entry/default/data2d/orig/norm']=[[0.,1.,1.],[0.,0.,1.]]
    return path


class ScanChecks(unittest.TestCase):
    def test_frame_identity_masks_and_nominal_vs_recorded_coordinates(self):
        with tempfile.TemporaryDirectory() as root:
            scan=IntegratedScan(fixture(root))
            self.assertEqual(scan.index.shape,(3,4))
            self.assertEqual(scan.index.nearest(-4.9,100),(1,1))
            self.assertEqual(scan.index.nearest(5,-250),(2,3))
            self.assertTrue(scan.index.details(1,0)['angle_flag'])
            self.assertEqual(scan.index.details(1,0)['angle'],90)
            self.assertEqual(scan.index.details(1,0)['nominal_angle'],100)
            q,phi,cake,intensity=scan.read(1,0)
            self.assertTrue(np.isnan(intensity[0]))
            np.testing.assert_array_equal(intensity[1:],[113.,114.])
            self.assertTrue(np.isnan(cake[1,1]))
            self.assertEqual(cake[1,2],30.)
            self.assertEqual(scan.index.details(1,0)['y_um'],-2000.)
            self.assertEqual(scan.q_unit,'1/angstrom')
            self.assertIs(scan.read(1,0)[2],cake)

    def test_mismatched_frames_rejected_and_source_files_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path=fixture(root);before=path.stat().st_mtime_ns
            scan=IntegratedScan(path);scan.read(0,0)
            self.assertEqual(path.stat().st_mtime_ns,before)
            with h5py.File(path,'a') as f:
                del f['entry/default/data1d/orig/I'];f['entry/default/data1d/orig/I']=np.zeros((11,3))
            with self.assertRaisesRegex(ValueError,'different dimensions'):
                IntegratedScan(path)


class WorkflowChecks(unittest.TestCase):
    def test_only_untouched_ct_motor_estimate_upgrades_to_stack(self):
        from tomoswaxs.registration import motor_rows
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);scattering=root/'Scattering data';scattering.mkdir()
            path=fixture(scattering)
            reference=dict(tab_x=0.,tab_y=0.,swaxs_x=0.,swaxs_y=-2.,tomo_xf=0.,tomo_zf=0.)
            with h5py.File(scattering/'Metadata/scan-0135.h5','a') as f:
                for k,v in reference.items():
                    if k!='swaxs_y':f['entry/instrument/start_positioners/'+k]=v
            (root/'Metadata_CT').mkdir()
            with h5py.File(root/'Metadata_CT/Radiographs.h5','w') as f:
                for k,v in reference.items():f['entry/instrument/start_positioners/'+k]=v
            app=self.app()
            async def run():
                await app.attach_saxs(scan_specs(path));await app._saxs_task
                saved=deepcopy(app._saxs_config)
                saved['placement'].update(model='motors',motors=motor_rows(reference))
                await app.attach_saxs(saved['scans'],saved);await app._saxs_task
                self.assertEqual(app._saxs_config['placement']['model'],'stack')
                saved['placement']['camera_x']=12.
                await app.attach_saxs(saved['scans'],saved);await app._saxs_task
                self.assertEqual(app._saxs_config['placement']['model'],'motors')
                self.assertEqual(app._saxs_config['placement']['camera_x'],12.)
            asyncio.run(run())

    def test_stack_axis_parameters_persist_and_swaxs_rotation_is_flagged(self):
        from tomoswaxs.registration import stack_rows
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);path=fixture(root)
            with h5py.File(root/'Metadata/scan-0135.h5','a') as f:
                for name in ('tab_x','tab_y','swaxs_x','tomo_xf','tomo_zf'):
                    f['entry/instrument/start_positioners/'+name]=0.
                f['entry/instrument/start_positioners/swaxs_ry']=0.
            app=self.app()
            async def run():
                await app.attach_saxs(scan_specs(path));await app._saxs_task
                mapping={**app._saxs_config['placement'],'model':'stack',
                         'motors':stack_rows({}),'pivot_x':520.,'pivot_z':370.}
                app.receive_saxs_selection(dict(scan=0,row=0,column=0,placement=mapping),app.state.sample_context)
                await app._saxs_task
                self.assertEqual(app._saxs_config['placement']['pivot_x'],520.)
                self.assertIn('swaxs_ry',app.state.saxs_flag)
                self.assertEqual(len(app.state.saxs_axes[0]['x_by_angle']),3)
                saved=deepcopy(app.scattering_record())
                await app.attach_saxs(saved['scans'],saved);await app._saxs_task
                self.assertEqual(app._saxs_config['placement']['pivot_z'],370.)
                self.assertEqual(app.state.saxs_map_model,'stack')
            asyncio.run(run())

    def app(self):
        app=Demo(get_server('saxs-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        return app

    def test_attach_selection_placement_and_project_restore(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);fixture(root);fixture(root,136,-1.9)
            app=self.app()
            project=Project.create(root/'project','Experiment')
            identifier=project.add_sample(None,'Sample')
            async def run():
                await app.open_project_path(project.path)
                await app.attach_saxs(scan_specs(root))
                await app._saxs_task
                self.assertTrue(app.state.saxs_available)
                self.assertEqual(app.signal_kind,'measured')
                spec=dict(scan=1,row=2,column=3,placement=app._saxs_config['placement'],link_ct=True,restrict_y=True)
                app.receive_saxs_selection(spec,app.state.sample_context)
                await app._saxs_task
                self.assertEqual(app.state.saxs_column,3)
                self.assertAlmostEqual(app.state.beam_x,7.5)
                self.assertAlmostEqual(app.state.beam_y,100.)
                self.assertNotIn('restrict_y',app._saxs_config)
                record=Project.load(project.path).sample(identifier)['datasets']['scattering']
                self.assertEqual(record['kind'],'formax-integrated')
                self.assertEqual(record['selection'],dict(scan=1,row=2,column=3))
                await app.open_project_path(project.path)
                await app._saxs_attach_task
                await app._saxs_task
                self.assertEqual(app.state.saxs_scan,1)
                self.assertEqual(app.state.saxs_column,3)
                np.testing.assert_array_equal(app.signal[3][1:],[134.,135.])
                app.close_project()
                await app._saxs_attach_task;await app._saxs_task
                app.state.project_new_directory=str(root/'new-project')
                app.state.project_include_current=True
                app.create_project()
                await app._saxs_attach_task;await app._saxs_task
                self.assertEqual(app.project.document['samples'],[])
            asyncio.run(run())

    def test_latest_frame_and_old_sample_reads_are_discarded(self):
        with tempfile.TemporaryDirectory() as root:
            fixture(root);app=self.app()
            async def run():
                await app.attach_saxs(scan_specs(root));await app._saxs_task
                scan=app.saxs_scans[0];original=scan.read
                entered=threading.Event();release=threading.Event();calls=[]
                def slow(row,column):
                    calls.append((row,column));entered.set();release.wait(5)
                    return original(row,column)
                with patch.object(scan,'read',side_effect=slow):
                    app.request_saxs_frame(0,0,0)
                    while not entered.is_set():await asyncio.sleep(.001)
                    app.request_saxs_frame(0,0,1)
                    app.request_saxs_frame(0,2,3)
                    release.set();await app._saxs_task
                self.assertEqual(calls,[(0,0),(2,3)])
                self.assertEqual(app.state.saxs_row,2)
                app._saxs_config['link_ct']=True;app.state.saxs_link_ct=True
                app.receive_pose(dict(beam_x=7.5,beam_y=0.,angle=110.),True,app.state.sample_context)
                if app._saxs_task:await app._saxs_task
                entered.clear();release.clear()
                with patch.object(scan,'read',side_effect=slow):
                    app.request_saxs_frame(0,2,3)
                    while not entered.is_set():await asyncio.sleep(.001)
                    app.receive_pose(dict(beam_x=7.4),True,app.state.sample_context)
                    release.set();await app._saxs_task
                self.assertEqual(app.state.beam_x,7.4,'A delayed measurement read cannot snap a newer continuous pose')
                previous=deepcopy(app.state.saxs_frame_info)
                entered.clear();release.clear()
                with patch.object(scan,'read',side_effect=slow):
                    app.request_saxs_frame(0,0,0)
                    while not entered.is_set():await asyncio.sleep(.001)
                    app.state.sample_context='different-sample'
                    release.set();await app._saxs_task
                self.assertEqual(app.state.saxs_frame_info,previous)
            asyncio.run(run())

    def test_failed_reads_are_visible_and_switching_samples_restores_sources(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);fixture(root);app=self.app()
            project=Project.create(root/'project','Experiment')
            first=project.add_sample(None,'Measured');second=project.add_sample(None,'Other')
            async def run():
                await app.open_project_path(project.path)
                await app.activate_sample(first)
                await app.attach_saxs(scan_specs(root));await app._saxs_task
                with patch.object(app.saxs_scans[0],'read',side_effect=OSError('disk read failed')):
                    with self.assertLogs('tomoswaxs.saxs_workflow',level='ERROR'):
                        app.request_saxs_frame(0,0,0);await app._saxs_task
                self.assertIn('disk read failed',app.state.saxs_error)
                self.assertFalse(app.state.saxs_loading)
                await app.activate_sample(second)
                self.assertFalse(app.state.saxs_available)
                self.assertIsNone(app._saxs_config)
                self.assertEqual(app.signal_kind,'none')
                await app.activate_sample(first)
                await app._saxs_attach_task;await app._saxs_task
                self.assertTrue(app.state.saxs_available)
                self.assertEqual(app.signal_kind,'measured')
                # Recall of a saved view changes the context even within one sample.
                app.state.saxs_link_ct=True
                app.state.sample_context='recalled-view'
                app.saxs_from_pose();await app._saxs_task
                self.assertEqual(app._saxs_requested_context,'recalled-view')
            asyncio.run(run())

    def test_restore_survives_cli_setup_loop_closing(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);fixture(root);app=self.app()
            project=Project.create(root/'project','Experiment')
            project.add_sample(None,'Measured')
            async def prepare():
                await app.open_project_path(project.path)
                await app.attach_saxs(scan_specs(root));await app._saxs_task
            asyncio.run(prepare())
            asyncio.run(app.open_project_path(project.path))
            async def server_ready():
                app.restore_saxs()
                if app._saxs_attach_task:await app._saxs_attach_task
                if app._saxs_task:await app._saxs_task
            asyncio.run(server_ready())
            self.assertTrue(app.state.saxs_available)
            self.assertTrue(app.state.saxs_frame_info)
