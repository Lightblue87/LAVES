#!/usr/bin/env python3
"""Qt-free BVL PDF update pipeline for LAVES.

This module is intentionally independent from PySide6 so it can run in
headless environments such as a Mac terminal, CI, or a small backend job. It
downloads the official BVL PDFs into ``Data/_bvl_pdfs`` and then delegates the
PDF-to-JSON conversion to ``laves_updater_v6``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import html
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import unquote, urljoin, urlparse

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - exercised by CLI error path
    requests = None  # type: ignore[assignment]
    HTTPAdapter = None  # type: ignore[assignment]
    Retry = None  # type: ignore[assignment]

BVL_LANDING_URL = (
    "https://www.bvl.bund.de/DE/Arbeitsbereiche/02_Futtermittel/03_AntragstellerUnternehmen/05_"
    "Zusatzstoffe_FM/03_Liste_zugelassene_Zusatzstoffe/fm_liste_zugelassener_zusatzstoffe_node.html"
    "?cms_thema=Liste+der+zugelassenen+Zusatzstoffe+in+Futtermitteln"
)

BVL_ALLOWED_PATHS = (
    "/SharedDocs/Downloads/02_Futtermittel/01_Zusatzstoffe_70_524/",
    "/SharedDocs/Downloads/02_Futtermittel/02_Zusatzstoffe_1831/",
)


def resolve_base_dir(base_dir: Optional[Path] = None) -> Path:
    if base_dir is not None:
        return base_dir.expanduser().resolve()

    env = os.environ.get("LAVES_BASE_DIR")
    if env:
        return Path(env).expanduser().resolve()

    here = Path(__file__).resolve().parent
    return here.parent if here.name.lower() == "data" else here


def default_pdf_dir(base_dir: Optional[Path] = None) -> Path:
    return resolve_base_dir(base_dir) / "Data" / "_bvl_pdfs"


def default_json_path(base_dir: Optional[Path] = None) -> Path:
    return resolve_base_dir(base_dir) / "Data" / "zusatzstoffe.json"


def _log_default(message: str) -> None:
    print(message, end="" if message.endswith("\n") else "\n")


def make_session(retries: int = 3, timeout: int = 25):
    if requests is None:
        raise RuntimeError("requests ist nicht installiert. Bitte: pip install requests")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; LAVES-Updater/3.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    original_get = session.get

    def get_with_timeout(url, *args, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return original_get(url, *args, **kwargs)

    session.get = get_with_timeout  # type: ignore[method-assign]
    return session


def normalize_bvl_pdf_url(url: str) -> str:
    normalized = html.unescape(url.strip())
    normalized = re.sub(r";jsessionid=[^?#\s]*", "", normalized, flags=re.I)

    match = re.search(r"(/SharedDocs/Downloads/.*)", normalized, flags=re.I)
    if match:
        normalized = "https://www.bvl.bund.de" + match.group(1)
    elif "SharedDocs/Downloads/" in normalized:
        index = normalized.lower().find("shareddocs/downloads/")
        normalized = "https://www.bvl.bund.de/" + normalized[index:]

    if "/SharedDocs/Downloads/" in normalized and "__blob=publicationFile" not in normalized:
        if re.search(r"\.html?(\?|#|$)", normalized, flags=re.I):
            normalized = re.sub(
                r"\.html?([?#].*)?$",
                ".pdf?__blob=publicationFile",
                normalized,
                flags=re.I,
            )
        else:
            separator = "&" if "?" in normalized else "?"
            normalized = normalized + separator + "__blob=publicationFile"

    return normalized


def _extract_cookie_check_target(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        if not parsed.path.endswith("/cookie-check"):
            return None
        match = re.search(r"(?:^|&)l=([^&]+)", parsed.query)
        if not match:
            return None
        target_path = unquote(match.group(1))
        if not target_path.startswith("/"):
            target_path = "/" + target_path
        return f"{parsed.scheme}://{parsed.netloc}{target_path}"
    except Exception:
        return None


def _maybe_bypass_cookie_check(session, response, log: Callable[[str], None]):
    target = _extract_cookie_check_target(getattr(response, "url", "") or "")
    if not target:
        return response
    try:
        log(f"[INFO] Cookie-Check erkannt -> rufe Zielseite erneut ab: {target}\n")
        return session.get(target)
    except Exception:
        return response


def _extract_links_from_text(text: str, base_url: str) -> list[str]:
    found: list[str] = []
    patterns = [
        r'href=["\']([^"\']+)["\']',
        r"href=([^\s>\"']+)",
        r'data-(?:href|url|src|link)=["\']([^"\']+)["\']',
        r'["\'](/?SharedDocs/Downloads/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            href = html.unescape(match.group(1).strip())
            if not href:
                continue
            if "SharedDocs/Downloads/" in href:
                href = href[href.find("SharedDocs/Downloads/") :]
                if not href.startswith("/"):
                    href = "/" + href
                absolute = "https://www.bvl.bund.de" + href
            else:
                absolute = urljoin(base_url, href)

            normalized = normalize_bvl_pdf_url(absolute)
            lower = normalized.lower()
            if any(path.lower() in lower for path in BVL_ALLOWED_PATHS):
                if lower.endswith(".pdf") or ".pdf?" in lower or lower.endswith((".htm", ".html")):
                    found.append(normalized)

    return _dedup(found)


def _build_seed_urls_from_pdf_dir(pdf_dir: Path) -> list[str]:
    base = "https://www.bvl.bund.de/SharedDocs/Downloads/02_Futtermittel"
    urls: list[str] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        if pdf.name.startswith("1831__"):
            urls.append(f"{base}/02_Zusatzstoffe_1831/{pdf.name.removeprefix('1831__')}?__blob=publicationFile")
        elif pdf.name.startswith("70524__"):
            urls.append(f"{base}/01_Zusatzstoffe_70_524/{pdf.name.removeprefix('70524__')}?__blob=publicationFile")
    return urls


def _dedup(items: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def discover_bvl_pdfs(session, log: Callable[[str], None] = _log_default, pdf_dir: Optional[Path] = None) -> list[str]:
    response = None
    try:
        response = session.get(BVL_LANDING_URL)
        response = _maybe_bypass_cookie_check(session, response, log)
        log(f"[DISCOVER] GET {BVL_LANDING_URL} -> {response.status_code}\n")
        if not response.ok or not response.text:
            response = None
    except Exception as exc:
        log(f"[WARN] Landingpage-Fehler: {exc}\n")
        log("[INFO] Versuche mit deaktivierter SSL-Verifikation...\n")
        try:
            session.verify = False
            requests.packages.urllib3.disable_warnings(  # type: ignore[union-attr]
                requests.packages.urllib3.exceptions.InsecureRequestWarning  # type: ignore[union-attr]
            )
            response = session.get(BVL_LANDING_URL)
            response = _maybe_bypass_cookie_check(session, response, log)
            log(f"[DISCOVER] GET (verify=False) {BVL_LANDING_URL} -> {response.status_code}\n")
            if not response.ok or not response.text:
                response = None
        except Exception as retry_exc:
            log(f"[ERROR] Auch mit verify=False fehlgeschlagen: {retry_exc}\n")
            response = None

    urls: list[str] = []
    if response is not None:
        urls.extend(_extract_links_from_text(response.text, response.url))

    if not urls and response is not None:
        log("[INFO] Keine direkten Links gefunden - starte Fallback-Crawl...\n")
        seen: set[str] = set()
        to_visit: list[tuple[str, int]] = [(BVL_LANDING_URL, 0)]
        host = urlparse(BVL_LANDING_URL).netloc.lower()

        while to_visit:
            url, depth = to_visit.pop(0)
            if url in seen or depth > 1:
                continue
            seen.add(url)
            try:
                crawl_response = session.get(url)
                crawl_response = _maybe_bypass_cookie_check(session, crawl_response, log)
                if crawl_response.status_code != 200 or not crawl_response.text:
                    continue
            except Exception:
                continue

            urls.extend(_extract_links_from_text(crawl_response.text, crawl_response.url))
            if depth == 0:
                for match in re.finditer(r"href=[\"']([^\"']+)[\"']", crawl_response.text, flags=re.I):
                    href = html.unescape(match.group(1).strip())
                    absolute = urljoin(url, href)
                    if urlparse(absolute).netloc.lower() == host:
                        to_visit.append((absolute, depth + 1))

    if not urls and pdf_dir is not None and pdf_dir.exists():
        seed = _build_seed_urls_from_pdf_dir(pdf_dir)
        if seed:
            log(f"[WARN] Keine PDF-Links gefunden - verwende {len(seed)} bekannte URLs aus lokalen PDFs.\n")
            urls = seed

    urls = _dedup(urls)
    log(f"[INFO] PDFs gefunden: {len(urls)}\n")
    for url in urls:
        log(f"  - {url}\n")
    return urls


def _url_to_fname(url: str) -> tuple[str, str]:
    clean = re.sub(r";jsessionid=[^?]+", "", url, flags=re.I)
    base = clean.split("?", 1)[0]
    fname = os.path.basename(base)
    if not fname.lower().endswith(".pdf"):
        fname = (fname.rsplit(".", 1)[0] if "." in fname else fname) + ".pdf"

    prefix = ""
    if "/01_Zusatzstoffe_70_524/" in clean:
        prefix = "70524__"
    elif "/02_Zusatzstoffe_1831/" in clean:
        prefix = "1831__"
    return prefix, prefix + fname


def _extract_candidate_pdf_urls_from_html(page_html: str, base_url: str) -> list[str]:
    out: list[str] = []
    patterns = [
        r"<a[^>]+href=[\"']([^\"']+)[\"']",
        r"<a[^>]+href=([^\s>\"']+)",
        r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+content=[\"'][^\"']*url=([^\"']+)[\"']",
        r"(?:window|document)[.]location(?:[.]href)? *= *[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, page_html, flags=re.I | re.S):
            absolute = urljoin(base_url, html.unescape(match.group(1).strip()))
            if "/SharedDocs/Downloads/" in absolute and "__blob=publicationFile" in absolute:
                out.append(absolute)
    return _dedup(out)


def _get_pdf_bytes(session, url: str, log: Callable[[str], None]) -> tuple[Optional[bytes], Optional[str]]:
    try:
        response = session.get(
            url,
            headers={"Accept": "application/pdf,application/octet-stream,*/*"},
            allow_redirects=True,
        )
        response = _maybe_bypass_cookie_check(session, response, log)
    except Exception as exc:
        log(f"[WARN] GET fehlgeschlagen: {url}\n  {exc}\n")
        return None, None

    ctype = (response.headers.get("content-type") or "").lower()
    if response.ok and response.content and ("application/pdf" in ctype or response.content[:4] == b"%PDF"):
        return response.content, response.url

    if response.ok and response.text and ("text/html" in ctype or "<html" in response.text.lower()):
        for candidate in _extract_candidate_pdf_urls_from_html(response.text, response.url):
            normalized = normalize_bvl_pdf_url(candidate)
            try:
                pdf_response = session.get(
                    normalized,
                    headers={"Accept": "application/pdf,application/octet-stream,*/*"},
                    allow_redirects=True,
                )
                pdf_response = _maybe_bypass_cookie_check(session, pdf_response, log)
            except Exception:
                continue
            pdf_ctype = (pdf_response.headers.get("content-type") or "").lower()
            if pdf_response.ok and pdf_response.content and (
                "application/pdf" in pdf_ctype or pdf_response.content[:4] == b"%PDF"
            ):
                log(f"[INFO] Vorschaltseite erkannt -> Direktlink genutzt: {normalized}\n")
                return pdf_response.content, pdf_response.url

    log(f"[WARN] Keine PDF-Daten erhalten: {url} (Status {response.status_code}, CT {ctype or 'n/a'})\n")
    return None, None


def _check_remote_size(session, url: str) -> Optional[int]:
    try:
        response = session.request(
            "HEAD",
            url,
            headers={"Accept": "application/pdf,application/octet-stream,*/*"},
            allow_redirects=True,
            timeout=15,
        )
        content_length = response.headers.get("content-length")
        return int(content_length) if content_length else None
    except Exception:
        return None


def download_files(urls: list[str], out_dir: Path, session, log: Callable[[str], None] = _log_default) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = {_url_to_fname(url)[1] for url in urls}
    saved: list[Path] = []

    for url in urls:
        _, fname = _url_to_fname(url)
        path = out_dir / fname
        if path.exists():
            local_size = path.stat().st_size
            remote_size = _check_remote_size(session, url)
            if remote_size == local_size:
                log(f"[OK] {fname} unveraendert ({local_size:,} B)\n")
                saved.append(path)
                continue
            log(f"[UPDATE] {fname} wird neu geladen\n")
        else:
            log(f"[DL] {fname}\n")

        content, _ = _get_pdf_bytes(session, url, log)
        if not content:
            if path.exists():
                log(f"[WARN] Download fehlgeschlagen - behalte vorhandene Datei: {fname}\n")
                saved.append(path)
            continue

        path.write_bytes(content)
        log(f"[SAVED] {path.name} ({len(content):,} B)\n")
        saved.append(path)

    if len(expected) >= 2:
        for existing in sorted(out_dir.glob("*.pdf")):
            if existing.name not in expected:
                existing.unlink()
                log(f"[CLEANUP] Entfernt: {existing.name}\n")
    else:
        log("[INFO] Cleanup uebersprungen (zu wenige Links gefunden).\n")

    return saved


def referenced_pdf_files(json_path: Path) -> set[str]:
    if not json_path.exists():
        return set()
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        str(record["source_file"])
        for record in data
        if isinstance(record, dict) and record.get("source_file")
    }


def assert_complete_pdf_set(pdf_dir: Path, json_path: Path, allow_partial: bool = False) -> None:
    if allow_partial:
        return

    referenced = referenced_pdf_files(json_path)
    if not referenced:
        return

    available = {path.name for path in pdf_dir.glob("*.pdf")}
    missing = sorted(referenced - available)
    if missing:
        sample = "\n  - ".join(missing[:10])
        more = f"\n  ... und {len(missing) - 10} weitere" if len(missing) > 10 else ""
        raise RuntimeError(
            "PDF-Satz ist unvollstaendig; Datenbank wird nicht neu geschrieben.\n"
            f"Fehlende PDFs: {len(missing)}\n"
            f"  - {sample}{more}\n"
            "Nutze --allow-partial nur fuer gezielte Parser-Tests."
        )


def build_database(
    pdf_dir: Path,
    json_path: Optional[Path] = None,
    allow_partial: bool = False,
    log: Callable[[str], None] = _log_default,
) -> None:
    if not any(pdf_dir.glob("*.pdf")):
        raise RuntimeError(f"Keine PDFs verfuegbar: {pdf_dir}")

    assert_complete_pdf_set(
        pdf_dir=pdf_dir,
        json_path=json_path or default_json_path(),
        allow_partial=allow_partial,
    )

    try:
        import laves_updater_v6
    except ImportError as exc:
        raise RuntimeError(
            "PDF-Parser-Abhaengigkeiten fehlen. Bitte ausfuehren: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    original_stdout = sys.stdout

    class _Writer:
        def write(self, text: str) -> int:
            if text.strip():
                if log is _log_default:
                    original_stdout.write(text)
                    original_stdout.flush()
                else:
                    log(text)
            return len(text)

        def flush(self) -> None:
            return None

    with contextlib.redirect_stdout(_Writer()), contextlib.redirect_stderr(_Writer()):
        laves_updater_v6.main(pdf_dir=pdf_dir)


def run_update(
    pdf_dir: Path,
    auto_download: bool = True,
    allow_partial: bool = False,
    json_path: Optional[Path] = None,
    log: Callable[[str], None] = _log_default,
) -> int:
    if auto_download:
        session = make_session()
        urls = discover_bvl_pdfs(session, log, pdf_dir=pdf_dir)
        if urls:
            download_files(urls, pdf_dir, session, log)
        else:
            log("[WARN] Keine PDF-URLs gefunden. Verwende vorhandene lokale PDFs, falls vorhanden.\n")

    build_database(pdf_dir, json_path=json_path, allow_partial=allow_partial, log=log)
    log("[OK] BVL-Pipeline abgeschlossen.\n")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Download BVL PDFs and rebuild Data/zusatzstoffe.json.")
    parser.add_argument("--base-dir", type=Path, default=None, help="Projektwurzel. Default: automatisch.")
    parser.add_argument("--pdf-dir", type=Path, default=None, help="PDF-Verzeichnis. Default: <base>/Data/_bvl_pdfs.")
    parser.add_argument("--no-download", action="store_true", help="Nur vorhandene PDFs parsen.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Unvollstaendigen PDF-Satz trotzdem parsen. Nur fuer Tests.",
    )
    args = parser.parse_args(argv)

    base_dir = resolve_base_dir(args.base_dir)
    pdf_dir = args.pdf_dir.expanduser().resolve() if args.pdf_dir else default_pdf_dir(base_dir)
    os.environ.setdefault("LAVES_BASE_DIR", str(base_dir))

    try:
        return run_update(
            pdf_dir=pdf_dir,
            auto_download=not args.no_download,
            allow_partial=args.allow_partial,
            json_path=default_json_path(base_dir),
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
