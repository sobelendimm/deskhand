"""Panel/tepsi durumunun türetilmesi (Qt'siz, test edilebilir).

Kaynaklar: DUR dosyası (guvenlik.dur_kaynagi), günlüğün son satırı + son yazılma zamanı, bekleyen onaylar,
sanal masaüstü durum dosyası (RUNTIME_DIR/sanal.json; yoksa "kapalı") ve Devral bayrağı.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .. import yollar
from ..i18n import _
from . import metinler as T

CALISMA_PENCERESI = 4.0  # son girdi satırı bu kadar yeniyse "çalışıyor"
RENK = {"bos": "#8a8f98", "ekran": "#e8590c", "arka": "#1c7ed6", "dur": "#e03131", "rozet": "#fab005"}


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
            satirlar[0] += f" ({_(T.DUR_KAYNAK.get(self.dur_kaynak, self.dur_kaynak))})"
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
        return os.path.join(yollar.runtime_dir(), "devral")


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
        with open(os.path.join(yollar.runtime_dir(), "sanal.json")) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None
