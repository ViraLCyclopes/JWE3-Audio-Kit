"""Offline regression checks. Native tests use fake Wwise, never the game API."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import audio_paths
import build_species_audio as builder
import merge_audio_registry as merge
import wwise_ids as ids

KIT = Path(__file__).resolve().parent
STOCK_XML = '<WmetasbRoot><bnks pool_type="4"><bnkmetanew fnv="1"><type_name>SFX</type_name></bnkmetanew></bnks></WmetasbRoot>'

def chunk(tag, data):
    return tag + struct.pack('<I', len(data)) + data

def bank(bid=2):
    return chunk(b'BKHD', struct.pack('<IIII', 150, bid, 0, 0))

def obj(kind, oid, payload=b''):
    return struct.pack('<BII', kind, 4 + len(payload), oid) + payload

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vlaudio-tests-')
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name) / 'Game 音声'
        self.ov = self.game / 'Win64/ovldata'
        self.stock = self.ov / merge.STOCK
        self.stock.parent.mkdir(parents=True)
        self.stock.write_bytes(b'stock')
        self.dest = self.ov / merge.MERGED
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b'previous registry')
        self.corrupt = False
        self.built = None

    def add_mod(self, name='Mod', bid=2, payload=None):
        folder = self.ov / name / 'Audio'
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'test.bnk').write_bytes(payload or bank(bid))
        frag = folder/'test.wmetasb.add'
        frag.write_text(f'<bnkmetanew fnv="{bid}"><type_name>SFX</type_name><events><evententry event_fnv="123" /></events></bnkmetanew>')
        return frag

    def cobra(self, args):
        out = Path(args[args.index('-o')+1])
        if args[0] == 'inject':
            self.built = Path(args[args.index('-f')+1]).read_text()
            out.write_text(self.built)
        else:
            out.mkdir(parents=True)
            xml = STOCK_XML if Path(args[1]) == self.stock else self.built
            if self.corrupt:
                xml = xml.replace('event_fnv="123"', 'event_fnv="999"')
            (out/'wwisemetadatasoundbanks.wmetasb').write_text(xml)
        return 'Validating succeeded Collecting succeeded Extracting succeeded'

    def build(self, check=False):
        a = argparse.Namespace(game=str(self.game), work=None, check=check, output=None)
        with patch.object(merge, 'run_cobra', self.cobra), contextlib.redirect_stdout(io.StringIO()):
            return merge.build(a)

    def manifest(self):
        data = merge.snapshot(self.ov)
        data[merge.MERGED] = merge.sha256(self.dest)
        target = self.dest.parent/merge.MANIFEST
        target.write_text('VLAUDIO1\n'+''.join(f'{h}\t{p}\n' for p,h in sorted(data.items())), encoding='utf-8', newline='')

    def native(self):
        exe = KIT/'dll/release/runtime_test.exe'
        if not exe.exists():
            self.skipTest('build the native harness with dll/build.bat first')
        # Different working directory explicitly exercises executable-root paths.
        return subprocess.run([str(exe), str(self.game)], cwd=self.temp.name, capture_output=True, text=True)

class MergeTests(Fixture):
    def test_last_mod_removed_replaces_old_registry(self):
        self.build()
        self.assertEqual(merge.bank_ids(self.dest.read_text()), [1])
        self.assertTrue((self.dest.parent/merge.MANIFEST).exists())

    def test_check_never_writes_game(self):
        self.add_mod()
        before = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        self.build(check=True)
        after = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.ov/'VLAudioLoader/_merge').exists())

    def test_conflicting_registry_rejected(self):
        self.add_mod('A')
        frag = self.add_mod('B')
        frag.write_text(frag.read_text().replace('123', '124'))
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.build()
        self.assertEqual(self.dest.read_bytes(), b'previous registry')

    def test_conflicting_bank_payload_rejected(self):
        self.add_mod('A')
        self.add_mod('B', payload=bank()+chunk(b'DATA', b'different'))
        with self.assertRaisesRegex(ValueError, 'different banks'):
            self.build()

    def test_identical_duplicates_deduplicated(self):
        self.add_mod('A'); self.add_mod('B')
        self.build()
        self.assertEqual(merge.bank_ids(self.dest.read_text()), [1,2])

    def test_missing_bank_rejected(self):
        fragment = self.add_mod()
        (fragment.parent/'test.bnk').unlink()
        with self.assertRaisesRegex(ValueError, 'no .bnk'):
            self.build()

    def test_same_count_event_corruption_rejected(self):
        self.add_mod(); self.corrupt = True
        with self.assertRaisesRegex(RuntimeError, 'content changed'):
            self.build()
        self.assertEqual(self.dest.read_bytes(), b'previous registry')

    def test_atomic_replace_failure_preserves_old(self):
        with patch.object(merge.os, 'replace', side_effect=PermissionError('simulated lock')):
            with self.assertRaises(PermissionError):
                merge.atomic_write(self.dest, b'new')
        self.assertEqual(self.dest.read_bytes(), b'previous registry')
        self.assertEqual(list(self.dest.parent.glob('.vlaudio-*')), [])

    def test_empty_fragment_rejected(self):
        self.add_mod().write_text('')
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.build()

    def test_stock_duplicate_rows_preserved(self):
        root = ET.fromstring(STOCK_XML)
        root.find('bnks').append(ET.fromstring('<bnkmetanew fnv="1" flag="2"/>'))
        merged, _, _ = merge.merge_xml(ET.tostring(root, encoding='unicode'), [])
        self.assertEqual(merge.bank_ids(merged), [1,1])

    def test_cobra_error_includes_stderr(self):
        fake = subprocess.CompletedProcess([], 4, 'partial success', 'real failure')
        with patch.object(audio_paths, 'cobra_path', return_value=Path('.')), patch.object(audio_paths.subprocess, 'run', return_value=fake):
            with self.assertRaisesRegex(RuntimeError, 'real failure'):
                audio_paths.run_cobra([])

class NativeTests(Fixture):
    def test_real_hooks_on_64k_stack(self):
        exe = KIT/'dll/release/hook_stack_test.exe'
        if not exe.exists():
            self.skipTest('build hook_stack_test first')
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('200 hook calls, 0 failures',result.stdout)

    def test_unicode_valid_manifest_loads_bank(self):
        self.add_mod('Mod音声'); self.manifest()
        result = self.native()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('fake_load_calls=1', result.stdout)

    def test_more_than_64_banks(self):
        for i in range(70): self.add_mod(f'Mod{i}', bid=i+2)
        self.manifest()
        result = self.native()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('fake_load_calls=70', result.stdout)

    def test_same_timestamp_changed_content_rejected(self):
        frag = self.add_mod(); self.manifest()
        stamp = frag.stat()
        frag.write_text(frag.read_text().replace('123', '456'))
        os.utime(frag, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.native().returncode, 1)

    def test_older_new_mod_rejected(self):
        self.add_mod('A'); self.manifest()
        frag = self.add_mod('B',3)
        os.utime(frag, (1,1))
        self.assertEqual(self.native().returncode, 1)

    def test_removed_mod_rejected(self):
        self.add_mod(); self.manifest()
        shutil.rmtree(self.ov/'Mod')
        self.assertEqual(self.native().returncode, 1)

    def test_stock_update_rejected(self):
        self.add_mod(); self.manifest(); self.stock.write_bytes(b'updated stock')
        self.assertEqual(self.native().returncode, 1)

    def test_partial_deploy_rejected(self):
        self.add_mod(); self.manifest(); self.dest.write_bytes(b'changed registry')
        self.assertEqual(self.native().returncode, 1)

    def test_identical_duplicate_only_loaded_once(self):
        self.add_mod('A'); self.add_mod('B'); self.manifest()
        self.assertIn('fake_load_calls=1', self.native().stdout)

class BuilderTests(unittest.TestCase):
    def test_remap_never_overlaps_object_header(self):
        data = bytearray(obj(ids.EVENT,0x404))
        ids.remap_ids(data,{0x404:0x55667788},[ids.HircObject(ids.EVENT,0,4,0x404)],0)
        self.assertEqual(struct.unpack_from('<I',data,1)[0],4)
        self.assertEqual(struct.unpack_from('<I',data,5)[0],0x55667788)

    def test_truncated_chunk_rejected(self):
        with self.assertRaises(ValueError): ids.chunks(b'BKHD'+struct.pack('<I',100))

    def test_didx_out_of_bounds_rejected(self):
        data = chunk(b'DIDX',struct.pack('<III',1,0,10))+chunk(b'DATA',b'one')
        with self.assertRaises(ValueError): ids.didx_entries(data)

    def test_custom_sound_keeps_remapped_media_ids(self):
        media = bytearray(bank()+chunk(b'DIDX',struct.pack('<III',222,0,3))+chunk(b'DATA',b'old'))
        # Synthetic event -> Sound references at the existing measured offsets.
        events = chunk(b'HIRC',struct.pack('<I',2)+obj(ids.EVENT,ids.fnv1_32('New_Roar'),struct.pack('<I',333))+
                       obj(ids.SOUND,333,b'\0'*5+struct.pack('<II',222,3)))
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'Roar.wem').write_bytes(b'new sound payload')
            actual, filled, unmatched = builder.apply_custom_sounds(media,{111:222},events,'New',td)
        self.assertEqual(ids.didx_entries(actual),[(222,0,17)])
        self.assertEqual(actual[ids.chunks(actual)['DATA'][0]:],b'new sound payload')
        self.assertEqual(filled,[('Roar',1,17)])
        self.assertEqual(unmatched,[])

if __name__ == '__main__':
    unittest.main(verbosity=2)
