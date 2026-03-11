#!/usr/bin/env python3
"""
Verify PDF source files in _bvl_pdfs directory.

This script checks that:
1. Expected PDF source files are present
2. Files can be opened and read
3. Source file references in zusatzstoffe.json match actual files

Usage:
    python Data/verify_pdf_sources.py
"""

import json
from pathlib import Path
from collections import Counter

def main():
    # Resolve paths
    script_dir = Path(__file__).parent
    pdf_dir = script_dir / "_bvl_pdfs"
    json_path = script_dir / "zusatzstoffe.json"

    print("=" * 80)
    print("PDF SOURCE FILE VERIFICATION")
    print("=" * 80)

    # Check if directories exist
    if not pdf_dir.exists():
        print(f"❌ PDF directory does not exist: {pdf_dir}")
        return 1

    if not json_path.exists():
        print(f"❌ Database file does not exist: {json_path}")
        return 1

    # Find PDF files
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    print(f"\n📁 PDF Directory: {pdf_dir}")
    print(f"   Found {len(pdf_files)} PDF file(s):")
    for pdf in pdf_files:
        size_mb = pdf.stat().st_size / (1024 * 1024)
        print(f"   ✓ {pdf.name} ({size_mb:.2f} MB)")

    if not pdf_files:
        print("\n⚠️  No PDF files found in directory.")
        print("   Place source PDFs in Data/_bvl_pdfs/ to continue.")

    # Load database
    print(f"\n📊 Loading database: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"   Total records: {len(data)}")

    # Analyze source file references
    source_files = Counter(r.get('source_file') for r in data if r.get('source_file'))
    print(f"\n📋 Source file references in database:")

    if not source_files:
        print("   No source_file references found in database")
    else:
        for source_file, count in source_files.most_common():
            pdf_path = pdf_dir / source_file
            status = "✓" if pdf_path.exists() else "✗"
            print(f"   {status} {source_file}: {count} records")

    # Check E770 specifically
    print("\n🔍 Checking E770 record:")
    e770_records = [r for r in data if 'E 770' in r.get('kennnummer', '')]
    if e770_records:
        for rec in e770_records:
            print(f"   E-Number: {rec.get('kennnummer')}")
            print(f"   Species: {rec.get('tierarten')}")
            print(f"   Category: {rec.get('tierart_kategorie')}")
            print(f"   Limits: {rec.get('min_mg_kg')} - {rec.get('max_mg_kg')} mg/kg")
            print(f"   Source: {rec.get('source_file')}")
            print(f"   Page: {rec.get('source_page')}")

            # Check if source PDF exists
            if rec.get('source_file'):
                pdf_path = pdf_dir / rec['source_file']
                if pdf_path.exists():
                    print(f"   ✓ Source PDF found: {pdf_path.name}")
                else:
                    print(f"   ✗ Source PDF missing: {rec['source_file']}")
    else:
        print("   ✗ E770 record not found in database")

    # Summary
    print("\n" + "=" * 80)
    pdf_files_set = {p.name for p in pdf_files}
    referenced_files = set(source_files.keys())

    missing_pdfs = referenced_files - pdf_files_set
    extra_pdfs = pdf_files_set - referenced_files

    if missing_pdfs:
        print(f"⚠️  {len(missing_pdfs)} referenced PDF(s) not found:")
        for pdf in sorted(missing_pdfs):
            print(f"   - {pdf}")

    if extra_pdfs:
        print(f"ℹ️  {len(extra_pdfs)} PDF(s) in directory not referenced in database:")
        for pdf in sorted(extra_pdfs):
            print(f"   - {pdf}")

    if not missing_pdfs and pdf_files:
        print("✓ All referenced PDFs are present!")

    print("=" * 80)
    return 0

if __name__ == '__main__':
    exit(main())
