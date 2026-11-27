"""Panel/tepsi durumunun türetilmesi (Qt'siz, test edilebilir).

Kaynaklar: DUR dosyası (guvenlik.dur_kaynagi), günlüğün son satırı + son yazılma zamanı, bekleyen onaylar,
sanal masaüstü durum dosyası (RUNTIME_DIR/sanal.json; yoksa "kapalı") ve Devral bayrağı.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from .. import yollar
from ..i18n import _
from . import metinler as T

CALISMA_PENCERESI = 4.0  # son girdi satırı bu kadar yeniyse "çalışıyor"
RENK = {"bos": "#8a8f98", "ekran": "#e8590c", "arka": "#1c7ed6", "dur": "#e03131", "rozet": "#fab005"}


def etiket_kacis(k: str, html: bool = False) -> str:
    """An unknown DUR source label (written by any same-uid process): printable ASCII only, the rest as \\u{XXXX},
    at most 64 characters (review INC6 D3). html=True (a tooltip that may be drawn as rich text): < > & as well."""
    def kac(c):
        return 0x20 <= ord(c) < 0x7F and not (html and c in "<>&")
    return "".join(c if kac(c) else f"\\u{{{ord(c):04X}}}" for c in str(k)[:64])


@dataclass(frozen=True)
class Durum:
    ad: str = "bos"                 # bos | ekran | arka | dur
    dur_kaynak: str | None = None   # kullanici | cli | None
    bekleyen: int = 0               # bekleyen onay sayısı (sarı rozet)
    sanal_acik: bool = False
    sanal_ekran: str = ""
    devral: bool = False
    son_eylem: str = ""

    @property
    def renk(self) -> str:
        return RENK[self.ad]

    @property
    def metin(self) -> str:
        return _(T.DURUM[self.ad])

    def ipucu(self) -> str:
        satirlar = [f"{T.UYGULAMA} — {self.metin}"]
        if self.ad == "dur" and self.dur_kaynak:
            ad = T.DUR_KAYNAK.get(self.dur_kaynak)
            # an unknown label comes from the DUR file (any same-uid process): escaped, never markup (review INC6 D3;
            # the tray tooltip is drawn as rich text by Plasma)
            satirlar[0] += f" ({_(ad) if ad else etiket_kacis(self.dur_kaynak, html=True)})"
        if self.bekleyen:
            satirlar.append(_(T.ONAY_BEKLIYOR).format(n=self.bekleyen))
        satirlar.append(_(T.SANAL_ACIK).format(ekran=self.sanal_ekran) if self.sanal_acik else _(T.SANAL_KAPALI))
        if self.devral:
            satirlar.append(_(T.DEVRAL_ACIK))
        if self.son_eylem and self.ad in ("ekran", "arka"):
            from .dil import _komut_adlari
            satirlar.append(_komut_adlari(self.son_eylem)[:120])
        return "\n".join(satirlar)


def durum_turet(dur_kaynak: str | None, son_satir: dict | None, son_yazim: float | None, simdi: float,
                bekleyen: int = 0, sanal: dict | None = None, devral: bool = False) -> Durum:
    """DUR her şeyin önündedir; değilse son girdi satırı CALISMA_PENCERESI içindeyse o satırın masaüstü."""
    ad = "bos"
    son_eylem = ""
    if dur_kaynak:
        ad = "dur"
    elif son_satir and son_yazim is not None and simdi - son_yazim <= CALISMA_PENCERESI \
            and son_satir.get("tur") == "girdi":
        ad = "arka" if son_satir.get("arka") == "arka" else "ekran"
        son_eylem = son_satir.get("eylem", "")
    return Durum(ad=ad, dur_kaynak=dur_kaynak, bekleyen=int(bekleyen), sanal_acik=sanal is not None,
                 sanal_ekran=str((sanal or {}).get("ekran") or ""), devral=bool(devral), son_eylem=son_eylem)


def devral_yolu() -> str:
    try:
        from .. import masaustu
        return masaustu.devral_yolu()
    except Exception:  # noqa: BLE001 - masaustu modülü yoksa aynı sözleşme
        from .. import masalar
        return masalar.devral_yolu("")


def devral_var(yol: str | None = None) -> bool:
    """Devral açık mı: dosya var VE yazan panel yaşıyor (masaustu.devral_var). Modül yüklenemezse dosyanın
    varlığı (güvenli taraf: ajan bekler)."""
    yol = yol or devral_yolu()
    try:
        from .. import masaustu
        return masaustu.devral_var(yol)
    except Exception:  # noqa: BLE001
        return os.path.exists(yol)


def devral_icerik() -> str:
    try:
        from .. import masaustu
        return masaustu.devral_icerik()
    except Exception:  # noqa: BLE001
        return f"panel {os.getpid()} -\n"


def devral_sahipsiz_sil(yol: str | None = None) -> bool:
    """Panel açılışında: önceki (çökmüş) panelden kalan sahipsiz Devral dosyasını sil. → silindi mi."""
    yol = yol or devral_yolu()
    try:
        from .. import masaustu
        return masaustu.devral_sil(yalniz_kendi=True, yol=yol)
    except Exception:  # noqa: BLE001
        return False


def sanal_durum(dogrula: bool = True) -> dict | None:
    """Sanal masaüstü durumu: masaustu.durum() (PID/soket doğrulamalı); modül yoksa sanal.json'u ham okur."""
    try:
        from .. import masaustu
    except Exception:  # noqa: BLE001
        masaustu = None
    if masaustu is not None and hasattr(masaustu, "durum"):
        try:
            return masaustu.durum(dogrula=dogrula)
        except TypeError:
            return masaustu.durum()
        except Exception:  # noqa: BLE001
            return None
    try:
        from .. import masalar
        with open(masalar.durum_yolu("")) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- çoklu arka plan masaüstü (SALT OKUMA)

def _masaustu_durumu(m, ad: str) -> dict | None:
    """Bir masaüstünün doğrulanmış durumu (masaustu.durum(ad=…, saglik=False)). `ad` parametresi olmayan eski/sahte
    modülde yalnız varsayılan masaüstü okunur."""
    try:
        return m.durum(saglik=False, ad=ad)
    except TypeError:
        if ad != "":
            return None
        try:
            return m.durum()
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001 - bozuk kayıt / yarışta silinmiş: listelenmez
        return None


def masa_listesi(masaustu_m=None) -> list[dict]:
    """O an ÇALIŞAN arka plan masaüstleri: [{ad, ekran, tur, baslangic, boyut, durum}] (varsayılan "" önce, sonra
    adlılar sıralı). SALT OKUR: masalar.adlar() (dizin listesi) + masaustu.durum(ad=…, saglik=False) (PID/soket
    doğrulamalı). Hiçbir masaüstünü başlatmaz, durdurmaz, temizlemez; sahiplik dosyasına dokunmaz."""
    from .. import masalar
    m = masaustu_m
    if m is None:
        try:
            from .. import masaustu as m
        except Exception:  # noqa: BLE001
            return []
    try:
        adlar = [a for a in masalar.adlar() if a != ""]
    except Exception:  # noqa: BLE001
        adlar = []
    sonuc = []
    for ad in [""] + adlar:
        d = _masaustu_durumu(m, ad)
        if not isinstance(d, dict):
            continue
        bas = d.get("baslangic")
        if not isinstance(bas, (int, float)):
            try:
                bas = os.path.getmtime(masalar.durum_yolu(ad))
            except Exception:  # noqa: BLE001
                bas = None
        sonuc.append({"ad": ad, "ekran": str(d.get("ekran") or ""), "tur": str(d.get("tur") or ""),
                      "baslangic": bas, "boyut": list(d.get("boyut") or [])[:2], "durum": d})
    return sonuc


def sure_metni(sn: float | None) -> str:
    """Süre → kısa metin: "12 sn", "5 dk", "2 sa 3 dk" (negatif/None: 0 sn)."""
    sn = max(0, int(sn or 0))
    if sn < 60:
        return _(T.A_SURE_SN).format(n=sn)
    if sn < 3600:
        return _(T.A_SURE_DK).format(n=sn // 60)
    return _(T.A_SURE_SA).format(s=sn // 3600, d=(sn % 3600) // 60)


def saat_epoch(zaman: str, simdi: float) -> float | None:
    """Günlük satırının "HH:MM:SS" saati → epoch (bugün; gelecekteyse dün: gece yarısından önceki satırlar)."""
    try:
        h, dk, sn = (int(x) for x in zaman.split(":"))
    except (ValueError, AttributeError):
        return None
    lt = time.localtime(simdi)
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, dk, sn, 0, 0, -1))
    if t > simdi + 300:
        t -= 86400
    return t


_GIZLI_IZ = re.compile(r"\*\*\*|(?:^|[\s;:])(?:type|keydown|keyup)\s")


def guvenli_eylem(e: dict) -> str:
    """Bir girdi kaydının GÖSTERİLEBİLİR özeti: yalnız komut etiketi (ör. "tikla (617,761) sol", "ogeye-tikla
    'Kaydet' sol", "yaz 12 karakter"); günlüğün satırlar kısmı (`type …` = yazılan metin) HİÇ kullanılmaz. Günlükte
    maskeli (***) girdi ya da etikette bir yazı/tuş satırı izi → "gizli alana yazı" (içerik yok)."""
    etiket = str(e.get("etiket") or "")
    if e.get("gizli") or not etiket or _GIZLI_IZ.search(etiket):
        return _(T.A_EYLEM_GIZLI)
    from .dil import _komut_adlari
    return _komut_adlari(etiket)[:100]


class SonEylemler:
    """Arka plan masaüstü başına (ekran adıyla) SON girdi kaydı: günlük satırlarından (gunluk_okur.ayristir) beslenir.
    Yalnız arka plan satırları ("arka <ekran> [...]"); kullanıcının ekranı ve DUR satırları sayılmaz."""

    def __init__(self):
        self._son: dict[str, dict] = {}

    def ekle(self, satirlar: list[dict], simdi: float) -> None:
        for d in satirlar or []:
            if not d or d.get("tur") != "girdi" or d.get("arka") != "arka" or not d.get("ekran"):
                continue
            t = saat_epoch(d.get("zaman", ""), simdi)
            if t is None:
                continue
            self._son[d["ekran"]] = {"zaman": t, "etiket": d.get("etiket", ""), "pencere": d.get("pencere", ""),
                                     "gizli": bool(d.get("gizli"))}

    def son(self, ekran: str, baslangic: float | None = None) -> dict | None:
        """`ekran`ın son eylemi; masaüstü `baslangic`tan ÖNCEKİ kayıt (aynı ekran adını kullanmış eski masaüstü) yok
        sayılır."""
        e = self._son.get(ekran or "")
        if e is None or (baslangic is not None and e["zaman"] < baslangic - 2):
            return None
        return e


def eylem_satiri(e: dict | None, simdi: float) -> str:
    """"Ajan şu an ne yapıyor" satırı."""
    if e is None:
        return _(T.A_EYLEM_YOK)
    pencere = str(e.get("pencere") or "?")
    if len(pencere) > 60:
        pencere = pencere[:59] + "…"
    return _(T.A_EYLEM).format(eylem=guvenli_eylem(e), pencere=pencere,
                               once=_(T.A_ONCE).format(sure=sure_metni(simdi - e["zaman"])))
