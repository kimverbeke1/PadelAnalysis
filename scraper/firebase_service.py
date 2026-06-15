"""
Compatibiliteitslaag voor oude imports zoals:
    from scraper.firebase_service import get_player

Deze file proxyt bewust naar de ROOT firebase_service.py.
"""

from firebase_service import *  # noqa: F401,F403
