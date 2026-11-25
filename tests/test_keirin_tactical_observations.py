"""Only source-bound race episodes contribute to the tactical dossier."""
import unittest

from race_ai import keirin_tactical_observations as tactics

REG = '015001'
TARGET = '202611252611'
AT = '2026-11-25T20:10:00+09:00'


def event(event_id, ability, **change):
    return dict(race_id='202611222611', registration=REG, event_id=event_id,
                ability=ability, source='video', receipt='witnessed',
                published_at='2026-11-22T21:00:00+09:00', observed_at='2026-11-23T12:00:00+09:00',
                **change)


def collect(*rows):
    return tactics.profile_episodes(rows, registration=REG, as_of=AT, target_race_id=TARGET,
                                    verify=lambda row: row['receipt']=='witnessed')


class TacticalObservationsTest(unittest.TestCase):
    def test_exact_opportunity_denominators_and_no_rating_for_unobserved(self):
        profile=collect(
            event('a','resist_makuri', outcome='success'),
            event('b','resist_makuri', outcome='failure'),
            event('c','resist_makuri', outcome='unknown'))
        resistance=profile['abilities']['resist_makuri']
        self.assertEqual((resistance['observed_opportunities'],resistance['known_outcomes'],resistance['unknown_outcomes']), (3,2,1))
        self.assertEqual(resistance['observed_success_rate'],.5)
        self.assertEqual(resistance['success_rate_bounds_for_all_observed'],[1/3,2/3])
        self.assertIsNone(profile['abilities']['follower_acceleration']['observed_success_rate'])
        self.assertEqual(len(profile['abilities']),6)

    def test_duplicate_or_conflicting_versions_do_not_manufacture_more_attempts(self):
        first=event('a','tactical_switch',outcome='success')
        notes=collect(first,dict(first),dict(first,outcome='failure'))
        self.assertEqual(notes['abilities']['tactical_switch']['observed_opportunities'],1)
        self.assertEqual(notes['abilities']['tactical_switch']['known_outcomes'],0)
        self.assertEqual(notes['abilities']['tactical_switch']['conflicts'],1)

    def test_relative_frames_are_not_sustained_speed_measurements(self):
        notes=collect(event('a','side_by_side_sustain',outcome='success', measurement='relative_position'),
                      event('b','side_by_side_sustain',outcome='failure', measurement='calibrated_speed'))
        ability=notes['abilities']['side_by_side_sustain']
        self.assertEqual(ability['observed_opportunities'],2)
        self.assertEqual(ability['known_outcomes'],1)
        self.assertEqual(ability['relative_position_only'],1)
        self.assertEqual(ability['observed_success_rate'],0.0)

    def test_unverified_future_current_race_and_user_do_not_set_an_ability(self):
        row=event('a','late_kick_after_effort',outcome='success')
        profile=collect(dict(row,observed_at=AT),dict(row,race_id=TARGET),dict(row,source='user'),
                        dict(row,receipt='unverified'),dict(row,registration='011111'))
        ability=profile['abilities']['late_kick_after_effort']
        self.assertEqual(ability['observed_opportunities'],0)
        self.assertIsNone(ability['observed_success_rate'])
        self.assertEqual(profile['excluded']['not_available_before_cutoff'],1)
        self.assertEqual(profile['excluded']['target_race'],1)
        self.assertEqual(profile['excluded']['source_unverified'],2)

    def test_inside_outside_finish_distributions_keep_exposures_and_finishes_separate(self):
        notes=collect(event('a','inside_outside',side='inside',finish=2),
                      event('b','inside_outside',side='outside',finish=1),
                      event('c','inside_outside',side='outside',finish=None))
        sides=notes['abilities']['inside_outside']['sides']
        self.assertEqual(sides['inside']['finish_counts'],{'2':1})
        self.assertEqual(sides['inside']['observed_win_rate'],0)
        self.assertEqual(sides['outside']['observed_opportunities'],2)
        self.assertEqual(sides['outside']['known_finishes'],1)
        self.assertEqual(sides['outside']['unknown_finishes'],1)

    def test_multiple_duels_in_one_race_do_not_repeat_its_finish(self):
        profile = collect(
            event('a', 'inside_outside', side='outside', finish=1),
            event('b', 'inside_outside', side='outside', finish=1),
            event('c', 'inside_outside', side='outside', finish=None),
            dict(event('d', 'inside_outside', side='outside', finish=3), race_id='202611212611'),
        )
        outside = profile['abilities']['inside_outside']['sides']['outside']
        self.assertEqual(outside['observed_opportunities'], 4)
        self.assertEqual(outside['observed_races'], 2)
        self.assertEqual(outside['races_with_confirmed_finish'], 2)
        self.assertEqual(outside['race_finish_counts'], {'1': 1, '3': 1})
        self.assertEqual(outside['observed_race_win_rate'], 0.5)

    def test_conflicting_finishes_in_the_same_race_are_not_counted_in_either_side(self):
        profile = collect(
            event('a', 'inside_outside', side='inside', finish=1),
            event('b', 'inside_outside', side='outside', finish=2),
        )
        sides = profile['abilities']['inside_outside']['sides']
        for side in sides.values():
            self.assertEqual(side['observed_races'], 1)
            self.assertEqual(side['races_with_confirmed_finish'], 0)
            self.assertEqual(side['races_with_unresolved_finish'], 1)
            self.assertEqual(side['races_with_conflicting_finish'], 1)
            self.assertIsNone(side['observed_race_win_rate'])

    def test_side_disagreement_does_not_hide_conflicting_finish_evidence(self):
        profile = collect(
            event('a', 'inside_outside', side='inside', finish=2),
            event('a', 'inside_outside', side='outside', finish=2),
            event('b', 'inside_outside', side='outside', finish=1),
        )
        sides = profile['abilities']['inside_outside']['sides']
        self.assertEqual(sides['inside']['observed_races'], 0)
        self.assertEqual(sides['outside']['observed_races'], 1)
        self.assertEqual(sides['outside']['races_with_conflicting_finish'], 1)
        self.assertEqual(sides['outside']['race_finish_counts'], {})

    def test_a_verified_capture_is_a_latest_availability_bound_when_publish_time_is_absent(self):
        profile=collect(dict(event('capture','resist_makuri',outcome='failure'),published_at=None))
        self.assertEqual(profile['abilities']['resist_makuri']['observed_opportunities'],1)
        self.assertEqual(profile['publication_times_unreported'],1)


if __name__=='__main__':
    unittest.main()
