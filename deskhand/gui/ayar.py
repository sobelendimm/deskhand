"""Panelin kendi ayarları (CONFIG_DIR/panel.json) ve deskhand.ayarlar ile köprü (meşgulken davranışı).

deskhand/ayarlar.py başka bir modülde yazılıyor; arayüzü kesinleşene dek esnek bağlanılır:
  al(bolum, anahtar[, varsayilan]) + ayarla(bolum, anahtar, deger)     (tercih edilen)
  ya da oku()/yukle() → {bolum: {anahtar: değer}} + yaz(d)/kaydet(d)
Seçenekler/aralıklar modülün SECENEK / ARALIK sözlüklerinden ((bolum, anahtar) → küme / (alt, üst)) alınır.
"""
from __future__ import annotations

import json
import os
import re

from .. import yollar
from .kisayol import VARSAYILAN_TUS

PANEL_VARSAYILAN = {"kisayol_acik": False, "kisayol": VARSAYILAN_TUS}
KARAR_ANAHTARLARI = ("mesgulken", "sor_sure", "cevapsiz", "tam_ekranda_sor")
SIRA = ("sor", "arka", "hep-arka", "bekle", "sonra")  # seçeneklerin gösterim sırası
VARSAYILAN_MESGULKEN = ("sor", "arka", "bekle")
VARSAYILAN_CEVAPSIZ = ("arka", "sonra")


def _sirala(secenek) -> tuple:
    return tuple(sorted(secenek, key=lambda s: (SIRA.index(s) if s in SIRA else len(SIRA), s)))


def panel_yolu() -> str:
    return os.path.join(yollar.config_dir(), "panel.json")


def panel_oku() -> dict:
    d = dict(PANEL_VARSAYILAN)
    try:
        with open(panel_yolu()) as f:
            v = json.load(f)
        if isinstance(v, dict):
            d.update({k: v[k] for k in PANEL_VARSAYILAN if k in v})
    except (OSError, ValueError):
        pass
    d["kisayol_acik"] = bool(d["kisayol_acik"])
    d["kisayol"] = str(d["kisayol"] or VARSAYILAN_TUS)
    return d


def panel_yaz(d: dict) -> None:
    os.makedirs(yollar.config_dir(), exist_ok=True)
    gecici = panel_yolu() + f".{os.getpid()}"
    with open(gecici, "w") as f:
        json.dump({k: d.get(k, v) for k, v in PANEL_VARSAYILAN.items()}, f, ensure_ascii=False, indent=1)
    os.replace(gecici, panel_yolu())


# ---------------------------------------------------------------- yasak pencereler

def yasak_metni() -> str:
    """Yasak dosyasının metni; yoksa varsayılan (dosya OLUŞTURULMAZ: yalnız Kaydet yazar)."""
    try:
        with open(yollar.yasak_dosya()) as f:
            return f.read()
    except OSError:
        from ..guvenlik import VARSAYILAN_YASAK
        return VARSAYILAN_YASAK


def yasak_dogrula(metin: str) -> tuple[int, str] | None:
    """Her desen satırı derlenebilmeli. → (satır no, hata) ya da None."""
    for no, satir in enumerate(metin.splitlines(), 1):
        s = satir.strip()
        if not s or s.startswith("#"):
            continue
        try:
            re.compile(s, re.I)
        except re.error as e:
            return no, str(e)
    return None


def yasak_kaydet(metin: str) -> None:
    hata = yasak_dogrula(metin)
    if hata:
        raise ValueError(hata)
    yol = yollar.yasak_dosya()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = yol + f".{os.getpid()}"
    with open(gecici, "w") as f:
        f.write(metin if metin.endswith("\n") else metin + "\n")
    os.replace(gecici, yol)


# ---------------------------------------------------------------- deskhand.ayarlar köprüsü

class KararAyarlari:
    """[karar] mesgulken / sor_sure / cevapsiz. `var` False ise Ayarlar bilgilendirme gösterir."""

    def __init__(self, modul=None):
        if modul is None:
            try:
                from .. import ayarlar as modul  # type: ignore[no-redef]
            except Exception:  # noqa: BLE001 - modül henüz yok
                modul = None
        self.m = modul
        self.var = modul is not None and (
            (hasattr(modul, "al") and hasattr(modul, "ayarla")) or
            (any(hasattr(modul, a) for a in ("oku", "yukle")) and any(hasattr(modul, a) for a in ("yaz", "kaydet"))))
        secenek = getattr(modul, "SECENEK", None) or {}
        aralik = getattr(modul, "ARALIK", None) or {}
        varsayilan = (getattr(modul, "VARSAYILAN", None) or {}).get("karar", {})
        self.mesgulken_secenek = _sirala(secenek.get(("karar", "mesgulken"), VARSAYILAN_MESGULKEN))
        self.cevapsiz_secenek = _sirala(secenek.get(("karar", "cevapsiz"), VARSAYILAN_CEVAPSIZ))
        self.sor_sure_aralik = tuple(aralik.get(("karar", "sor_sure"), (5, 600)))
        self.anahtarlar = tuple(k for k in KARAR_ANAHTARLARI if not varsayilan or k in varsayilan)

    def _hepsi(self) -> dict:
        f = getattr(self.m, "oku", None) or getattr(self.m, "yukle")
        d = f()
        return d if isinstance(d, dict) else {}

    def oku(self) -> dict:
        if not self.var:
            return {}
        if hasattr(self.m, "al"):
            sonuc = {}
            for k in self.anahtarlar:
                try:
                    sonuc[k] = self.m.al("karar", k)
                except (KeyError, ValueError):
                    pass
            return sonuc
        return dict(self._hepsi().get("karar") or {})

    def yaz(self, degerler: dict) -> None:
        if not self.var:
            raise RuntimeError("deskhand.ayarlar yok")
        if hasattr(self.m, "ayarla"):
            for k in self.anahtarlar:
                if k in degerler:
                    self.m.ayarla("karar", k, degerler[k])
            return
        d = self._hepsi()
        d.setdefault("karar", {}).update({k: v for k, v in degerler.items() if k in KARAR_ANAHTARLARI})
        (getattr(self.m, "yaz", None) or getattr(self.m, "kaydet"))(d)
