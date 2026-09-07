"""Deploy the reviewed local release with backup, input checks and rollback.

Does not launch the game. Use only after the regression tests and staged OVL
round trip have passed. --backup must name an existing backup directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid
from bundle_integrity import verify_bundle
from merge_audio_registry import atomic_write, sha256, snapshot, MANIFEST, MERGED

# Only remove an existing override when --use-bundled-cobra explicitly requests
# that migration. A user may intentionally select another checkout.
OBSOLETE = (Path('JWE3 Audio Kit/audio_tools.json'),)


def require_game_closed():
    # tasklist returns CSV on every locale; the executable name is stable.
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq JWE3.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, check=True)
    if 'jwe3.exe' in result.stdout.lower():
        raise RuntimeError('Close JWE3 before deploying audio files')


def apply_deployment(game, backup, artifacts, receipt_path, expected=None, obsolete=()):
    """Back up, apply and verify one deployment, including its receipt.

    The receipt participates in rollback. Attempt every restore even when a
    locked file prevents an earlier restore, and retain the backup on failure.
    """
    backup = backup/('deployment_previous_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    backup.mkdir()
    previous = {rel: (game/rel).read_bytes() if (game/rel).exists() else None for rel in artifacts}
    obsolete = {rel: (game/rel).read_bytes() for rel in obsolete if (game/rel).is_file()}
    old_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
    for rel, data in {**previous, **obsolete}.items():
        if data is not None:
            atomic_write(backup/rel, data)
    if old_receipt is not None:
        atomic_write(backup/'receipt_before.json',old_receipt)
    atomic_write(backup/'previous_files.json',json.dumps({str(p): None if b is None else hashlib.sha256(b).hexdigest()
                                                        for p,b in {**previous, **obsolete}.items()},indent=2).encode())
    changed, removed = [], []
    receipt_attempted = False
    try:
        if expected is not None:
            require_game_closed()
        for rel, data in artifacts.items():
            changed.append(rel)
            atomic_write(game/rel,data)
            if sha256(game/rel) != hashlib.sha256(data).hexdigest():
                raise RuntimeError(f'Deployed hash mismatch: {rel}')
        for rel in obsolete:
            removed.append(rel)
            (game/rel).unlink()
        if expected is not None and snapshot(game/'Win64/ovldata') != expected:
            raise RuntimeError('Audio inputs changed during deployment')
        receipt = {str(p): hashlib.sha256(b).hexdigest() for p,b in artifacts.items()}
        receipt_attempted = True
        atomic_write(receipt_path,json.dumps(receipt,indent=2).encode())
    except Exception as cause:
        failures = []
        def restore(path, data):
            try:
                if data is None:
                    path.unlink(missing_ok=True)
                elif not path.is_file() or path.read_bytes() != data:
                    atomic_write(path,data)
            except OSError as exc:
                failures.append(f'{path}: {exc}')
        if receipt_attempted:
            restore(receipt_path,old_receipt)
        for rel in removed:
            restore(game/rel,obsolete[rel])
        for rel in reversed(changed):
            restore(game/rel,previous[rel])
        if failures:
            raise RuntimeError(f'Deployment failed ({cause}); rollback incomplete. Backup: {backup}\n'+'\n'.join(failures)) from cause
        raise RuntimeError(f'Deployment failed and prior files restored: {cause}. Backup: {backup}') from cause
    return backup, removed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', required=True)
    ap.add_argument('--backup', required=True)
    ap.add_argument('--tools-only', action='store_true', help='update scripts/docs/vendor only; leave runtime DLLs and registry untouched')
    ap.add_argument('--use-bundled-cobra', action='store_true', help='back up and remove an existing audio_tools.json override')
    args = ap.parse_args()
    game = Path(args.game).resolve()
    kit = Path(__file__).resolve().parent
    backup = Path(args.backup).resolve()
    if not backup.is_dir() or not (game/'JWE3.exe').is_file():
        raise RuntimeError('Expected existing game and backup directories')
    if not args.tools_only:
        require_game_closed()
    ov = game/'Win64/ovldata'
    staged = kit/'staging/Audio'
    expected = None
    if not args.tools_only:
        lines = (staged/MANIFEST).read_text(encoding='utf-8').splitlines()
        if not lines or lines[0] != 'VLAUDIO1':
            raise RuntimeError('Invalid staged manifest')
        expected = {p: h for h,p in (line.split('\t',1) for line in lines[1:])}
        merged_hash = expected.pop(MERGED)
        if snapshot(ov) != expected or sha256(staged/'audiometadata.ovl') != merged_hash:
            raise RuntimeError('Installed audio inputs changed since staging; rebuild the registry first')
    artifacts = {}
    for name in ('audio_paths.py','bundle_integrity.py','merge_audio_registry.py','wwise_ids.py','build_species_audio.py',
                 'merge_registry.bat','requirements.txt','FIXES_20260906.md','README.md',
                 'END_USER_INSTALL.md','USING_A_REPLACEMENT_SOUND_MOD.md'):
        artifacts[Path('JWE3 Audio Kit')/name] = (kit/name).read_bytes()
    # The bundled cobra-tools subset travels with the kit, so the installed copy
    # needs no separate checkout and no configuration to find one.
    if not (kit/'vendor/cobra-tools/ovl_tool_cmd.py').is_file():
        raise RuntimeError('vendor/cobra-tools is missing; the deployed kit could not merge')
    verify_bundle(kit/'vendor')
    for source in sorted((kit/'vendor').rglob('*')):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix not in ('.pyc', '.pyo'):
            artifacts[Path('JWE3 Audio Kit')/source.relative_to(kit)] = source.read_bytes()
    artifacts[Path('merge_registry.bat')] = b'@echo off\r\ncall "%~dp0JWE3 Audio Kit\\merge_registry.bat" %*\r\nexit /b %errorlevel%\r\n'
    if not args.tools_only:
        artifacts[Path('Win64/ovldata/VLAudioLoader/Manifest.xml')] = (kit/'mod/VLAudioLoader/Manifest.xml').read_bytes()
        artifacts[Path('Win64/ovldata/VLAudioLoader/VLAudioLoader.dll')] = (kit/'dll/release/VLAudioLoader.dll').read_bytes()
        artifacts[Path('Win64/ovldata/VLAudioLoader/Audio/audiometadata.ovl')] = (staged/'audiometadata.ovl').read_bytes()
        artifacts[Path('Win64/ovldata/VLAudioLoader/Audio')/MANIFEST] = (staged/MANIFEST).read_bytes()
        artifacts[Path('xinput1_4.dll')] = (kit/'dll/release/xinput1_4.dll').read_bytes()
    receipt = kit/'staging'/('DEPLOYED_TOOLS_SHA256.json' if args.tools_only else 'DEPLOYED_SHA256.json')
    backup, removed = apply_deployment(game,backup,artifacts,receipt,expected,
                                       OBSOLETE if args.use_bundled_cobra else ())
    print(f'Deployed and hash-verified {len(artifacts)} files to {game}')
    for rel in removed:
        print(f'Removed obsolete {rel}; the kit now uses its bundled cobra-tools')
    print(f'Previous installed files: {backup}')
    print('Run merge_registry.bat in the game root after changing audio mods.')

if __name__ == '__main__':
    main()
