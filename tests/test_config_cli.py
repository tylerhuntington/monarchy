"""Preview and project CI validation never create a royalty database."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ConfigCLITests(unittest.TestCase):
    def run_cli(self,*args):
        return subprocess.run([sys.executable,'-m','monarchy',*args],cwd=ROOT,capture_output=True,text=True)

    def test_project_check_needs_no_state_and_hides_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'project.json'
            path.write_text('{"project.repository":"example/project"}')
            result=self.run_cli('config','check',str(path),'--layer','project')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['valid'])
            path.write_text('{"voice.zone":"SENSITIVE_VALUE"}')
            result=self.run_cli('config','check',str(path),'--layer','project')
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('SENSITIVE_VALUE',result.stderr)
            self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_preview_shows_values_provenance_and_why_without_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner=Path(tmp)/'owner.json'
            owner.write_text('{"voice.zone":"UTC","_why":{"voice.zone":"Chosen zone"}}')
            result=self.run_cli('config','show','voice.zone','--owner',str(owner))
            self.assertEqual(result.returncode,0,result.stderr)
            row=json.loads(result.stdout)['config']['voice.zone']
            self.assertEqual(row['value'],'UTC')
            self.assertIn('owner',row['layers'])
            self.assertIn('Chosen zone',row['why'].values())

    def test_order_preview_and_unknown_commands_do_not_open_state(self):
        result=self.run_cli('orders','worker')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('<!-- rule:',json.loads(result.stdout)['text'])
        result=self.run_cli('status','task')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--state',result.stderr)
