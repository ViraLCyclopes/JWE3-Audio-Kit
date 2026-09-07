"""Packaging and deployment failure regression tests; never touch the game."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audio_paths
import bundle_integrity as bundle
import deploy_local as deploy


class PackagingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='vlaudio-packaging-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.kit = self.root/'kit'
        self.vendor = self.kit/'vendor'
        self.cobra = self.vendor/'cobra-tools'
        self.cobra.mkdir(parents=True)
        (self.cobra/'ovl_tool_cmd.py').write_bytes(b'# fixture')
        self.pin()
        self.game = self.root/'game'
        self.game.mkdir()
        self.backup = self.root/'backups'
        self.backup.mkdir()
        self.receipt = self.root/'receipt.json'
        self.config = self.game/'JWE3 Audio Kit/audio_tools.json'
        self.config.parent.mkdir()
        self.config.write_bytes(b'{"cobra_tools": "intentional checkout"}')

    def pin(self):
        data = {'schema': 1, 'files': {p: bundle.digest(f) for p,f in bundle.bundle_files(self.vendor).items()}}
        (self.vendor/bundle.MANIFEST).write_text(json.dumps(data), encoding='utf-8')

    def test_bundle_valid_and_bytecode_ignored(self):
        cache = self.cobra/'__pycache__'
        cache.mkdir()
        (cache/'cached.pyc').write_bytes(b'cache')
        (self.cobra/'cached.pyc').write_bytes(b'cache')
        self.assertEqual(bundle.verify_bundle(self.vendor), 1)

    def test_bundle_missing_changed_and_extra(self):
        source = self.cobra/'ovl_tool_cmd.py'
        source.unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing:'):
            bundle.verify_bundle(self.vendor)
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'changed:'):
            bundle.verify_bundle(self.vendor)
        source.write_bytes(b'# fixture')
        (self.cobra/'unexpected.py').write_bytes(b'extra')
        with self.assertRaisesRegex(RuntimeError, 'unexpected:'):
            bundle.verify_bundle(self.vendor)

    def test_bundle_invalid_inventory(self):
        for data in ('{}', '[]', '{invalid', '{"schema":1,"files":{"../escape":"bad"}}'):
            with self.subTest(data=data):
                (self.vendor/bundle.MANIFEST).write_text(data)
                with self.assertRaisesRegex(RuntimeError, 'integrity check failed'):
                    bundle.verify_bundle(self.vendor)

    def test_discovery_verifies_bundle_but_preserves_external_override(self):
        external = self.root/'external'
        external.mkdir()
        (external/'ovl_tool_cmd.py').touch()
        (self.cobra/'ovl_tool_cmd.py').write_bytes(b'damaged')
        with patch.object(audio_paths, '__file__', str(self.kit/'audio_paths.py')), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(audio_paths.cobra_path(str(external)), external)
            (self.kit/'audio_tools.json').write_text(json.dumps({'cobra_tools': str(external)}))
            self.assertEqual(audio_paths.cobra_path(), external)
            (self.kit/'audio_tools.json').unlink()
            with self.assertRaisesRegex(RuntimeError, 'integrity check failed'):
                audio_paths.cobra_path()

    def test_missing_bundled_entry_point_does_not_silently_select_sibling(self):
        sibling = self.kit.parent/'cobra-tools-master'
        sibling.mkdir()
        (sibling/'ovl_tool_cmd.py').touch()
        (self.cobra/'ovl_tool_cmd.py').unlink()
        with patch.object(audio_paths, '__file__', str(self.kit/'audio_paths.py')), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'missing: cobra-tools/ovl_tool_cmd.py'):
                audio_paths.cobra_path()

    def test_deploy_preserves_configuration_by_default(self):
        old = self.config.read_bytes()
        deploy.apply_deployment(self.game, self.backup, {Path('tool.py'): b'new'}, self.receipt)
        self.assertEqual(self.config.read_bytes(), old)
        self.assertEqual(json.loads(self.receipt.read_text())['tool.py'], bundle.digest(self.game/'tool.py'))

    def test_explicit_configuration_migration_is_backed_up(self):
        old = self.config.read_bytes()
        backup, removed = deploy.apply_deployment(self.game, self.backup, {}, self.receipt, obsolete=deploy.OBSOLETE)
        self.assertFalse(self.config.exists())
        self.assertEqual(removed, list(deploy.OBSOLETE))
        self.assertEqual((backup/deploy.OBSOLETE[0]).read_bytes(), old)

    def test_receipt_failure_restores_files_config_and_receipt(self):
        target = self.game/'tool.py'
        target.write_bytes(b'old')
        self.receipt.write_bytes(b'old receipt')
        config = self.config.read_bytes()
        real_write = deploy.atomic_write
        def fail_receipt(path, data):
            if path == self.receipt and data != b'old receipt':
                # Also cover a write that changed its destination before failing.
                path.write_bytes(b'partial receipt')
                raise OSError('receipt locked')
            real_write(path, data)
        with patch.object(deploy, 'atomic_write', fail_receipt):
            with self.assertRaisesRegex(RuntimeError, 'prior files restored'):
                deploy.apply_deployment(self.game, self.backup,
                                        {Path('tool.py'): b'new', Path('added.py'): b'new'},
                                        self.receipt, obsolete=deploy.OBSOLETE)
        self.assertEqual(target.read_bytes(), b'old')
        self.assertFalse((self.game/'added.py').exists())
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(self.receipt.read_bytes(), b'old receipt')

    def test_one_failed_restore_does_not_skip_others(self):
        a, b = self.game/'a.py', self.game/'b.py'
        a.write_bytes(b'old a')
        b.write_bytes(b'old b')
        real_write = deploy.atomic_write
        def failing_write(path, data):
            if path == self.receipt or (path == b and data == b'old b'):
                raise OSError('locked')
            real_write(path, data)
        with patch.object(deploy, 'atomic_write', failing_write):
            with self.assertRaisesRegex(RuntimeError, 'rollback incomplete.*Backup:'):
                deploy.apply_deployment(self.game, self.backup, {Path('a.py'): b'new a', Path('b.py'): b'new b'}, self.receipt)
        self.assertEqual(a.read_bytes(), b'old a')
        self.assertEqual(next(self.backup.glob('deployment_previous_*/b.py')).read_bytes(), b'old b')

    def test_tools_only_preserves_runtime_and_requires_no_staging(self):
        (self.game/'JWE3.exe').touch()
        runtime = [Path('xinput1_4.dll'), Path('Win64/ovldata/VLAudioLoader/Audio/audiometadata.ovl')]
        for rel in runtime:
            path = self.game/rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'working runtime')
        for name in ('audio_paths.py', 'bundle_integrity.py', 'merge_audio_registry.py', 'wwise_ids.py',
                     'build_species_audio.py', 'merge_registry.bat', 'requirements.txt', 'FIXES_20260906.md',
                     'README.md', 'END_USER_INSTALL.md', 'USING_A_REPLACEMENT_SOUND_MOD.md'):
            (self.kit/name).write_bytes(b'fixture')
        argv = ['deploy_local.py', '--game', str(self.game), '--backup', str(self.backup), '--tools-only']
        with patch('sys.argv', argv), patch.object(deploy, '__file__', str(self.kit/'deploy_local.py')), \
             patch.object(deploy, 'require_game_closed', side_effect=AssertionError('runtime guard called')), \
             contextlib.redirect_stdout(io.StringIO()):
            deploy.main()
        for rel in runtime:
            self.assertEqual((self.game/rel).read_bytes(), b'working runtime')
        self.assertTrue(self.config.exists())
        self.assertTrue((self.kit/'staging/DEPLOYED_TOOLS_SHA256.json').is_file())
        self.assertEqual(bundle.verify_bundle(self.game/'JWE3 Audio Kit/vendor'), 1)


if __name__ == '__main__':
    unittest.main()
