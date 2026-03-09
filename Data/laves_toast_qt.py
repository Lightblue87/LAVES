from __future__ import annotations

import sys
import os
import json
import re
import html as _html
import io
import contextlib
import subprocess
import traceback
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urljoin, urlparse

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QTextEdit,
    QHBoxLayout,
    QPushButton,
)

try:
    import requests
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

import laves_updater_v6   # ← Direkter Import – entscheidend für PyInstaller/Nuitka

# ─────────────────────────────────────────────────────────────────────────────
# Konstanten
# ─────────────────────────────────────────────────────────────────────────────

BVL_LANDING_URL = (
    "https://www.bvl.bund.de/DE/Arbeitsbereiche/02_Futtermittel/03_AntragstellerUnternehmen/05_"
    "Zusatzstoffe_FM/03_Liste_zugelassene_Zusatzstoffe/fm_liste_zugelassener_zusatzstoffe_node.html"
    "?cms_thema=Liste+der+zugelassenen+Zusatzstoffe+in+Futtermitteln"
)
BVL_ALLOWED_PATHS = [
    "/SharedDocs/Downloads/02_Futtermittel/01_Zusatzstoffe_70_524/",
    "/SharedDocs/Downloads/02_Futtermittel/02_Zusatzstoffe_1831/",
]

APP_TITLE = "LAVES Updater"
AUTO_CLOSE_MS = 3000
WINDOW_SIZE = (580, 300)

# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen (Download-Logik – vollständig übernommen)
# ─────────────────────────────────────────────────────────────────────────────

def _make_session(retries: int = 3, timeout: int = 25):
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; LAVES-Updater/2.1)",
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
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    orig_get = s.get

    def _get(url, *a, **kw):
        if "timeout" not in kw:
            kw["timeout"] = timeout
        return orig_get(url, *a, **kw)

    s.get = _get  # type: ignore[method-assign]
    return s


def _normalize_bvl_pdf_url(u: str) -> str:
    u = re.sub(r";jsessionid=[^?]+", "", u, flags=re.I)
    if "/SharedDocs/Downloads/" in u and "__blob=publicationFile" not in u:
        sep = "&" if "?" in u else "?"
        u = u + sep + "__blob=publicationFile"
    return u


def _extract_cookie_check_target(url: str) -> Optional[str]:
    try:
        pu = urlparse(url)
        if not pu.path.endswith("/cookie-check"):
            return None
        qs = pu.query
        m = re.search(r"(?:^|&)l=([^&]+)", qs)
        if not m:
            return None
        lval = m.group(1)
        from urllib.parse import unquote
        target_path = unquote(lval)
        if not target_path.startswith("/"):
            target_path = "/" + target_path
        return f"{pu.scheme}://{pu.netloc}{target_path}"
    except Exception:
        return None


def _maybe_bypass_cookie_check(session, rr, log: Callable[[str], None]):
    target = _extract_cookie_check_target(getattr(rr, "url", "") or "")
    if not target:
        return rr
    try:
        log(f"[INFO] Cookie-Check erkannt → rufe Zielseite erneut ab: {target}\n")
        return session.get(target)
    except Exception:
        return rr


def _build_seed_urls_from_pdf_dir(pdf_dir: Path) -> List[str]:
    base = "https://www.bvl.bund.de/SharedDocs/Downloads/02_Futtermittel"
    urls: List[str] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        name = pdf.name
        if name.startswith("1831__"):
            fname = name[len("1831__"):]
            urls.append(f"{base}/02_Zusatzstoffe_1831/{fname}?__blob=publicationFile")
        elif name.startswith("70524__"):
            fname = name[len("70524__"):]
            urls.append(f"{base}/01_Zusatzstoffe_70_524/{fname}?__blob=publicationFile")
    return urls


def _extract_links_from_text(text: str, base_url: str) -> List[str]:
    found: List[str] = []
    attr_pats = [
        r"href=[\"']([^\"']+)[\"']",
        r"href=([^\s>\"']+)",
        r"data-(?:href|url|src|link)=[\"']([^\"']+)[\"']",
    ]
    js_path_pat = r"[\"'](/SharedDocs/Downloads/[^\"']+)[\"']"
    base_host = "https://www.bvl.bund.de"
    for pat in attr_pats + [js_path_pat]:
        for m in re.finditer(pat, text, flags=re.I | re.S):
            href = _html.unescape(m.group(1).strip())
            if not href:
                continue
            absu = urljoin(base_url if not href.startswith("/") else base_host, href)
            low = absu.lower()
            if any(seg.lower() in low for seg in BVL_ALLOWED_PATHS):
                if (low.endswith(".pdf") or ".pdf?" in low
                        or low.endswith(".htm") or low.endswith(".html")):
                    found.append(_normalize_bvl_pdf_url(absu))
    return found


def _discover_bvl_pdfs(
    session,
    log: Callable[[str], None],
    pdf_dir: Optional[Path] = None,
) -> List[str]:
    r = None
    try:
        r = session.get(BVL_LANDING_URL)
        r = _maybe_bypass_cookie_check(session, r, log)
        log(f"[DISCOVER] GET {BVL_LANDING_URL} -> {r.status_code}\n")
        if not r.ok or not r.text:
            log("[ERROR] Landingpage nicht erreichbar.\n")
            r = None
    except Exception as e:
        log(f"[WARN] Landingpage-Fehler: {e}\n")
        log("[INFO] Versuche mit deaktivierter SSL-Verifikation…\n")
        try:
            r = session.get(BVL_LANDING_URL, verify=False)
            r = _maybe_bypass_cookie_check(session, r, log)
            log(f"[DISCOVER] GET (verify=False) {BVL_LANDING_URL} -> {r.status_code}\n")
            if not r.ok or not r.text:
                log("[ERROR] Landingpage nicht erreichbar (auch mit verify=False).\n")
                log("[HINT] Bitte prüfe:\n")
                log("  - Netzwerkverbindung und Firewall\n")
                log("  - VPN-Verbindung (wenn aktiv, versuche zu trennen)\n")
                log("  - Website-Erreichbarkeit in Browser\n")
                r = None
        except Exception as e2:
            log(f"[ERROR] Auch mit verify=False fehlgeschlagen: {e2}\n")
            log("[HINT] Die BVL-Website ist möglicherweise nicht erreichbar.\n")
            r = None

    urls: List[str] = []

    if r is not None:
        urls.extend(_extract_links_from_text(r.text, r.url))

    if not urls and r is not None:
        log("[INFO] Keine direkten Links gefunden – starte Fallback-Crawl…\n")
        seen: set[str] = set()
        to_visit: list[tuple[str, int]] = [(BVL_LANDING_URL, 0)]
        host = urlparse(BVL_LANDING_URL).netloc.lower()

        while to_visit:
            url, depth = to_visit.pop(0)
            if url in seen or depth > 1:
                continue
            seen.add(url)

            try:
                rr = session.get(url)
                rr = _maybe_bypass_cookie_check(session, rr, log)
                if rr.status_code != 200 or not rr.text:
                    continue
            except Exception:
                continue

            urls.extend(_extract_links_from_text(rr.text, rr.url))

            if depth == 0:
                for m in re.finditer(r"href=[\"']([^\"']+)[\"']", rr.text, flags=re.I):
                    href = _html.unescape(m.group(1).strip())
                    if not href:
                        continue
                    absu = urljoin(url, href)
                    if urlparse(absu).netloc.lower() == host:
                        to_visit.append((absu, depth + 1))

    if not urls and pdf_dir is not None and pdf_dir.exists():
        seed = _build_seed_urls_from_pdf_dir(pdf_dir)
        if seed:
            log(
                f"[WARN] Keine PDF-Links auf BVL-Seite gefunden (möglicherweise JavaScript-gerendert).\n"
                f"[INFO] Verwende {len(seed)} bekannte URLs aus vorhandenen PDFs als Fallback.\n"
            )
            urls = seed

    out: List[str] = []
    seen2: set[str] = set()
    for u in urls:
        if u not in seen2:
            seen2.add(u)
            out.append(u)

    log(f"[INFO] PDFs gefunden: {len(out)}\n")
    for u in out:
        log(f"  - {u}\n")
    return out


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


def _extract_candidate_pdf_urls_from_html(html: str, base_url: str) -> list[str]:
    out: list[str] = []

    a_pats = [
        "<a[^>]+href=[\\\"']([^\\\"']+)[\\\"']",
        "<a[^>]+href=([^\\s>\"']+)",
    ]

    for a_pat in a_pats:
        for m in re.finditer(a_pat, html, flags=re.I | re.S):
            href = _html.unescape(m.group(1).strip())
            if not href:
                continue
            absu = urljoin(base_url, href)
            if "/SharedDocs/Downloads/" in absu and "__blob=publicationFile" in absu:
                out.append(absu)

    mr_pat = (
        "<meta[^>]+http-equiv=[\\\"']refresh[\\\"'][^>]+content=[\\\"'][^\\\"']*url=([^\\\"']+)[\\\"']"
    )
    mm = re.search(mr_pat, html, flags=re.I | re.S)
    if mm:
        absu = urljoin(base_url, _html.unescape(mm.group(1).strip()))
        if "/SharedDocs/Downloads/" in absu and "__blob=publicationFile" in absu:
            out.append(absu)

    wl_pat = "(?:window|document)[.]location(?:[.]href)? *= *[\\\"']([^\\\"']+)[\\\"']"
    for m in re.finditer(wl_pat, html, flags=re.I | re.S):
        absu = urljoin(base_url, _html.unescape(m.group(1).strip()))
        if "/SharedDocs/Downloads/" in absu and "__blob=publicationFile" in absu:
            out.append(absu)

    dedup: list[str] = []
    seen: set[str] = set()
    for u in out:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup


def _get_pdf_bytes(session, url: str, log: Callable[[str], None]) -> tuple[Optional[bytes], Optional[str]]:
    rr = None
    try:
        rr = session.get(
            url,
            headers={"Accept": "application/pdf,application/octet-stream,*/*"},
            allow_redirects=True,
        )
        rr = _maybe_bypass_cookie_check(session, rr, log)
    except Exception:
        log(f"[WARN] GET fehlgeschlagen, versuche mit verify=False: {url}\n")
        try:
            rr = session.get(
                url,
                headers={"Accept": "application/pdf,application/octet-stream,*/*"},
                allow_redirects=True,
                verify=False,
            )
            rr = _maybe_bypass_cookie_check(session, rr, log)
        except Exception as e2:
            log(f"[WARN] GET fehlgeschlagen (auch mit verify=False): {url}\n  {e2}\n")
            return None, None

    if not rr:
        return None, None

    ctype = (rr.headers.get("content-type") or rr.headers.get("Content-Type") or "").lower()

    if rr.ok and rr.content and ("application/pdf" in ctype or rr.content[:4] == b"%PDF"):
        return rr.content, rr.url

    if rr.ok and rr.text and ("text/html" in ctype or "<html" in rr.text.lower()):
        candidates = _extract_candidate_pdf_urls_from_html(rr.text, rr.url)
        for cu in candidates:
            nu = _normalize_bvl_pdf_url(cu)
            try:
                rr2 = session.get(
                    nu,
                    headers={"Accept": "application/pdf,application/octet-stream,*/*"},
                    allow_redirects=True,
                )
                rr2 = _maybe_bypass_cookie_check(session, rr2, log)
            except Exception:
                continue

            ctype2 = (rr2.headers.get("content-type") or rr2.headers.get("Content-Type") or "").lower()
            if rr2.ok and rr2.content and ("application/pdf" in ctype2 or rr2.content[:4] == b"%PDF"):
                log(f"[INFO] Vorschaltseite erkannt → Direktlink genutzt: {nu}\n")
                return rr2.content, rr2.url

    log(
        f"[WARN] Keine PDF-Daten erhalten: {url} (Status {getattr(rr, 'status_code', 'n/a')}, CT {ctype or 'n/a'})\n"
    )
    return None, None


def _check_remote_size(session, url: str) -> Optional[int]:
    try:
        r = session.request(
            "HEAD", url,
            headers={"Accept": "application/pdf,application/octet-stream,*/*"},
            allow_redirects=True,
            timeout=15,
        )
        cl = r.headers.get("content-length") or r.headers.get("Content-Length")
        return int(cl) if cl else None
    except Exception:
        return None


def _download_files(urls: List[str], out_dir: Path, session, log: Callable[[str], None]) -> List[str]:
    out_dir.mkdir(parents=True, exist_ok=True)

    expected: set[str] = set()
    for url in urls:
        _, fname = _url_to_fname(url)
        expected.add(fname)

    saved: List[str] = []
    for url in urls:
        prefix, fname = _url_to_fname(url)
        path = out_dir / fname
        try:
            if path.exists():
                local_size = path.stat().st_size
                log(f"[CHECK] {fname} (lokal: {local_size:,} B)…\n")
                remote_size = _check_remote_size(session, url)
                if remote_size is None:
                    log(f"[UPDATE] {fname} – Remote-Größe unbekannt, lade neu…\n")
                elif remote_size == local_size:
                    log(f"[OK] {fname} – unverändert ({local_size:,} B)\n")
                    saved.append(str(path))
                    continue
                else:
                    log(
                        f"[UPDATE] {fname} – Größe geändert "
                        f"(lokal: {local_size:,} B → remote: {remote_size:,} B), lade neu…\n"
                    )
            else:
                log(f"[DL] {fname} (neu)\n")

            content, final_url = _get_pdf_bytes(session, url, log)
            if not content:
                if path.exists():
                    log(f"[WARN] Download fehlgeschlagen – behalte vorhandene Datei: {fname}\n")
                    saved.append(str(path))
                continue

            if final_url:
                try:
                    rr_head = session.get(
                        final_url,
                        headers={"Accept": "application/pdf,application/octet-stream,*/*"},
                        stream=True,
                        allow_redirects=True,
                    )
                    rr_head = _maybe_bypass_cookie_check(session, rr_head, log)
                    cd = rr_head.headers.get("content-disposition") or rr_head.headers.get("Content-Disposition")
                    if cd:
                        mc = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
                        if mc:
                            fn = os.path.basename(mc.group(1))
                            if fn:
                                if prefix and not fn.startswith(prefix):
                                    fn = prefix + fn
                                expected.discard(fname)
                                expected.add(fn)
                                path = out_dir / fn
                except Exception:
                    pass

            path.write_bytes(content)
            log(f"[SAVED] {path.name} ({len(content):,} B)\n")
            saved.append(str(path))

        except Exception as e:
            log(f"[WARN] Fehler: {url}\n {e}\n")

    removed = 0
    if len(expected) >= 2:
        for existing in sorted(out_dir.glob("*.pdf")):
            if existing.name not in expected:
                try:
                    existing.unlink()
                    log(f"[CLEANUP] Entfernt (veraltet): {existing.name}\n")
                    removed += 1
                except Exception as e:
                    log(f"[WARN] Konnte {existing.name} nicht löschen: {e}\n")
    else:
        log("[INFO] Cleanup übersprungen (zu wenige Links gefunden).\n")

    log(f"[INFO] {len(saved)} PDF(s) vorhanden, {removed} veraltete entfernt.\n")
    return saved


def _resolve_base_dir() -> Path:
    env = os.environ.get("LAVES_BASE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    try:
        p = Path(__file__).resolve().parent
    except NameError:
        p = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()
    # When running from source inside a 'Data' subdirectory, go up to the project root
    # so that <base>/Data/_bvl_pdfs resolves correctly in both dev and frozen scenarios.
    if p.name.lower() == "data":
        return p.parent
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Worker-Klassen
# ─────────────────────────────────────────────────────────────────────────────

class DownloadWorker(QThread):
    message = Signal(str)
    finished = Signal(bool)

    def __init__(self, pdf_dir: Path):
        super().__init__()
        self.pdf_dir = pdf_dir

    def run(self):
        if not _HAS_REQUESTS:
            self.message.emit("[ERROR] 'requests' ist nicht installiert. Bitte: pip install requests\n")
            self.finished.emit(False)
            return

        try:
            session = _make_session()
            self.message.emit("[DOWNLOAD] Starte PDF-Suche auf BVL-Seite …\n")
            urls = _discover_bvl_pdfs(session, self.message.emit, pdf_dir=self.pdf_dir)
            if not urls:
                self.message.emit("[WARN] Keine neuen PDF-Links gefunden.\n")
            saved = _download_files(urls, self.pdf_dir, session, self.message.emit)
            self.message.emit(f"[OK] {len(saved)} PDF(s) geprüft/heruntergeladen.\n")
            self.finished.emit(True)
        except Exception as e:
            self.message.emit(f"[ERROR] Download-Fehler: {e}\n{traceback.format_exc()}\n")
            self.finished.emit(False)


class ParserWorker(QThread):
    message = Signal(str)
    finished = Signal(bool)

    def __init__(self, pdf_dir: Path):
        super().__init__()
        self.pdf_dir = pdf_dir

    def run(self):
        try:
            self.message.emit("[PARSER] Starte JSON-Erstellung aus PDFs …\n")

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                laves_updater_v6.main(pdf_dir=self.pdf_dir)

            output = captured.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.message.emit(f"[PARSER] {line}\n")

            self.message.emit("[PARSER] Fertig – JSON sollte jetzt aktualisiert sein.\n")
            self.finished.emit(True)

        except Exception as e:
            tb = traceback.format_exc()
            self.message.emit(f"[ERROR] Parser-Absturz:\n{e}\n{tb}\n")
            self.finished.emit(False)


# ─────────────────────────────────────────────────────────────────────────────
# GUI – UpdaterToastQt (komplett angepasst)
# ─────────────────────────────────────────────────────────────────────────────

class UpdaterToastQt(QWidget):
    def __init__(self, auto_start: bool = False):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint | Qt.MSWindowsFixedSizeDialogHint)
        self.setWindowTitle(APP_TITLE)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setFixedSize(*WINDOW_SIZE)

        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - WINDOW_SIZE[0] - 24
        y = screen.bottom() - WINDOW_SIZE[1] - 48
        self.setGeometry(x, y, *WINDOW_SIZE)

        self.base_dir = _resolve_base_dir()
        self.pdf_dir = self.base_dir / "Data" / "_bvl_pdfs"
        self.log_path = self.base_dir / "Data" / "update.log"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.lblTitle = QLabel("Bereit")
        self.lblTitle.setStyleSheet("font-weight:600; font-size:14px;")
        lay.addWidget(self.lblTitle)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        lay.addWidget(self.progress)

        self.lblStatus = QLabel("Klicke 'Aktualisieren' um PDFs zu prüfen und die Datenbank zu aktualisieren.")
        self.lblStatus.setStyleSheet("color:#bbb; background:#222; padding:4px 6px; border-radius:4px;")
        self.lblStatus.setWordWrap(True)
        lay.addWidget(self.lblStatus)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setStyleSheet("background:#0d0d0d; color:#ddd; border:1px solid #333; border-radius:6px;")
        self.txt.setFixedHeight(160)
        lay.addWidget(self.txt, 1)

        h = QHBoxLayout()
        self.btnUpdate = QPushButton("⟳  Aktualisieren")
        self.btnUpdate.setStyleSheet("font-weight:600; padding:4px 12px;")
        self.btnUpdate.clicked.connect(self._start_update)
        self.btnLog = QPushButton("Log öffnen")
        self.btnClose = QPushButton("Schließen")
        self.btnClose.clicked.connect(self.close)
        self.btnLog.clicked.connect(self._open_log)
        h.addWidget(self.btnUpdate)
        h.addStretch(1)
        h.addWidget(self.btnLog)
        h.addWidget(self.btnClose)
        lay.addLayout(h)

        self._dl_worker: Optional[DownloadWorker] = None
        self._parser_worker: Optional[ParserWorker] = None

        if auto_start:
            QTimer.singleShot(100, self._start_update)

    def closeEvent(self, event):
        if self._dl_worker and self._dl_worker.isRunning():
            self._dl_worker.requestInterruption()
            self._dl_worker.wait(1500)
        if self._parser_worker and self._parser_worker.isRunning():
            self._parser_worker.requestInterruption()
            self._parser_worker.wait(1500)
        super().closeEvent(event)

    def _append(self, text: str):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
        self.txt.moveCursor(QTextCursor.End)
        self.txt.insertPlainText(text)
        self.txt.moveCursor(QTextCursor.End)

    def _set_busy(self, busy: bool):
        self.btnUpdate.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1)

    def _start_update(self):
        if self._dl_worker and self._dl_worker.isRunning():
            return

        self._set_busy(True)
        self.lblTitle.setText("Schritt 1/2 – PDFs werden geprüft…")
        self.lblStatus.setText("Verbinde mit BVL und prüfe auf Änderungen…")
        self.txt.clear()
        self._append("=== Update gestartet ===\n")

        self._dl_worker = DownloadWorker(self.pdf_dir)
        self._dl_worker.message.connect(self._append)
        self._dl_worker.finished.connect(self._on_download_finished)
        self._dl_worker.start()

    def _on_download_finished(self, ok: bool):
        pdfs_available = self.pdf_dir.exists() and any(self.pdf_dir.glob("*.pdf"))

        if not pdfs_available:
            self._set_busy(False)
            self.lblTitle.setText("Keine PDFs verfügbar ✗")
            self.lblTitle.setStyleSheet("color:#ff9393; font-weight:600; font-size:14px;")
            self.lblStatus.setText("Download fehlgeschlagen und keine lokalen PDFs vorhanden.")
            return

        if not ok:
            self._append("[INFO] Download hatte Probleme – versuche mit vorhandenen PDFs weiter.\n")

        self.lblTitle.setText("Schritt 2/2 – Datenbank wird aktualisiert…")
        self.lblStatus.setText("Parser läuft – JSON wird neu erstellt…")

        self._parser_worker = ParserWorker(self.pdf_dir)
        self._parser_worker.message.connect(self._append)
        self._parser_worker.finished.connect(self._on_parser_finished)
        self._parser_worker.start()

    def _on_parser_finished(self, success: bool):
        self._set_busy(False)

        if success:
            self.lblTitle.setText("Update abgeschlossen ✓")
            self.lblTitle.setStyleSheet("color:#a6f3a6; font-weight:600; font-size:14px;")
            self.lblStatus.setText(f"Datenbank aktualisiert. Schließe in {AUTO_CLOSE_MS//1000} s…")
            QTimer.singleShot(AUTO_CLOSE_MS, self.close)
        else:
            self.lblTitle.setText("Fehler beim Erstellen der Datenbank ✗")
            self.lblTitle.setStyleSheet("color:#ff9393; font-weight:600; font-size:14px;")
            self.lblStatus.setText("Bitte Log prüfen. Fenster bleibt offen.")

    def _open_log(self):
        path = str(self.log_path)
        try:
            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except OSError as e:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(None, "Log öffnen", f"Konnte Log nicht öffnen:\n{e}")
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Headless-Modus (angepasst)
# ─────────────────────────────────────────────────────────────────────────────

def run_update_headless(args=None, auto_download=True) -> int:
    base = _resolve_base_dir()
    pdf_dir = base / "Data" / "_bvl_pdfs"

    if auto_download and _HAS_REQUESTS:
        try:
            session = _make_session()
            urls = _discover_bvl_pdfs(session, print, pdf_dir)
            if urls:
                _download_files(urls, pdf_dir, session, print)
        except Exception as e:
            print(f"[ERROR] Download fehlgeschlagen: {e}")

    if not any(pdf_dir.glob("*.pdf")):
        print("Keine PDFs verfügbar → Abbruch.")
        return 3

    try:
        laves_updater_v6.main(pdf_dir=pdf_dir)
        print("Parser erfolgreich abgeschlossen.")
        return 0
    except Exception as e:
        print(f"Parser-Fehler: {e}")
        return 2


# ─────────────────────────────────────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────────────────────────────────────

def run_toast(auto_start: bool = False):
    app = QApplication.instance() or QApplication(sys.argv)
    w = UpdaterToastQt(auto_start=auto_start)
    w.show()
    return app.exec()


if __name__ == "__main__":
    if "--headless" in sys.argv:
        sys.exit(run_update_headless())
    else:
        sys.exit(run_toast(auto_start="--auto" in sys.argv))