# PDF Source Files - User Guide

## Current Status

The infrastructure for PDF source files is fully set up:
- ✅ Directory created: `Data/_bvl_pdfs/`
- ✅ Documentation: `README.md` in the directory
- ✅ Git configuration: PDFs are excluded from version control (`.gitignore`)
- ✅ Verification script: `verify_pdf_sources.py` to check PDF presence

## Important: PDFs Are Not Committed to Git

**By design**, PDF files placed in `Data/_bvl_pdfs/` are **NOT** tracked in the git repository. This is intentional because:
- PDF files are large binary files (typically several MB each)
- They should be obtained from official BVL sources
- Git is optimized for source code, not large binaries
- The extracted data (`zusatzstoffe.json`) is version controlled instead

## How PDF Files Work in LAVES

### 1. Local Development / Testing

If you're working locally and have PDF files:

```bash
# Place PDFs directly in the directory
cp /path/to/your/pdfs/*.pdf Data/_bvl_pdfs/

# Verify they're present
python Data/verify_pdf_sources.py

# Process them to update the database
python Data/laves_updater_v6.py
```

The PDFs will be ignored by git (won't show up in `git status`), which is correct.

### 2. CI/CD and Testing Environments

In automated environments (like GitHub Actions), PDF files are **not available** because:
- They're not in the repository
- They're typically not needed for testing (we test with the extracted `zusatzstoffe.json`)

### 3. Distribution

For end users who need to process PDFs:
- Users should obtain PDFs from official BVL sources
- Place them in `Data/_bvl_pdfs/` directory
- Run the updater script to process them

## E770 Source File

The E770 record references:
- **Filename**: `70524__futtermittel_zusatzstoffe_kokzidiostatika_histomonostatika.pdf`
- **Page**: 14
- **Content**: Kokzidiostatika and Histomonostatika additives

### To Verify E770 Source:

```bash
# Check if the PDF is present
ls -lh Data/_bvl_pdfs/70524__futtermittel_zusatzstoffe_kokzidiostatika_histomonostatika.pdf

# Run verification
python Data/verify_pdf_sources.py

# If PDF is present and you want to re-extract data
cd Data
python laves_updater_v6.py
```

## Complete Workflow

### Initial Setup (Already Done)
1. ✅ Create `Data/_bvl_pdfs/` directory
2. ✅ Configure `.gitignore` to exclude PDFs
3. ✅ Add documentation

### For Processing PDFs (User Action Required)

1. **Obtain PDFs** from official BVL sources
2. **Place PDFs** in `Data/_bvl_pdfs/` directory
3. **Verify** with: `python Data/verify_pdf_sources.py`
4. **Process** with: `python Data/laves_updater_v6.py`

### What Gets Committed to Git

- ✅ Directory structure (`Data/_bvl_pdfs/`)
- ✅ Documentation files (`.gitkeep`, `README.md`)
- ✅ Extracted database (`zusatzstoffe.json`)
- ✅ Processing scripts (`laves_updater_v6.py`, `verify_pdf_sources.py`)
- ❌ PDF files themselves (by design)

## Troubleshooting

### "PDFs not found" when running verification

This is **expected** if:
- You're in a CI/CD environment
- You haven't placed PDFs in the directory yet
- You're working with a fresh clone of the repository

**Solution**: Place the PDF files in `Data/_bvl_pdfs/` on your local machine.

### PDFs don't show up in `git status`

This is **correct behavior**. The `.gitignore` file excludes them intentionally.

### Need to share PDFs with team

**Do not** commit PDFs to git. Instead:
- Share them via file sharing service
- Document the official BVL source URLs
- Or use Git LFS if your repository is configured for it (currently it is not)

## Summary

The PDF infrastructure is ready and working as designed. The system is set up so that:
- PDF files remain local (not in version control)
- Extracted data is version controlled (`zusatzstoffe.json`)
- Processing can be repeated when needed by users who have the PDFs

If you have PDFs on your local machine and want to process them, place them in `Data/_bvl_pdfs/` and run the updater script.
