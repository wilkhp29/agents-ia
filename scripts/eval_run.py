#!/usr/bin/env python3
"""Fail-closed inventory check; does not execute agents or claim quality scores."""
import argparse
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'eval/MANIFEST.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    source = ROOT / 'docs/evaluations/agent-workflow-v1.json'
    suite_bytes = source.read_bytes()
    suite = json.loads(suite_bytes)
    expected_hash = manifest.get("inventory_sha256")
    actual_hash = hashlib.sha256(suite_bytes).hexdigest()
    if expected_hash != actual_hash:
        parser.error(f"inventory SHA mismatch: expected={expected_hash!r} actual={actual_hash}")
    if not args.dry_run:
        parser.error('only --dry-run is supported until an authorized reference corpus exists')
    for case in suite.get('cases', []):
        print(f"{case['id']}\tPENDING\t{case['title']}")
    print(f"manifest_status={manifest['status']} reason={manifest['reason']}")
    print('No agent invocation, reference diff comparison, or score was performed.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
