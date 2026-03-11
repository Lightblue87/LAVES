# BVL PDF Source Files

This directory contains the original PDF source files from which additive data is extracted.

## Purpose

The PDF files in this directory are processed by `laves_updater_v6.py` to generate and update the `zusatzstoffe.json` database. Each record in the JSON database includes:
- `source_file`: The filename of the PDF
- `source_page`: The page number where the record was found

## Directory Structure

Place PDF files directly in this directory:
```
Data/_bvl_pdfs/
├── 70524__futtermittel_zusatzstoffe_kokzidiostatika_histomonostatika.pdf
├── other_source_file.pdf
└── ...
```

## Supported PDF Formats

The updater automatically detects and processes multiple regulatory document formats:

- **Schema A**: VO 1831/2003 Main lists (amino acids, vitamins, flavorings)
- **Schema A1**: VO 1831/2003 Individual approvals with analysis methods
- **Schema B/B2**: RL 70/524 Nutrients (amino acids, vitamins)
- **Schema C**: RL 70/524 Technology (antioxidants, binders, emulsifiers)
- **Schema S**: Silage additives

## Processing PDFs

To process PDF files and update the database:

```bash
cd Data
python laves_updater_v6.py
```

The updater will:
1. Scan all `.pdf` files in this directory
2. Auto-detect the document schema
3. Extract additive records with text extraction and column detection
4. Categorize species using keyword matching
5. Merge records and output to `zusatzstoffe.json`

## E770 Source

The E770 record (Maduramicin for Truthühner) is extracted from:
- **File**: `70524__futtermittel_zusatzstoffe_kokzidiostatika_histomonostatika.pdf`
- **Page**: 14
- **Schema**: C (RL 70/524 Technology format)
- **Limits**: 5-5 mg/kg for Truthühner

## Notes

- PDF files are NOT committed to the repository by default (see `.gitignore`)
- Only the extracted JSON database (`zusatzstoffe.json`) is version controlled
- Source PDFs should be obtained from official BVL (Bundesamt für Verbraucherschutz und Lebensmittelsicherheit) sources
- The processing relies on `pdfminer.six` for text extraction with layout analysis
