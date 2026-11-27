"""Exercise the aggregate-only dashboard in the existing runner's browser."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil


def check(html, output):
    from playwright.sync_api import sync_playwright
    html, output = Path(html).resolve(), Path(output).resolve()
    if not html.is_file() or output.exists():
        raise ValueError('EXISTING_REPORT_AND_NEW_OUTPUT_REQUIRED')
    browser_path = os.environ.get('RACE_AI_TEST_CHROMIUM') or shutil.which('google-chrome') or shutil.which('chromium')
    if not browser_path:
        raise ValueError('INSTALLED_BROWSER_REQUIRED')
    output.mkdir(parents=True, mode=0o700)
    checks = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=browser_path, headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'])
        version = browser.version
        for name, width, height in (('desktop', 1440, 1080), ('mobile', 390, 844)):
            context = browser.new_context(viewport={'width': width, 'height': height})
            page = context.new_page(); errors, external = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(request):
                if request.request.url.startswith(('http://', 'https://')):
                    external.append(request.request.url); request.abort()
                else:
                    request.continue_()
            page.route('**/*', route)
            page.goto(html.as_uri(), wait_until='load')
            page.wait_for_function("document.getElementById('hero-hit4').textContent.endsWith('%')")
            data = page.locator('#report-data').text_content(); report = json.loads(data)
            assert report['mode'] == 'aggregate'
            assert page.locator('#hero-hit4').text_content() == f"{report['main']['trifecta']['4']['all_target_rate']*100:.2f}%"
            assert page.locator('#feature-count').text_content() == f"{report['feature_count']:,}"
            assert page.locator('#ablation-body tr').count() == max(1, len(report['ablations']))
            assert page.locator('#entrants article').count() == 3
            for dimension in ('field_size', 'class', 'venue'):
                page.select_option('#dimension', dimension)
                for key in report['subgroups'][dimension]:
                    page.select_option('#group', key)
                    expected = report['subgroups'][dimension][key]['trifecta']['4']['all_target_rate']
                    assert page.locator('#hero-hit4').text_content() == ('未集計' if expected is None else f'{expected*100:.2f}%')
            page.select_option('#dimension', 'all')
            for policy in report['confidence']:
                page.select_option('#confidence-policy', policy['id'])
                assert page.locator('#confidence-cells .confidence-card').count() == 5
                for label, card_class in (('HOT', 'hot'), ('HIGH', 'high'), ('MEDIUM', 'medium'), ('LOW', 'low'), ('HOLD', 'hold')):
                    expected = policy['labels'][label]['n']
                    actual = page.locator('#confidence-cells .' + card_class + ' .amount').text_content()
                    assert actual == ('未集計' if expected is None else f'{expected:,}件')
            if report['confidence']:
                wanted = 'trifecta_4' if any(p['id'] == 'trifecta_4' for p in report['confidence']) else report['confidence'][0]['id']
                page.select_option('#confidence-policy', wanted)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'PAGE_HORIZONTAL_OVERFLOW'
            assert not errors, errors
            assert not external, 'UNEXPECTED_EXTERNAL_REQUEST'
            screenshot = output / (name + '.png')
            page.screenshot(path=str(screenshot), full_page=True)
            checks.append({'viewport': name, 'width': width, 'height': height,
                'groups_checked': sum(len(v) for v in report['subgroups'].values()),
                'confidence_policies_checked': len(report['confidence']),
                'candidate_rows': len(report['ablations']), 'script_errors': 0, 'external_requests': 0,
                'screenshot_sha256': sha256(screenshot.read_bytes()).hexdigest()})
            context.close()
        browser.close()
    receipt = {'schema': 'dt-r1-browser-check-v1', 'html_sha256': sha256(html.read_bytes()).hexdigest(),
               'model_sha256': report['model_sha256'], 'browser_version': version, 'checks': checks,
               'scope': 'Aggregate dashboard rendering and controls, not forecast quality'}
    (output / 'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).parent / 'evidence' / '20261128-completion' / 'bundle' / 'dashboard.html'
    if not default.exists():
        default = Path(__file__).parent / 'evidence' / '20261128' / 'dashboard.html'
    parser.add_argument('--html', type=Path, default=default)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.html, args.output_dir), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
