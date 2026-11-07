"""Authored Sunday cards/rules only; no provider calls or real future cards."""
from copy import deepcopy
from datetime import datetime
import unittest

from race_ai.actions_contract import digest
from race_ai import jra_official_sparse_adapter as adapter
from tests import test_jra_official_sparse_adapter as fixtures

NOW = datetime.fromisoformat('2026-11-08T01:10:00+00:00')
CARD_URL = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0103202603021120261108/AA'
HEADER = '<tr><th>対象レース</th><th>発売開始日時</th><th>発売締切時刻</th></tr>'
SATURDAY = '<tr><th>土曜日全レース</th><td>金曜日の18時30分</td><td>各レース 発走時刻1分前</td></tr>'
SUNDAY = '<tr><th>日曜日全レース</th><td>土曜日の19時30分</td><td>各レース 発走時刻1分前</td></tr>'


def rule_html(rows=SATURDAY+SUNDAY):
    return '<html><head><meta charset="utf-8"></head><body><h2>即PAT会員の発売時間（2026年）</h2><table class="basic auto"><caption><h3>当日発売</h3><p>表はスクロールすることができます</p></caption><thead>'+HEADER+'</thead><tbody>'+rows+'</tbody></table></body></html>'


def evidence(html=None):
    raw=(rule_html() if html is None else html).encode()
    return dict(raw=raw, metadata=fixtures.metadata(raw,fixtures.RULE_URL),
        sales_channel=adapter.CHANNEL,rule_id='JRA_2026_SUNDAY_ALL_RACES_START_MINUS_60_SECONDS')


def build(proof=None,*,event='2026-11-08',meeting_day=2):
    y,m,d=map(int,event.split('-'))
    raw=fixtures.card().decode('cp932').replace('2026年11月7日（土曜）3回福島1日',f'{y}年{m}月{d}日（日曜）3回福島{meeting_day}日').encode('cp932')
    url=f'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0103{y}03{meeting_day:02d}11{y}{m:02d}{d:02d}/AA'
    meta=fixtures.metadata(raw,url,completed='2026-11-08T01:00:03+00:00');meta['fetched_at']='2026-11-08T01:00:00+00:00'
    return adapter.build_sparse_payload(raw,meta,now=NOW,source_rights_ref=fixtures.RIGHTS,cutoff_evidence=evidence() if proof is None else proof)


class SundayJraSalesRuleTests(unittest.TestCase):
    def test_explicit_sunday_primary_table_gives_cutoff_with_original_source_clocks(self):
        proof=evidence();before=deepcopy(proof);value=build(proof)
        self.assertEqual(value['state'],'READY')
        self.assertEqual(value['native_payload']['snapshot']['race']['sales_cutoff_at'],'2026-11-08T15:19:00+09:00')
        self.assertEqual(value['native_payload']['cutoff_evidence']['rule_id'],proof['rule_id'])
        self.assertEqual(value['native_payload']['source_evidence'][1]['captured_at'],proof['metadata']['response_received_at'])
        self.assertEqual(proof,before)

    def test_sunday_cutoff_can_inherit_exact_same_table_rowspan(self):
        rows=SATURDAY.replace('<td>各レース','<td rowspan="2">各レース')+SUNDAY.replace('<td>各レース 発走時刻1分前</td>','')
        self.assertEqual(build(evidence(rule_html(rows)))['state'],'READY')

    def test_day_channel_year_and_rule_id_cannot_be_borrowed(self):
        for field,value in [('sales_channel','WIN5'),('rule_id','JRA_2026_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS')]:
            proof=evidence();proof[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):build(proof)
        with self.assertRaises(ValueError):build(evidence(rule_html().replace('2026年','2025年')))
        for event,meeting in [('2026-11-07',1),('2026-11-09',3),('2027-11-07',2)]:
            with self.subTest(event=event),self.assertRaises(ValueError):build(event=event,meeting_day=meeting)

    def test_saturday_only_wrong_section_or_wrong_column_cannot_supply_sunday_cutoff(self):
        examples=[rule_html(SATURDAY),rule_html().replace('<h3>当日発売</h3>','<h3>前日発売</h3>'),
            rule_html(SATURDAY).replace('</body>','<table><caption><h3>WIN5</h3></caption>'+HEADER+SUNDAY+'</table></body>'),
            rule_html(SATURDAY).replace('</body>','<p>日曜日全レース 各レース発走時刻1分前</p></body>'),
            rule_html().replace('発売締切時刻','発売開始時刻'),
            rule_html(SATURDAY+SUNDAY.replace('各レース 発走時刻1分前','各レース 発走時刻3分前')),
            rule_html(SATURDAY+SUNDAY.replace('各レース 発走時刻1分前','各レース 発走時刻1分前ではありません'))]
        for html in examples:
            with self.subTest(html=html),self.assertRaises(ValueError):build(evidence(html))

    def test_ambiguous_rows_tables_and_invalid_spans_hold(self):
        examples=[rule_html(SATURDAY+SUNDAY+SUNDAY),rule_html().replace('</body>','<table><caption><h3>当日発売</h3></caption>'+HEADER+SUNDAY+'</table></body>'),
            rule_html().replace('<td>各レース 発走時刻1分前</td></tr>', '<td rowspan="0">各レース 発走時刻1分前</td></tr>',1),
            rule_html().replace('<td>各レース 発走時刻1分前</td></tr>', '<td rowspan>各レース 発走時刻1分前</td></tr>',1),
            rule_html(SATURDAY.replace('<td>各レース','<td rowspan="3">各レース')+SUNDAY.replace('<td>各レース 発走時刻1分前</td>','')),
            rule_html(SATURDAY+SUNDAY.replace('<td>土曜日の19時30分</td>','<td colspan="2">土曜日の19時30分</td>'))]
        for html in examples:
            with self.subTest(html=html),self.assertRaises(ValueError):build(evidence(html))

    def test_nonrendered_rule_fragments_do_not_supply_sunday_evidence(self):
        for opening,closing in [('<template>','</template>'),('<div hidden>','</div>'),('<div style="display: none">','</div>')]:
            with self.subTest(opening=opening),self.assertRaises(ValueError):build(evidence(opening+rule_html()+closing))

    def test_legacy_saturday_output_remains_byte_equivalent(self):
        value=adapter.build_sparse_payload(fixtures.card(),fixtures.metadata(fixtures.card()),now=fixtures.NOW,
            source_rights_ref=fixtures.RIGHTS,cutoff_evidence=fixtures.evidence())
        self.assertEqual(digest(value),'8b2944c97dfd4ee04edb2e565dea525189ca1a9d5ba7360f8703fbf380e5fc94')


if __name__=='__main__':unittest.main()
