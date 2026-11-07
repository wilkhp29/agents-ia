#!/usr/bin/env python3
"""Promotion remains fail-closed until authorized evals and runtime controls exist."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    manifest=json.loads((ROOT/'eval/MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'READY' or not args.candidate or not args.baseline:
        parser.error('promotion unavailable: requires authorized reproducible eval manifest, candidate, and baseline')
    if args.apply:
        parser.error('automatic application is disabled; promotion requires reviewed PR and independent QA PASS')
    parser.error('shadow comparison is not implemented; no promotion was performed')
if __name__=='__main__': raise SystemExit(main())
