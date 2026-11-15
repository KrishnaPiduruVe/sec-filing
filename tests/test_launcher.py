import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from corporate_atlas.launcher import main


class LauncherTests(unittest.TestCase):
    def test_existing_app_is_reported_without_starting_duplicates(self):
        with patch('sys.argv', ['run_app.py']), patch('corporate_atlas.launcher.port_in_use', return_value=True), patch('corporate_atlas.launcher.already_running', return_value=True), patch('corporate_atlas.launcher.subprocess.Popen') as spawn, redirect_stdout(io.StringIO()) as output:
            main()
        spawn.assert_not_called()
        self.assertIn('already running', output.getvalue())
        self.assertIn('http://127.0.0.1:8501', output.getvalue())

    def test_conflicting_port_fails_before_launch(self):
        with patch('sys.argv', ['run_app.py']), patch('corporate_atlas.launcher.port_in_use', side_effect=[True, False]), patch('corporate_atlas.launcher.subprocess.Popen') as spawn, redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exc:
                main()
        self.assertEqual(exc.exception.code, 1)
        spawn.assert_not_called()
        self.assertIn('8000', output.getvalue())
        self.assertIn('--api-port 8001', output.getvalue())


if __name__ == '__main__':
    unittest.main()
