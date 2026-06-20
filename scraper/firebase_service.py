"""Compatibility shim — forwards to root firebase_service."""
import sys
import importlib
from pathlib import Path

# Remove scraper dir temporarily to force loading the root module
_scraper = str(Path(__file__).parent)
_root = str(Path(__file__).parent.parent)

# Load root firebase_service directly by spec
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "firebase_service_root",
    Path(__file__).parent.parent / "firebase_service.py"
)
_root_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root_mod)

# Re-export everything
db = _root_mod.db
get_player = _root_mod.get_player
save_player = _root_mod.save_player
save_player_v2 = _root_mod.save_player_v2
get_player_profile = _root_mod.get_player_profile
save_player_profile = _root_mod.save_player_profile
search_player_profiles = _root_mod.search_player_profiles
save_player_search_cache = _root_mod.save_player_search_cache
get_player_search_cache = _root_mod.get_player_search_cache
get_app_settings = _root_mod.get_app_settings
save_app_settings = _root_mod.save_app_settings
PLAYERS_COLLECTION = _root_mod.PLAYERS_COLLECTION
PLAYER_PROFILES_COLLECTION = _root_mod.PLAYER_PROFILES_COLLECTION
PLAYER_SEARCH_CACHE_COLLECTION = _root_mod.PLAYER_SEARCH_CACHE_COLLECTION
utc_now_iso = _root_mod.utc_now_iso
sanitize_for_firestore = _root_mod.sanitize_for_firestore
normalize_name = _root_mod.normalize_name
