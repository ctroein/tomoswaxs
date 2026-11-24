"""Saved pose/camera bookmarks, isolation and atomic recall."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from trame.app import get_server
from sample_fixture import Demo
from tomoswaxs.projects import Project


class SavedViewChecks(unittest.TestCase):
    def app(self):
        app=Demo(get_server('saved-view-'+uuid.uuid4().hex,client_type='vue3'))
        self.addCleanup(app.window.Finalize)
        return app

    def save(self,app,name):
        app.begin_save_view()
        app.state.saved_view_name=name
        app.commit_saved_view()
        self.assertFalse(app.state.saved_view_error)
        return app.current_saved_views()[-1]

    def test_recall_restores_pose_and_camera_once_and_rejects_old_input(self):
        app=self.app()
        app.receive_pose({'beam_x':300,'beam_y':-200,'angle':37.25},True)
        camera=app.renderer.GetActiveCamera()
        camera.SetPosition(5,6,7);camera.SetFocalPoint(.2,-.3,.4);camera.SetViewUp(0,1,0)
        camera.SetViewAngle(25);camera.SetParallelScale(1.2)
        saved=self.save(app,'North side')
        app.receive_pose({'beam_x':-500,'beam_y':600,'angle':-80},True)
        camera.SetPosition(8,7,6);camera.SetParallelProjection(True);camera.SetParallelScale(2.3)
        with app.state:
            app.state.opacity=.8
            app.state.radius_x=120
        previous=app.state.sample_context
        with patch.object(app.view,'update') as render:
            app.recall_saved_view(saved['id'],previous)
        self.assertEqual(render.call_count,1)
        self.assertEqual([app.state.beam_x,app.state.beam_y,app.state.angle],[300,-200,37.25])
        self.assertEqual(app.capture_view()['camera'],saved['view']['camera'])
        self.assertEqual(app.state.opacity,.8)
        self.assertEqual(app.state.radius_x,120)
        self.assertNotEqual(app.state.sample_context,previous)
        app.receive_pose({'angle':150},True,previous)
        self.assertEqual(app.state.angle,37.25)

    def test_name_validation_rename_and_delete(self):
        app=self.app()
        app.begin_save_view();app.state.saved_view_name=' ';app.commit_saved_view()
        self.assertTrue(app.state.show_saved_view_dialog)
        self.assertFalse(app.current_saved_views())
        app.state.saved_view_name='Face';app.commit_saved_view()
        item=app.current_saved_views()[0]
        app.begin_save_view();app.state.saved_view_name=' FACE ';app.commit_saved_view()
        self.assertIn('already',app.state.saved_view_error)
        self.assertEqual(len(app.current_saved_views()),1)
        app.cancel_saved_view_dialog()
        app.manage_saved_views();app.begin_rename_saved_view(item['id'])
        app.state.saved_view_name='Other side';app.commit_saved_view()
        self.assertEqual(app.current_saved_views()[0]['id'],item['id'])
        self.assertEqual(app.current_saved_views()[0]['name'],'Other side')
        app.delete_saved_view(item['id'])
        self.assertFalse(app.current_saved_views())

    def test_latest_client_pose_is_captured_and_stale_dialog_cannot_save(self):
        app=self.app()
        app.begin_save_view({'beam_x':'123.4','beam_y':'-56.7','angle':'185.25'},app.state.sample_context)
        app.state.saved_view_name='Latest';app.commit_saved_view()
        self.assertEqual(app.current_saved_views()[0]['view']['angle'],-174.75)
        self.assertEqual(app.current_saved_views()[0]['view']['beam_x'],123.4)
        app.begin_save_view(context=app.state.sample_context)
        app.state.sample_context=uuid.uuid4().hex
        app.state.saved_view_name='Stale';app.commit_saved_view()
        self.assertIn('changed',app.state.saved_view_error)
        self.assertEqual(len(app.current_saved_views()),1)

    def test_project_sample_isolation_reopen_and_standalone_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Project.create(Path(folder)/'project','Experiment')
            first=project.add_sample(None,'First');second=project.add_sample(None,'Second')
            app=self.app();app.project=project;app.active_sample_id=first;app.sync_project()
            saved=self.save(app,'First view')
            asyncio.run(app.activate_sample(second))
            self.assertFalse(app.current_saved_views())
            self.save(app,'Second view')
            reopened=Project.load(project.path)
            self.assertEqual(reopened.sample(first)['saved_views'][0],saved)
            self.assertEqual(reopened.sample(second)['saved_views'][0]['name'],'Second view')
            app.close_project()
            self.assertEqual(app.current_saved_views()[0]['name'],'Second view')
            app.state.project_new_directory=str(Path(folder)/'copy');app.create_project()
            copied=Project.load(Path(folder)/'copy')
            self.assertEqual(copied.document['samples'],[])

    def test_invalid_project_bookmark_preserves_manifest(self):
        app=self.app();saved=self.save(app,'View')
        with tempfile.TemporaryDirectory() as folder:
            project=Project.create(folder,'Experiment');identifier=project.add_sample(None,'Sample')
            original=project.path.read_bytes()
            invalid=deepcopy(saved);invalid['view']['camera']['view_up']=[0,0,0]
            with self.assertRaises(ValueError):
                project.update_sample(identifier,saved_views=[invalid])
            self.assertEqual(project.path.read_bytes(),original)

    def test_project_name_applies_on_close_and_retains_relink_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Project.create(folder,'Old');first=project.add_sample(None,'First');project.add_sample(None,'Second')
            app=self.app();app.project=project;app.active_sample_id=first;app.sync_project()
            app.show_project_settings();app.state.project_relink_choice=first
            app.state.project_name_draft='New name';app.close_project_dialog()
            self.assertEqual(Project.load(folder).document['name'],'New name')
            self.assertFalse(app.state.show_project)
            self.assertEqual(app.state.project_relink_choice,first)
            app.show_project_settings();app.state.project_name_draft=' ';app.close_project_dialog()
            self.assertTrue(app.state.show_project)
            self.assertEqual(Project.load(folder).document['name'],'New name')
