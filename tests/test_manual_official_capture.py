"""Fictional official-host responses, no provider requests or real keys."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError


DAY = '2030-04-01'
URL = 'https://autorace.jp/race_info/Program/kawaguchi/2030-04-01_1'
BODY = b'<html>invented source bytes retained exactly</html>'


class Clock:
    def __init__(self): self.current = datetime(2030, 4, 1, 1, tzinfo=timezone.utc); self.seconds = 0.; self.waits = []
    def now(self): return self.current
    def monotonic(self): return self.seconds
    def advance(self, seconds): self.seconds += seconds; self.current += timedelta(seconds=seconds)
    def sleep(self, seconds): self.waits.append(seconds); self.advance(seconds)


class Response(io.BytesIO):
    def __init__(self, body=BODY, *, url=URL, status=200, headers=None):
        super().__init__(body); self.url=url; self.status=status
        self.headers={'Content-Type':'text/html; charset=utf-8', **(headers or {})}
    def geturl(self): return self.url


def manifest(urls):
    groups = {}
    for url in urls:
        sport = 'keirin' if 'keirin.jp' in url else 'horse' if 'jra.go.jp' in url else 'autorace'
        groups.setdefault(sport, []).append(url)
    hosts = {'keirin':'keirin.jp', 'autorace':'autorace.jp', 'horse':'www.jra.go.jp'}
    return dict(schema='RACE_AI_MANUAL_OFFICIAL_TERMS_V1', execution_day=DAY,
        purpose='PRIVATE_FACTUAL_ANALYSIS', public_redistribution=False,
        provider_model_training_permission_confirmed=False, owner_instruction_ref='FICTIONAL_OWNER_PRIVATE_REQUEST',
        terms=[dict(sport=sport, terms_url='https://'+hosts[sport]+'/terms', policy_sha256='a'*64,
                    policy_captured_at='2030-04-01T00:59:00+00:00', source_urls=values,
                    uses=['private_retention','private_factual_analysis']) for sport,values in sorted(groups.items())])


class ManualOfficialCaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.manual_official_capture'),
                             'one-time source collection needs private original retention')
        self.api = importlib.import_module('race_ai.manual_official_capture')
        self.tmp = tempfile.TemporaryDirectory(prefix='fictional-official-capture-'); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.clock = Clock(); self.calls = []

    def collect(self, urls=None, *, opener=None, **changes):
        urls = [URL] if urls is None else urls
        def fetch(request, timeout):
            self.calls.append((request.full_url, timeout, self.clock.monotonic()))
            return Response(url=request.full_url)
        args = dict(execution_day=DAY, terms_manifest=manifest(urls), cache_dir=self.root/'cache',
                    clock=self.clock.now, monotonic=self.clock.monotonic, sleeper=self.clock.sleep,
                    opener=fetch if opener is None else opener)
        args.update(changes)
        return self.api.collect_once(urls, **args)

    def test_original_bytes_clocks_private_modes_and_cache_survive_without_refetch(self):
        original_manifest = manifest([URL]); before = deepcopy(original_manifest)
        first = self.collect(terms_manifest=original_manifest)
        stored = self.api.read_capture(self.root/'cache', URL)
        self.assertEqual(stored['raw'], BODY)
        self.assertEqual(stored['metadata']['source_sha256'], hashlib.sha256(BODY).hexdigest())
        self.assertEqual(stored['metadata']['captured_at'], self.clock.now().isoformat())
        self.assertIsNone(stored['metadata']['published_at'])
        self.assertEqual(len(self.calls), 1); self.assertEqual(self.calls[0][1], 12)
        self.assertEqual((self.root/'cache').stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in (self.root/'cache').iterdir()))
        self.clock.advance(5)
        second = self.collect(opener=lambda *args,**kwargs:self.fail('cached bytes must not cause another GET'))
        self.assertEqual(second['cache_hits'], 1)
        self.assertEqual(self.api.read_capture(self.root/'cache', URL), stored)
        self.assertEqual(original_manifest, before)
        self.assertEqual(first['source_requests'], 1)
        self.assertNotIn(URL, json.dumps(first)); self.assertNotIn(BODY.decode(), json.dumps(first))

    def test_explicit_official_rights_bind_sport_host_and_reject_credentials(self):
        for sport, host in (('keirin','keirin.jp'), ('autorace','www.autorace.jp'), ('horse','jra.go.jp')):
            rights = self.api.official_rights_ref(sport)
            self.assertEqual(rights, 'OWNER_PERSONAL_OFFICIAL_'+sport.upper()+'_FACTUAL_ANALYSIS_20261107')
            self.assertEqual(self.api.validate_source_pair('https://'+host+'/card?race=1', rights),
                             ('https://'+host+'/card?race=1', rights))
        rights = self.api.official_rights_ref('autorace')
        for url in ('http://autorace.jp/card', 'https://autorace.jp.evil.test/card',
                    'https://www.winticket.jp/autorace/card', 'https://jra.go.jp/card',
                    'https://user:pass@autorace.jp/card', 'https://autorace.jp/card#private',
                    'https://autorace.jp/card#',
                    'https://autorace.jp/card?api_key=secret', 'https://autorace.jp/card?%74oken=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError): self.api.validate_source_pair(url, rights)

    def test_sequential_spacing_same_host_redirects_and_actual_request_budget(self):
        urls = [URL, URL.replace('_1','_2')]
        def fetch(request, timeout):
            self.calls.append((request.full_url, timeout, self.clock.monotonic()))
            if request.full_url == URL:
                raise HTTPError(URL, 302, 'redirect', {'Location':'/actual-card'}, None)
            return Response(url=request.full_url)
        report = self.collect(urls, opener=fetch)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(b[2]-a[2] >= .8-1e-9 for a,b in zip(self.calls,self.calls[1:])))
        self.assertEqual(report['source_requests'], 3)
        stored = self.api.read_capture(self.root/'cache', URL)
        self.assertEqual(stored['metadata']['final_url'], 'https://autorace.jp/actual-card')
        self.assertEqual(stored['metadata']['redirect_chain'], [URL,'https://autorace.jp/actual-card'])

    def test_denied_hosts_remain_stopped_across_resume_and_other_hosts_are_independent(self):
        urls = [URL, URL.replace('_1','_2'), 'https://keirin.jp/pc/card']
        for status in (401,403,429):
            folder = self.root/str(status)
            def fetch(request, timeout):
                self.calls.append(request.full_url)
                if 'autorace.jp' in request.full_url:
                    raise HTTPError(request.full_url,status,'stop',{'Retry-After':'60'},None)
                return Response(url=request.full_url)
            result = self.collect(urls, opener=fetch, cache_dir=folder)
            self.assertEqual(result['source_requests'], 2)
            self.assertEqual(result['blocked_host_count'], 1)
            self.collect(urls, opener=lambda *a,**k:self.fail('denied or captured targets must not be retried'),cache_dir=folder)

    def test_denial_stops_the_host_even_if_the_response_reports_an_unexpected_url(self):
        urls=[URL,URL.replace('_1','_2')]
        def denied(request, timeout):
            self.calls.append(request.full_url)
            return Response(url='https://autorace.jp/unexpected',status=403)
        report=self.collect(urls,opener=denied)
        self.assertEqual((report['source_requests'],report['blocked_host_count']),(1,1))
        self.assertEqual(len(self.calls),1)

    def test_redirect_bypasses_unexpected_following_and_oversized_bodies_are_rejected(self):
        cases = ('foreign', 'credentials', 'unexpected_final', 'oversized', 'declared_oversized', 'truncated')
        for kind in cases:
            def fetch(request, timeout):
                self.calls.append(request.full_url)
                if kind in ('foreign','credentials'):
                    target='https://jra.go.jp/card' if kind=='foreign' else '/card?token=private'
                    raise HTTPError(request.full_url,302,'redirect',{'Location':target},None)
                if kind=='unexpected_final': return Response(url=URL+'/silently-followed')
                if kind=='oversized': return Response(b'x'*(2*1024*1024+1),url=request.full_url)
                if kind=='truncated': return Response(url=request.full_url,headers={'Content-Length':str(len(BODY)+1)})
                return Response(url=request.full_url,headers={'Content-Length':str(2*1024*1024+1)})
            result=self.collect(opener=fetch,cache_dir=self.root/kind)
            self.assertEqual(result['captured_sources'],0)
            with self.assertRaises(ValueError): self.api.read_capture(self.root/kind,URL)

    def test_request_cap_terms_day_and_paths_are_enforced_before_network(self):
        urls=[URL+'?race='+str(n) for n in range(33)]
        with self.assertRaises(ValueError): self.collect(urls)
        for mutation in (lambda m:m.update(public_redistribution=True),
                         lambda m:m.update(provider_model_training_permission_confirmed=True),
                         lambda m:m['terms'][0].update(policy_captured_at='2031-01-01T00:00:00Z'),
                         lambda m:m['terms'][0].update(policy_sha256='invalid')):
            terms=manifest([URL]);mutation(terms)
            with self.assertRaises(ValueError): self.collect(terms_manifest=terms)
        with self.assertRaises(ValueError): self.collect(execution_day='2029-12-31')
        repo=self.root/'repo';repo.mkdir();(repo/'.git').write_text('gitdir: /fictional')
        with self.assertRaises(ValueError): self.collect(cache_dir=repo/'private')
        target=self.root/'target';target.mkdir(mode=0o700);link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(ValueError): self.collect(cache_dir=link)
        self.assertEqual(self.calls,[])

    def test_imported_probe_bytes_are_cached_with_original_clocks_and_no_network(self):
        captured='2030-04-01T00:59:30+00:00'
        report=self.api.import_captures([dict(url=URL,raw=BODY,captured_at=captured,content_type='text/html',final_url=URL)],
            execution_day=DAY,terms_manifest=manifest([URL]),cache_dir=self.root/'cache',clock=self.clock.now)
        self.assertEqual(report['imported_sources'],1)
        self.assertEqual(self.api.read_capture(self.root/'cache',URL)['metadata']['captured_at'],captured)
        self.collect(opener=lambda *a,**k:self.fail('actual probe bytes must not be collected again'))

    def test_redirect_requests_share_the_durable_32_request_bound(self):
        urls=[URL+'?race='+str(number) for number in range(32)]
        def fetch(request, timeout):
            self.calls.append(request.full_url)
            if '?race=' in request.full_url:
                target='/actual/'+request.full_url.rsplit('=',1)[1]
                raise HTTPError(request.full_url,302,'redirect',{'Location':target},None)
            return Response(url=request.full_url)
        report=self.collect(urls,opener=fetch)
        self.assertEqual((report['source_requests'],report['captured_sources']), (32,16))
        self.assertEqual(len(self.calls),32)
        resumed=self.collect(urls,opener=lambda *a,**k:self.fail('request reservations must not reset'))
        self.assertEqual((resumed['source_requests'],resumed['total_collector_requests']),(0,32))

    def test_uncertain_reserved_request_is_not_retried_after_interruption(self):
        def interrupted(request, timeout):
            self.calls.append(request.full_url)
            raise KeyboardInterrupt('fictional interruption after durable reservation')
        with self.assertRaises(KeyboardInterrupt): self.collect(opener=interrupted)
        ledger=json.loads((self.root/'cache'/'cache.json').read_bytes())
        self.assertEqual(len(ledger['attempts']),1)
        self.assertEqual(ledger['attempts'][0]['state'],'RESERVED')
        with self.assertRaisesRegex(ValueError,'UNCERTAIN_PRIOR_REQUEST_NO_RETRY'):
            self.collect(opener=lambda *a,**k:self.fail('uncertain source attempts must not retry'))

    def test_cli_collect_seal_restore_prints_counts_and_preserves_exact_source(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.manual_official_capture'),
                             'the one-time capture path needs an explicit CLI')
        cli=importlib.import_module('scripts.manual_official_capture')
        terms=self.root/'terms.json';terms.write_text(json.dumps(manifest([URL])),encoding='utf-8')
        def run(arguments, **kwargs):
            stdout=io.StringIO()
            with redirect_stdout(stdout):
                status=cli.main(arguments,clock=self.clock.now,monotonic=self.clock.monotonic,
                                sleeper=self.clock.sleep,**kwargs)
            report=json.loads(stdout.getvalue());self.assertEqual(status,0)
            self.assertNotIn(URL,stdout.getvalue());self.assertNotIn(BODY.decode(),stdout.getvalue())
            return report
        run(['collect','--execution-day',DAY,'--url',URL,'--terms-manifest',str(terms),
             '--cache-dir',str(self.root/'cache')],opener=lambda request,timeout:Response(url=request.full_url))
        sealed=run(['seal','--cache-dir',str(self.root/'cache'),'--sealed-dir',str(self.root/'sealed'),
                    '--run-id','42','--round-no','0'],key=bytes(range(32)))
        run(['restore','--sealed-dir',str(self.root/'sealed'),'--output-dir',str(self.root/'restored'),
             '--expected-index-sha256',sealed['index_sha256']],key=bytes(range(32)))
        self.assertEqual(self.api.read_capture(self.root/'restored',URL)['raw'],BODY)


if __name__=='__main__':unittest.main()
