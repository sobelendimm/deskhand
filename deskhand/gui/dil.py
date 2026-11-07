"""Panelde dil değişimi (Qt'siz yardımcılar).

Panel, dil Ayarlar'dan değişince yeniden başlatılmaz: her bileşen görünen metinlerini bir ``Metinler`` kaydına
yazar; ``tazele()`` hepsini yeni dilde yeniden uygular (i18n.yeniden_yukle sonrası). Böylece günlük akışı,
onay geçmişi, Devral durumu ve yazılmış ama kaydedilmemiş ayarlar korunur.

    self.m = Metinler()
    self.m(dugme.setText, T.A_BASLAT)            # şimdi uygular + kaydeder
    self.m.fn(lambda: tablo.setHorizontalHeaderLabels([_(s) for s in T.O_SUTUNLAR]))
    ...
    self.m.tazele()                              # dil değişti
"""
from __future__ import annotations

from .. import i18n
from ..i18n import _
from . import metinler as T


class Metinler:
    """(işlev) kaydı: her biri bir metni ayarlar; kayıtta bir kez, tazele()'de yeniden çağrılır."""

    def __init__(self):
        self._islevler: list = []

    def fn(self, f):
        f()
        self._islevler.append(f)
        return f

    def __call__(self, ayarla, msgid: str, **bicim):
        return self.fn(lambda: ayarla(_(msgid).format(**bicim) if bicim else _(msgid)))

    def tazele(self) -> None:
        for f in self._islevler:
            f()


def dil_secenekleri() -> list[tuple[str, str]]:
    """Dil seçicinin öğeleri [(kod, görünen ad)]: Otomatik (sistem dili) + her dil kendi adıyla (çevrilmez);
    katalogu %95'ten az çevrilmiş dile oran eklenir (çevrilmeyen metinler Türkçe görünür)."""
    sistem = i18n.sistem_dili()
    sonuc = [(i18n.OTOMATIK, _(T.Y_DIL_OTOMATIK).format(dil=i18n.DILLER.get(sistem, sistem)))]
    for kod, ad in i18n.DILLER.items():
        oran = i18n.kapsama(kod)
        if oran is not None and oran < 0.95:
            ad = f"{ad} ({oran:.0%})"
        sonuc.append((kod, ad))
    return sonuc


def gunluk_eylemi(d: dict) -> str:
    """Etkinlik satırının Eylem sütunu: günlük metni (Türkçe) olduğu gibi; yalnız sabit satırlar ve onay
    satırlarının "onay <karar>" öneki çevrilir."""
    eylem = d.get("eylem", "")
    if eylem in T.GUNLUK_ESLEME:
        return _(T.GUNLUK_ESLEME[eylem])
    if d.get("tur") == "onay" and eylem.startswith("onay "):
        karar, ayrac, kalan = eylem[5:].partition(": ")
        if ayrac and karar in T.O_KARAR:
            return _(T.E_ONAY_SATIRI).format(karar=_(T.O_KARAR[karar]), eylem=kalan)
    return _komut_adlari(eylem)


_SOZ = {"sol": "left", "sag": "right", "cift": "double", "orta": "middle", "karakter": "chars", "asagi": "down",
        "yukari": "up", "basili": "held", "kez": "times"}


def _komut_adlari(eylem: str) -> str:
    """İngilizce arayüzde günlükteki Türkçe komut sözcüklerini (tikla, metne-tikla, yaz 11 karakter, ac:) YALNIZ
    GÖSTERİRKEN İngilizce adlarına çevirir; günlük dosyası ve süzgeç Türkçe kalır. Türkçe arayüzde dokunmaz."""
    from .. import i18n, komutlar
    if i18n.dil() == "tr" or not eylem:
        return eylem
    import re
    dur = re.match(r"^DUR (\d+) · ([a-z-]+):", eylem)  # "DUR 4 · yaz: …" → "STOP 4 · type: …"
    if dur:
        eylem = f"{_('DUR')} {dur.group(1)} · {komutlar.TR_EN.get(dur.group(2), dur.group(2))}:" + eylem[dur.end():]
    bas = re.match(r"^(dizi: )?([a-z-]+)(:?)(?=\s|$)", eylem)
    if bas and bas.group(2) in komutlar.TR_EN:
        eylem = (bas.group(1) or "") + komutlar.TR_EN[bas.group(2)] + bas.group(3) + eylem[bas.end():]
    return re.sub(r"(?<=[\s)])(" + "|".join(_SOZ) + r")(?=[\s:;,]|$)", lambda m: _SOZ[m.group(1)], eylem)
