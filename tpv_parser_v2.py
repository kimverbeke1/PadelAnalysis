from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from tpv_models_v2 import MatchIndexEntry, PlayerMatchRecord, TeamPairingRecord, TeamTieRecord

BASE_URL = 'https://www.tennisenpadelvlaanderen.be'
DATE_RE = re.compile(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})')
WEEK_RE = re.compile(r'(week\s+\d{1,2}/\d{4})', re.I)
SCORE_RE = re.compile(r'(\d+\s*[-:]\s*\d+(?:\s+\d+\s*[-:]\s*\d+)*)')


def clean_text(value: str) -> str:
    return ' '.join(str(value or '').split()).strip()


def absolute_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith('http'):
        return url
    return urljoin(BASE_URL, url)


def guess_competition_type(text: str, href: Optional[str]) -> str:
    t = clean_text(text).lower()
    h = (href or '').lower()
    if 'interclub' in t or 'interclub' in h or 'uitslagenblad' in t or 'uitslagenblad' in h:
        return 'interclub'
    if 'tornooi' in t or 'p100' in t or 'p200' in t or 'p300' in t or 'dagplanning' in h or 'poule-tabel' in h:
        return 'tornooi'
    if 'competitie' in t or 'competitie' in h:
        return 'interclub'
    return 'unknown'


def extract_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or '')
    return m.group(1) if m else None


def extract_week(text: str) -> Optional[str]:
    m = WEEK_RE.search(text or '')
    return clean_text(m.group(1)) if m else None


def _parse_index_candidate_blocks(soup: BeautifulSoup) -> List[Dict]:
    candidates: List[Dict] = []

    # 1) tabular rows
    for tr in soup.select('tr'):
        text = clean_text(tr.get_text(' ', strip=True))
        if not text:
            continue
        link = tr.select_one('a[href]')
        href = absolute_url(link.get('href')) if link else None
        if not href:
            continue
        ctype = guess_competition_type(text, href)
        if ctype == 'unknown':
            continue
        tds = tr.select('td')
        date_raw = clean_text(tds[0].get_text(' ', strip=True)) if tds else extract_date(text)
        candidates.append({
            'date_raw': date_raw or extract_date(text),
            'text': text,
            'href': href,
            'competition_type': ctype,
        })

    # 2) cards / accordions / list items
    selectors = ['article', '.card', '.accordion-item', '.result', '.match-row', 'li']
    for selector in selectors:
        for node in soup.select(selector):
            text = clean_text(node.get_text(' ', strip=True))
            if not text:
                continue
            link = node.select_one('a[href]')
            href = absolute_url(link.get('href')) if link else None
            if not href:
                continue
            ctype = guess_competition_type(text, href)
            if ctype == 'unknown':
                continue
            candidates.append({
                'date_raw': extract_date(text),
                'text': text,
                'href': href,
                'competition_type': ctype,
            })

    # unique by href+text
    seen = set()
    unique = []
    for c in candidates:
        key = (c['href'], c['text'])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def parse_player_results_index(html: str, player_id: str, source_url: str) -> List[MatchIndexEntry]:
    soup = BeautifulSoup(html, 'html.parser')
    entries: List[MatchIndexEntry] = []

    for c in _parse_index_candidate_blocks(soup):
        # very light series extraction heuristic
        series_name = None
        text = c['text']
        m_series = re.search(r'(P\d+\s*[-–]\s*P\d+|P\d+)', text, re.I)
        if m_series:
            series_name = clean_text(m_series.group(1))

        entries.append(MatchIndexEntry(
            player_id=str(player_id),
            date_raw=c['date_raw'],
            competition_name=text[:240],
            competition_type=c['competition_type'],
            series_name=series_name,
            detail_url=c['href'],
            source_url=source_url,
            raw_text=text,
            metadata={},
        ))
    return entries


def parse_tournament_detail(html: str, player_id: str, player_name: Optional[str], source_url: str) -> Tuple[List[PlayerMatchRecord], Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    title = clean_text(soup.title.get_text(' ', strip=True)) if soup.title else ''

    # Try to capture visible page headers
    header_candidates = [clean_text(x.get_text(' ', strip=True)) for x in soup.select('h1, h2, h3, .title, .page-title')]
    competition_name = next((x for x in header_candidates if len(x) > 3), title or 'Onbekend tornooi')

    records: List[PlayerMatchRecord] = []

    # Tournament pages often show tables or bracket/list rows. We collect row-like text blocks.
    blocks = []
    for sel in ['tr', '.match-row', '.result-row', '.poule-row', 'li', '.card']:
        for node in soup.select(sel):
            text = clean_text(node.get_text(' ', strip=True))
            if len(text) >= 8:
                blocks.append(text)

    seen = set()
    for text in blocks:
        if text in seen:
            continue
        seen.add(text)

        date = extract_date(text)
        week = extract_week(text)
        score_match = SCORE_RE.search(text)
        score = clean_text(score_match.group(1)) if score_match else None
        result = 'Winst' if re.search(r'\bW\b|winst|gewonnen', text, re.I) else 'Verlies' if re.search(r'\bV\b|verlies|verloren', text, re.I) else None

        # Basic heuristic: if the player name appears, split around it
        partner = None
        opponent_1 = None
        opponent_2 = None
        if player_name and player_name.lower() in text.lower():
            # keep heuristic shallow; detail refinement comes later
            pass

        if date or score or result:
            records.append(PlayerMatchRecord(
                player_id=str(player_id),
                match_date=date,
                match_week=week,
                competition_type='tornooi',
                competition_name=competition_name,
                series_name=None,
                phase_name='tornooi',
                team_name=None,
                opponent_team_name=None,
                partner=partner,
                opponent_1=opponent_1,
                opponent_2=opponent_2,
                score=score,
                result=result,
                source_url=source_url,
                raw_text=text,
                metadata={},
            ))

    debug = {
        'detail_type': 'tornooi',
        'competition_name': competition_name,
        'candidate_blocks': len(blocks),
        'parsed_matches': len(records),
    }
    return records, debug


def parse_interclub_detail(html: str, player_id: str, source_url: str) -> Tuple[List[TeamTieRecord], List[TeamPairingRecord], Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    title = clean_text(soup.title.get_text(' ', strip=True)) if soup.title else 'Interclub'

    header_texts = [clean_text(x.get_text(' ', strip=True)) for x in soup.select('h1, h2, h3, .title, .page-title')]
    competition_name = next((x for x in header_texts if len(x) > 3), title)

    page_text = clean_text(soup.get_text(' ', strip=True))
    tie_date = extract_date(page_text)

    # crude team split heuristics
    home_team = None
    away_team = None
    total_score = None
    line_match = re.search(r'(\d+\s*[-:]\s*\d+)', page_text)
    if line_match:
        total_score = clean_text(line_match.group(1))

    tie_id = re.sub(r'\W+', '_', f'{competition_name}_{tie_date or "no_date"}')[:120]
    ties = [TeamTieRecord(
        tie_id=tie_id,
        competition_name=competition_name,
        series_name=None,
        tie_date=tie_date,
        home_team=home_team,
        away_team=away_team,
        total_score=total_score,
        source_url=source_url,
        raw_text=page_text[:1500],
        metadata={},
    )]

    pairings: List[TeamPairingRecord] = []

    blocks = []
    for sel in ['tr', '.match-row', '.line-row', 'li', '.card']:
        for node in soup.select(sel):
            text = clean_text(node.get_text(' ', strip=True))
            if len(text) >= 8:
                blocks.append(text)

    seen = set()
    line_idx = 0
    for text in blocks:
        if text in seen:
            continue
        seen.add(text)
        score_match = SCORE_RE.search(text)
        score = clean_text(score_match.group(1)) if score_match else None
        if not score:
            continue
        line_idx += 1
        result = 'Winst' if re.search(r'\bW\b|winst|gewonnen', text, re.I) else 'Verlies' if re.search(r'\bV\b|verlies|verloren', text, re.I) else None
        pairings.append(TeamPairingRecord(
            tie_id=tie_id,
            team_name=None,
            line_number=str(line_idx),
            player_1=None,
            player_2=None,
            opponent_1=None,
            opponent_2=None,
            score=score,
            result=result,
            source_url=source_url,
            raw_text=text,
            metadata={},
        ))

    debug = {
        'detail_type': 'interclub',
        'competition_name': competition_name,
        'candidate_blocks': len(blocks),
        'parsed_pairings': len(pairings),
    }
    return ties, pairings, debug
