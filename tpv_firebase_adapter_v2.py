from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


try:
    from firebase_service import get_player, save_player, save_player_profile  # type: ignore
except Exception:
    get_player = None
    save_player = None
    save_player_profile = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def firebase_available() -> bool:
    return callable(save_player)


def build_legacy_player_document(bundle_dict: Dict[str, Any]) -> Dict[str, Any]:
    player_matches = bundle_dict.get('player_matches', [])

    wins = sum(1 for m in player_matches if (m.get('result') or '').lower().startswith('w'))
    losses = sum(1 for m in player_matches if (m.get('result') or '').lower().startswith('v'))
    unknown = len(player_matches) - wins - losses
    known = wins + losses
    winrate = round((wins / known) * 100, 2) if known else 0.0

    legacy_matches = []
    for m in player_matches:
        legacy_matches.append({
            'period': m.get('match_week') or m.get('match_date') or m.get('competition_name'),
            'match_date': m.get('match_date'),
            'match_week': m.get('match_week'),
            'raw_text': m.get('raw_text'),
            'partner_name': m.get('partner'),
            'opponent_1_name': m.get('opponent_1'),
            'opponent_2_name': m.get('opponent_2'),
            'ranking_player_or_team': None,
            'ranking_opponents': None,
            'round_text': m.get('phase_name') or m.get('series_name'),
            'result_text': m.get('result'),
            'score': m.get('score'),
            'won': True if (m.get('result') or '').lower().startswith('w') else False if (m.get('result') or '').lower().startswith('v') else None,
            'competition_name': m.get('competition_name'),
            'competition_type': m.get('competition_type'),
            'series_name': m.get('series_name'),
            'team_name': m.get('team_name'),
            'opponent_team_name': m.get('opponent_team_name'),
            'source_url': m.get('source_url'),
        })

    return {
        'player_id': bundle_dict.get('player_id'),
        'last_updated': utc_now_iso(),
        'stats': {
            'matches': len(player_matches),
            'wins': wins,
            'losses': losses,
            'unknown_results': unknown,
            'winrate': winrate,
        },
        'raw_data': {
            'schema_version': 'tpv_index_v2',
            'matches_count': len(player_matches),
            'matches': legacy_matches,
            'index_entries': bundle_dict.get('index_entries', []),
            'team_ties': bundle_dict.get('team_ties', []),
            'team_pairings': bundle_dict.get('team_pairings', []),
            'failed_periods': [],
            'failed_periods_last_run': [],
            'failed_periods_open': [],
            'empty_periods': [],
            'periods_processed': [],
            'source_index_url': bundle_dict.get('source_index_url'),
            'debug': bundle_dict.get('debug', {}),
        },
    }


def save_bundle_to_firebase(bundle_dict: Dict[str, Any], display_name: Optional[str] = None, club: Optional[str] = None) -> bool:
    if not callable(save_player):
        return False

    player_id = str(bundle_dict.get('player_id'))
    doc = build_legacy_player_document(bundle_dict)
    save_player(player_id, doc)

    if callable(save_player_profile):
        profile_name = display_name or bundle_dict.get('player_name') or player_id
        save_player_profile(player_id=player_id, display_name=profile_name, club=club)

    return True
