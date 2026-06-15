"""
Scraper package

Belangrijk voor cloud/deploy:
- GEEN imports met side effects hier.
- Anders kan een simpele import van scraper.firebase_service eerst __init__.py laden,
  wat op zijn beurt scraper.py zou importeren.
"""

__all__ = []
