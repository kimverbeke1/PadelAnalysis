from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from tpv_firebase_adapter_v2 import save_bundle_to_firebase
from tpv_models_v2 import ScrapeBundle
from tpv_parser_v2 import (
    BASE_URL,
    parse_interclub_detail,
    parse_player_results_index,
    parse_tournament_detail,
)

DEBUG_DIR = Path('debug_output_v2')
DEBUG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(DEBUG_DIR / 'tpv_v2.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def save_debug_file(name: str, content: str):
    path = DEBUG_DIR / name
    path.write_text(content, encoding='utf-8')
    return str(path)


def dismiss_cookie_banner_if_present(page):
    for label in ['Alle cookies accepteren', 'Cookies accepteren', 'Ik ga akkoord', 'Accepteren']:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(1000)
                log(f'Cookie banner gesloten via: {label}')
                return True
        except Exception:
            continue
    return False


def detect_robot_page(page) -> bool:
    try:
        body = page.locator('body').inner_text(timeout=3000).lower()
        return ('ben jij een robot?' in body) or ('verhoogd aantal geautomatiseerde toegangspogingen' in body)
    except Exception:
        return False


def infer_player_name_from_page(page) -> Optional[str]:
    for sel in ['h1', 'h2', '.page-title', '.title']:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                text = ' '.join(loc.first.inner_text().split()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def _click_or_goto(page, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    full = href if href.startswith('http') else urljoin(BASE_URL, href)
    page.goto(full, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(2500)
    dismiss_cookie_banner_if_present(page)
    return full


def scrape_player_index(player_id: str, headless: bool = True) -> Dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            url = f'{BASE_URL}/dashboard/resultaten?userId={player_id}&tab=padel'
            log(f'Open indexpagina: {url}')
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_cookie_banner_if_present(page)

            if detect_robot_page(page):
                raise RuntimeError('Robot-check gedetecteerd op indexpagina')

            html = page.content()
            save_debug_file(f'index_{player_id}.html', html)
            player_name = infer_player_name_from_page(page)
            entries = parse_player_results_index(html, player_id=player_id, source_url=page.url)
            log(f'Index entries gevonden: {len(entries)}')
            return {
                'player_id': str(player_id),
                'player_name': player_name,
                'source_index_url': page.url,
                'index_entries': [x.to_dict() for x in entries],
                'debug': {
                    'index_html_file': str(DEBUG_DIR / f'index_{player_id}.html'),
                    'index_entries_count': len(entries),
                }
            }
        finally:
            context.close()
            browser.close()


def scrape_player_v2(
    player_id: str,
    headless: bool = True,
    follow_first_tournament: bool = True,
    follow_first_interclub: bool = True,
    save_to_firebase: bool = False,
) -> Dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            index_url = f'{BASE_URL}/dashboard/resultaten?userId={player_id}&tab=padel'
            log(f'Open indexpagina: {index_url}')
            page.goto(index_url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_cookie_banner_if_present(page)
            if detect_robot_page(page):
                raise RuntimeError('Robot-check gedetecteerd op indexpagina')

            index_html = page.content()
            save_debug_file(f'index_{player_id}.html', index_html)
            player_name = infer_player_name_from_page(page)
            index_entries = parse_player_results_index(index_html, player_id=player_id, source_url=page.url)
            log(f'Index entries gevonden: {len(index_entries)}')

            bundle = ScrapeBundle(
                player_id=str(player_id),
                player_name=player_name,
                source_index_url=page.url,
                index_entries=index_entries,
                debug={
                    'index_entries_count': len(index_entries),
                    'detail_debug': [],
                },
            )

            # Follow first tournament and first interclub entry only (Phase 1 proof of concept)
            first_tournament = next((e for e in index_entries if e.competition_type == 'tornooi' and e.detail_url), None)
            first_interclub = next((e for e in index_entries if e.competition_type == 'interclub' and e.detail_url), None)

            if follow_first_tournament and first_tournament:
                log(f'Volg eerste tornooilink: {first_tournament.detail_url}')
                detail_url = _click_or_goto(page, first_tournament.detail_url)
                if detail_url:
                    detail_html = page.content()
                    save_debug_file(f'tournament_{player_id}.html', detail_html)
                    player_matches, debug = parse_tournament_detail(detail_html, player_id=str(player_id), player_name=player_name, source_url=detail_url)
                    bundle.player_matches.extend(player_matches)
                    bundle.debug['detail_debug'].append(debug)
                    log(f'Tornooimatches geparsed: {len(player_matches)}')

            if follow_first_interclub and first_interclub:
                log(f'Volg eerste interclublink: {first_interclub.detail_url}')
                detail_url = _click_or_goto(page, first_interclub.detail_url)
                if detail_url:
                    detail_html = page.content()
                    save_debug_file(f'interclub_{player_id}.html', detail_html)
                    ties, pairings, debug = parse_interclub_detail(detail_html, player_id=str(player_id), source_url=detail_url)
                    bundle.team_ties.extend(ties)
                    bundle.team_pairings.extend(pairings)
                    bundle.debug['detail_debug'].append(debug)
                    log(f'Interclub ties geparsed: {len(ties)} | pairings: {len(pairings)}')

            bundle_dict = bundle.to_dict()
            save_debug_file(f'bundle_{player_id}.json', json.dumps(bundle_dict, ensure_ascii=False, indent=2))

            if save_to_firebase:
                ok = save_bundle_to_firebase(bundle_dict, display_name=player_name)
                bundle_dict['debug']['saved_to_firebase'] = ok
                log(f'Saved to firebase: {ok}')

            return bundle_dict
        finally:
            context.close()
            browser.close()
