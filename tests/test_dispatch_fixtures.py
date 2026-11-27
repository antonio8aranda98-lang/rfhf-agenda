import contextlib
import io
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dispatch_fixtures as trigger

class DispatchTests(unittest.TestCase):
    def test_empty_queue_dispatches_exactly_the_existing_main_workflow(self):
        calls=[]
        def request(path, token, data=None):
            calls.append((path, data));return {'workflow_runs': []} if data is None else None
        trigger.dispatch('FAKE_TEST_ONLY', request)
        self.assertEqual(calls, [('/actions/runs?per_page=100&branch=main',None),('/actions/workflows/valencia-horarios.yml/dispatches',{'ref':'main'})])
    def test_active_production_runs_are_never_cancelled_or_duplicated(self):
        for name in trigger.PRODUCTION:
            for status in trigger.ACTIVE:
                calls=[]
                def request(path, token, data=None):
                    calls.append(path);return {'workflow_runs':[{'path':'.github/workflows/'+name,'status':status}]}
                trigger.dispatch('FAKE_TEST_ONLY',request)
                self.assertEqual(len(calls),1)
    def test_failures_never_expose_exception_or_credentials(self):
        stderr=io.StringIO()
        with patch.dict(os.environ,{'RFHF_DISPATCH_TOKEN':'FAKE_PRIVATE_VALUE'}),patch.object(trigger,'dispatch',side_effect=RuntimeError('FAKE_PRIVATE_VALUE')),contextlib.redirect_stderr(stderr):
            self.assertEqual(trigger.main(),1)
        self.assertNotIn('FAKE_PRIVATE_VALUE',stderr.getvalue())

if __name__ == '__main__': unittest.main()
