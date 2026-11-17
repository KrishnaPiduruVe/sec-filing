"""Verify installed packages and worker paths after the src layout migration."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from corporate_atlas.paths import PROJECT_ROOT, ENV_FILE
from corporate_atlas.services.jobs import command_for
from corporate_atlas.services.prepare import run_script


class LayoutTests(unittest.TestCase):
    def test_config_and_data_stay_in_checkout(self):
        self.assertTrue((PROJECT_ROOT / 'pyproject.toml').is_file())
        self.assertEqual(ENV_FILE, PROJECT_ROOT / '.env')
        self.assertTrue((PROJECT_ROOT / 'src/ui/public/capgemini-icon.png').is_file())

    def test_worker_commands_are_importable_modules(self):
        for data in [{'action':'prepare','tickers':'AAPL'}, {'action':'query','question':'Risk?'},
                     {'action':'delete_filings','selections':[{'ticker':'AAPL','accession':'0000320193-26-000020'}]},
                     {'action':'vector','tickers':'AAPL'}, {'action':'usage'}]:
            command = command_for(data)
            self.assertEqual(command[2], '-m')
            self.assertIsNotNone(importlib.util.find_spec(command[3]))

    def test_module_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-m', 'corporate_atlas.services.prepare', '--help'],
                                    cwd=folder, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--tickers', result.stdout)
            env = {**os.environ, 'ATLAS_DATA_DIR': folder}
            code = 'import json; from corporate_atlas.paths import DATA_ROOT, ENV_FILE; print(json.dumps([str(DATA_ROOT), str(ENV_FILE)]))'
            result = subprocess.run([sys.executable, '-c', code], cwd=folder, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [str(Path(folder).resolve()), str(ENV_FILE)])

    def test_workflow_uses_module_entrypoint_and_restores_argv(self):
        before = sys.argv
        with patch('importlib.import_module') as execute:
            run_script('corporate_atlas.core.build_vector_store_paced', '--tickers', 'AAPL')
        execute.assert_called_once_with('corporate_atlas.core.build_vector_store_paced')
        execute.return_value.main.assert_called_once_with()
        self.assertIs(sys.argv, before)


if __name__ == '__main__':
    unittest.main()
