"""İnsan önceliği: KENDİ girdimizin yansıması insan sanılmasın, gerçek insan girdisi YİNE yazmayı kessin (0.8.1).

Hata (0.8.0, Steam iade formu): `type_text("Satın alımdan vazgeçtim.")` her denemede 12/24'te (2. kelime sınırında)
"kullanıcı klavye/fare kullandı" ile kesiliyordu; kullanıcı dokunmuyordu. Kök neden: her komut yeni bir
deskhand-etkinlik yardımcısı açar; girdi merkezi hazır olduğundan yazı, boşta bildiriminin ETKINLIK_MS (50 ms) süresi
dolmadan başlar → harf arası < 50 ms olduğu için 'bosta' HİÇ gelmez; Etkinlik.insan() "açılıştan beri hiç bosta yok"
durumunu, hazir'dan 0,2 sn sonra koşulsuz insan sayıyordu (12 harf ≈ 0,25 sn → 2. kelime sınırı).

Bu takım EKRANSIZ: gerçek dotool/yardımcı/pencere yok. KWin'in ext-idle-notify-v1 davranışı (ETKINLIK_MS girdisiz →
'bosta', sonraki ilk girdi → 'aktif') bir benzetici iş parçacığıyla üretilir; GERÇEK kde.Girdi (sahte _yaz) ve GERÇEK
eylem._harf_harf_yaz (parçalama, kelime başı etk_denetle) koşar.

Çalıştır:  python3 tests/test_insan_yansima.py"""
import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _yalitim  # noqa: F401,E402

from deskhand import eylem, guvenlik, insan  # noqa: E402
from deskhand.arka_uc import kde  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ek=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def sahte_etk(olaylar=(), kendi=(), hazir_once=1.0):
    e = insan.Etkinlik.__new__(insan.Etkinlik)
    e.olaylar, e.kendi, e.hata, e.p = list(olaylar), [list(x) for x in kendi], None, None
    e.hazir_an = time.monotonic() - hazir_once
    e._hazir = types.SimpleNamespace(wait=lambda t: True)
    return e


MS = insan.ETKINLIK_MS / 1000

# ================================================================ 1) Etkinlik.insan birim (sentetik olaylar)
print("1) Etkinlik.insan: açılıştan beri bosta yok")
t = time.monotonic()
# HATANIN BİREBİR ÖRNEĞİ: yardımcı 0,30 sn önce hazır; yazı 20 ms sonra başladı, harf arası 20 ms, 12 harf; hiç olay yok
e = sahte_etk(hazir_once=0.30)
for i in range(12):
    b = e.hazir_an + 0.02 + i * 0.02
    e.kendi_girdi(b, b + insan.HARF_SN)
kontrol("yazı ETKINLIK_MS dolmadan başladı, bosta hiç gelmedi, süreklilik bizim → insan DEĞİL (0.8.0: 12/24'te 12)",
        not e.insan(t - 0.05), str(e.kendi))
kontrol("hiç kendi girdimiz yok, açılıştan beri bosta yok → İNSAN", sahte_etk(hazir_once=0.5).insan(t - 1))
e = sahte_etk(hazir_once=0.5)
e.kendi_girdi(e.hazir_an + 0.25, e.hazir_an + 0.45)  # ilk girdimiz 0,25 sn sonra: öncesinde bosta gelmeliydi
kontrol("ilk kendi girdimiz ETKINLIK_MS'den çok sonra, arada bosta yok → İNSAN (öncesi başkasının)", e.insan(t - 1))
e = sahte_etk(hazir_once=0.8)
e.kendi_girdi(e.hazir_an + 0.01, e.hazir_an + 0.05)
kontrol("kendi girdimiz çoktan bitti, açılıştan beri bosta yok → İNSAN", e.insan(t - 1))

print("2) Etkinlik.insan: süreklilik + yerleşme")
e = sahte_etk([("bosta", t - 2), ("aktif", t - 1.0)], kendi=[(t - 1.01, t - 0.8), (t - 0.4, t + 0.1)])
kontrol("pencerelerimiz arasında 0,4 sn boşluk, bosta gelmedi → İNSAN (boşluğu biri doldurdu)", e.insan(t - 1.5))
e = sahte_etk([("bosta", t - 2), ("aktif", t - 1.0)], kendi=[(t - 1.01, t - 0.9), (t - 0.88, t + 0.1)])
kontrol("pencerelerimiz arası boşluk < ETKINLIK_MS → insan değil", not e.insan(t - 1.5))
# gecikmeli yansıma: son girdimizin penceresi bitti, bosta biraz geç geliyor (kuyruk/compositor gecikmesi)
e = sahte_etk([("bosta", t - 2), ("aktif", t - 0.5)], kendi=[(t - 0.51, t - 0.2)])
kontrol("yerleşmesiz: girdimiz bitti, bosta henüz yok → insan sayılır (eski davranış)", e.insan(t - 1))
threading.Timer(0.08, lambda: e.olaylar.append(("bosta", time.monotonic()))).start()
t0 = time.monotonic()
kontrol("YERLEŞME: bosta 80 ms geç geldi → insan DEĞİL (kendi yansımamız)", not e.insan(t - 1, yerlesme=insan.YERLESME))
kontrol("yerleşme bosta gelince hemen biter", time.monotonic() - t0 < 0.25, f"{time.monotonic() - t0:.3f}")
e = sahte_etk([("bosta", t - 2), ("aktif", t - 0.5)], kendi=[(t - 0.51, t - 0.2)])
t0 = time.monotonic()
kontrol("YERLEŞME: bosta hiç gelmiyor (insan yazmayı sürdürüyor) → İNSAN", e.insan(t - 1, yerlesme=0.15))
kontrol("… en çok yerleşme süresi beklendi", 0.13 <= time.monotonic() - t0 < 0.5, f"{time.monotonic() - t0:.3f}")
# (0.9.0: penceremizden YANSIMA_PAY'den uzak olay — yakın olanlar için yerleşme beklenir, bkz. 2c)
e = sahte_etk([("bosta", t - 2), ("aktif", t - 1.2), ("bosta", t - 1.1), ("aktif", t - 0.1)], kendi=[(t - 1.21, t - 1.15)])
t0 = time.monotonic()
kontrol("pencere dışı 'aktif' (gerçek insan olayı, penceremizden 1 sn sonra) → İNSAN, yerleşme beklemeden",
        e.insan(t - 1.5, yerlesme=insan.YERLESME) and time.monotonic() - t0 < 0.05)
kontrol("kendi pencere payı ≥ 0,2 sn (gecikmeli yansıma toleransı)", insan.KENDI_PAY >= 0.2, str(insan.KENDI_PAY))


print("2c) penceremiz bittikten hemen sonra gelen TEK 'aktif' (gecikmeli yansıma, 0.9.0)")
# BİREBİR örnek: bosta; harf t; aktif t+0,30 (pencere t+0,263'te bitti); bosta t+0,33 → insan DEĞİL
h = time.monotonic() - 1.0
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h, h + insan.HARF_SN)
e.olaylar += [("aktif", h + 0.30), ("bosta", h + 0.33)]
kontrol("bosta; harf t; aktif t+0,30; bosta t+0,33 → insan DEĞİL (0.8.2: 12)", not e.insan(h - 0.5, yerlesme=insan.YERLESME))
kontrol("… yerleşmesiz de insan değil (bosta zaten geldi)", not e.insan(h - 0.5))
# bosta henüz gelmedi: yerleşme beklenir, 30 ms sonra gelir → insan değil
h = time.monotonic()
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h - 0.30, h - 0.30 + insan.HARF_SN)
e.olaylar.append(("aktif", h))
threading.Timer(0.03 + insan.ETKINLIK_MS / 1000, lambda: e.olaylar.append(("bosta", h + 0.03))).start()
t0 = time.monotonic()
kontrol("aktif penceremizden hemen sonra, bosta 80 ms sonra geldi → yerleşme bekler, insan DEĞİL",
        not e.insan(h - 0.5, yerlesme=insan.YERLESME) and time.monotonic() - t0 < 0.25, f"{time.monotonic() - t0:.3f}")
# insanın tek tuşu: basılı tutma + bırakma 80 ms → patlama YANSIMA_SURE'den uzun → İNSAN
h = time.monotonic() - 1.0
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h, h + insan.HARF_SN)
e.olaylar += [("aktif", h + 0.30), ("bosta", h + 0.30 + 0.08 + insan.ETKINLIK_MS / 1000)]
kontrol("pencere sonrası insan tuşu (80 ms basılı) → İNSAN", e.insan(h - 0.5, yerlesme=insan.YERLESME))
# gerçek idle-notify'da basma ve bırakma (80 ms > ETKINLIK_MS) AYRI 'aktif' olur: iki kısa patlama → tek değil → İNSAN
h = time.monotonic() - 1.0
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h, h + insan.HARF_SN)
e.olaylar += [("aktif", h + 0.30), ("bosta", h + 0.35), ("aktif", h + 0.38), ("bosta", h + 0.43)]
kontrol("pencere sonrası insan tuşu (basma + bırakma = iki 'aktif') → İNSAN", e.insan(h - 0.5, yerlesme=insan.YERLESME))
# bosta hiç gelmiyor (insan yazmayı sürdürüyor) → yerleşmeden sonra İNSAN
h = time.monotonic()
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h - 0.30, h - 0.30 + insan.HARF_SN)
e.olaylar.append(("aktif", h))
t0 = time.monotonic()
kontrol("pencere sonrası 'aktif', bosta gelmiyor → yerleşme sonrası İNSAN", e.insan(h - 0.5, yerlesme=0.15)
        and 0.13 <= time.monotonic() - t0 < 0.5, f"{time.monotonic() - t0:.3f}")
# penceremizden YANSIMA_PAY'den sonra → yansıma sayılmaz
h = time.monotonic() - 2.0
e = sahte_etk([("bosta", h - 1)])
e.kendi_girdi(h, h + insan.HARF_SN)
e.olaylar += [("aktif", h + insan.KENDI_PAY + insan.YANSIMA_PAY + 0.1), ("bosta", h + insan.KENDI_PAY + insan.YANSIMA_PAY + 0.13)]
kontrol("penceremizden YANSIMA_PAY sonra tek 'aktif' → İNSAN", e.insan(h - 0.5))
# hiç kendi girdimiz yok → yansıma olamaz
e = sahte_etk([("bosta", h - 1), ("aktif", h), ("bosta", h + 0.03)])
kontrol("kendi girdimiz yokken tek 'aktif' → İNSAN", e.insan(h - 0.5))

print("2d) Etkinlik.kapat: yardımcı beklenir, boru kapanır (zombi / fd sızıntısı yok)")
import subprocess  # noqa: E402
e = sahte_etk()
e.p = subprocess.Popen(["sleep", "30"], stdout=subprocess.PIPE, text=True)
fd_once = len(os.listdir("/proc/self/fd"))
e.kapat()
kontrol("kapat → süreç toplandı (returncode var, zombi yok)", e.p.returncode is not None)
kontrol("kapat → stdout kapandı", e.p.stdout.closed)
kontrol("kapat → fd sayısı azaldı", len(os.listdir("/proc/self/fd")) < fd_once)
e.kapat()  # ikinci kez: hata yok
kontrol("kapat iki kez çağrılabilir", True)
e = insan.Etkinlik.__new__(insan.Etkinlik)
e.olaylar, e.hata, e.hazir_an, e._hazir = [], None, None, threading.Event()
e.p = subprocess.Popen(["sh", "-c", "echo hazir 1.0; exec sleep 30"], stdout=subprocess.PIPE, text=True)
okuyucu = threading.Thread(target=e._oku, daemon=True)
okuyucu.start()
e._hazir.wait(2)
e.kapat()
okuyucu.join(2)
kontrol("okuyucu iş parçacığı kapat sonrası hatasız biter", not okuyucu.is_alive())

print("2b) taban_bekle: ilk girdiden önce ilk 'bosta'")
e = sahte_etk(hazir_once=0.0)
threading.Timer(0.06, lambda: e.olaylar.append(("bosta", time.monotonic()))).start()
t0 = time.monotonic()
insan.taban_bekle(e)
kontrol("bosta 60 ms'de geldi → hemen döner", e.olaylar and 0.05 <= time.monotonic() - t0 < 0.15,
        f"{time.monotonic() - t0:.3f}")
e = sahte_etk(hazir_once=0.0)
t0 = time.monotonic()
insan.taban_bekle(e)
kontrol("bosta gelmiyor (kullanıcı o an yazıyor) → en çok ETKINLIK_MS+0,15 sn bekler, sonra insan sayılır",
        0.18 <= time.monotonic() - t0 < 0.4 and e.insan(t0), f"{time.monotonic() - t0:.3f}")
e = sahte_etk([("bosta", time.monotonic() - 0.5)], hazir_once=0.6)
t0 = time.monotonic()
insan.taban_bekle(e)
kontrol("bosta zaten gelmiş → beklemez", time.monotonic() - t0 < 0.02)

# ================================================================ 3) benzetici: KWin boşta bildirimi + gerçek yazma yolu
class SimKWin:
    """ext-idle-notify-v1: ETKINLIK_MS girdisiz → 'bosta'; ardından ilk girdi → 'aktif' (zaman = iletim anı).
    Zamanlayıcı bildirim oluşturulunca (hazir) başlar. Girdiler 'gecikme' kadar sonra compositor'a ulaşır."""

    def __init__(self, etk, gecikme=0.003):
        self.etk, self.gecikme = etk, gecikme
        self.girdiler = []  # compositor'a ulaşma zamanları
        self.kilit = threading.Lock()
        self.dur = threading.Event()
        self.son = time.monotonic()  # bildirim kuruldu: zamanlayıcı şimdi başlar
        self.etk.hazir_an = self.son
        self.bosta = False
        threading.Thread(target=self._dongu, daemon=True).start()

    def girdi(self, t):
        with self.kilit:
            self.girdiler.append(t + self.gecikme)

    def insan_girdisi(self, t):
        with self.kilit:
            self.girdiler.append(t)

    def _dongu(self):
        while not self.dur.is_set():
            simdi = time.monotonic()
            with self.kilit:
                hazir = sorted(x for x in self.girdiler if x <= simdi)
                self.girdiler = [x for x in self.girdiler if x > simdi]
            for x in hazir:
                if self.bosta:
                    self.etk.olaylar.append(("aktif", x))
                    self.bosta = False
                self.son = max(self.son, x)
            if not self.bosta and simdi - self.son >= MS:
                self.etk.olaylar.append(("bosta", self.son + MS))
                self.bosta = True
            time.sleep(0.002)


def sim_girdi(gecikme=0.003, yavas_parca=None, insan_plani=None):
    """Gerçek kde.Girdi (merkez/dotool yok): _yaz satırları kaydeder ve benzeticiye girdi olarak verir."""
    etk = sahte_etk(hazir_once=0.0)
    sim = SimKWin(etk, gecikme)
    g = kde.Girdi.__new__(kde.Girdi)
    g.au = types.SimpleNamespace(baslik=lambda k: "Steam", fare=lambda: (None, None, None))
    g.denetle = lambda k, d: None
    g.etk, g.etk_sahibi, g.merkez, g.p = etk, False, None, None
    g.t0 = g.son_etk = time.monotonic()
    g.hazir, g.uyarilar, g.etiket, g.gizli, g.kesildi = True, [], "test", False, None
    g.fare0 = g.son_fare = (None, None)
    g.koruma_denetle = lambda her_zaman=True: None
    g.izle = lambda k, desen, fare_izle=True: None
    g.izle_bitir = lambda: None
    g.satirlar = []

    def _yaz(satirlar):
        simdi = time.monotonic()
        for s in satirlar:
            g.satirlar.append(s)
            if not s.startswith(("typedelay", "typehold")):
                sim.girdi(simdi)
    g._yaz = _yaz
    sayac = {"n": 0}

    def denetle(k, desen):  # kelime başı tam denetim (eylem.denetle): istenen parçada yavaş (ör. KWin sorgusu)
        sayac["n"] += 1
        if yavas_parca and sayac["n"] == yavas_parca[0]:
            if insan_plani:
                insan_plani(sim)
            time.sleep(yavas_parca[1])
    return g, sim, denetle


def yaz(metin, **kw):
    g, sim, denetle = sim_girdi(**kw)
    eski = eylem.denetle, guvenlik.seviye_denetle, eylem._au
    eylem.denetle = denetle
    guvenlik.seviye_denetle = lambda k, ne: None
    eylem._au = lambda: g.au
    try:
        eylem._harf_harf_yaz(g, "{steam}", None, metin, False)
        hata = None
    except Dur as e:
        hata = e
    finally:
        eylem.denetle, guvenlik.seviye_denetle, eylem._au = eski
        sim.dur.set()
    yazilan = "".join(" " if s == "key space" else s[5:] for s in g.satirlar if s.startswith(("type ", "key space")))
    return yazilan, hata


print("3) benzetici: gerçek kde.Girdi + eylem._harf_harf_yaz")
for i in range(10):
    yazilan, hata = yaz("Satın alımdan vazgeçtim.")
    if hata or yazilan != "Satın alımdan vazgeçtim.":
        break
kontrol("'Satın alımdan vazgeçtim.' 10 kez, insan yok, yazı hemen başlıyor → hep TAM (0.8.0: 12/24'te kesilirdi)",
        hata is None and yazilan == "Satın alımdan vazgeçtim.", f"{i}. tur: {yazilan!r} {hata}")
UZUN = "Şu iade talebini, ürünü hiç açmadığım için gönderiyorum; lütfen ödemeyi Çarşamba'ya kadar iade edin."
yazilan, hata = yaz(UZUN)
kontrol(f"uzun Türkçe cümle ({len(UZUN)} karakter) tam yazıldı", hata is None and yazilan == UZUN, f"{yazilan!r} {hata}")
yazilan, hata = yaz("Satın alımdan vazgeçtim.", gecikme=0.2, yavas_parca=(3, 0.12))
kontrol("gecikmeli yansıma (200 ms) + yavaş kelime sınırı → kesilmez", hata is None and
        yazilan == "Satın alımdan vazgeçtim.", f"{yazilan!r} {hata}")


def insan_tek_tus(sim):  # yavaş kelime sınırının ortasında (bizim girdimiz yokken) insan bir tuşa basar
    # gerçek tuş: bas + 80 ms sonra bırak (iki 'aktif'). 0.9.0: anlık TEK kısa olay penceremizden hemen sonra
    # gelirse kendi girdimizin gecikmeli yansımasından ayrılamaz → yansıma sayılır
    t = time.monotonic() + 0.35
    sim.insan_girdisi(t)
    sim.insan_girdisi(t + 0.08)


yazilan, hata = yaz("Satın alımdan vazgeçtim.", yavas_parca=(3, 0.5), insan_plani=insan_tek_tus)
kontrol("GERÇEK insan tuşu (bizim girdimiz bitmişken) → 12 ile KESİLİR", hata is not None and hata.kod == 12 and
        "12/24" in hata.mesaj, f"{yazilan!r} {hata}")


def insan_surekli(sim):  # insan kelime sınırında yazmayı sürdürüyor (30 ms'de bir, 1,2 sn)
    t0 = time.monotonic() + 0.01
    for i in range(40):
        sim.insan_girdisi(t0 + i * 0.03)


t0 = time.monotonic()
yazilan, hata = yaz("Satın alımdan vazgeçtim.", yavas_parca=(2, 0.5), insan_plani=insan_surekli)
kontrol("GERÇEK insan sürekli yazıyor (bosta hiç gelmiyor) → yerleşmeden sonra 12 ile KESİLİR",
        hata is not None and hata.kod == 12 and "6/24" in hata.mesaj, f"{yazilan!r} {hata}")

print(f"\n{GECEN}/{TOPLAM} insan-yansıma testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
