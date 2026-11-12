"""Dependency policy and guarded acceptance checks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement

spec = importlib.util.spec_from_file_location('dependency_trial', Path(__file__).parents[1]/'tools/try_dependency_updates.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class DependencyChecks(unittest.TestCase):
    def test_trial_preserves_minimum_exclusions_extras_and_marker(self):
        text = trial.trial_requirements(['example[fast]>=1.2,!=1.3,<2; python_version >= "3.12"'], {})[0]
        requirement = Requirement(text)
        self.assertEqual(requirement.extras, {'fast'})
        self.assertIsNotNone(requirement.marker)
        self.assertNotIn('1.1', requirement.specifier)
        self.assertNotIn('1.3', requirement.specifier)
        self.assertIn('3.0', requirement.specifier)

    def test_keep_exception_and_implicit_bound(self):
        self.assertEqual(trial.trial_requirements(['example~=1.2'], {'Example':'API series'}), ['example~=1.2'])
        with self.assertRaises(ValueError):
            trial.trial_requirements(['example~=1.2'], {})
        with self.assertRaises(ValueError):
            trial.trial_requirements(['example<2'], {'example':''})

    def test_accept_raises_only_upper_limit(self):
        result = trial.accepted_requirements(['example>=1.2,<1.4'], {'example':'2.7.3'}, {})[0]
        self.assertEqual(set(map(str, Requirement(result).specifier)), {'>=1.2','<2.8'})
        self.assertEqual(trial.accepted_requirements(['example>=1.2,<1.4'], {'example':'1.3.4'}, {}), ['example>=1.2,<1.4'])
        with self.assertRaises(ValueError):
            trial.accepted_requirements(['example>=1.2,<1.4'], {'example':'2.7rc1'}, {})

    def test_promotion_rejects_concurrent_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'root'; root.mkdir()
            candidate = Path(directory)/'candidate'; candidate.mkdir()
            for name in ('pyproject.toml','uv.lock'):
                (root/name).write_text('original')
                (candidate/name).write_text('candidate')
            expected = trial.fingerprint(root)
            (root/'source.py').write_text('edited')
            with self.assertRaises(RuntimeError):
                trial.promote(root, candidate, expected)
            self.assertEqual((root/'pyproject.toml').read_text(), 'original')

    def test_partial_promotion_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'root'; root.mkdir()
            candidate = Path(directory)/'candidate'; candidate.mkdir()
            for name in ('pyproject.toml','uv.lock'):
                (root/name).write_text('original')
                (candidate/name).write_text('candidate')
            replace = trial.os.replace
            def fail_lock(source, target):
                if Path(target).name == 'uv.lock':
                    raise OSError('test write failure')
                replace(source, target)
            with patch.object(trial.os, 'replace', side_effect=fail_lock):
                with self.assertRaises(OSError):
                    trial.promote(root, candidate, trial.fingerprint(root))
            for name in ('pyproject.toml','uv.lock'):
                self.assertEqual((root/name).read_text(), 'original')
