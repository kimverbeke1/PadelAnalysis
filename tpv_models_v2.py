from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class MatchIndexEntry:
    player_id: str
    date_raw: Optional[str]
    competition_name: str
    competition_type: str
    series_name: Optional[str]
    detail_url: Optional[str]
    source_url: str
    raw_text: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PlayerMatchRecord:
    player_id: str
    match_date: Optional[str]
    match_week: Optional[str]
    competition_type: str
    competition_name: str
    series_name: Optional[str]
    phase_name: Optional[str]
    team_name: Optional[str]
    opponent_team_name: Optional[str]
    partner: Optional[str]
    opponent_1: Optional[str]
    opponent_2: Optional[str]
    score: Optional[str]
    result: Optional[str]
    source_url: str
    raw_text: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TeamTieRecord:
    tie_id: str
    competition_name: Optional[str]
    series_name: Optional[str]
    tie_date: Optional[str]
    home_team: Optional[str]
    away_team: Optional[str]
    total_score: Optional[str]
    source_url: str
    raw_text: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TeamPairingRecord:
    tie_id: str
    team_name: Optional[str]
    line_number: Optional[str]
    player_1: Optional[str]
    player_2: Optional[str]
    opponent_1: Optional[str]
    opponent_2: Optional[str]
    score: Optional[str]
    result: Optional[str]
    source_url: str
    raw_text: str
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ScrapeBundle:
    player_id: str
    player_name: Optional[str]
    source_index_url: str
    index_entries: List[MatchIndexEntry] = field(default_factory=list)
    player_matches: List[PlayerMatchRecord] = field(default_factory=list)
    team_ties: List[TeamTieRecord] = field(default_factory=list)
    team_pairings: List[TeamPairingRecord] = field(default_factory=list)
    debug: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'player_id': self.player_id,
            'player_name': self.player_name,
            'source_index_url': self.source_index_url,
            'index_entries': [x.to_dict() for x in self.index_entries],
            'player_matches': [x.to_dict() for x in self.player_matches],
            'team_ties': [x.to_dict() for x in self.team_ties],
            'team_pairings': [x.to_dict() for x in self.team_pairings],
            'debug': self.debug,
        }
