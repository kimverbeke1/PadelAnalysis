import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, firestore


# =========================================================
# CONFIG
# =========================================================

SERVICE_ACCOUNT_FILE = "firebase-key.json"
PLAYERS_COLLECTION = "players"
PLAYER_SEARCH_CACHE_COLLECTION = "player_search_cache"


# =========================================================
# FIREBASE INIT
# =========================================================

def _init_firebase():
    if not firebase_admin._apps:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            raise FileNotFoundError(
                f"Firebase key bestand niet gevonden: {SERVICE_ACCOUNT_FILE}"
            )

        cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
        firebase_admin.initialize_app(cred)

    return firestore.client()


db = _init_firebase()


# =========================================================
# HELPERS
# =========================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def convert_firestore_values(obj: Any):
    if isinstance(obj, dict):
        return {k: convert_firestore_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_firestore_values(v) for v in obj]
    elif hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    else:
        return obj


def sanitize_for_firestore(obj: Any):
    if isinstance(obj, dict):
        return {str(k): sanitize_for_firestore(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_firestore(v) for v in obj]
    elif isinstance(obj, tuple):
        return [sanitize_for_firestore(v) for v in obj]
    elif hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    else:
        return obj


def build_minimal_defaults(player_id: str, player_data: dict) -> dict:
    if not isinstance(player_data, dict):
        raise ValueError("player_data moet een dictionary zijn")

    data = dict(player_data)
    data.setdefault("player_id", str(player_id))
    data.setdefault("last_updated", utc_now_iso())
    data.setdefault("stats", {})
    data.setdefault("raw_data", {})

    raw = dict(data.get("raw_data", {}))
    raw.setdefault("player_id", str(player_id))
    raw.setdefault("timestamp", utc_now_iso())
    raw.setdefault("matches", [])
    if isinstance(raw.get("matches", []), list):
        raw.setdefault("matches_count", len(raw.get("matches", [])))
    else:
        raw.setdefault("matches_count", 0)
    data["raw_data"] = raw

    stats = dict(data.get("stats", {}))
    stats.setdefault("matches", raw.get("matches_count", 0))
    stats.setdefault("wins", 0)
    stats.setdefault("losses", 0)
    stats.setdefault("unknown_results", 0)
    stats.setdefault("winrate", 0.0)
    data["stats"] = stats

    return data


def normalize_search_key(name_query: str, club: Optional[str] = None, sport: str = "Padel") -> str:
    name_query = (name_query or "").strip().lower()
    club = (club or "").strip().lower()
    sport = (sport or "").strip().lower()
    return f"{sport}|{name_query}|{club}"


# =========================================================
# PLAYERS CRUD
# =========================================================

def save_player(player_id: str, player_data: dict):
    prepared = build_minimal_defaults(player_id, player_data)
    clean_doc = sanitize_for_firestore(prepared)
    db.collection(PLAYERS_COLLECTION).document(str(player_id)).set(clean_doc, merge=False)
    return clean_doc


def get_player(player_id: str, converted: bool = True):
    doc = db.collection(PLAYERS_COLLECTION).document(str(player_id)).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return convert_firestore_values(data) if converted else data


def player_exists(player_id: str) -> bool:
    return db.collection(PLAYERS_COLLECTION).document(str(player_id)).get().exists


def delete_player(player_id: str):
    db.collection(PLAYERS_COLLECTION).document(str(player_id)).delete()
    return True


def reset_player(player_id: str):
    delete_player(player_id)
    print(f"Player {player_id} verwijderd uit Firestore.")


def get_all_players(converted: bool = True):
    docs = db.collection(PLAYERS_COLLECTION).stream()
    result = []
    for doc in docs:
        data = doc.to_dict()
        result.append(convert_firestore_values(data) if converted else data)
    return result


# =========================================================
# PLAYER SEARCH CACHE
# =========================================================

def save_player_search_cache(name_query: str, club: Optional[str], sport: str, candidates: List[Dict[str, Any]]):
    key = normalize_search_key(name_query, club=club, sport=sport)
    doc = {
        "search_key": key,
        "name_query": name_query,
        "club": club,
        "sport": sport,
        "last_updated": utc_now_iso(),
        "candidate_count": len(candidates),
        "candidates": sanitize_for_firestore(candidates),
    }
    db.collection(PLAYER_SEARCH_CACHE_COLLECTION).document(key).set(doc, merge=False)
    return doc


def get_player_search_cache(name_query: str, club: Optional[str] = None, sport: str = "Padel", converted: bool = True):
    key = normalize_search_key(name_query, club=club, sport=sport)
    doc = db.collection(PLAYER_SEARCH_CACHE_COLLECTION).document(key).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return convert_firestore_values(data) if converted else data


# =========================================================
# DEBUG
# =========================================================

def print_player(player_id: str):
    player = get_player(player_id, converted=True)
    if not player:
        print(f"Geen speler gevonden met id {player_id}")
        return
    print("=== PLAYER DOCUMENT ===")
    print(player)
