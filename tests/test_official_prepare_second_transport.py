"""The actual transport route gate admits only one extra read-only jobs route."""
import json,unittest

from race_ai.all_existing_model_official_issue_transport import GithubIssueTransport


class SecondViewerTransportTests(unittest.TestCase):
    def test_actual_transport_admits_exact_attempt_two_jobs_metadata(self):
        calls=[];value=dict(total_count=1,jobs=[dict(id=101,run_attempt=2)])
        def request(method,path,body):
            calls.append((method,path,body));return json.dumps(value).encode()
        reader=GithubIssueTransport(request)
        try:actual=reader.json('actions/runs/17/attempts/2/jobs?per_page=100')
        except ValueError as exc:self.fail('exact second-attempt metadata route rejected: '+str(exc))
        self.assertEqual(actual,value)
        self.assertEqual(calls,[('GET','actions/runs/17/attempts/2/jobs?per_page=100',None)])

    def test_other_attempts_queries_and_mutations_reject_before_transport(self):
        calls=[]
        def request(*args):calls.append(args);raise AssertionError('NO_REQUEST')
        reader=GithubIssueTransport(request)
        for method,path in (('GET','actions/runs/17/attempts/2'),
            ('GET','actions/runs/17/attempts/3/jobs?per_page=100'),
            ('GET','actions/runs/17/attempts/2/jobs?per_page=101'),
            ('GET','actions/runs/17/attempts/2/jobs?per_page=100&page=2'),
            ('POST','actions/runs/17/rerun'),('POST','actions/runs/17/attempts/2/jobs?per_page=100')):
            with self.subTest(method=method,path=path),self.assertRaises(ValueError):reader._call(method,path)
        self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
