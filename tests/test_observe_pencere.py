"""Aynı süreçte birden çok pencere: observe(window=A) B'nin sayfasını döndürmemeli (ABM-SOAK "yanlış hedef", SOAK-FIX).

Kök neden (SOAK-FIX raporu): Firefox F3'e gezinirken F3'ün AT-SPI çerçeve adı geçici olarak "Mozilla Firefox" olur;
bu ad F1'in başlığının ("Soak-F1-p4 — Mozilla Firefox") İÇİNDE geçtiği için web._cerceve_bul onu tam eşleşmeyle aynı
puanlıyor (1.0) ve eşitlikte "active" durumu (gezinilen, etkin pencere F3) kazanıyordu → F1 penceresi için F3'ün
sayfası. erisim._cerceve_bul tam eşleşmeyi öne alır, ama A'nın çerçeve adı pencere başlığının gerisinde kaldığında
(başlık geçişi) aynı içerme kuralıyla B'yi seçiyordu.

Beklenen: aynı süreç ağacında birden çok çerçeve varken pencere başlığıyla BİREBİR eşleşen tek çerçeve yoksa tahmin
yok → Dur 6 (sayfa belirsiz, yeniden dene); okunan üst belgenin başlığı pencere başlığında geçmiyorsa da Dur 6.
Sahte AT-SPI (D-Bus yanıtları / libatspi nesneleri); gerçek masaüstü, ağ, ~/.config yok.

Çalıştır:  python3 tests/test_observe_pencere.py"""
import os
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import erisim, web  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ayrinti=""):
    global gecen, toplam
    toplam += 1
    if kosul:
        gecen += 1
        print(f"  ✓ {ad}")
    else:
        print(f"  ✗ {ad}  {ayrinti}")


def sonuc(f, *a, **k):
    """→ ("ok", dönüş) | ("dur", Dur)."""
    try:
        return "ok", f(*a, **k)
    except Dur as e:
        return "dur", e


PID = os.getpid()  # sahte uygulama bu sürecin PID'iyle (tam eşleşme: kendi.atalar çağrılmaz)
WPID = 424242  # web: pencere = uygulama süreci (web._cerceve_bul bu sürecin kendi bağlantısını sayar)
F1, F2 = "Soak-F1-p4 — Mozilla Firefox", "Soak-F2-p1 — Mozilla Firefox"
GECIS = "Mozilla Firefox"  # gezinme sırasında başlıksız F3 çerçevesi


# ================================================================ web._cerceve_bul (jeepney boru hattı, sahte veri yolu)

class SahteYol:
    """web._Yol yerine: ListNames / GetConnectionUnixProcessID / GetChildren(kök) / Name / GetState yanıtları."""

    def __init__(self, cerceveler, uyg_pid=None, bus=":1.50"):
        self.bus, self.pid = bus, uyg_pid or WPID
        self.cerceveler = [(f"/org/a11y/atspi/accessible/{i + 1}", ad, durum) for i, (ad, durum) in enumerate(cerceveler)]
        self.c = type("C", (), {"unique_name": ":1.1"})()

    def _yanit(self, m):
        from jeepney.low_level import HeaderFields
        f = m.header.fields
        uye, yol = f.get(HeaderFields.member), f.get(HeaderFields.path)
        if uye == "ListNames":
            return ([":1.1", self.bus],)
        if uye == "GetConnectionUnixProcessID":
            return (self.pid,) if m.body[0] == self.bus else (999999,)
        if uye == "GetChildren" and yol == web.KOK_YOL:
            return ([(self.bus, y) for y, _a, _d in self.cerceveler],)
        for y, ad, durum in self.cerceveler:
            if yol == y:
                if uye == "Get" and m.body[1] == "Name":
                    return (("s", ad),)
                if uye == "GetState":
                    bit = sum(1 << web._DURUM_BIT[d] for d in durum)
                    return ([bit & 0xFFFFFFFF, bit >> 32],)
        if uye == "Get" and m.body[1] == "Name":
            return (("s", "firefox"),)
        return None

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        return [self._yanit(m) for m in mesajlar]

    def kapat(self):
        pass


def web_sec(cerceveler, baslik, kardes=None):
    r, v = sonuc(web._cerceve_bul, SahteYol(cerceveler), WPID, baslik, kardes)
    return (r, v[4]) if r == "ok" else (r, v)


print("A) web._cerceve_bul: aynı süreçte 3 Firefox çerçevesi")
S, AS = ("showing",), ("active", "showing")
r, v = web_sec([(F1, S), (F2, S), (GECIS, AS)], F1, [F2, "Soak-F3-p1 — Mozilla Firefox"])
kontrol("geçiş anı: F3 etkin ve adı 'Mozilla Firefox' (F1 başlığının içinde) → yine F1'in çerçevesi", r == "ok" and v == F1,
        f"{r} {v}")
r, v = web_sec([(F1, S), (F2, S), ("Soak-loading — Mozilla Firefox", AS)], F1, [F2, "Soak-loading — Mozilla Firefox"])
kontrol("geçiş anı: F3 'Soak-loading' başlığında, etkin → F1", r == "ok" and v == F1, f"{r} {v}")
r, v = web_sec([("Soak-F1-p3 — Mozilla Firefox", S), (F2, S), (GECIS, AS)], F1)
kontrol("F1'in çerçeve adı pencere başlığının gerisinde (birebir eşleşme yok) → tahmin yok, Dur 6 (yeniden dene)",
        r == "dur" and v.kod == 6, f"{r} {v}")
r, v = web_sec([(F1, S), (F1, AS), (F2, S)], F1)
kontrol("aynı süreçte aynı başlıklı iki çerçeve → etkin olan SEÇİLMEZ, Dur 6 (pencere kimliği yok)", r == "dur" and v.kod == 6,
        f"{r} {v}")
r, v = web_sec([("Soak-C1-p0 - Chromium", AS)], "Soak-C1-p0 - Chromium")
kontrol("tek çerçeve, birebir → seçilir", r == "ok" and v == "Soak-C1-p0 - Chromium", f"{r} {v}")
r, v = web_sec([("Soak-C1-p0", AS)], "Soak-C1-p0 - Chromium", [])
kontrol("tek çerçeve (karışacak başka pencere yok), ad pencere başlığının içinde → seçilir (gerileme yok)",
        r == "ok" and v == "Soak-C1-p0", f"{r} {v}")
r, v = web_sec([(F2, S), (GECIS, AS)], "Gizli Banka — Mozilla Firefox")
kontrol("A'nın çerçevesi ağaçta yok, B 'Mozilla Firefox' (A başlığının içinde) → B'ye düşülmez, Dur 6", r == "dur" and
        v.kod == 6, f"{r} {v}")

# ================================================================ erisim._cerceve_bul (libatspi nesneleri)


class Cerceve:
    def __init__(self, ad): self.ad = ad
    def get_name(self): return self.ad


class Uyg:
    def __init__(self, pid, ad, cerceveler): self.pid, self.ad, self.c = pid, ad, cerceveler
    def get_process_id(self): return self.pid
    def get_name(self): return self.ad
    def get_child_count(self): return len(self.c)
    def get_child_at_index(self, i): return self.c[i]


class Masa:
    def __init__(self, uyg): self.u = uyg
    def get_child_count(self): return len(self.u)
    def get_child_at_index(self, i): return self.u[i]


class SahteAtspi:
    def __init__(self, uyg): self.m = Masa(uyg)
    def get_desktop(self, i): return self.m


def er_sec(adlar, baslik, kardes=None):
    r, v = sonuc(erisim._cerceve_bul, SahteAtspi([Uyg(PID, "Firefox", [Cerceve(a) for a in adlar])]), PID, baslik,
                 kardes)
    return (r, v[0].ad) if r == "ok" else (r, v)


print("B) erisim._cerceve_bul: aynı süreçte 3 çerçeve")
r, v = er_sec([F1, F2, GECIS], F1, [F2, "Soak-F3-p1 — Mozilla Firefox"])
kontrol("birebir başlık → F1", r == "ok" and v == F1, f"{r} {v}")
r, v = er_sec(["Soak-F1-p3 — Mozilla Firefox", F2, GECIS], F1)
kontrol("F1 adı geride, F3 'Mozilla Firefox' (içerme) → F3 SEÇİLMEZ, Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = er_sec(["Soak-F1-p3 — Mozilla Firefox", F2], F1)
kontrol("birebir eşleşme yok, benzerlikle tahmin yok → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = er_sec(["Belge — KWrite"], "Belge — KWrite")
kontrol("tek çerçeve → seçilir", r == "ok" and v == "Belge — KWrite", f"{r} {v}")
r, v = er_sec(["Belge"], "Belge — KWrite", [])
kontrol("tek çerçeve, içerme → seçilir (gerileme yok)", r == "ok" and v == "Belge", f"{r} {v}")
DIYALOG = "File Upload - Soak-F1-p4 — Mozilla Firefox"
r, v = er_sec([F1, DIYALOG], DIYALOG, [F1])
kontrol("GTK dosya diyaloğu (adı ana pencereyi içerir): birebir diyalog çerçevesi", r == "ok" and v == DIYALOG, f"{r} {v}")

# ================================================================ web.oku: okunan üst belge pencereye ait mi


class SahteAu:
    ad = "kwin"

    def __init__(self, baslik): self.b = baslik
    def baslik(self, k): return self.b


def oku_belge(belge_adi, pencere=F1):
    eski = web._baglam, web._yuru
    web._baglam = lambda k, islem="tara": (SahteAu(pencere), SahteYol([]), ":1.50", "/c", 0, (0, 0), "c")
    web._yuru = lambda *a, **k: ([], [{"ad": belge_adi, "adres": "http://127.0.0.1/x", "durum": {"showing"},
                                       "derinlik": 1, "kutu": None}], 3)
    try:
        return sonuc(web.oku, "arka:{x}", ayrinti=False)
    finally:
        web._baglam, web._yuru = eski


print("C) web.oku: üst belge başlığı pencere başlığında geçmeli")
r, v = oku_belge("Soak-F3-p6")
kontrol("belge 'Soak-F3-p6', pencere F1 → B'nin sayfası A çıktısına girmez, Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = oku_belge("Soak-F1-p4")
kontrol("belge başlığı pencere başlığında → okunur", r == "ok" and v["sayfa"]["baslik"] == "Soak-F1-p4", f"{r} {v}")
r, v = oku_belge("")
kontrol("başlıksız belge (yükleniyor) → okunur (karşılaştırılacak ad yok)", r == "ok", f"{r} {v}")

# ================================================================ SOAK-FIX-R1: bağımsız kanal (KWin kardeş pencereleri)
# Bağımsız K2 incelemesinin PoC'leri (SOAK-FIX-INC/poc.py P1–P4b) + ORTA 1 (belge adı gecikmesi) + ORTA 3 (sızıntı).
# kardes = hedef pencereyle AYNI süreçteki ÖBÜR pencerelerin KWin başlıkları (sayfadan bağımsız: pencere listesi KWin'in);
# None = bilinmiyor (güvenli yön: yalnız tartışmasız durumda seçilir).
MF = " — Mozilla Firefox"


def web_sec2(cerceveler, baslik, kardes):
    r, v = sonuc(web._cerceve_bul, SahteYol(cerceveler), WPID, baslik, kardes)
    return (r, v[4]) if r == "ok" else (r, v)


def er_sec2(adlar, baslik, kardes, uyg_pid=None, pencere_pid=None):
    u = Uyg(uyg_pid or PID, "Firefox", [Cerceve(a) for a in adlar])
    r, v = sonuc(erisim._cerceve_bul, SahteAtspi([u]), pencere_pid or PID, baslik, kardes)
    return (r, v[0].ad) if r == "ok" else (r, v)


print("D) SOAK-FIX-R1: saldırgan sayfa başlığı (P1–P4b), kardeş pencere teklik kuralı")
# P1: F1'in (saldırgan sayfa) çerçeve adı eski; F1 pencere başlığını F3'ün (banka) başlığına eşitledi → iki KWin penceresi
# aynı başlıkta: başlık kimlik kanıtı değil → Dur (önce: F3'ün çerçevesi seçiliyordu = banka içeriği F1 adına)
for ad_, k_ in (("kardeş listesiyle", ["Banka Giris" + MF]), ("kardeş bilinmiyor", None)):
    r, v = web_sec2([("Eski sayfa" + MF, S), ("Banka Giris" + MF, AS)], "Banka Giris" + MF, k_)
    kontrol(f"P1 web ({ad_}): saldırgan başlığı kopyaladı → banka çerçevesi SEÇİLMEZ, Dur 6", r == "dur" and v.kod == 6,
            f"{r} {v}")
    r, v = er_sec2(["Eski sayfa" + MF, "Banka Giris" + MF], "Banka Giris" + MF, k_)
    kontrol(f"P1 erisim ({ad_}): aynı → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
# P2: hedefin çerçevesi henüz yayınlanmamış; tek çerçeve öbür pencerenin → Dur (önce: tek aday = seçilirdi)
for ad_, k_ in (("kardeş listesiyle", ["Banka Giris" + MF]), ("kardeş bilinmiyor", None)):
    r, v = web_sec2([("Banka Giris" + MF, AS)], "Odeme listesi" + MF, k_)
    kontrol(f"P2 web ({ad_}): tek çerçeve başka pencerenin → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
    r, v = er_sec2(["Banka Giris" + MF], "Odeme listesi" + MF, k_)
    kontrol(f"P2 erisim ({ad_}): aynı → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
# tek pencereli uygulama (kardeş YOK, KWin'den bilinir): ad gecikmesi karışıklık değil → seçilir (gerileme yok)
r, v = web_sec2([("Mozilla Firefox", AS)], "Soak-F1-p4" + MF, [])
kontrol("tek pencere (kardeş yok), çerçeve adı geride → seçilir", r == "ok" and v == "Mozilla Firefox", f"{r} {v}")
r, v = er_sec2(["Belge"], "Belge — KWrite", [])
kontrol("erisim tek pencere (kardeş yok), ad geride → seçilir", r == "ok" and v == "Belge", f"{r} {v}")
# meşru çok pencere: F3 geçişte (genel ad), F2 güncel → F1
r, v = web_sec2([(F1, S), (F2, S), (GECIS, AS)], F1, [F2, "Soak-F3-p1" + MF])
kontrol("3 Firefox, F3 geçişte (genel ad), kardeşler KWin'de → F1 seçilir", r == "ok" and v == F1, f"{r} {v}")
r, v = er_sec2([F1, F2, GECIS], F1, [F2, "Soak-F3-p1" + MF])
kontrol("erisim: aynı → F1", r == "ok" and v == F1, f"{r} {v}")
# öbür çerçevenin adı hiçbir güncel pencere başlığında yok (bayat, genel değil) → geçiş sürüyor: Dur (çift yarış kapısı)
r, v = web_sec2([(F1, S), ("Soak-F2-p0" + MF, S)], F1, [F2])
kontrol("kardeş çerçevenin adı bayat (KWin'de böyle pencere yok) → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
# boş/genel pencere başlığı + kardeş var → başlık kanıt değil
# genel pencere başlığı (yeni boş pencere "Mozilla Firefox"): ad kanıt değil; ÖBÜR her çerçeve bir kardeşe, her kardeş bir
# çerçeveye denk geliyorsa kalan çerçeve elemeyle bu pencerenin (ölçüldü: yeni pencerede adres yazma akışı buna dayanır)
r, v = web_sec2([("Mozilla Firefox", AS), (F2, S)], "Mozilla Firefox", [F2])
kontrol("genel başlık, tüm kardeşler çerçeveleriyle açıklanıyor → elemeyle seçilir", r == "ok" and v == "Mozilla Firefox",
        f"{r} {v}")
r, v = web_sec2([("Mozilla Firefox", AS)], "Mozilla Firefox", [F2])
kontrol("genel başlık, kardeşin çerçevesi yok (o çerçeve geçişte olabilir) → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = web_sec2([("Mozilla Firefox", AS), (F2, S), ("Soak-F3-p0" + MF, S)], "Mozilla Firefox", [F2])
kontrol("genel başlık, açıklanmayan ADLI çerçeve var → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
# ölçüldü (gerçek KWin, test_arka_chromium): Ctrl+L sonrası Chromium öneri listesi adsız üst düzey çerçeve
r, v = er_sec2(["F3R2-CR-BIR - Chromium", "Yeni Sekme - Chromium", ""], "Yeni Sekme - Chromium", ["F3R2-CR-BIR - Chromium"])
kontrol("Chromium yeni pencere + adsız öneri çerçevesi (gerçek ölçüm) → yeni pencerenin çerçevesi",
        r == "ok" and v == "Yeni Sekme - Chromium", f"{r} {v}")
r, v = er_sec2(["Yeni Sekme - Chromium", ""], "Yeni Sekme - Chromium", ["F3R2-CR-BIR - Chromium"])
kontrol("genel başlık, kardeşin çerçevesi yok + adsız çerçeve (kardeşinki olabilir) → Dur 6", r == "dur" and v.kod == 6,
        f"{r} {v}")
r, v = web_sec2([("Mozilla Firefox", AS), ("Mozilla Firefox", S)], "Mozilla Firefox", ["Mozilla Firefox"])
kontrol("iki boş pencere (aynı genel başlık) → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = er_sec2(["", F2], "", [F2])
kontrol("boş pencere başlığı + kardeş → Dur 6 (SequenceMatcher('', '') = 1.0 benzerlik sayılmaz)", r == "dur" and v.kod == 6,
        f"{r} {v}")
r, v = er_sec2([""], "", None)
kontrol("boş başlık, tek çerçeve, kardeş bilinmiyor → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
# GTK diyaloğu: diyalog ayrı KWin penceresi (kardeş) → ana pencere de diyalog da birebir seçilir
r, v = er_sec2([F1, DIYALOG], DIYALOG, [F1])
kontrol("GTK diyaloğu (kardeş = ana pencere) → diyalog çerçevesi", r == "ok" and v == DIYALOG, f"{r} {v}")
r, v = er_sec2([F1, DIYALOG], F1, [DIYALOG])
kontrol("ana pencere (kardeş = diyalog) → ana çerçeve", r == "ok" and v == F1, f"{r} {v}")
# P4 / P4b: torun süreç (Chromium); süzgeç aday elemeden ÖNCE sayılır
_eski = erisim._surec_akrabasi, erisim._exe
erisim._surec_akrabasi, erisim._exe = (lambda a, b: True), (lambda p: "/usr/bin/chromium")
try:
    r, v = er_sec2(["Inbox - Gmail - Chromium", "Faturalar - Banka - Chromium"], "Faturalar - Banka - Chromiun",
                   ["Faturalar - Banka - Chromium"], uyg_pid=777, pencere_pid=4242)
    kontrol("P4 torun: hedef adı eski, öbürü benzer → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
    r, v = er_sec2(["Eski - Chromium", "Faturalar - Banka - Chromium"], "Faturalar - Banka 2 - Chromium",
                   ["Faturalar - Banka - Chromium"], uyg_pid=777, pencere_pid=4242)
    kontrol("P4b torun: hedef çerçevesi süzgeçte düşerdi, tek kalan öbürü → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
    r, v = er_sec2(["Eski - Chromium", "Faturalar - Banka - Chromium"], "Faturalar - Banka 2 - Chromium", None,
                   uyg_pid=777, pencere_pid=4242)
    kontrol("P4b torun, kardeş bilinmiyor → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
finally:
    erisim._surec_akrabasi, erisim._exe = _eski


class KardesAu:
    ad = "sanal"

    def __init__(self, pencereler): self.p = pencereler  # [(kimlik, başlık, pid)]
    def pencereler(self, desen=None): return [(k, b, (0, 0, 10, 10)) for k, b, _p in self.p]
    def pid(self, k): return next(p for k_, _b, p in self.p if k_ == k)
    def baslik(self, k): return next(b for k_, b, _p in self.p if k_ == k)


au_ = KardesAu([("arka:{a}", F1, 50), ("arka:{b}", F2, 50), ("arka:{c}", "Belge — KWrite", 60)])
kontrol("kardes_basliklari: yalnız AYNI süreçteki öbür pencereler", erisim.kardes_basliklari(au_, "arka:{a}", 50) == [F2],
        str(erisim.kardes_basliklari(au_, "arka:{a}", 50)))

class KwinKardesAu:
    tur = "kwin"

    def _liste(self):
        return [{"i": "00000000-0000-0000-0000-00000000000a", "t": F1, "p": 50},
                {"i": "00000000-0000-0000-0000-00000000000b", "t": F2, "p": 50},
                {"i": "00000000-0000-0000-0000-00000000000c", "t": "Belge — KWrite", "p": 60}]


kontrol("kardes_basliklari (KWin: tek liste betiği, pid dahil): yalnız aynı süreçteki öbürleri",
        erisim.kardes_basliklari(KwinKardesAu(), "arka:00000000-0000-0000-0000-00000000000a", 50) == [F2],
        str(erisim.kardes_basliklari(KwinKardesAu(), "arka:00000000-0000-0000-0000-00000000000a", 50)))
kontrol("kardes_basliklari: liste alınamazsa None (bilinmiyor)",
        erisim.kardes_basliklari(object(), "arka:{a}", 50) is None)

print("E) web.oku ikinci kilit: önek + ayraç, sızıntısız ileti, ≤1 sn yeniden deneme (ORTA 1, ORTA 3, DÜŞÜK 4)")
for belge, pencere in [("a", "X" + MF), ("Firefox", "Odeme" + MF), ("—", "Odeme" + MF), ("!!!", "Odeme" + MF),
                       ("🏦", "Odeme" + MF), ("Banka", "Banka odemeleri — Odeme" + MF)]:
    r, v = sonuc(web._belge_pencereye_ait, {"ad": belge}, pencere)
    kontrol(f"P3 belge {belge!r} / pencere {pencere!r} → Dur 6 (alt dizge kanıt değil)", r == "dur" and v.kod == 6,
            f"{r} {v}")
for belge, pencere in [("Banka odemeleri — Odeme", "Banka odemeleri — Odeme" + MF), ("Soak-C1-p0", "Soak-C1-p0 - Chromium"),
                       ("Electron Belge", "Electron Belge")]:
    r, v = sonuc(web._belge_pencereye_ait, {"ad": belge}, pencere)
    kontrol(f"belge {belge!r} pencere başlığının başında + ayraç/marka → geçer", r == "ok", f"{r} {v}")
r, v = sonuc(web._belge_pencereye_ait, {"ad": "Hesap Ozeti - Ali Veli 4421"}, "Odeme" + MF)
kontrol("P3 sızıntı: Dur iletisi OKUNAN belgenin başlığını içermez", r == "dur" and "Ali Veli" not in v.mesaj and
        "Hesap Ozeti" not in v.mesaj, f"{r} {v}")


def oku_dizi(adlar, pencere):
    """Her _yuru çağrısında sıradaki belge adı (son ad tekrarlanır): belge adı pencere başlığının gerisinde (ORTA 1)."""
    eski = web._baglam, web._yuru
    sayac = [0]

    def yuru(*a, **k):
        ad = adlar[min(sayac[0], len(adlar) - 1)]
        sayac[0] += 1
        return [], [{"ad": ad, "adres": "http://127.0.0.1/x", "durum": {"showing"}, "derinlik": 1, "kutu": None}], 3
    web._baglam = lambda k, islem="tara": (SahteAu(pencere), SahteYol([]), ":1.50", "/c", 0, (0, 0), "c")
    web._yuru = yuru
    t = time.monotonic()
    try:
        r = sonuc(web.oku, "arka:{x}", ayrinti=False)
        return r, sayac[0], time.monotonic() - t
    finally:
        web._baglam, web._yuru = eski


(r, v), n, sure = oku_dizi(["TIK Bülten aboneliği #2", "TIK Bülten aboneliği #2", "TIK Kaydet #3"], "TIK Kaydet #3" + MF)
kontrol("ORTA 1: tıklama sonrası belge adı 2 okuma geride → kısa yeniden denemeyle okunur (yanlış pozitif yok)",
        r == "ok" and v["sayfa"]["baslik"] == "TIK Kaydet #3" and n == 3, f"{r} {v} n={n}")
(r, v), n, sure = oku_dizi(["Soak-F3-p6"], F1)
kontrol("kalıcı uyuşmazlık → Dur 6, üst sınır ≤ 1.5 sn", r == "dur" and v.kod == 6 and sure <= 1.5 and n >= 2,
        f"{r} n={n} sure={sure:.2f}")

# ================================================================ SOAK-FIX-R2: REL-INC poc2 (O1, O2, O2b, O3) + poc3
print("F) SOAK-FIX-R2: kısayol yalnız pencerenin KENDİ süreci, pid okunamazsa bilinmiyor, yeniden deneme = yeni girişim")
# O1 (ORTA 2): tek çerçeve torun süreçten, ad hiç uymuyor, kardeş yok → kısayol AÇILMAZ (birebir ad şart)
r, v = sonuc(erisim.cerceve_karari, ["Gizli Hesap" + MF], "Odeme" + MF, [], [False])
kontrol("O1 torun tek çerçeve, ad uymuyor, kardes=[] → Dur 6 (kısayol yalnız pencerenin kendi sürecinden)",
        r == "dur" and v.kod == 6, f"{r} {v}")
r, v = sonuc(erisim.cerceve_karari, ["Gizli Hesap" + MF], "Odeme" + MF, [], None)
kontrol("O1 tam_pid bilinmiyor, ad uymuyor → Dur 6 (güvenli yön)", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = sonuc(erisim.cerceve_karari, ["Odeme"], "Odeme" + MF, [], [True])
kontrol("O1b pencerenin KENDİ sürecinden tek çerçeve, ad geride → seçilir (gerileme yok)", r == "ok" and v == 0, f"{r} {v}")
r, v = sonuc(erisim.cerceve_karari, ["Odeme" + MF], "Odeme" + MF, [], [False])
kontrol("torun tek çerçeve, BİREBİR ad, kardeş yok → seçilir", r == "ok" and v == 0, f"{r} {v}")
erisim._surec_akrabasi, erisim._exe = (lambda a, b: True), (lambda p: "/usr/bin/firefox")
try:
    r, v = er_sec2(["Gizli Hesap" + MF], "Odeme" + MF, [], uyg_pid=777, pencere_pid=4242)
    kontrol("O1 uçtan uca (_cerceve_bul): torun çerçevesi başka pencere adında → Dur 6", r == "dur" and v.kod == 6,
            f"{r} {v}")
finally:
    erisim._surec_akrabasi, erisim._exe = _eski
# O1 ileti: _cerceve_denetle yasak iletisi seçilen çerçevenin adını (belge başlığı) taşımaz
_eski_yd = erisim.guvenlik.yasak_desenler
erisim.guvenlik.yasak_desenler = lambda: ["Gizli"]
try:
    for islem in ("tara", "eylem"):
        r, v = sonuc(erisim._cerceve_denetle, 999999, "Firefox", "Gizli Hesap Ozeti Ali Veli 4421" + MF, islem)
        kontrol(f"O1 ileti ({islem}): yasak çerçeve → Dur 10, iletide çerçeve adı/belge başlığı YOK",
                r == "dur" and v.kod == 10 and "Ali Veli" not in v.mesaj and "Hesap Ozeti" not in v.mesaj, f"{r} {v}")
finally:
    erisim.guvenlik.yasak_desenler = _eski_yd


class PidsizAu(KardesAu):
    def pid(self, k): return next(p for k_, _b, p in self.p if k_ == k)


for bos in ("", None, 0):
    au_ = PidsizAu([("arka:{a}", "Odeme" + MF, 4242), ("arka:{b}", "Banka" + MF, bos), ("arka:{c}", "X" + MF, 4242)])
    kontrol(f"O2 bir pencerenin pid'i okunamıyor ({bos!r}) → kardes_basliklari None (bilinmiyor)",
            erisim.kardes_basliklari(au_, "arka:{a}", 4242) is None, str(erisim.kardes_basliklari(au_, "arka:{a}", 4242)))


class KwinPidsizAu:
    tur = "kwin"

    def __init__(self, p): self.p = p

    def _liste(self):
        return [{"i": "00000000-0000-0000-0000-00000000000a", "t": "Odeme" + MF, "p": 4242},
                {"i": "00000000-0000-0000-0000-00000000000b", "t": "Banka" + MF, "p": self.p}]


for bos in (-1, 0, None, ""):
    kontrol(f"O2 KWin: pencerenin pid'i {bos!r} → None (bilinmiyor)",
            erisim.kardes_basliklari(KwinPidsizAu(bos), "arka:00000000-0000-0000-0000-00000000000a", 4242) is None)
kd = erisim.kardes_basliklari(PidsizAu([("arka:{a}", "Odeme" + MF, 4242), ("arka:{b}", "Banka" + MF, "")]), "arka:{a}", 4242)
r, v = er_sec2(["Banka" + MF], "Odeme" + MF, kd)
kontrol("O2b A + B(pid okunamıyor), tek çerçeve B'nin → Dur 6 (önce: seçiliyordu = sızıntı)", r == "dur" and v.kod == 6,
        f"{r} {v}")
r, v = er_sec2(["Odeme" + MF], "Odeme" + MF, kd)
kontrol("O2b kardeş bilinmiyor, tek çerçeve BİREBİR ve güçlü başlık → seçilir (gerileme yok)", r == "ok", f"{r} {v}")
# O3 (DÜŞÜK 4): hedefin çerçevesi yok, öbür pencerenin a11y adı hedef başlığına eşit, WM başlığı geride
r, v = sonuc(erisim.cerceve_karari, ["Odeme" + MF], "Odeme" + MF, ["Banka" + MF], [True])
kontrol("O3 iki adlı pencere, tek çerçeve → Dur 6 (bir pencerenin çerçevesi yok: birebir ad kanıt değil)",
        r == "dur" and v.kod == 6, f"{r} {v}")
r, v = sonuc(erisim.cerceve_karari, ["Odeme" + MF, "Banka" + MF], "Odeme" + MF, ["Banka" + MF], [True, True])
kontrol("iki pencere, iki çerçeve → hedef seçilir (gerileme yok)", r == "ok" and v == 0, f"{r} {v}")
r, v = sonuc(erisim.cerceve_karari, ["Odeme" + MF], "Odeme" + MF, [""], [True])
kontrol("adsız kardeş pencere (açılır pencere) çerçeve sayısına katılmaz → seçilir", r == "ok" and v == 0, f"{r} {v}")


def calistir(baslik_sirasi, islem, yeniden_denetim="yok", basla="Docs" + MF):
    """_atspi_calistir: ilk çağrı SAYFA_BELIRSIZ, sonraki başarılı; tazelenen başlık baslik_sirasi'ndan.
    yeniden_denetim: "yok" = istekte _korumalar yok; None = korumalar geçer; işlev = korumalar onu çağırır."""
    eski = erisim._atspi_is, erisim._pencere_istegi, erisim._atspi_korumalari
    cagri = []

    def isle(i):
        cagri.append(("atspi_is", i["baslik"]))
        if len([c for c in cagri if c[0] == "atspi_is"]) == 1:
            raise Dur(6, "x", tur=erisim.SAYFA_BELIRSIZ)
        return {"tamam": True}
    sira = iter(baslik_sirasi)
    erisim._atspi_is = isle
    erisim._pencere_istegi = lambda k_, i: {"pid": "1", "baslik": next(sira), "kardes": []}
    def korumalar(k_, desen, tur):
        cagri.append(("denetim", k_, desen, tur))
        if callable(yeniden_denetim):
            yeniden_denetim()
    erisim._atspi_korumalari = korumalar
    ek = {} if yeniden_denetim == "yok" else {"_korumalar": ["Docs", "fare"]}
    try:
        return sonuc(erisim._atspi_calistir, {"_pencere": "A", "islem": islem, "baslik": basla, "pid": "1",
                                               "kardes": [], **ek}), cagri
    finally:
        erisim._atspi_is, erisim._pencere_istegi, erisim._atspi_korumalari = eski


for islem in ("eylem", "yaz"):
    (r, v), c = calistir(["Bank odeme" + MF], islem, None)
    kontrol(f"poc3 {islem}: yeniden denemede başlık değişti (sayfa geçişi) → eylem YOK, Dur 6",
            r == "dur" and v.kod == 6 and c == [("atspi_is", "Docs" + MF)], f"{r} {v} {c}")
    (r, v), c = calistir(["Docs" + MF], islem)
    kontrol(f"{islem}: istekte _korumalar yok → yeniden deneme YOK (güvenli yön), Dur 6",
            r == "dur" and v.kod == 6 and len(c) == 1, f"{r} {v} {c}")
    (r, v), c = calistir(["Docs" + MF], islem, None)
    kontrol(f"{islem}: başlık aynı → denetimler BAŞTAN koşar, sonra yeniden denenir",
            r == "ok" and c == [("atspi_is", "Docs" + MF), ("denetim", "A", "Docs", "fare"), ("atspi_is", "Docs" + MF)], f"{r} {v} {c}")

    def kilit():
        raise Dur(4, "başlık kilidi")
    (r, v), c = calistir(["Docs" + MF], islem, kilit)
    kontrol(f"{islem}: yeniden denemedeki denetim Dur verirse eylem YOK", r == "dur" and v.kod == 4 and
            c[0] == ("atspi_is", "Docs" + MF) and len([x for x in c if x[0] == "atspi_is"]) == 1, f"{r} {v} {c}")
(r, v), c = calistir(["Yeni sayfa" + MF], "tara")
kontrol("okuma (tara): başlık değişse de kısa yeniden deneme sürer (çerçeve kararı yeniden koşar)",
        r == "ok" and c[-1] == ("atspi_is", "Yeni sayfa" + MF), f"{r} {v} {c}")

t0 = time.monotonic()
print(f"\n{gecen}/{toplam} test geçti ({time.monotonic() - t0:.1f} sn)")
sys.exit(0 if gecen == toplam else 1)
