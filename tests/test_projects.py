"""Project persistence, read-only inspection and transactional sample loading."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import tifffile
from trame.app import get_server

from sample_fixture import Demo
from tomoswaxs.projects import Project, legacy_axis
from tomoswaxs.volumes import VolumeSource, import_tiff


class ProjectChecks(unittest.TestCase):
    def test_new_manifests_follow_umask_and_saves_preserve_access(self):
        with tempfile.TemporaryDirectory() as folder:
            for mask,expected in ((0o002,0o664),(0o007,0o660),(0o027,0o640),(0o077,0o600)):
                with self.subTest(umask=oct(mask)):
                    previous_mask=os.umask(mask)
                    try:
                        project=Project.create(Path(folder)/str(mask),'Experiment')
                    finally:
                        os.umask(previous_mask)
                    self.assertEqual(project.path.stat().st_mode & 0o777,expected)
                    project.path.chmod(0o660)
                    group=project.path.stat().st_gid
                    previous_mask=os.umask(0o077)
                    try:
                        project.change(name='Updated experiment')
                    finally:
                        os.umask(previous_mask)
                    self.assertEqual(project.path.stat().st_mode & 0o777,0o660)
                    self.assertEqual(project.path.stat().st_gid,group)
                    self.assertEqual(Project.load(project.path).document['name'],'Updated experiment')
                    self.assertFalse(list(project.root.glob('.project-*')))

    def test_references_move_with_project_and_shared_datasets_keep_independent_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project=Project.create(root/'first','Experiment')
            image=project.root/'data'/'volume.zarr'; image.mkdir(parents=True)
            identifier=project.add_sample(image,'Sample',axis='z')
            self.assertEqual(project.sample(identifier)['datasets']['ct']['path'],'data/volume.zarr')
            project.update_sample(identifier,name='New name')
            shutil.move(project.root,root/'moved')
            reopened=Project.load(root/'moved')
            self.assertEqual(reopened.sample(identifier)['name'],'New name')
            self.assertTrue(reopened.dataset_path(reopened.sample(identifier)).is_dir())
            other=Project.create(root/'second','Other experiment')
            other_id=other.add_sample(reopened.dataset_path(reopened.sample(identifier)),'Shared image')
            self.assertTrue(Path(other.sample(other_id)['datasets']['ct']['path']).is_absolute())
            other.update_sample(other_id,settings={'rotation_axis':'x'})
            self.assertEqual(Project.load(root/'moved').sample(identifier)['settings']['rotation_axis'],'z')
            self.assertEqual(other.output_directory('figures',other_id),other.root/'figures'/other_id)
            self.assertFalse((other.root/'figures').exists())

    def test_atomic_write_failure_and_concurrent_edits_preserve_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Project.create(folder,'Experiment')
            before=project.path.read_bytes()
            with patch('tomoswaxs.projects.os.replace',side_effect=PermissionError('read-only')):
                with self.assertRaises(PermissionError):
                    project.change(name='Changed')
            self.assertEqual(project.path.read_bytes(),before)
            self.assertEqual(project.document['name'],'Experiment')
            self.assertFalse(list(Path(folder).glob('.project-*')))
            second=Project.load(folder);second.change(name='Other writer')
            with self.assertRaisesRegex(OSError,'changed on disk'):
                project.change(name='Stale writer')
            self.assertEqual(Project.load(folder).document['name'],'Other writer')
            with self.assertRaises(FileExistsError):
                Project.create(folder,'Overwrite')

    def test_invalid_manifest_and_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Project.create(folder,'Experiment')
            identifier=project.add_sample(None,'Synthetic')
            for field,value in [('version',99),('active_sample_id','missing'),('name','')]:
                invalid={**deepcopy(project.document),field:value}
                with self.assertRaises(ValueError):
                    Project(project.path,invalid)
            for view in ({'opacity':2},{'contrast_low':3,'contrast_high':1},{'beam_x':float('nan')},{'camera':{}}):
                with self.assertRaises(ValueError):
                    project.update_sample(identifier,view=view)
            with self.assertRaises(ValueError):
                project.update_sample(identifier,id='../escape')


class WorkflowChecks(unittest.TestCase):
    count=0
    def fixture(self,folder):
        path=Path(folder)/'input.tif'
        values=np.arange(12*13*14,dtype=np.uint16).reshape(12,13,14)
        tifffile.imwrite(path,values,metadata={'axes':'ZYX'})
        output=import_tiff(path,Path(folder)/'image.zarr',100)
        type(self).count+=1
        app=Demo(get_server(f'project-test-{self.count}',client_type='vue3'),volume=VolumeSource(output).preview(1))
        return app,path,output

    def new_project(self,app,directory,include=True):
        if app.state.picker_mode=='project_directory':
            directory.mkdir(parents=True,exist_ok=True)
            app.state.volume_directory=str(directory)
            app.finish_project_directory()
        app.state.update(project_new_directory=str(directory),project_include_current=include)
        app.create_project()
        self.assertEqual(app.state.project_error,'')
        return app.project

    def test_include_current_only_for_standalone_real_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            self.assertTrue(app.can_include_current())
            project=self.new_project(app,Path(folder)/'first')
            self.assertFalse(app.can_include_current())
            other=self.new_project(app,Path(folder)/'second')
            self.assertEqual(other.document['samples'],[])
            app.close_project()
            app.volume_source=None
            app.state.has_sample=True
            app.sync_project()
            app.new_project_dialog()
            self.assertFalse(app.state.can_include_current)
            self.assertFalse(app.state.project_include_current)

    def test_file_filter_defaults_follow_the_open_action(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            app.open_project_dialog()
            self.assertEqual(app.state.volume_name_filter,'project.json')
            self.assertEqual(app.state.volume_filter_options[0]['label'],'Projects (project.json)')
            app.choose_volume_filter('*')
            self.assertEqual(app.state.volume_name_filter,'*')
            app.open_volume_picker()
            self.assertIn('*.tiff',app.state.volume_name_filter)
            app.open_saxs_picker()
            self.assertEqual(app.state.volume_name_filter,'*_eiger_integrated.h5')

    def test_view_settings_camera_and_sample_selection_survive_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            (output/'nim-view.json').write_text('{"rotation_axis":"z"}')
            project=self.new_project(app,Path(folder)/'project')
            first=app.active_sample_id
            with app.state:
                app.state.rotation_axis='x'; app.state.beam_x=100; app.state.angle=37
                app.state.contrast_high=1500; app.state.opacity=.8
            app.update_scene()
            app.renderer.GetActiveCamera().Azimuth(25)
            app.limit_zoom()
            expected=app.capture_view()
            self.assertTrue(app.persist_active())
            second=project.add_sample(output,'Another sample',axis='z')
            async def check():
                await app.activate_sample(second)
                self.assertEqual(app.active_sample_id,second)
                self.assertEqual(app.state.rotation_axis,'z')
                await app.activate_sample(first)
                self.assertEqual(app.capture_view(),expected)
                app.close_project()
                self.assertIsNone(app.project)
                await app.open_project_path(project.path)
                self.assertEqual(app.active_sample_id,first)
                self.assertEqual(app.capture_view(),expected)
            asyncio.run(check())
            self.assertEqual((output/'nim-view.json').read_text(),'{"rotation_axis":"z"}')

    def test_legacy_axis_is_imported_on_add_and_standalone_changes_are_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            (output/'nim-view.json').write_text('{"rotation_axis":"z"}')
            self.assertEqual(legacy_axis(output),'z')
            app.state.volume_selection=str(output)
            asyncio.run(app._load_selected_volume())
            self.assertEqual(app.state.rotation_axis,'z')
            app.state.rotation_axis='x';app.rotation_axis_changed()
            self.assertTrue(app.persist_active())
            self.assertEqual(legacy_axis(output),'z')
            project=self.new_project(app,Path(folder)/'project')
            self.assertEqual(project.sample(app.active_sample_id)['settings']['rotation_axis'],'x')

    def test_missing_data_can_be_relinked_without_losing_sample_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            project=self.new_project(app,Path(folder)/'project')
            identifier=app.active_sample_id
            app.close_project()
            moved=Path(folder)/'renamed.zarr';output.rename(moved)
            old_volume=app.volume
            async def check():
                await app.open_project_path(project.path)
                self.assertTrue(app.state.project_error)
                self.assertIs(app.volume,old_volume)
                self.assertIsNone(app.active_sample_id)
                app._relink_id=identifier
                app.state.update(picker_mode='relink',volume_selection=str(moved))
                await app._load_selected_volume()
                self.assertFalse(app.state.volume_error,app.state.volume_error)
                self.assertEqual(app.active_sample_id,identifier)
                self.assertEqual(app.project.dataset_path(app.project.sample(identifier)),moved)
            asyncio.run(check())

    def test_tiff_external_and_create_project_destinations(self):
        with tempfile.TemporaryDirectory() as folder:
            app,tiff,_=self.fixture(folder)
            app.state.volume_selection=str(tiff);app.volume_selection_changed()
            external=Path(folder)/'external.zarr';app.state.volume_destination=str(external)
            asyncio.run(app._load_selected_volume())
            self.assertIsNone(app.project)
            self.assertTrue(external.exists())
            app.state.volume_selection=str(tiff);app.volume_selection_changed()
            app.show_new_project_for_tiff()
            project=self.new_project(app,Path(folder)/'project',include=False)
            destination=Path(app.state.volume_destination)
            self.assertTrue(destination.is_relative_to(project.root/'data'))
            self.assertEqual(project.document['samples'],[])
            asyncio.run(app._load_selected_volume())
            self.assertTrue(destination.is_dir())
            self.assertIsNotNone(app.active_sample_id)
            self.assertEqual(len(project.document['samples']),1)

    def test_opening_a_project_restores_its_sample_and_open_sample_adds_members(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            project=Project.create(Path(folder)/'project','Existing project')
            first=project.add_sample(None,'Earlier sample')
            asyncio.run(app.open_project_path(project.path))
            self.assertEqual(app.active_sample_id,first)
            app.state.volume_selection=str(output)
            asyncio.run(app._load_selected_volume())
            self.assertNotEqual(app.active_sample_id,first)
            self.assertEqual(len(app.project.document['samples']),2)
            self.assertEqual(app.project.dataset_path(app.project.sample(app.active_sample_id)),output)

    def test_samples_can_be_listed_renamed_and_removed_without_deleting_data(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            project=self.new_project(app,Path(folder)/'project')
            first=app.active_sample_id
            second=project.add_sample(output,'Second sample')
            app.show_samples()
            self.assertEqual(len(app.state.project_samples),2)
            app.select_managed_sample(second)
            app.state.managed_sample_name='Renamed sample'
            app.rename_managed_sample()
            self.assertEqual(project.sample(second)['name'],'Renamed sample')
            asyncio.run(app._remove_managed_sample())
            self.assertEqual(app.active_sample_id,first)
            self.assertEqual(len(project.document['samples']),1)
            self.assertTrue(output.is_dir())
            app.select_managed_sample(first)
            asyncio.run(app._remove_managed_sample())
            self.assertEqual(project.document['samples'],[])
            self.assertIsNone(project.document['active_sample_id'])
            self.assertIsNone(app.active_sample_id)
            self.assertFalse(app.state.has_sample)
            self.assertEqual(app.state.sample_name,'')
            self.assertTrue(output.is_dir())
            with self.assertRaisesRegex(ValueError,'Open a sample'):
                app.capture_view()
            app.state.volume_selection=str(output)
            asyncio.run(app._load_selected_volume())
            self.assertTrue(app.state.has_sample)
            self.assertEqual(len(project.document['samples']),1)

    def test_removing_the_active_sample_switches_and_failed_replacement_keeps_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            project=self.new_project(app,Path(folder)/'project')
            first=app.active_sample_id
            second=project.add_sample(output,'Second sample')
            app.show_samples()
            app.select_managed_sample(first)
            with patch('tomoswaxs.project_workflow.VolumeSource',side_effect=OSError('Cannot read replacement')):
                asyncio.run(app._remove_managed_sample())
            self.assertEqual(len(project.document['samples']),2)
            self.assertEqual(app.active_sample_id,first)
            self.assertIn('Cannot read replacement',app.state.sample_manager_error)
            asyncio.run(app._remove_managed_sample())
            self.assertEqual(app.active_sample_id,second)
            self.assertEqual(project.document['active_sample_id'],second)
            self.assertEqual(len(project.document['samples']),1)
            self.assertTrue(output.is_dir())

    def test_empty_project_does_not_adopt_a_standalone_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            project=Project.create(Path(folder)/'empty','Empty')
            asyncio.run(app.open_project_path(project.path))
            self.assertFalse(app.state.has_sample)
            self.assertEqual(app.state.sample_choices,[])
            self.assertEqual(app.project.document['samples'],[])
            app.close_project()
            self.assertFalse(app.state.has_sample)

    def test_project_directory_picker_preserves_pending_tiff_and_can_create_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            app,tiff,_=self.fixture(folder)
            root=Path(folder)
            app.state.update(volume_selection=str(tiff),show_volume_picker=True)
            app.volume_selection_changed()
            app.state.update(volume_voxel_x=12,volume_voxel_y=13,volume_voxel_z=14,
                             volume_voxel_linked=False,volume_destination=str(root/'chosen.zarr'))
            app.show_new_project_for_tiff()
            identifier=app._import_sample_id
            app.browse_project_directory()
            self.assertEqual(app.state.picker_mode,'project_directory')
            self.assertTrue(all(Path(entry['path']).is_dir() and not entry['path'].endswith('.zarr')
                                for entry in app.state.volume_entries))
            app.state.project_new_folder='experiment'
            app.create_project_folder()
            self.assertEqual(Path(app.state.volume_directory),root/'experiment')
            self.assertTrue((root/'experiment').is_dir())
            app.finish_project_directory()
            self.assertEqual(Path(app.state.project_new_directory),root/'experiment')
            self.assertEqual(app.state.volume_selection,str(tiff))
            self.assertEqual(app.state.volume_destination,str(root/'chosen.zarr'))
            self.assertEqual([app.state.volume_voxel_x,app.state.volume_voxel_y,app.state.volume_voxel_z],[12,13,14])
            self.assertEqual(app._import_sample_id,identifier)
            self.assertTrue(app.state.show_volume_picker)
            self.assertTrue(app.state.show_project)
            self.assertTrue(app.state.project_for_tiff)
            app.browse_project_directory()
            app.state.volume_directory=str(root)
            app.cancel_volume_load()
            self.assertEqual(Path(app.state.project_new_directory),root/'experiment')
            self.assertEqual(app.state.picker_mode,'volume')
            self.assertEqual(app.state.volume_selection,str(tiff))

    def test_external_destination_browse_preserves_import_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            app,tiff,_=self.fixture(folder)
            app.state.volume_selection=str(tiff)
            app.volume_selection_changed()
            original=str(Path(folder)/'custom.ome.zarr')
            app.state.update(volume_destination=original,volume_voxel_x=12,show_volume_picker=True)
            app.browse_import_destination()
            self.assertEqual(app.state.directory_picker_title,'Select conversion directory')
            target=Path(folder)/'destination';target.mkdir()
            app.state.volume_directory=str(target)
            app.finish_project_directory()
            self.assertEqual(app.state.volume_destination,str(target/'custom.ome.zarr'))
            self.assertEqual(app.state.volume_selection,str(tiff))
            self.assertEqual(app.state.volume_voxel_x,12)
            self.assertFalse(app.state.show_project)
            app.browse_import_destination()
            app.state.volume_directory=folder
            app.cancel_volume_load()
            self.assertEqual(app.state.volume_destination,str(target/'custom.ome.zarr'))
            self.assertTrue(app.state.show_volume_picker)

    def test_directory_picker_navigates_and_rejects_invalid_folder_names(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            root=Path(folder);child=root/'child';child.mkdir()
            app.browse_project_directory()
            for name in ('','..','../escape','child'):
                app.state.project_new_folder=name
                app.create_project_folder()
                self.assertTrue(app.state.volume_error)
                self.assertTrue(child.is_dir())
            app.state.volume_selection=str(child)
            asyncio.run(app._load_selected_volume())
            self.assertEqual(Path(app.state.volume_directory),child)
            app.finish_project_directory()
            self.assertEqual(Path(app.state.project_new_directory),child)

    def test_new_project_uses_directory_name_and_dialogs_have_separate_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            self.assertEqual(app.state.project_new_directory,'')
            app.new_project_dialog()
            self.assertEqual(app.state.project_dialog_mode,'new')
            self.assertEqual(app.state.picker_mode,'project_directory')
            self.assertTrue(app.state.show_volume_picker)
            self.assertFalse(app.state.show_project)
            app.finish_project_directory(False)
            self.assertFalse(app.state.show_project)
            project=self.new_project(app,Path(folder)/'Beamline experiment')
            self.assertEqual(project.document['name'],'Beamline experiment')
            app.show_project_settings()
            self.assertEqual(app.state.project_dialog_mode,'settings')
            app.open_project_dialog()
            self.assertEqual(app.state.picker_mode,'project')
            self.assertTrue(app.state.show_volume_picker)
            self.assertFalse(app.state.show_project)
            app.close_project()
            app.new_project_dialog()
            self.assertEqual(app.state.project_dialog_mode,'new')

    def test_directory_failures_are_visible_and_keep_the_current_listing(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            app.state.volume_directory=folder
            app.list_volume_directory()
            entries=deepcopy(app.state.volume_entries)
            child=Path(folder)/'unreadable';child.mkdir()
            app.state.volume_selection=str(child)
            with patch('tomoswaxs.app.directory_entries',side_effect=PermissionError('Permission denied')):
                with self.assertLogs('tomoswaxs.app',level='ERROR'):
                    asyncio.run(app._load_selected_volume())
            self.assertIn(str(child),app.state.volume_error)
            self.assertIn('Permission denied',app.state.volume_error)
            self.assertEqual(app.state.volume_directory,folder)
            self.assertEqual(app.state.volume_entries,entries)

    def test_project_chooser_reports_invalid_projects_and_unexpected_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            invalid=Path(folder)/'project.json';invalid.write_text('{broken')
            app.open_project_dialog()
            app.state.volume_selection=str(invalid)
            asyncio.run(app._load_selected_volume())
            self.assertTrue(app.state.show_volume_picker)
            self.assertIn('Cannot open project',app.state.volume_error)
            with patch.object(app,'load_volume_selection',side_effect=RuntimeError('unexpected test failure')):
                with self.assertLogs('tomoswaxs.app',level='ERROR'):
                    asyncio.run(app._load_selected_volume())
            self.assertIn('RuntimeError: unexpected test failure',app.state.volume_error)

    def test_project_open_failures_are_visible_for_picker_recent_and_sample_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            invalid=Path(folder)/'project.json';invalid.write_text('{broken')
            app.open_project_dialog()
            asyncio.run(app.open_project_path(invalid))
            self.assertTrue(app.state.show_project_open_error)
            self.assertEqual(app.state.project_open_error,app.state.volume_error)
            self.assertTrue(app.state.show_volume_picker)
            app.state.update(picker_mode='volume',show_volume_picker=False)
            asyncio.run(app.open_project_path(Path(folder)/'missing.json'))
            self.assertTrue(app.state.show_project_open_error)
            self.assertIn('missing.json',app.state.project_open_error)
            with patch.object(Project,'load',side_effect=RuntimeError('unexpected failure')):
                with self.assertLogs('tomoswaxs.project_workflow',level='ERROR'):
                    asyncio.run(app.open_project_path(invalid))
            self.assertIn('RuntimeError: unexpected failure',app.state.project_open_error)
            project=Project.create(Path(folder)/'broken-sample','Broken sample')
            project.add_sample(Path(folder)/'missing.ome.zarr','Missing CT')
            asyncio.run(app.open_project_path(project.path))
            self.assertTrue(app.state.show_project_open_error)
            self.assertIn('sample could not be loaded',app.state.project_open_error)
            empty=Project.create(Path(folder)/'empty','Empty project')
            asyncio.run(app.open_project_path(empty.path))
            self.assertFalse(app.state.show_project_open_error)
            self.assertEqual(app.state.project_open_error,'')

    def test_failed_save_prevents_sample_switch_and_old_pose_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            project=self.new_project(app,Path(folder)/'project')
            first=app.active_sample_id
            second=project.add_sample(output,'Second sample')
            app.state.opacity=.6
            with patch.object(project,'_write',side_effect=PermissionError('read-only')):
                asyncio.run(app.activate_sample(second))
            self.assertEqual(app.active_sample_id,first)
            self.assertIn('Could not save',app.state.project_error)
            stale=app.state.sample_context
            asyncio.run(app.activate_sample(second))
            before=app.state.beam_x
            app.receive_pose({'beam_x':150},True,stale)
            app.receive_beam_position(.1,.1,True,True,stale)
            self.assertEqual(app.state.beam_x,before)

    def test_reload_recovers_from_external_manifest_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,_=self.fixture(folder)
            project=self.new_project(app,Path(folder)/'project')
            saved_x=app.state.beam_x
            external=Project.load(project.path);external.change(name='Changed externally')
            app.state.beam_x=150
            self.assertFalse(app.persist_active())
            asyncio.run(app.open_project_path(project.path,discard=True))
            self.assertEqual(app.state.project_name,'Changed externally')
            self.assertEqual(app.state.beam_x,saved_x)

    def test_cancelled_and_stale_background_loads_preserve_current_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            app,_,output=self.fixture(folder)
            before=app.volume
            entered=threading.Event();release=threading.Event()
            original=VolumeSource.preview
            def delayed(source,*args,**kwargs):
                entered.set();release.wait(10)
                return original(source,*args,**kwargs)
            async def check():
                with patch.object(VolumeSource,'preview',delayed):
                    task=asyncio.create_task(app.load_sample(output,None))
                    await asyncio.to_thread(entered.wait,5)
                    app.cancel_volume_load();release.set()
                    await task
                self.assertIs(app.volume,before)
                self.assertIn('cancelled',app.state.volume_error.lower())
                entered.clear();release.clear()
                with patch.object(VolumeSource,'preview',delayed):
                    task=asyncio.create_task(app.load_sample(output,None))
                    await asyncio.to_thread(entered.wait,5)
                    app.state.sample_context='newer selection'
                    release.set();await task
                self.assertIs(app.volume,before)
            asyncio.run(check())
