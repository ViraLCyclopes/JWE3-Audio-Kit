"""Verify the pinned Cobra subset without importing it or loading its DLL.

Maintainers: after reviewing an intentional vendor refresh and its provenance,
run `python bundle_integrity.py --write`, then repeat the real OVL comparisons.
A checksum inventory proves packaging integrity, not format correctness.
"""
from pathlib import Path
import hashlib
import json
import re

MANIFEST = 'BUNDLE_SHA256.json'


def bundle_files(vendor):
    root = vendor / 'cobra-tools'
    return {p.relative_to(vendor).as_posix(): p for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bundle(vendor):
    vendor = Path(vendor)
    try:
        manifest = json.loads((vendor / MANIFEST).read_text(encoding='utf-8'))
        expected = manifest['files']
        if manifest['schema'] != 1 or not isinstance(expected, dict) or not expected:
            raise ValueError('invalid inventory')
        for name, checksum in expected.items():
            if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
                raise ValueError('invalid checksum')
            if not name.startswith('cobra-tools/') or '\\' in name or '..' in Path(name).parts:
                raise ValueError('invalid inventory path')
        actual = bundle_files(vendor)
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        changed = {p for p in set(actual) & set(expected) if digest(actual[p]) != expected[p]}
        if missing or extra or changed:
            details = '; '.join(f'{label}: {", ".join(sorted(values)[:5])}'
                                for label, values in [('missing', missing), ('unexpected', extra), ('changed', changed)]
                                if values)
            raise ValueError(details)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f'Bundled Cobra integrity check failed: {exc}. Restore the complete vendor folder from the same kit release.') from exc
    return len(expected)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write', action='store_true', help='record a reviewed vendor refresh')
    args = ap.parse_args()
    vendor = Path(__file__).resolve().parent / 'vendor'
    if args.write:
        data = {'schema': 1, 'files': {p: digest(source) for p, source in sorted(bundle_files(vendor).items())}}
        (vendor / MANIFEST).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(f'Verified {verify_bundle(vendor)} bundled files')


if __name__ == '__main__':
    main()
