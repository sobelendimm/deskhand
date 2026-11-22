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
    """Yasak listesinin metni: panel koruyucusu etkinse BELLEKTEKİ yetkili kopya; değilse dosya; yoksa varsayılan
    (dosya OLUŞTURULMAZ: yalnız Kaydet yazar)."""
    from .. import liste_koruma
    if liste_koruma.AKTIF is not None and liste_koruma.AKTIF.metin("yasak") is not None:
        return liste_koruma.AKTIF.metin("yasak")
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
    from .. import liste_koruma
    liste_koruma.panel_kaydet("yasak", metin if metin.endswith("\n") else metin + "\n")  # panel: tek yetkili yazar


# ---------------------------------------------------------------- uygulama erişim seviyeleri

def seviye_metni() -> str:
    """uygulama-seviyeleri.txt metni; yoksa açıklamalı boş şablon (dosya OLUŞTURULMAZ: yalnız Kaydet yazar).
    Varsayılan kurulumda dosyada hiçbir kural satırı yoktur. Panel koruyucusu etkinse bellekteki yetkili kopya."""
    from .. import liste_koruma
    if liste_koruma.AKTIF is not None and liste_koruma.AKTIF.metin("seviye") is not None:
        return liste_koruma.AKTIF.metin("seviye")
    try:
        with open(yollar.seviye_dosya()) as f:
            return f.read()
    except OSError:
        from ..guvenlik import VARSAYILAN_SEVIYE
        from ..i18n import _
        return _(VARSAYILAN_SEVIYE)


def seviye_dogrula(metin: str) -> tuple[int, str] | None:
    """Her kural satırı `DESEN = goruntule|tikla|tam` (ya da view|click|full) olmalı, DESEN derlenebilmeli.
    → (satır no, hata) ya da None."""
    from ..guvenlik import SEVIYELER
    from ..i18n import _
    for no, satir in enumerate(metin.splitlines(), 1):
        s = satir.strip()
        if not s or s.startswith("#"):
            continue
        desen, ayrac, sev = s.rpartition("=")
        if not ayrac or not desen.strip():
            return no, _("DESEN = goruntule | tikla | tam biçiminde olmalı")
        if sev.strip().lower() not in SEVIYELER:
            return no, _("bilinmeyen seviye {sev}; goruntule, tikla ya da tam olmalı").format(sev=repr(sev.strip()))
        try:
            re.compile(desen.strip(), re.I)
        except re.error as e:
            return no, str(e)
    return None


def seviye_kaydet(metin: str) -> None:
    hata = seviye_dogrula(metin)
    if hata:
        raise ValueError(hata)
    from .. import liste_koruma
    liste_koruma.panel_kaydet("seviye", metin if metin.endswith("\n") else metin + "\n")  # panel: tek yetkili yazar


# ---------------------------------------------------------------- onay kapsamı ([guvenlik] onaylar)

ONAY_KAPSAMLARI = ("hepsi", "kart")


def onay_kapsami_oku() -> str:
    from .. import guvenlik
    return guvenlik.onay_kapsami(taze=True)


def onay_kapsami_yaz(deger: str) -> None:
    if deger not in ONAY_KAPSAMLARI:
        raise ValueError(deger)
    from .. import guvenlik, liste_koruma
    liste_koruma.panel_kapsam_kaydet(deger)  # panel: tek yetkili yazar (bellek + ayarlar.toml + işaret)
    guvenlik.onay_kapsami_sifirla()


# ---------------------------------------------------------------- hesap oturumları ([guvenlik] hesap_oturumlari)

HESAP_SAGLAYICILARI = ("microsoft", "google", "edevlet")


def hesap_oturumlari_oku() -> frozenset:
    """Panelin bellekteki yetkili değeri (panel dışında yazılmış izin burada görünmez)."""
    from .. import liste_koruma
    return liste_koruma.kimlik_izinleri()


def hesap_oturumu_yaz(saglayici: str, acik: bool) -> frozenset:
    """Tek sağlayıcıyı aç/kapat (panel: tek yetkili yazar; açarken onay diyaloğu pencere.py'de). → yeni küme."""
    if saglayici not in HESAP_SAGLAYICILARI:
        raise ValueError(saglayici)
    from .. import liste_koruma
    k = set(hesap_oturumlari_oku())
    (k.add if acik else k.discard)(saglayici)
    liste_koruma.panel_kimlik_kaydet(liste_koruma.kimlik_metni(k))
    return hesap_oturumlari_oku()


def hesap_oturumlari_hepsi_yaz(acik: bool) -> frozenset:
    """Ana anahtar: üç sağlayıcıyı birlikte aç/kapat (banka/ödeme hiçbir izinde yok). → yeni küme."""
    from .. import liste_koruma
    liste_koruma.panel_kimlik_kaydet(liste_koruma.kimlik_metni(HESAP_SAGLAYICILARI if acik else ()))
    return hesap_oturumlari_oku()


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
