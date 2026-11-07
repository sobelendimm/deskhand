"""User-facing language: Turkish source texts + English catalog.

    from .i18n import _
    raise Dur(6, _("'{metin}' bulunamadı").format(metin=m))

The source language is Turkish: the msgid IS the Turkish text. The catalog lives in
``deskhand/i18n/en.json`` = {"Türkçe metin": "English text", …}; a missing or empty entry
falls back to the Turkish text, so an incomplete catalog never breaks anything.
Placeholders are named (``{metin}``) and must survive translation (tools/i18n_denetle.py checks).

Language: ``CONFIG_DIR/arayuz.json`` {"dil": "otomatik" | "tr" | "en"};
"otomatik" = LANGUAGE / LC_ALL / LC_MESSAGES / LANG (Turkish → Turkish, anything else → English).
``DESKHAND_DIL`` overrides both (tests force "tr"). Read once per process, lazily, on the first _().
The activity log (gunluk) stays Turkish on purpose: the panel parses it.
Adapted from the i18n module of Kulak Kesil (same author, GPL-3.0-or-later).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

DILLER = {"tr": "Türkçe", "en": "English"}  # code -> name in its own language
KAYNAK = "tr"
OTOMATIK = "otomatik"
YEDEK = "en"  # system language not supported → English
CATALOG_DIR = Path(__file__).resolve().parent / "i18n"
SETTINGS_FILE = "arayuz.json"

_lock = threading.Lock()
_state: dict = {"dil": None, "katalog": {}}


def _settings_path() -> Path:
    from . import yollar
    return Path(yollar.config_dir()) / SETTINGS_FILE  # resolved at call time (tests redirect CONFIG_DIR)


def ayar_oku() -> str:
    """Saved choice: "otomatik" or a code of DILLER."""
    try:
        v = json.loads(_settings_path().read_text("utf-8")).get("dil", OTOMATIK)
    except (OSError, ValueError, AttributeError):
        return OTOMATIK
    return v if isinstance(v, str) and (v == OTOMATIK or v in DILLER) else OTOMATIK


def ayar_yaz(dil: str) -> None:
    """Save the choice atomically (applies to new processes; the panel reloads)."""
    if dil != OTOMATIK and dil not in DILLER:
        raise ValueError(f"desteklenmeyen dil: {dil}")
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(p.read_text("utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["dil"] = dil
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _kod(value: str) -> str:
    return value.strip().split(".")[0].split("@")[0].split("_")[0].lower()


def sistem_dili(env: dict | None = None) -> str:
    """Code from the POSIX locale variables (gettext rules): the locale is the first non-empty of
    LC_ALL / LC_MESSAGES / LANG; "C"/"POSIX" (or none) → English. LANGUAGE (a priority list, KDE sets it)
    wins with its first supported entry; then the locale's own language; anything else → English."""
    env = os.environ if env is None else env
    loc = next(((env.get(v) or "").strip() for v in ("LC_ALL", "LC_MESSAGES", "LANG")
                if (env.get(v) or "").strip()), "")
    if not loc or loc in ("C", "POSIX") or loc.startswith(("C.", "POSIX.")):
        return YEDEK
    for item in (env.get("LANGUAGE") or "").split(":"):
        if item.strip() and _kod(item) in DILLER:
            return _kod(item)
    code = _kod(loc)
    return code if code in DILLER else YEDEK


def secilen_dil(env: dict | None = None) -> str:
    """The language this process uses: DESKHAND_DIL > arayuz.json > system locale."""
    env = os.environ if env is None else env
    forced = (env.get("DESKHAND_DIL") or "").strip().lower()
    if forced in DILLER:
        return forced
    saved = ayar_oku()
    return sistem_dili(env) if saved == OTOMATIK else saved


def katalog_oku(dil: str, directory: Path | None = None) -> dict[str, str]:
    """{msgid: translation} of one language ({} for Turkish / missing / broken file)."""
    if dil == KAYNAK:
        return {}
    p = Path(directory or CATALOG_DIR) / f"{dil}.json"
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def kapsama(dil: str, directory: Path | None = None) -> float | None:
    """Share of the source texts (kaynak.json) this language translates, 0..1 (None: Turkish / no kaynak.json)."""
    if dil == KAYNAK:
        return None
    try:
        kaynak = json.loads((Path(directory or CATALOG_DIR) / "kaynak.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(kaynak, dict) or not kaynak:
        return None
    katalog = katalog_oku(dil, directory)
    return sum(1 for m in kaynak if m in katalog) / len(kaynak)


def _load() -> None:
    with _lock:
        if _state["dil"] is None:
            dil_ = secilen_dil()
            _state["katalog"] = katalog_oku(dil_)
            _state["dil"] = dil_


def yeniden_yukle() -> str:
    """Forget the loaded catalog; the next _() reads the language setting again. → new language code."""
    with _lock:
        _state["dil"] = None
    return dil()


def dil() -> str:
    """Active language code of this process."""
    if _state["dil"] is None:
        _load()
    return _state["dil"]


def _(text: str) -> str:
    """Translate one Turkish UI text (unknown text → itself)."""
    if _state["dil"] is None:
        _load()
    return _state["katalog"].get(text, text) if _state["katalog"] else text


def h_(text: str) -> str:
    """argparse help text: argparse %-formats it, so a lone "%" in a translation must not break it."""
    return _(text).replace("%", "%%")


def N_(text: str) -> str:
    """Mark a text for the catalog without translating it now (translate at use: _(x))."""
    return text


def sifirla(dil_kodu: str | None = None, katalog: dict[str, str] | None = None) -> None:
    """Tests/tools: drop the cached language (next _() re-reads) or force one."""
    with _lock:
        _state["dil"] = dil_kodu
        _state["katalog"] = dict(katalog or {}) if dil_kodu is not None else {}
