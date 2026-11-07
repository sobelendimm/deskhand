"""Girdi günlüğünün (STATE_DIR/gunluk-YYYYAAGG.log) ayrıştırılması ve kuyruk (tail) okuması. Qt'siz.

Satır biçimleri (deskhand/gunluk.py: "HH:MM:SS <satır>"):
  <etiket> | [<başlık>] | <satırlar>                 kullanıcının ekranı (kde arka ucu)
  <etiket> | arka :90 [<başlık>] | <satırlar>         arka plan masaüstü (sanal arka uç)
  <etiket> | bırak | <satır>,  <etiket> | arka bırak | <satır>
  DUR <kod> | <komut> <kimlik> | <mesaj>             bir komut durduruldu
  DUR anahtarı açıldı / kaldırıldı
  ac | <ad> | <komut>,  akis <dosya> | ekran '<ad>' | <adımlar>,  erisim | <işlem>,  kapat | [<b>] | windowclose
  onay <sonuç> | [<hedef>] | <eylem>   (onay <sonuç> | arka sanal [<hedef>] | <eylem>)
"""
from __future__ import annotations

import os
import re
import time

from .. import yollar

SATIR = re.compile(r"^(\d\d:\d\d:\d\d) (.*)$")
PENCERELI = re.compile(r"^(?P<etiket>.*?) \| (?:arka (?P<ekran>\S+) )?\[(?P<pencere>.*?)\] \| (?P<eylem>.*)$")
DUR_SATIRI = re.compile(r"^DUR (?P<kod>\d+) \| (?P<komut>.*?) \| (?P<mesaj>.*)$")
BIRAK = re.compile(r"^(?P<etiket>.*?) \| (?P<arka>arka )?bırak \| (?P<eylem>.*)$")
KUYRUK = 500


def ayristir(satir: str) -> dict | None:
    """Bir günlük satırı → {zaman, arka ("ekran"|"arka"|""), pencere, eylem, tur, ham}. tur: girdi|dur|onay|diger.
    Biçimsiz satır None."""
    satir = satir.rstrip("\n")
    m = SATIR.match(satir)
    if not m:
        return None
    zaman, govde = m.groups()
    d = {"zaman": zaman, "arka": "", "pencere": "", "eylem": govde, "tur": "diger", "ham": satir}
    if govde.startswith("DUR "):
        d["tur"] = "dur"
        md = DUR_SATIRI.match(govde)
        if md:
            komut, _, kimlik = md.group("komut").partition(" ")
            d["arka"] = "arka" if kimlik.startswith("arka:") else ("ekran" if kimlik else "")
            d["pencere"] = kimlik
            d["eylem"] = f"DUR {md.group('kod')} · {komut}: {md.group('mesaj')}"
        return d
    mb = BIRAK.match(govde)
    if mb:
        d.update(arka="arka" if mb.group("arka") else "ekran", tur="girdi",
                 eylem=f"{mb.group('etiket')}: bırak {mb.group('eylem')}")
        return d
    mp = PENCERELI.match(govde)
    if mp:
        etiket = mp.group("etiket")
        d.update(arka="arka" if mp.group("ekran") else "ekran", pencere=mp.group("pencere"),
                 eylem=f"{etiket}: {mp.group('eylem')}")
        d["tur"] = "onay" if etiket.startswith("onay ") else "girdi"
        return d
    parcalar = govde.split(" | ", 2)
    if len(parcalar) == 3:
        etiket, orta, son = parcalar
        d.update(pencere=orta, eylem=f"{etiket}: {son}")
        if etiket in ("ac",) or etiket.startswith("akis "):
            d["tur"] = "girdi"
    elif len(parcalar) == 2:
        d["eylem"] = f"{parcalar[0]}: {parcalar[1]}"
    return d


def gunluk_adi(t: float | None = None) -> str:
    return time.strftime("gunluk-%Y%m%d.log", time.localtime(time.time() if t is None else t))


def _son_satirlar(yol: str, n: int) -> tuple[list[str], int]:
    """Dosyanın son n satırı + dosya sonu konumu (blok blok geriye okur; tüm dosyayı belleğe almaz)."""
    try:
        with open(yol, "rb") as f:
            f.seek(0, os.SEEK_END)
            son = f.tell()
            blok, veri, konum = 65536, b"", son
            while konum > 0 and veri.count(b"\n") <= n:
                oku = min(blok, konum)
                konum -= oku
                f.seek(konum)
                veri = f.read(oku) + veri
    except OSError:
        return [], 0
    tam = veri.endswith(b"\n")
    satirlar = veri.split(b"\n")
    if tam:
        satirlar = satirlar[:-1]
        bitis = son
    else:  # son satır yarım (yazılıyor): okunmuş sayma, sonra baştan okunur
        bitis = son - len(satirlar[-1])
        satirlar = satirlar[:-1]
    return [s.decode("utf-8", "replace") for s in satirlar[-n:]], bitis


class GunlukOkuyucu:
    """Bugünün günlük dosyasını kuyruk mantığıyla okur: ilk() son KUYRUK satırı, yeni() yalnız eklenenleri döndürür.
    Gün dönümü (yeni dosya), dosyanın kırpılması/silinmesi ve yarım yazılmış son satır ele alınır."""

    def __init__(self, dizin_f=yollar.gunluk_dizin, saat=time.time):
        self.dizin_f, self.saat = dizin_f, saat
        self.yol: str | None = None
        self.konum = 0
        self.son_ino = None

    def bugunku(self) -> str:
        return os.path.join(self.dizin_f(), gunluk_adi(self.saat()))

    def ilk(self, n: int = KUYRUK) -> list[dict]:
        yol = self.bugunku()
        satirlar, self.konum = _son_satirlar(yol, n)
        if len(satirlar) < n:  # gece yarısından hemen sonra: dünün sonunu da göster
            dun = os.path.join(self.dizin_f(), gunluk_adi(self.saat() - 86400))
            onceki, _ = _son_satirlar(dun, n - len(satirlar))
            satirlar = onceki + satirlar
        self.yol = yol
        self.son_ino = self._ino(yol)
        return [d for d in map(ayristir, satirlar) if d]

    @staticmethod
    def _ino(yol):
        try:
            return os.stat(yol).st_ino
        except OSError:
            return None

    def _oku(self, yol: str, konum: int) -> tuple[list[str], int]:
        try:
            with open(yol, "rb") as f:
                f.seek(0, os.SEEK_END)
                boy = f.tell()
                if boy < konum:  # kırpıldı/yeniden yazıldı: baştan
                    konum = 0
                f.seek(konum)
                veri = f.read(boy - konum)
        except OSError:
            return [], 0
        kesim = veri.rfind(b"\n")
        if kesim < 0:
            return [], konum
        tam = veri[:kesim]
        return [s.decode("utf-8", "replace") for s in tam.split(b"\n")], konum + kesim + 1

    def yeni(self) -> list[dict]:
        if self.yol is None:
            return self.ilk()
        satirlar: list[str] = []
        bugun = self.bugunku()
        if bugun != self.yol:  # gün döndü: eskinin kalanını bitir, yenisine baştan geç
            eski, _ = self._oku(self.yol, self.konum)
            satirlar += eski
            self.yol, self.konum, self.son_ino = bugun, 0, None
        ino = self._ino(self.yol)
        if ino is not None and self.son_ino is not None and ino != self.son_ino:
            self.konum = 0  # dosya silinip yeniden oluşturuldu
        self.son_ino = ino
        yeni, self.konum = self._oku(self.yol, self.konum)
        satirlar += yeni
        return [d for d in map(ayristir, satirlar) if d]

    def son_degisim(self) -> float | None:
        """Bugünün günlüğünün son yazılma zamanı (mtime) ya da None."""
        try:
            return os.stat(self.bugunku()).st_mtime
        except OSError:
            return None


def onay_gecmisi(satirlar: list[dict]) -> list[dict]:
    """Günlükteki "onay …" satırları → [{zaman, eylem, hedef, masaustu, sonuc}] (Onaylar › Geçmiş)."""
    sonuc = []
    for d in satirlar:
        if d.get("tur") != "onay":
            continue
        etiket, _, eylem = d["eylem"].partition(": ")
        sonuc.append({"zaman": d["zaman"], "eylem": eylem, "hedef": d["pencere"],
                      "masaustu": d["arka"] or "ekran", "sonuc": etiket.split(" ", 1)[1] if " " in etiket else ""})
    return sonuc
