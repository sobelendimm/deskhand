"""Bağımlılık denetimi (Sağlık sekmesi). Qt'siz; yalnız okur (`which`, `tesseract --list-langs`, find_spec)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess

from ..i18n import N_

# (ad, açıklama/paket) — araç adları tek dizede: ham araç taraması (tests/test_mantik.py) yalnız arka_uc'ye izin verir.
# Açıklamalar msgid (N_): Sağlık sekmesi gösterirken çevirir; paket adları parantez içinde aynen kalmalı.
_ARAC_ADLARI = "kdotool dotool spectacle tesseract Xvfb xdotool openbox bwrap kwin_wayland".split()
ARAC_NOT = dict(zip(_ARAC_ADLARI, (
    N_("pencere bulma (AUR: kdotool-bin)"), N_("fare/klavye (AUR: dotool)"), N_("ekran görüntüsü (spectacle)"),
    N_("metin okuma (tesseract)"), N_("arka plan masaüstü (xorg-server-xvfb)"), N_("arka plan yedek araç (xdotool)"),
    N_("arka plan pencere yöneticisi (openbox)"),
    N_("arka plan uygulama yalıtımı; yoksa arka planda hiçbir uygulama açılmaz (bubblewrap)"),
    N_("GPU'lu arka plan masaüstü; yoksa Xvfb kullanılır (kwin)"))))
# Eksikse yalnız bilgi (sarı) olanlar: bir yedek yol var
BILGI = {"kwin_wayland"}
DILLER = {"tur": N_("Türkçe OCR (tesseract-data-tur)"), "eng": N_("İngilizce OCR (tesseract-data-eng)")}
MODULLER = {"PyQt6": N_("arayüz (python-pyqt6)"), "Xlib": N_("arka plan girdi/görüntü (python-xlib)"),
            "numpy": N_("görüntü işleme (python-numpy)"), "scipy": N_("simge eşleme (python-scipy)"),
            "PIL": N_("görüntü (python-pillow)"), "jeepney": N_("D-Bus (python-jeepney)"),
            "secretstorage": N_("kalıcı oturum anahtarı, KDE Cüzdanı (python-secretstorage)"),
            "cryptography": N_("kalıcı oturum şifrelemesi (python-cryptography)"),
            "mcp": N_("MCP sunucusu (python-mcp)")}


def tesseract_dilleri(calistir=subprocess.run) -> set[str] | None:
    yol = shutil.which("tesseract")
    if not yol:
        return None
    try:
        r = calistir([yol, "--list-langs"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    satirlar = (r.stdout or "").splitlines() + (r.stderr or "").splitlines()
    return {s.strip() for s in satirlar if s.strip() and " " not in s.strip() and not s.endswith(":")}


def denetle(which=shutil.which, find_spec=importlib.util.find_spec, diller_f=tesseract_dilleri) -> list[dict]:
    """→ [{ad, tur ("arac"|"dil"|"modul"), ok, not}]."""
    sonuc = []
    for ad in _ARAC_ADLARI:
        ok = bool(which(ad))
        sonuc.append({"ad": ad, "tur": "arac", "ok": ok, "not": ARAC_NOT[ad],
                      "durum": "tamam" if ok else ("uyari" if ad in BILGI else "eksik")})
    diller = diller_f()
    for ad, n in DILLER.items():
        sonuc.append({"ad": f"tesseract: {ad}", "tur": "dil", "ok": bool(diller and ad in diller), "not": n})
        sonuc[-1]["durum"] = "tamam" if sonuc[-1]["ok"] else "eksik"
    for ad, n in MODULLER.items():
        try:
            ok = find_spec(ad) is not None
        except (ImportError, ValueError):
            ok = False
        sonuc.append({"ad": ad, "tur": "modul", "ok": ok, "not": n, "durum": "tamam" if ok else "eksik"})
    return sonuc


def ek_satirlar(doktor_f=None) -> list[dict]:
    """Doctor'ın satır işlevlerini yeniden kullanır (yeni denetim mantığı YOK): C yardımcıları (deskhand-eis dahil),
    arka plan masaüstü türü (kwin|xvfb), onay kapsamı ve hesap oturumları (panelin bellekteki yetkili değeri: liste_koruma).
    → denetle() ile aynı biçim; tur "ek", not = doctor'ın (zaten çevrilmiş) ayrıntısı."""
    if doktor_f is None:
        from .. import doktor
        doktor_f = (doktor.satir_yardimcilar, doktor.satir_arka_tur, doktor.satir_onay_kapsami,
                    doktor.satir_hesap_oturumlari, doktor.satir_kalici_oturum)
    sonuc = []
    for f in doktor_f:
        try:
            r = f()
            sonuc.append({"ad": r["ad"], "tur": "ek", "ok": r["durum"] == "tamam", "durum": r["durum"],
                          "not": r["ayrinti"]})
        except Exception as e:  # noqa: BLE001 - tek denetim sekmeyi çökertmesin
            sonuc.append({"ad": getattr(f, "__name__", "?").removeprefix("satir_"), "tur": "ek", "ok": False,
                          "durum": "uyari", "not": str(e)})
    return sonuc


def tam_denetim() -> list[dict]:
    return denetle() + ek_satirlar()
