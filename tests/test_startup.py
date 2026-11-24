"""Empty startup, legacy sample handling and guarded project recovery."""
import asyncio
from pathlib import Path
import tempfile
import unittest
import uuid
from trame.app import get_server
from tomoswaxs.app import Demo
from tomoswaxs.projects import Project


class StartupChecks(unittest.TestCase):
    def app(self,**kwargs):
        kwargs.setdefault('render_device','system')
        app=Demo(get_server('startup-'+uuid.uuid4().hex,client_type='vue3'),**kwargs)
        self.addCleanup(app.window.Finalize)
        return app

    def test_empty_startup_has_no_rendered_specimen_or_beam(self):
        app=self.app()
        self.assertFalse(app.state.has_sample)
        self.assertFalse(app.state.has_volume)
        self.assertFalse(app.sample.GetVisibility())
        self.assertFalse(app.beam.GetVisibility())
        self.assertEqual(app.volume.size,8)
        self.assertIsNone(app.volume_source)
        self.assertEqual(app.state.volume_summary,'No sample open')

    def test_recovery_is_once_only_and_explicit_startup_takes_precedence(self):
        with tempfile.TemporaryDirectory() as root:
            path=Project.create(Path(root)/'project','Recovered').path
            async def run():
                app=self.app()
                app.open_recent_project(str(path),True);await app._volume_task
                self.assertEqual(app.state.project_name,'Recovered')
                self.assertEqual(app.state.project_history_event['kind'],'opened')
                app.close_project()
                self.assertEqual(app.state.project_history_event['kind'],'closed')
                app.open_recent_project(str(path),True)
                self.assertIsNone(app.project)
                explicit=self.app(restore_project=False)
                explicit.open_recent_project(str(path),True)
                self.assertIsNone(explicit.project)
            asyncio.run(run())

    def test_missing_recovery_is_visible_and_retains_empty_workspace(self):
        app=self.app()
        async def run():
            app.open_recent_project('/missing-tomoswaxs-project/project.json',True)
            await app._volume_task
            self.assertTrue(app.state.project_error)
            self.assertIsNone(app.project)
            self.assertFalse(app.state.has_sample)
        asyncio.run(run())

    def test_legacy_generated_record_opens_without_a_fabricated_volume(self):
        with tempfile.TemporaryDirectory() as root:
            p=Project.create(root,'Legacy')
            identifier=p.add_sample(None,'Old example')
            record=p.sample(identifier);p.update_sample(identifier,datasets={**record['datasets'],'ct':{'kind':'synthetic'}})
            app=self.app()
            asyncio.run(app.open_project_path(p.path))
            self.assertEqual(app.active_sample_id,identifier)
            self.assertTrue(app.state.has_sample)
            self.assertFalse(app.state.has_volume)
            self.assertFalse(app.sample.GetVisibility())
            self.assertEqual(app.volume.size,8)
