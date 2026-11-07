#!/usr/bin/env python3
"""Classify changed paths; declared class is metadata, never authorization."""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy import classify

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--mode', choices=('pull_request','push'), default='pull_request')
    parser.add_argument('--record', default=os.environ.get('POLICY_CLASS', ''))
    args=parser.parse_args()
    if args.mode == 'push' and set(args.base) == {"0"}:
        # Branch create events have no previous commit; skip based on event SHA, not user metadata.
        print('Push without a valid previous commit: skipped path classification (no code diff to classify).')
        return 0
    result=subprocess.run(['git','diff','--name-only','-z',args.base,args.head],check=True,stdout=subprocess.PIPE)
    paths=[x.decode('utf-8','surrogateescape') for x in result.stdout.split(b'\0') if x]
    category,reasons=classify({'paths':paths,'files_touched':len(paths)})
    print(json.dumps({'class':category,'reasons':reasons,'paths_count':len(paths),'authorizes_action':False}))
    if args.mode == 'pull_request':
        records=re.findall(r'\[policy-class:([ABC])\]', args.record)
        if len(records) != 1:
            print('PR metadata must contain exactly one [policy-class:A|B|C] marker.',file=sys.stderr);return 2
        declared=records[0]
        if declared != category:
            print(f'declared class {declared} differs from calculated class {category}',file=sys.stderr);return 1
    else:
        # The push event cannot prove whether this is a PR merge or direct push; report classification only.
        print('Push classification is informational; PR event is the enforcement gate. Verify branch protection externally.')
    return 0
if __name__=='__main__': raise SystemExit(main())
