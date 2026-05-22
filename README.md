# FeedLabel Check

iOS app and data pipeline for checking pet-food label compliance with EU Regulation (EC) No 767/2009.

## Overview

**FeedLabel Check** lets you scan a feed-ingredient label with your iPhone, runs offline OCR, and checks the declaration against the mandatory labeling requirements of EU Regulation (EC) No 767/2009.
Additive declarations (e.g. Taurine 1,000 mg/kg) are matched against the official EU register of authorised feed additives (EC No 1831/2003).

Everything runs fully offline — no data leaves the device.

## Repository layout

```
FeedLabelCheck/          iOS Xcode project
  FeedLabelCheck/        Swift app sources
  FeedLabelCheckTests/   XCTest unit tests
Data/                    BVL PDF pipeline (Python)
scripts/                 SQLite and manifest build scripts
tests/                   Python unit tests (pytest)
dist/                    Generated data artefacts (gitignored in prod)
```

## Getting started

### iOS app

Open `FeedLabelCheck/FeedLabelCheck.xcodeproj` in Xcode 16+, select an iPhone 16 simulator, and run.

The app ships with bundled baseline data (`labeling.sqlite`, `zusatzstoffe.json`).
An in-app update button downloads fresh data from the **FeedLabelCheck-Data** companion repository.

### Data pipeline (Python)

```bash
python3 -m pip install -r requirements-pipeline.txt
python3 Data/bvl_update_pipeline.py
python3 scripts/build_sqlite_db.py --json Data/zusatzstoffe.json --out dist/feedlabelcheck.sqlite
python3 scripts/build_labeling_db.py --out dist/labeling.sqlite
python3 scripts/build_data_manifest.py --out dist/manifest.json
```

### Tests

```bash
python3 -m pip install -r requirements.txt
pytest tests/
```

## Data sources

| Source | Description |
|--------|-------------|
| BVL (Bundesamt für Verbraucherschutz und Lebensmittelsicherheit) | EU authorised feed additive lists (PDFs) |
| VO (EG) Nr. 767/2009 | EU labeling regulation for feed |
| VO (EG) Nr. 1831/2003 | EU register of authorised feed additives |

## Licence

See `LICENSE` (if present). All regulatory source texts are public EU law.
