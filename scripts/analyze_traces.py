#!/usr/bin/env python3
"""Summarize validated, minimized JSONL ledger events without echoing identifiers."""
from __future__ import annotations
import argparse, json, math, re, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ALLOWED = {"task", "class", "agent", "attempts", "tests", "judge", "human", "tokens_in", "tokens_out", "ts", "duration_seconds", "cost_credits", "failure_code", "review_findings", "reopened"}
FAILURE_CODES = {"none", "test_failure", "lint_failure", "type_failure", "build_failure", "tool_timeout", "tool_error", "review_changes_requested", "qa_fail", "blocked", "unknown"}
AGENTS = {"product-lead", "product-manager", "product-designer", "deep-researcher", "software-architect", "software-engineer", "code-reviewer", "product-qa", "intake-normalizer", "judge", "judge-auditor", "retro", "unknown"}
SECRETISH = re.compile(r"(?i)(api[_-]?key|secret|password|token=|sk-[a-z0-9]|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{3}[-.]?\d{3}[-.]?\d{3}[-.]?\d{2}\b)")
RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")

def validate_event(row: object, number: int) -> dict:
    if not isinstance(row,dict) or set(row)-ALLOWED: raise ValueError(f"line {number}: unsupported or raw fields")
    required={"task","class","agent","attempts","tests","judge","human","tokens_in","tokens_out","ts"}
    if required-set(row): raise ValueError(f"line {number}: missing required fields")
    if not isinstance(row["task"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",row["task"]): raise ValueError(f"line {number}: task must be a non-personal identifier")
    if not isinstance(row["class"],str) or row["class"] not in ("A","B","C","unknown"): raise ValueError(f"line {number}: invalid class")
    if not isinstance(row["agent"],str) or row["agent"] not in AGENTS: raise ValueError(f"line {number}: unknown agent")
    if isinstance(row["attempts"],bool) or not isinstance(row["attempts"],int) or not 0<=row["attempts"]<=100: raise ValueError(f"line {number}: invalid attempts")
    if not isinstance(row["tests"],list) or len(row["tests"])>100 or any(not isinstance(x,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}",x) for x in row["tests"]): raise ValueError(f"line {number}: invalid test code; free text is not accepted")
    if not isinstance(row["judge"],str) or row["judge"] not in ("pass","fail","pending","not_applicable"): raise ValueError(f"line {number}: invalid judge status")
    if not isinstance(row["human"],str) or row["human"] not in ("none","input","approval","blocked"): raise ValueError(f"line {number}: invalid human status")
    for key in ("tokens_in","tokens_out","review_findings","reopened"):
        value=row.get(key)
        if value is not None and (isinstance(value,bool) or not isinstance(value,int) or value<0 or value>10**12): raise ValueError(f"line {number}: invalid {key}")
    for key in ("duration_seconds","cost_credits"):
        value=row.get(key)
        try:
            valid=value is None or (isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=10**12)
        except (OverflowError,TypeError):
            valid=False
        if not valid: raise ValueError(f"line {number}: invalid {key}")
    code=row.get("failure_code","none")
    if not isinstance(code,str) or code not in FAILURE_CODES: raise ValueError(f"line {number}: invalid failure_code")
    if not isinstance(row["ts"],str) or len(row["ts"])>40 or RFC3339.fullmatch(row["ts"]) is None: raise ValueError(f"line {number}: invalid timestamp")
    try:
        parsed = datetime.fromisoformat(row["ts"].replace("Z","+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError("missing timezone")
    except ValueError as error: raise ValueError(f"line {number}: invalid timestamp") from error
    return row

def read_events(path: Path):
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip(): continue
        if SECRETISH.search(raw): raise ValueError(f"line {number}: possible secret/PII; refusing analysis")
        yield validate_event(json.loads(raw),number)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path)
    args=parser.parse_args()
    events=list(read_events(args.ledger))
    if not events: parser.error("ledger contains no events")
    failures=Counter(row.get("failure_code","none") for row in events)
    judge=Counter(row["judge"] for row in events)
    retries=[row["attempts"] for row in events]
    token_samples=[row["tokens_in"]+row["tokens_out"] for row in events if isinstance(row["tokens_in"],int) and isinstance(row["tokens_out"],int)]
    suggestions=[]
    for code,count in failures.most_common(2):
        if code!="none": suggestions.append({"observation_code":code,"count":count,"proposal":"Add or strengthen a deterministic regression case before changing prompts/workflow.","status":"proposal_only"})
    report={"events":len(events),"judge_counts":dict(judge),"failure_counts":dict(failures),"mean_attempts":sum(retries)/len(retries) if retries else None,"mean_tokens_observed":sum(token_samples)/len(token_samples) if token_samples else None,"recommendations":suggestions,"limitations":["Only validated minimized ledger fields analyzed; no raw prompt or tool output read.","This report is descriptive, not causal; missing tokens/cost remain N/A.","No agent configuration was changed or promoted."]}
    output=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if args.output: args.output.write_text(output,encoding="utf-8")
    else: print(output,end="")
if __name__=="__main__":
    try: main()
    except (OSError,ValueError,json.JSONDecodeError) as error: print(f"trace analysis failed: {error}",file=sys.stderr);raise SystemExit(2)
