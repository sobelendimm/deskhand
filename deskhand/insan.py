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
KENDI_PAY = 0.25   # kendi girdimizin compositor'a ulaşıp 'aktif' olayı üretmesi için zaman payı (sn; 0.8.1: 0,12 → 0,25,
#                    dotool kuyruğu / meşgul compositor yansımayı geciktirebilir)
SUREKLILIK_PAY = 0.05  # 'bosta' bildiriminin bize ulaşma payı (sn): ETKINLIK_MS + bu kadar girdisiz geçerse bosta gelmeli
YERLESME = 0.3     # etkinlik sürüyor görünüyor ama son girdi bizimdi: 'bosta' için en çok bu kadar beklenir (sn; kendi
#                    girdimizin yansıması dotool kuyruğunda / compositor'da gecikmiş olabilir; insan sürdürürse yine 12)
YANSIMA_PAY = 0.5  # kendi penceremiz bittikten sonra bu kadar sn içinde gelen TEK kısa 'aktif' (ardından hemen 'bosta')
#                    kendi girdimizin gecikmeli yansıması sayılır (0.9.0)
YANSIMA_SURE = 0.04  # böyle bir yansımanın en uzun süresi ('aktif' → son girdi, sn): dotool tuşu 6 ms basılı tutar.
#                    İnsanın tek tuşu (basma + ~80 ms sonra bırakma) İKİ 'aktif' üretir → tek değil → insan
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
        try:
            self._oku_dongu()
        except (ValueError, OSError):  # kapat() boruyu kapattı
            pass
        if not self._hazir.is_set():
            self.hata = self.hata or _("yardımcı süreç kapandı")
            self._hazir.set()

    def _oku_dongu(self):
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

    def _kapsaniyor(self, bas, bit):
        """[bas, bit] boyunca SÜREN etkinlik (arada 'bosta' yok) bizim girdimizle açıklanıyor mu? Boşta bildirimi
        ETKINLIK_MS hiç girdi olmayınca gelir: bu aralıkta kendi pencerelerimizin dışında ETKINLIK_MS (+ pay) kadar
        boşluk varsa bosta gelmeliydi; gelmediyse o boşlukta başkası (insan) girdi gönderdi."""
        esik = ETKINLIK_MS / 1000 + SUREKLILIK_PAY
        imlec = bas
        for b, s in self.kendi:  # zamana göre sıralı (kendi_girdi sırayla eklenir)
            if s < imlec:
                continue
            if b > bit:
                break
            if b - imlec > esik:
                return False
            imlec = max(imlec, s)
        return bit - imlec <= esik

    def _yansima(self, olaylar, i):
        """olaylar[i] = ('aktif', ta) kendi pencerelerimizin DIŞINDA. Son kendi penceremiz biteli YANSIMA_PAY'den az
        olduysa bu, girdimizin gecikmeli yansıması olabilir (dotool kuyruğu / meşgul compositor; 0.8.1'de pencere
        sonrası tek 'aktif' koşulsuz insan sayılıyordu). → "bizim" (ardından 'bosta' geldi ve etkinlik ne gönderdiğimiz
        girdiden ne YANSIMA_SURE'den uzun sürdü) | "bekle" ('bosta' henüz yok: yerleşme beklenebilir) | None (insan)."""
        ta = olaylar[i][1]
        onceki = None
        for b, s in self.kendi:
            if s < ta:
                onceki = (b, s)
            else:
                break
        if onceki is None or ta - onceki[1] > YANSIMA_PAY:
            return None
        # TEK olmalı: insanın bir tuşu bile iki 'aktif' üretir (basma, ≥ ETKINLIK_MS sonra bırakma; arada 'bosta')
        if sum(1 for tur, t in olaylar if tur == "aktif" and t > onceki[1] and not self._bizim(t)) > 1:
            return None
        if i + 1 >= len(olaylar):
            return "bekle"
        tur, tb = olaylar[i + 1]
        if tur != "bosta":
            return None
        gonderilen = max(0.0, (onceki[1] - KENDI_PAY) - (onceki[0] + 0.005))  # penceremizdeki girdinin süresi
        return "bizim" if tb - ETKINLIK_MS / 1000 - ta <= min(gonderilen + 0.01, YANSIMA_SURE) else None

    def _insan(self, beri):
        """→ None (insan yok) | "olay" (pencerelerimiz dışında 'aktif': kesin) | "suruyor" (bosta gelmedi, etkinlik
        kendi girdimizle açıklanamıyor: yansıma gecikmesi de olabilir)."""
        simdi = time.monotonic()
        olaylar = list(self.olaylar)
        bekle = False
        for i, (tur, t) in enumerate(olaylar):
            if tur == "aktif" and t >= beri and not self._bizim(t):
                y = self._yansima(olaylar, i)
                if y is None:
                    return "olay"
                bekle = bekle or y == "bekle"
        if bekle:
            return "suruyor"  # pencere sonrası tek 'aktif': yerleşme ('bosta') beklenir; gelmezse insan
        if not olaylar:  # yardımcı başladığından beri hiç 'bosta' gelmedi = kesintisiz girdi (açılıştan beri)
            if simdi - self.hazir_an <= ETKINLIK_MS / 1000 + 0.15:
                return None
            # Biz ETKINLIK_MS dolmadan yazmaya başladıysak bosta HİÇ gelmez (harf arası < ETKINLIK_MS): süreklilik
            # bizim pencerelerimizle örtülüyorsa insan değil (0.8.0'da 2. kelime sınırında yanlış 12 veriyordu)
            return None if self._kapsaniyor(self.hazir_an, simdi) else "suruyor"
        tur, t = olaylar[-1]
        if tur != "aktif":
            return None
        if not self._bizim(t):
            return "olay"  # insan başlattı, sürüyor
        return None if self._kapsaniyor(t, simdi) else "suruyor"  # bizimki bitti, etkinlik sürüyor → insan

    def insan(self, beri, yerlesme=0.0):
        """'beri' anından bu yana İNSAN girdisi var mı? (1) bizim pencerelerimiz dışında 'aktif' olayı, ya da
        (2) etkinlik hâlâ sürüyor ('bosta' gelmedi) ve bu süreklilik bizim girdimizle açıklanamıyor (girdimiz
        bitmiş / hiç girdimiz yok / pencerelerimiz arasında ETKINLIK_MS'den uzun boşluk). yerlesme > 0: yalnız (2)
        durumunda 'bosta' gelsin diye en çok bu kadar sn beklenir (kendi girdimizin gecikmeli yansıması); insan
        girdisi sürerse bosta gelmez → yine True."""
        if not self.calisiyor():
            return False
        sonuc = self._insan(beri)
        bitis = time.monotonic() + yerlesme
        while sonuc == "suruyor" and time.monotonic() < bitis:
            time.sleep(0.01)
            sonuc = self._insan(beri)
        return sonuc is not None

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
        """Yardımcıyı sonlandır, BEKLE (zombi kalmasın) ve boruyu kapat (fd sızmasın; uzun yaşayan MCP sunucusu her
        komutta bir izleyici açar)."""
        if not self.p:
            return
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(0.5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                try:
                    self.p.wait(0.5)
                except subprocess.TimeoutExpired:
                    pass
        try:
            self.p.stdout.close()
        except (OSError, ValueError, AttributeError):
            pass


def taban_bekle(etk, azami=ETKINLIK_MS / 1000 + 0.15):
    """İlk girdiden ÖNCE: yardımcının ilk olayını ('bosta' = kullanıcı şu an boşta) en çok 'azami' sn (hazir'dan
    itibaren) bekle. Yazı bosta gelmeden başlarsa harfler arası < ETKINLIK_MS olduğundan bosta hiç gelmez ve o andaki
    insan girdisi bizimkinden ayrılamaz; taban önce kurulunca sonraki her 'aktif' bizim pencerelerimizle eşlenir.
    Bosta gelmezse (kullanıcı tam o an yazıyor/fareyi oynatıyor) ardından gelen klavye_bekle sessizliği bekler."""
    if etk is None or not hasattr(etk, "olaylar") or not etk.calisiyor():  # sahte/sanal izleyicide taban yok
        return
    while not etk.olaylar and time.monotonic() - etk.hazir_an < azami:
        time.sleep(0.005)


def klavye_bekle(etk, beri, azami=8.0):
    """İNSAN ÖNCELİĞİ (klavye + fare): 'beri'den bu yana insan girdisi varsa, 1,5 sn hiç girdi olmayana dek
    bekle (en çok 'azami' sn), yoksa DUR 12. Kullanıcı ör. terminale yazarken araç araya girmesin."""
    if etk is None or not etk.insan(beri, yerlesme=YERLESME):
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
