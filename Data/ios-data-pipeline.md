# FeedLabelCheck iOS Data Pipeline

The iOS app should not parse BVL PDFs directly. PDF extraction depends on
`pdfminer.six`, source-specific column calibration, and operational retry logic.
Keep that work in a headless Python pipeline and ship the generated
`zusatzstoffe.json` to the app.

## Local Update

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the full update:

```bash
python3 Data/bvl_update_pipeline.py
```

Parse existing PDFs only:

```bash
python3 Data/bvl_update_pipeline.py --no-download
```

By default, the pipeline refuses to rebuild `Data/zusatzstoffe.json` when the
local PDF directory is incomplete compared with the current database's
`source_file` references. For parser experiments with a small PDF subset, use:

```bash
python3 Data/bvl_update_pipeline.py --no-download --allow-partial
```

After a successful update, copy the generated database into the iOS bundle:

```bash
cp Data/zusatzstoffe.json FeedLabelCheck/FeedLabelCheck/Resources/zusatzstoffe.json
```

Then rebuild:

```bash
xcodebuild \
  -project FeedLabelCheck/FeedLabelCheck.xcodeproj \
  -scheme FeedLabelCheck \
  -sdk iphonesimulator \
  -configuration Debug \
  -derivedDataPath /private/tmp/FeedLabelCheckDerivedData \
  CODE_SIGNING_ALLOWED=NO \
  build
```

## Architecture

- `Data/bvl_update_pipeline.py`: Qt-free download and orchestration CLI.
- `Data/laves_updater_v6.py`: PDF parsing and JSON generation.
- `Data/_bvl_pdfs/`: source PDFs downloaded from BVL.
- `Data/zusatzstoffe.json`: canonical generated database.
- `FeedLabelCheck/FeedLabelCheck/Resources/zusatzstoffe.json`: iOS app bundle copy.

For production, run this pipeline as a release step or scheduled job, review
the generated JSON diff, then ship the updated JSON with the iOS app.
