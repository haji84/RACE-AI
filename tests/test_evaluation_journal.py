"""Real temporary filesystem tests of reveal ordering and crash-safe refusal."""
import copy
from pathlib import Path
import tempfile
import unittest
from test_evaluation_experiment import plan, payload, labels
from race_ai.actions_contract import digest
from race_ai.evaluation_journal import EvaluationJournal
from race_ai.evaluation_experiment import EvaluationError


class EvaluationJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.j=EvaluationJournal(self.root,'fictional-1')
        self.p=plan();self.j.register(self.p)

    def seal(self):
        c,o=payload(self.p)
        return self.j.seal(c,o,sealed_at='2030-01-06T00:00:01Z',expected_plan_sha256=digest(self.p))

    def test_cannot_rewrite_plan_or_predictions(self):
        with self.assertRaises(FileExistsError):self.j.register(self.p)
        self.seal()
        with self.assertRaises(FileExistsError):self.seal()

    def test_reader_never_called_without_valid_seal(self):
        called=[]
        with self.assertRaises((EvaluationError,FileNotFoundError)):
            self.j.reveal(lambda:called.append(1),expected_seal_sha256='0'*64,now='2030-01-06T01:00:00Z')
        self.assertEqual(called,[])

    def test_seal_hash_mismatch_prevents_result_read(self):
        self.seal();called=[]
        with self.assertRaises(EvaluationError):
            self.j.reveal(lambda:called.append(1),expected_seal_sha256='0'*64,now='2030-01-06T01:00:00Z')
        self.assertEqual(called,[])

    def test_results_are_read_once_and_report_recoverable_without_reread(self):
        s=self.seal();called=[]
        def reader():called.append(1);return labels()
        r=self.j.reveal(reader,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        self.assertEqual(r['models'][0]['hit8'],3)
        self.assertEqual(self.j.read_report(expected_seal_sha256=s['seal_sha256']),r)
        with self.assertRaises((FileExistsError,EvaluationError)):
            self.j.reveal(reader,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(called,[1])

    def test_crash_after_read_does_not_allow_second_read(self):
        s=self.seal();called=[]
        def reader():called.append(1);raise RuntimeError('synthetic crash')
        with self.assertRaises(RuntimeError):
            self.j.reveal(reader,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        with self.assertRaises((FileExistsError,EvaluationError)):
            self.j.reveal(reader,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(called,[1])

    def test_new_experiment_id_cannot_reuse_consumed_final_races(self):
        s=self.seal();self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        p=copy.deepcopy(self.p);p['experiment_id']='different';p['races'][2]['race_id']='renamed'
        for e in p['eligibility']:
            if e['race_id']=='r4':e['race_id']='renamed'
        j=EvaluationJournal(self.root,'different');j.register(p)
        c,o=payload(p);s2=j.seal(c,o,sealed_at='2030-01-06T01:00:01Z',expected_plan_sha256=digest(p))
        called=[]
        with self.assertRaises(EvaluationError):
            j.reveal(lambda:called.append(1),expected_seal_sha256=s2['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(called,[])

    def test_registry_busy_does_not_call_result_reader(self):
        s=self.seal();(self.root/'final-reveal.lock').write_text('another process')
        called=[]
        with self.assertRaises(FileExistsError):
            self.j.reveal(lambda:called.append(1),expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        self.assertEqual(called,[])

    def test_validation_exposure_cannot_be_renamed_into_new_final_test(self):
        s=self.seal();self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        p=copy.deepcopy(self.p);p['experiment_id']='shifted'
        p['windows']['train_end']='2030-01-01';p['windows']['validation_end']='2030-01-02'
        p['races']=[r for r in p['races'] if r['race_id']=='r3']
        p['eligibility']=[e for e in p['eligibility'] if e['race_id']=='r3']
        j=EvaluationJournal(self.root,'shifted');j.register(p)
        c,o=payload(p);s2=j.seal(c,o,sealed_at='2030-01-06T01:00:01Z',expected_plan_sha256=digest(p))
        called=[]
        with self.assertRaises(EvaluationError):
            j.reveal(lambda:(called.append(1) or []),expected_seal_sha256=s2['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(called,[])

    def test_unknown_results_require_new_append_only_update_not_refit(self):
        s=self.seal();self.j.reveal(lambda:[],expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        # A missing result must not silently restart the final test or model run.
        with self.assertRaises((FileExistsError,EvaluationError)):
            self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')

    def test_reader_time_and_result_future_observation_rejected(self):
        s=self.seal();called=[]
        with self.assertRaises(EvaluationError):
            self.j.reveal(lambda:called.append(1),expected_seal_sha256=s['seal_sha256'],now='2030-01-05T00:00:00Z')
        self.assertEqual(called,[])

    def test_later_results_append_without_refit_or_rewrite(self):
        s=self.seal();first=self.j.reveal(lambda:[],expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        saved=(self.j.directory/'predictions.json').read_bytes()
        updated=self.j.append_results(labels,batch_number=1,expected_report_sha256=digest(first),
            expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(updated['models'][0]['hit8'],3)
        self.assertEqual(self.j.read_report(expected_seal_sha256=s['seal_sha256']),updated)
        self.assertEqual((self.j.directory/'predictions.json').read_bytes(),saved)
        self.assertEqual((self.j.directory/'labels.json').read_text(), '[]\n')

    def test_result_update_requires_new_revision_and_expected_parent(self):
        s=self.seal();r=self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z');called=[]
        with self.assertRaises(EvaluationError):
            self.j.append_results(lambda:(called.append(1) or labels()),batch_number=1,
                expected_report_sha256='0'*64,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(called,[])
        with self.assertRaises(EvaluationError):
            self.j.append_results(labels,batch_number=1,expected_report_sha256=digest(r),
                expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        with self.assertRaises((EvaluationError,FileExistsError,FileNotFoundError)):
            self.j.append_results(lambda:(called.append(1) or []),batch_number=1,expected_report_sha256=digest(r),
                expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:10:00Z')
        self.assertEqual(called,[])

    def test_official_revision_retains_original_result_and_changes_score_only(self):
        s=self.seal();r=self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        revised=copy.deepcopy(labels()[0]);revised.update(revision=2,status='CANCELLED',winning_triples=[],observed_at='2030-01-06T01:30:00Z')
        result=self.j.append_results(lambda:[revised],batch_number=1,expected_report_sha256=digest(r),
            expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(result['models'][0]['known_results'],2)
        self.assertEqual(result['models'][0]['excluded_results'],1)
        self.assertEqual(self.j.read_report(expected_seal_sha256=s['seal_sha256']),result)

    def test_interrupted_update_allows_explicit_prior_report_recovery_only(self):
        s=self.seal();r=self.j.reveal(labels,expected_seal_sha256=s['seal_sha256'],now='2030-01-06T01:00:00Z')
        called=[]
        def broken():called.append(1);raise RuntimeError('fictional failure after exposure')
        with self.assertRaises(RuntimeError):
            self.j.append_results(broken,batch_number=1,expected_report_sha256=digest(r),
                expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:00:00Z')
        self.assertEqual(self.j.read_report(expected_seal_sha256=s['seal_sha256'],through_batch=0),r)
        with self.assertRaises((EvaluationError,FileNotFoundError)):
            self.j.append_results(broken,batch_number=1,expected_report_sha256=digest(r),
                expected_seal_sha256=s['seal_sha256'],now='2030-01-06T02:10:00Z')
        self.assertEqual(called,[1])


if __name__=='__main__':unittest.main()
