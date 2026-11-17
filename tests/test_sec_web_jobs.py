"""Offline tests for the web application's input handling and task lifecycle."""
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from corporate_atlas.services.jobs import JobManager, command_for


class CommandTests(unittest.TestCase):
    def test_query_is_passed_as_literal_argument(self):
        command = command_for(dict(action='query', tickers='aapl, WFC', question='--help; $(echo bad)', mode='vector'))
        self.assertEqual(command[-2:], ['--', '--help; $(echo bad)'])
        self.assertNotIn('--tickers', command)  # Preparation tickers never constrain questions.

    def test_usage_query_uses_the_local_query_service(self):
        command = command_for(dict(action='query', question='Total input tokens?', mode='usage'))
        self.assertIn('corporate_atlas.services.query', command)
        self.assertIn('usage', command)

    def test_rejects_invalid_inputs(self):
        for data in [dict(action='fetch', tickers='../secret'),
                     dict(action='vector', tickers='AAPL', batch_delay='nan'),
                     dict(action='vector', tickers='AAPL', batch_size=0),
                     dict(action='query', tickers='AAPL', question=''),
                     dict(action='query', tickers='AAPL', question='Risk?', mode='unknown')]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                command_for(data)

    def test_uses_paced_indexer(self):
        command = command_for(dict(action='vector', tickers='AAPL'))
        self.assertTrue(command[3].endswith('corporate_atlas.core.build_vector_store_paced'))
        self.assertEqual(command[-2:], ['--batch-delay', '0.0'])


class JobTests(unittest.TestCase):
    def wait_finished(self, jobs):
        deadline = time.monotonic() + 5
        while jobs.snapshot()['status'] in {'running', 'stopping'}:
            if time.monotonic() > deadline:
                self.fail('Task did not finish')
            time.sleep(.01)
        return jobs.snapshot()

    def test_output_and_exit_status(self):
        jobs = JobManager()
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'print("test result")']):
            jobs.start({'action': 'usage'})
            job = self.wait_finished(jobs)
        self.assertEqual(job['status'], 'completed')
        self.assertIn('test result', job['output'])
        self.assertEqual(job['exit_code'], 0)

    def test_stop_and_prevent_concurrent_writes(self):
        jobs = JobManager()
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            jobs.start({'action': 'usage'})
            with self.assertRaises(RuntimeError):
                jobs.start({'action': 'usage'})
            jobs.stop()
            self.assertEqual(self.wait_finished(jobs)['status'], 'stopped')

    def test_failure_reports_exit_code(self):
        jobs = JobManager()
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'raise SystemExit(2)']):
            jobs.start({'action': 'usage'})
            self.assertEqual(self.wait_finished(jobs)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
