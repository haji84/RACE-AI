"""Create-only local experiment journal and one-use final-label reveal.

The root directory is a trusted, caller-managed private registry shared across
experiments. A different/deleted registry cannot prove non-exposure. File hashes
and fsync are corruption/order controls, not an external clock or WORM service.
Partial writes and stale locks fail closed; no automatic deletion or retry.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from .actions_contract import canonical, digest
from .evaluation_experiment import (EvaluationError, require, name, sha, moment,
    validate_plan, seal_predictions, verify_seal, score_seal, split_for)


def _read(path):
    def unique(pairs):
        out = {}
        for k,v in pairs:
            require(k not in out, 'duplicate journal JSON field')
            out[k] = v
        return out
    require(not path.is_symlink(), 'journal symlink rejected')
    with path.open('rb') as stream:
        raw = stream.read(100_000_001)
    require(len(raw) <= 100_000_000, 'journal exceeds limit')
    obj = json.loads(raw, object_pairs_hook=unique,
                     parse_constant=lambda x: (_ for _ in ()).throw(EvaluationError('nonfinite JSON')))
    require(raw == (canonical(obj)+'\n').encode('utf-8'), 'noncanonical journal bytes')
    return obj


def _create(path, value):
    raw = (canonical(value)+'\n').encode('utf-8')
    require(len(raw) <= 100_000_000, 'journal exceeds limit')
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(path.read_bytes() == raw, 'journal readback differs')


class EvaluationJournal:
    def __init__(self, root, experiment_id):
        require(name(experiment_id) and '/' not in experiment_id and ':' not in experiment_id
                and experiment_id not in ('.','..'), 'safe experiment directory required')
        self.root = Path(root)
        self.directory = self.root / experiment_id
        self.experiment_id = experiment_id

    def register(self, plan):
        p = validate_plan(plan)
        require(p['experiment_id'] == self.experiment_id, 'journal/experiment identity mismatch')
        self.root.mkdir(parents=True, exist_ok=True)
        require(not self.root.is_symlink(), 'registry symlink rejected')
        self.directory.mkdir()  # Another writer or interrupted creation is not overwritten.
        _create(self.directory/'plan.json', p)
        return digest(p)

    def seal(self, contexts, outputs, *, sealed_at, expected_plan_sha256):
        p = _read(self.directory/'plan.json')
        require(sha(expected_plan_sha256) and digest(p) == expected_plan_sha256, 'registered plan changed')
        bundle = seal_predictions(p, contexts, outputs, sealed_at=sealed_at)
        _create(self.directory/'predictions.json', bundle)
        return bundle

    @contextmanager
    def _lock(self):
        lock = self.root/'final-reveal.lock'
        # Only unlink the lock this process successfully created, never an old one.
        with lock.open('xb') as stream:
            stream.write(self.experiment_id.encode('ascii')); stream.flush(); os.fsync(stream.fileno())
        try:
            yield
        finally:
            lock.unlink()

    def _verified(self, expected_seal_sha256):
        s = verify_seal(_read(self.directory/'predictions.json'))
        require(sha(expected_seal_sha256) and s['seal_sha256'] == expected_seal_sha256,
                'expected sealed prediction digest mismatch')
        p = _read(self.directory/'plan.json')
        require(digest(p) == s['plan_sha256'] and p['experiment_id'] == self.experiment_id,
                'registered plan/seal mismatch')
        return s

    def reveal(self, label_reader, *, expected_seal_sha256, now):
        """Reserve exposure before invoking reader. A crash is not a retry grant.

        The reader receives no model or tuning callback. Results are separate
        supplied source claims, not authenticated by this local filesystem.
        """
        s = self._verified(expected_seal_sha256)
        require(callable(label_reader) and moment(now) >= moment(s['sealed_at']), 'reader/clock invalid')
        with self._lock():
            used = self.root/'used-final-races'; used.mkdir(exist_ok=True)
            require(not used.is_symlink(), 'consumed registry symlink rejected')
            exposed = self.root/'exposed-races'; exposed.mkdir(exist_ok=True)
            require(not exposed.is_symlink(), 'exposure registry symlink rejected')
            targets = []
            exposures = []
            for race in s['plan']['races']:
                identity = {k:race[k] for k in ('sport','venue','event_date_jst','race_no')}
                exposure = exposed/(digest(identity)+'.json')
                if split_for(s['plan'], race) == 'test':
                    path = used/(digest(identity)+'.json')
                    require(not path.exists() and not exposure.exists(), 'final race already exposed by this registry')
                    targets.append((path,identity))
                if not exposure.exists():
                    exposures.append((exposure,identity,split_for(s['plan'],race)))
            intent = {'schema':'RACE_AI_FINAL_REVEAL_INTENT_V1',
                      'experiment_id':self.experiment_id,'seal_sha256':s['seal_sha256'],
                      'reserved_at':now,'final_race_count':len(targets),
                      'potentially_exposed_race_count':len(s['plan']['races'])}
            _create(self.directory/'reveal-intent.json', intent)
            for path,identity in targets:
                _create(path, {**intent,'race_identity':identity})
            for path,identity,phase in exposures:
                _create(path, {**intent,'race_identity':identity,'first_phase':phase})
            # The registry is durable before potentially result-bearing I/O.
            labels = label_reader()
            require(type(labels) is list, 'label list required')
            for label in labels:
                require(type(label) is dict and 'observed_at' in label and moment(label['observed_at']) <= moment(now), 'result observed in future')
            report = score_seal(s, labels)
            _create(self.directory/'labels.json', labels)
            _create(self.directory/'report.json', report)
            _create(self.directory/'completed.json', {'seal_sha256':s['seal_sha256'],
                'labels_sha256':digest(labels),'report_sha256':digest(report),'completed_at_claim':now})
            return report

    def _completed_state(self, expected_seal_sha256, through_batch=None):
        require(through_batch is None or type(through_batch) is int and 0 <= through_batch <= 1000, 'explicit completed batch required')
        s = self._verified(expected_seal_sha256)
        done = _read(self.directory/'completed.json')
        labels = _read(self.directory/'labels.json'); report = _read(self.directory/'report.json')
        require(done.get('seal_sha256') == s['seal_sha256'] and done.get('labels_sha256') == digest(labels)
                and done.get('report_sha256') == digest(report), 'completed journal changed')
        require(canonical(score_seal(s, labels)) == canonical(report), 'report arithmetic mismatch')
        count = 0
        updates = self.directory/'result-updates'
        if updates.exists() and through_batch != 0:
            require(not updates.is_symlink(), 'update registry symlink rejected')
            paths = sorted(updates.iterdir())
            require(through_batch is None or through_batch <= len(paths), 'requested batch does not exist')
            if through_batch is not None:
                paths = paths[:through_batch]
            for count,path in enumerate(paths,1):
                require(path.name == f'{count:06d}' and path.is_dir() and not path.is_symlink(), 'result batch sequence invalid')
                intent = _read(path/'intent.json'); delta = _read(path/'labels.json')
                next_report = _read(path/'report.json'); next_done = _read(path/'completed.json')
                require(intent == {'batch_number':count,'seal_sha256':s['seal_sha256'],
                    'previous_report_sha256':digest(report),'reserved_at':next_done['completed_at_claim']}, 'result batch parent changed')
                self._new_labels(delta, labels, next_done['completed_at_claim'])
                require(moment(next_done['completed_at_claim']) >= moment(done['completed_at_claim']), 'update clock reversed')
                labels = labels + delta
                require(next_done == {'seal_sha256':s['seal_sha256'], 'labels_sha256':digest(labels),
                    'report_sha256':digest(next_report),'completed_at_claim':intent['reserved_at']}, 'result update digest mismatch')
                require(canonical(score_seal(s,labels)) == canonical(next_report), 'updated report arithmetic mismatch')
                report,done = next_report,next_done
        require(through_batch is None or count == through_batch, 'requested batch does not exist')
        return s,labels,report,done,count

    @staticmethod
    def _new_labels(delta, previous, now):
        require(type(delta) is list and delta, 'new nonempty result batch required')
        prior = {}
        for label in previous:
            prior[label['race_id']] = max(prior.get(label['race_id'],0),label['revision'])
        for label in delta:
            require(type(label) is dict and type(label.get('race_id')) is str and type(label.get('revision')) is int
                and label['revision'] > prior.get(label['race_id'],0), 'result update must have new revision')
            require('observed_at' in label and moment(label['observed_at']) <= moment(now), 'result observed in future')

    def append_results(self, label_reader, *, batch_number, expected_report_sha256, expected_seal_sha256, now):
        """Append new official observations to the same frozen predictions.

        The batch intent is written before the reader. Interrupted batches are
        not retried. No model callback or tuning operation occurs here.
        """
        require(type(batch_number) is int and 1 <= batch_number <= 1000 and callable(label_reader), 'bounded batch/reader required')
        with self._lock():
            s,labels,report,done,count = self._completed_state(expected_seal_sha256)
            require(batch_number == count+1 and sha(expected_report_sha256)
                and expected_report_sha256 == digest(report), 'result batch parent mismatch')
            require(moment(now) >= moment(done['completed_at_claim']), 'update clock reversed')
            updates = self.directory/'result-updates'; updates.mkdir(exist_ok=True)
            require(not updates.is_symlink(), 'update registry symlink rejected')
            path = updates/f'{batch_number:06d}'; path.mkdir()
            _create(path/'intent.json', {'batch_number':batch_number,'seal_sha256':s['seal_sha256'],
                'previous_report_sha256':digest(report),'reserved_at':now})
            delta = label_reader(); self._new_labels(delta,labels,now)
            combined = labels+delta; result = score_seal(s,combined)
            _create(path/'labels.json',delta); _create(path/'report.json',result)
            _create(path/'completed.json',{'seal_sha256':s['seal_sha256'], 'labels_sha256':digest(combined),
                'report_sha256':digest(result),'completed_at_claim':now})
            return result

    def read_report(self, *, expected_seal_sha256, through_batch=None):
        """Read latest, or explicitly recover a prior completed batch.

        A pending later batch never becomes a retry grant; callers can request
        through_batch=0 for the original report without hiding that selection.
        """
        _,_,report,_,_ = self._completed_state(expected_seal_sha256,through_batch)
        return report
