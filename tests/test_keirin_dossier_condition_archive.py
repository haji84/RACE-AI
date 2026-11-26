from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_dossier_condition_archive as build


class HistoricConditionTests(unittest.TestCase):
    def test_numeric_archive_rows_are_joined_by_race_car_and_official_identity(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'fixture.db'
            with sqlite3.connect(path) as conn:
                conn.executescript('''
                    CREATE TABLE entries(race_date,venue_code,rno,kumiban,racer_name,kyu,prefecture);
                    CREATE TABLE results(race_date,venue_code,rno,kumiban,racer_name,rank,is_incident);
                    CREATE TABLE races(race_date,venue_code,rno,grade,race_type);
                    INSERT INTO races VALUES ('20261120',98,1,'F2','A級準決勝');
                    INSERT INTO races VALUES ('20261123',98,1,'F2','A級決勝');
                    INSERT INTO entries VALUES ('20261120',98,1,1,'架空 選手',88,'京都');
                    INSERT INTO entries VALUES ('20261120',98,1,2,'別人 同名',89,'京都');
                    INSERT INTO entries VALUES ('20261120',98,1,3,'落車 選手',87,'京都');
                    INSERT INTO entries VALUES ('20261123',98,1,1,'架空 選手',88,'京都');
                    INSERT INTO results VALUES ('20261120',98,1,1,'架空選手','1',0);
                    INSERT INTO results VALUES ('20261120',98,1,2,'別人同名','2',0);
                    INSERT INTO results VALUES ('20261120',98,1,3,'落車選手','3',1);
                    INSERT INTO results VALUES ('20261123',98,1,1,'架空選手','1',0);
                ''')
            lookup = build.identity_lookup([
                dict(registration='014001', name='架空選手', cohort=88, prefecture_or_country='京都府'),
                dict(registration='014002', name='別人同名', cohort=89, prefecture_or_country='京都府'),
                dict(registration='014003', name='別人同名', cohort=89, prefecture_or_country='京都府'),
                dict(registration='014004', name='落車選手', cohort=87, prefecture_or_country='京都府')])
            starts = build.matching_starts(path, '2026-11-20', '2026-11-22', lookup)
            self.assertEqual(list(starts), [
                (('20261120', 98, 1, 1), ('014001', 'F2', 'SEMI_FINAL', 1)),
            ])
