"""Synthetic browser responses; rejected playback must never be reloaded."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from race_ai import boat_screen_record_research as screen


class ScreenSourceRejectionTests(unittest.TestCase):
    def exercise(self, status, host, resource='xhr'):
        now = datetime.now(timezone.utc)
        day = now.astimezone(screen.JST).strftime('%Y%m%d')
        source = dict(schema='RACE_AI_BOAT_SCREEN_SOURCE_V1', race_id=day+'-01-01',
            cutoff_at=(now+timedelta(minutes=20)).isoformat(),
            page_url='https://race.boatcast.jp/replay?jo=01&md=T',
            mode='REPLAY', play_selector=None)
        callbacks = {}
        page = SimpleNamespace(video=None, url=source['page_url'])
        page.on = Mock(side_effect=lambda event, callback: callbacks.setdefault(event, callback))
        response = SimpleNamespace(status=status, url='https://'+host+'/private-media-reference',
                                   request=SimpleNamespace(resource_type=resource))

        async def goto(*args, **kwargs):
            callback = callbacks.get('response')
            if callback:
                callback(response)
            return SimpleNamespace(status=200)

        page.goto = AsyncMock(side_effect=goto)
        context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
        identity = AsyncMock(return_value=dict(race_id=source['race_id'], observed_from_page=True))
        with patch.object(screen, '_visible_state', new=AsyncMock(side_effect=RuntimeError('no playback'))) as visible:
            result = asyncio.run(screen.record_screen(browser, source, now=now, aes_key=b'k'*32,
                timeout_seconds=2, verify_page_identity=identity))
        page.goto.assert_awaited_once()
        context.close.assert_awaited_once()
        self.assertNotIn('private-media-reference', str(result))
        self.assertNotIn('envelope', result)
        self.assertFalse(result['model_eligible'])
        self.assertTrue(result['source_fetch_performed'])
        return result, visible

    def test_official_playback_rejection_has_exact_safe_status_and_stops_before_polling(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                result, visible = self.exercise(status, 'playback.api.streaks.jp')
                self.assertEqual(result['status'], f'HOLD_SCREEN_PROVIDER_HTTP_{status}')
                self.assertTrue(result['source_fetch_performed'])
                self.assertEqual(result['http_status'], status)
                self.assertEqual(result['provider_requests_retried'], 0)
                visible.assert_not_awaited()

    def test_unrelated_ad_font_and_analytics_denials_do_not_become_video_denials(self):
        for host, resource in (('analytics.example.org', 'xhr'),
                               ('front.player.boatrace-cdn.jp', 'font'),
                               ('not-playback.api.streaks.jp', 'fetch')):
            with self.subTest(host=host, resource=resource):
                result, visible = self.exercise(403, host, resource)
                self.assertEqual(result['status'], 'HOLD_SCREEN_PLAYBACK_UNAVAILABLE')
                visible.assert_awaited_once()

    def test_success_is_not_synthesized_from_metadata_response(self):
        result, visible = self.exercise(200, 'playback.api.streaks.jp')
        self.assertEqual(result['status'], 'HOLD_SCREEN_PLAYBACK_UNAVAILABLE')
        visible.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
