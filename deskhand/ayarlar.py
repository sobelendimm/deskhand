"""Kullanıcı ayarları: CONFIG_DIR/ayarlar.toml (okuma tomllib; yazma basit TOML üreteci).

Dosya yoksa varsayılanlar kullanılır; OKUMA dosya oluşturmaz. Bilinmeyen/yanlış türde değerler varsayılana düşer
(bir kez uyarı). Yazma atomiktir (geçici dosya + os.replace); yorumlar korunmaz.

  [karar]
  mesgulken = "sor"        # sor | arka | bekle   (kullanıcı meşgulken ne yapılsın; "hep-arka" = "arka")
  sor_sure = 45            # sn: bildirim yanıtı için bekleme
  cevapsiz = "arka"        # süre dolunca: arka | sonra
  girdi_esik_sn = 20       # son bu kadar sn'de insan girdisi varsa meşgul (etkinlik kaydı varsa)
  tam_ekranda_sor = false  # tam ekran (film/oyun) varken bildirimle sor (kritik bildirim) ya da sormadan 'cevapsiz'
"""
from __future__ import annotations

import os
import sys
import tempfile
import tomllib

from . import yollar
from .i18n import _

VARSAYILAN = {
    "karar": {
        "mesgulken": "sor",
        "sor_sure": 45,
        "cevapsiz": "arka",
        "girdi_esik_sn": 20,
        "tam_ekranda_sor": False,
    },
}
TAKMA = {("karar", "mesgulken"): {"hep-arka": "arka"}}
SECENEK = {("karar", "mesgulken"): {"sor", "arka", "bekle"}, ("karar", "cevapsiz"): {"arka", "sonra"}}
ARALIK = {("karar", "sor_sure"): (1, 3600), ("karar", "girdi_esik_sn"): (0, 3600)}

_uyarilan = set()


def dosya() -> str:
    return os.path.join(yollar.config_dir(), "ayarlar.toml")


def _uyar(ileti):
    if ileti not in _uyarilan:
        _uyarilan.add(ileti)
        print(_("UYARI: ayarlar.toml: {ileti}").format(ileti=ileti), file=sys.stderr)


def ham_oku() -> dict:
    """Dosyadaki ham içerik (yoksa/bozuksa {})."""
    try:
        with open(dosya(), "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        _uyar(_("okunamadı ({hata}); varsayılanlar kullanılıyor").format(hata=e))
        return {}


def dogrula(bolum: str, anahtar: str, deger):
    """Değeri doğrula/dönüştür → geçerli değer; geçersizse ValueError."""
    if bolum not in VARSAYILAN or anahtar not in VARSAYILAN[bolum]:
        raise ValueError(_("bilinmeyen ayar: {ayar}").format(ayar=f"{bolum}.{anahtar}"))
    vars_ = VARSAYILAN[bolum][anahtar]
    if isinstance(vars_, bool):
        if isinstance(deger, str) and deger.lower() in ("true", "false", "evet", "hayir", "hayır", "1", "0"):
            deger = deger.lower() in ("true", "evet", "1")
        if not isinstance(deger, bool):
            raise ValueError(_("{ayar} true/false olmalı").format(ayar=f"{bolum}.{anahtar}"))
        return deger
    if isinstance(vars_, (int, float)):
        if isinstance(deger, bool):
            raise ValueError(_("{ayar} sayı olmalı").format(ayar=f"{bolum}.{anahtar}"))
        try:
            deger = type(vars_)(deger)
        except (TypeError, ValueError):
            raise ValueError(_("{ayar} sayı olmalı").format(ayar=f"{bolum}.{anahtar}")) from None
        alt, ust = ARALIK.get((bolum, anahtar), (None, None))
        if alt is not None and not alt <= deger <= ust:
            raise ValueError(_("{ayar} {alt}..{ust} arasında olmalı").format(ayar=f"{bolum}.{anahtar}", alt=alt, ust=ust))
        return deger
    if not isinstance(deger, str):
        raise ValueError(_("{ayar} metin olmalı").format(ayar=f"{bolum}.{anahtar}"))
    deger = TAKMA.get((bolum, anahtar), {}).get(deger, deger)
    secenek = SECENEK.get((bolum, anahtar))
    if secenek and deger not in secenek:
        raise ValueError(_("{ayar} şunlardan biri olmalı: {secenekler}").format(
            ayar=f"{bolum}.{anahtar}", secenekler=" | ".join(sorted(secenek))))
    return deger


def oku() -> dict:
    """Varsayılanlar + dosya (doğrulanmış). Dönen sözlük kopyadır."""
    sonuc = {b: dict(v) for b, v in VARSAYILAN.items()}
    for bolum, icerik in ham_oku().items():
        if bolum not in VARSAYILAN or not isinstance(icerik, dict):
            continue
        for anahtar, deger in icerik.items():
            if anahtar not in VARSAYILAN[bolum]:
                _uyar(_("bilinmeyen ayar yok sayıldı: {ayar}").format(ayar=f"{bolum}.{anahtar}"))
                continue
            try:
                sonuc[bolum][anahtar] = dogrula(bolum, anahtar, deger)
            except ValueError as e:
                _uyar(_("{hata}; varsayılan ({deger}) kullanılıyor").format(hata=e, deger=repr(VARSAYILAN[bolum].get(anahtar))))
    return sonuc


def al(bolum: str, anahtar: str):
    return oku()[bolum][anahtar]


# ---------------------------------------------------------------- yazma

def _toml_deger(d) -> str:
    if isinstance(d, bool):
        return "true" if d else "false"
    if isinstance(d, (int, float)):
        return repr(d)
    if isinstance(d, str):
        kacis = d.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{kacis}"'
    if isinstance(d, (list, tuple)):
        return "[" + ", ".join(_toml_deger(x) for x in d) + "]"
    raise TypeError(f"TOML'a yazılamayan tür: {type(d).__name__}")


def _anahtar(a: str) -> str:
    return a if a and all(c.isalnum() or c in "-_" for c in a) and a.isascii() else _toml_deger(a)


def toml_uret(ayarlar: dict) -> str:
    """Tek düzeyli bölümler ([bolum] anahtar = değer) içeren basit TOML."""
    satirlar = ["# Deskhand ayarları (deskhand). Açıklama: deskhand/ayarlar.py"]
    for bolum, icerik in ayarlar.items():
        satirlar += ["", f"[{_anahtar(bolum)}]"]
        for anahtar, deger in icerik.items():
            satirlar.append(f"{_anahtar(anahtar)} = {_toml_deger(deger)}")
    return "\n".join(satirlar) + "\n"


def yaz(ayarlar: dict) -> str:
    """Tüm ayarları dosyaya yaz (atomik). → dosya yolu."""
    yol = dosya()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    metin = toml_uret(ayarlar)
    tomllib.loads(metin)  # ürettiğimiz geri okunabilmeli
    fd, gecici = tempfile.mkstemp(dir=os.path.dirname(yol), prefix=".ayarlar-", suffix=".toml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(metin)
        os.replace(gecici, yol)
    except BaseException:
        try:
            os.remove(gecici)
        except OSError:
            pass
        raise
    return yol


def ayarla(bolum: str, anahtar: str, deger) -> str:
    """Tek bir ayarı doğrulayıp yaz (dosyadaki diğer ayarlar korunur)."""
    deger = dogrula(bolum, anahtar, deger)
    ham = ham_oku()
    ham.setdefault(bolum, {})[anahtar] = deger
    return yaz(ham)
