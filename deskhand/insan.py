"""İNSAN ÖNCELİĞİ: kullanıcı klavyeyi ya da fareyi kullanıyorsa girdi gönderilmez.

Etkinlik: Wayland ext-idle-notify-v1 (C yardımcısı `deskhand-etkinlik`, kaynak deskhand/yardimci/) ile klavye + fare
etkinliği. insan_bekle: fare tabanlı bekleme. klavye_bekle: etkinlik tabanlı bekleme.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from . import yollar
from .hata import Dur
from .i18n import _

ETKINLIK_MS = 50   # bu kadar ms hiç girdi yoksa 'bosta'; sonraki ilk girdi 'aktif'
KENDI_PAY = 0.12   # kendi girdimizin compositor'a ulaşıp 'aktif' olayı üretmesi için zaman payı (sn)
# YALNIZ TESTLER: bu süreç İNSANI TAKLİT ediyor (ör. yazarken fareyi oynatan ikinci süreç) → kendisi insan
# önceliği için beklemez. Gerçek kullanımda ASLA verilmez.
INSAN_TAKLIDI = os.environ.get("DESKHAND_INSAN_TAKLIDI") == "1" or os.environ.get("EKRAN_INSAN_TAKLIDI") == "1"
HARF_SN = 0.013  # harf başına: girdi dili typehold 6 + typedelay 4 ms + pay (yazma ~75 harf/sn)


def girdi_suresi(satirlar):
    """Girdi satırlarının (dotool satır dili) yaklaşık süresi: kendi girdi penceremiz için."""
    s = 0.0
    for x in satirlar:
        if x.startswith("type "):
            s += (len(x) - 5) * HARF_SN
        elif x.startswith(("key ", "click ")):
            s += 0.03
        elif x.startswith(("mouseto", "wheel", "hwheel", "keydown", "keyup", "buttondown", "buttonup")):
            s += 0.01
    return s


class Etkinlik:
    """KLAVYE + FARE etkinliği (insan önceliğinin klavye ayağı). Wayland ext-idle-notify-v1 v2 ile: yetki
    gerekmez (input grubu/sudo yok), video oynarken uyku engelleyicilerinden etkilenmez. Yardımcı süreç
    ETKINLIK_MS boyunca girdi yoksa 'bosta', ardından ilk girdide 'aktif' bildirir. Kendi girdilerimiz de
    'aktif' üretir → gönderdiğimiz her girdi zaman penceresiyle kaydedilir; pencere DIŞINDAKİ etkinlik insandır.
    Sınır: biz kesintisiz yazarken (harf arası ~13 ms < 50 ms) araya giren insan tuşu ayrılamaz; orada fare
    gözcüsü sürer. Yardımcı yoksa/çalışmazsa sessizce eski davranış (yalnız fare) + bir kez uyarı."""

    def __init__(self):
        self.olaylar = []
        self.kendi = []  # [[bas, son]] birleştirilmiş kendi girdi pencerelerimiz
        self.hata = None
        self.hazir_an = None
        self._hazir = threading.Event()
        try:
            self.p = subprocess.Popen([yollar.etkinlik_bin(), str(ETKINLIK_MS)], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        except OSError as e:
            self.p, self.hata = None, _("başlatılamadı: {hata}").format(hata=e)
            self._hazir.set()
            return
        threading.Thread(target=self._oku, daemon=True).start()

    def _oku(self):
        for satir in self.p.stdout:
            t = satir.split()
            if not t:
                continue
            if t[0] in ("bosta", "aktif"):
                self.olaylar.append((t[0], float(t[1])))
                if len(self.olaylar) > 600:
                    del self.olaylar[:300]
            elif t[0] == "hazir":
                self.hazir_an = float(t[-1])
                self._hazir.set()
            elif t[0] == "hata":
                self.hata = satir.strip()
                self._hazir.set()
        if not self._hazir.is_set():
            self.hata = self.hata or _("yardımcı süreç kapandı")
            self._hazir.set()

    def calisiyor(self):
        self._hazir.wait(1.0)
        if self.hata or self.hazir_an is None:
            if not getattr(Etkinlik, "_uyarildi", False):
                Etkinlik._uyarildi = True
                print(_("UYARI: klavye etkinliği izlenemiyor ({neden}); yalnız fare izleniyor").format(
                    neden=self.hata or _("zaman aşımı")), file=sys.stderr)
            return False
        return True

    def kendi_girdi(self, bas, son):
        """Biz [bas, son] arasında girdi gönderdik (pay eklenir, çakışanlar birleşir)."""
        bas, son = bas - 0.005, son + KENDI_PAY
        if self.kendi and bas <= self.kendi[-1][1]:
            self.kendi[-1][1] = max(self.kendi[-1][1], son)
        else:
            self.kendi.append([bas, son])
            if len(self.kendi) > 400:
                del self.kendi[:200]

    def _bizim(self, t):
        return any(b <= t <= s for b, s in reversed(self.kendi))

    def insan(self, beri):
        """'beri' anından bu yana İNSAN girdisi var mı? (1) bizim pencerelerimiz dışında 'aktif' olayı, ya da
        (2) etkinlik hâlâ sürüyor ('bosta' gelmedi) ama bizim girdimiz bitmiş / hiç girdimiz yok."""
        if not self.calisiyor():
            return False
        simdi = time.monotonic()
        olaylar = list(self.olaylar)
        if any(tur == "aktif" and t >= beri and not self._bizim(t) for tur, t in olaylar):
            return True
        if not olaylar:  # yardımcı başladığından beri hiç 'bosta' gelmedi = kesintisiz girdi
            return simdi - self.hazir_an > ETKINLIK_MS / 1000 + 0.15
        tur, t = olaylar[-1]
        if tur != "aktif":
            return False
        if not self._bizim(t):
            return True  # insan başlattı, sürüyor
        return simdi > self.kendi[-1][1] + ETKINLIK_MS / 1000 + 0.05  # bizimki bitti, etkinlik sürüyor → insan

    def sessiz_mi(self, sure=1.5):
        """Son 'sure' saniyedir hiç girdi yok mu? (beklerken biz girdi göndermeyiz → her girdi insanındır)"""
        olaylar = list(self.olaylar)
        if not olaylar or olaylar[-1][0] != "bosta":
            return False
        son_girdi = olaylar[-1][1] - ETKINLIK_MS / 1000
        if len(olaylar) == 1 or olaylar[-2][0] != "aktif":  # yardımcı açılınca ilk 'bosta': öncesi bilinmez
            son_girdi = min(son_girdi, (self.hazir_an or 0))
        return time.monotonic() - son_girdi >= sure

    def kapat(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()


def klavye_bekle(etk, beri, azami=8.0):
    """İNSAN ÖNCELİĞİ (klavye + fare): 'beri'den bu yana insan girdisi varsa, 1,5 sn hiç girdi olmayana dek
    bekle (en çok 'azami' sn), yoksa DUR 12. Kullanıcı ör. terminale yazarken araç araya girmesin."""
    if etk is None or not etk.insan(beri):
        return
    print(_("bekleniyor: kullanıcı klavye/fare kullanıyor…"), file=sys.stderr)
    bitis = time.monotonic() + azami
    while time.monotonic() < bitis:
        if etk.sessiz_mi(1.5):
            return
        time.sleep(0.05)
    raise Dur(12, _("kullanıcı {sn} sn boyunca klavye/fare kullandı (insan önceliği); girdi gönderilmedi").format(
        sn=f"{azami:.0f}"))


def insan_bekle(f0, fare, azami=8.0):
    """İNSAN ÖNCELİĞİ: girdi aracı kurulurken (dotool ≈0,65 sn) fare kıpırdadıysa kullanıcı bilgisayarı
    kullanıyor → fare 1,5 sn hareketsiz kalana kadar bekle (en çok 8 sn), yoksa DUR. Ek gecikme yok (kurulumla
    örtüşür). fare: () → (x, y, ...) veren işlev (arka ucun fare()'si)."""
    if f0[0] is None or fare()[:2] in (f0, (None, None)):
        return
    print(_("bekleniyor: kullanıcı fareyi kullanıyor…"), file=sys.stderr)
    bitis = time.monotonic() + azami
    son = fare()[:2]
    durgun_bas = time.monotonic()
    while time.monotonic() < bitis:
        time.sleep(0.05)
        f = fare()[:2]
        if f != son:
            son, durgun_bas = f, time.monotonic()
        elif time.monotonic() - durgun_bas >= 1.5:  # kısa duraksama yetmez: kullanıcı işini bitirsin
            return
    raise Dur(12, _("kullanıcı {sn} sn boyunca fareyi kullandı (insan önceliği); girdi gönderilmedi").format(
        sn=f"{azami:.0f}"))
