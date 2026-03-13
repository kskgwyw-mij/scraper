# Willhaben Scraper

Webanwendung zum Durchsuchen von willhaben.at mit Preisprognose.

## Schnellstart

```bash
pip install -r requirements.txt
python run.py
```

Dann im Browser öffnen: http://localhost:5000

## Funktionen
- Suche nach beliebigen Produkten auf willhaben.at
- Anzeige mit Bildern, Preis und Standort
- Automatische Preisprognose mit Perzentilen
- Katalog aller gespeicherten Suchen mit Filter & Sortierung

## Konfiguration
Umgebungsvariablen (optional):
- `FLASK_ENV` – `development` (Standard) oder `production`
- `SECRET_KEY` – Sicherheitsschlüssel für Sessions
- `DATABASE_URL` – SQLite-Pfad oder PostgreSQL-URL
