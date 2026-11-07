import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
SCRIPT=Path(__file__).with_name('analyze_traces.py')
BASE={"task":"task_1","class":"A","agent":"software-engineer","attempts":2,"tests":["unit_suite"],"judge":"pass","human":"none","tokens_in":10,"tokens_out":20,"ts":"2026-11-06T10:00:00Z","failure_code":"test_failure"}
class TraceAnalysisTests(unittest.TestCase):
 def run_cli(self,rows):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'ledger.jsonl';path.write_text(''.join(json.dumps(x)+'\n' for x in rows))
   return subprocess.run([sys.executable,str(SCRIPT),str(path)],text=True,capture_output=True)
 def test_aggregates_minimized_events_without_echoing_identifiers(self):
  result=self.run_cli([BASE]);self.assertEqual(result.returncode,0,result.stderr)
  report=json.loads(result.stdout);self.assertEqual(report['events'],1);self.assertEqual(report['mean_tokens_observed'],30)
  self.assertEqual(len(report['recommendations']),1);self.assertNotIn('task_1',result.stdout)
 def test_rejects_raw_fields(self):
  result=self.run_cli([{**BASE,"prompt":"raw prompt"}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_secret_in_allowed_test_label(self):
  result=self.run_cli([{**BASE,"tests":["api_key=abc"]}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_email_in_allowed_identifier(self):
  result=self.run_cli([{**BASE,"task":"person@example.com"}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_invalid_attempts(self):
  result=self.run_cli([{**BASE,"attempts":-1}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_unknown_failure_code(self):
  result=self.run_cli([{**BASE,"failure_code":"freeform raw data"}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_free_text_test_label(self):
  result=self.run_cli([{**BASE,"tests":["customer email jane@example.com"]}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_wrong_enum_type(self):
  result=self.run_cli([{**BASE,"judge":[]}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_wrong_agent_type(self):
  result=self.run_cli([{**BASE,"agent":[]}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_huge_numeric_metric(self):
  result=self.run_cli([{**BASE,"duration_seconds":10**1000}]);self.assertNotEqual(result.returncode,0);self.assertIn("invalid duration_seconds",result.stderr)
 def test_rejects_bad_timestamp(self):
  result=self.run_cli([{**BASE,"ts":"yesterday"}]);self.assertNotEqual(result.returncode,0)
 def test_rejects_timestamp_without_timezone(self):
  result=self.run_cli([{**BASE,"ts":"2026-11-06T10:00:00"}]);self.assertNotEqual(result.returncode,0)
if __name__=='__main__':unittest.main()
