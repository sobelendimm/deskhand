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


def web_sec(cerceveler, baslik):
    r, v = sonuc(web._cerceve_bul, SahteYol(cerceveler), WPID, baslik)
    return (r, v[4]) if r == "ok" else (r, v)


print("A) web._cerceve_bul: aynı süreçte 3 Firefox çerçevesi")
S, AS = ("showing",), ("active", "showing")
r, v = web_sec([(F1, S), (F2, S), (GECIS, AS)], F1)
kontrol("geçiş anı: F3 etkin ve adı 'Mozilla Firefox' (F1 başlığının içinde) → yine F1'in çerçevesi", r == "ok" and v == F1,
        f"{r} {v}")
r, v = web_sec([(F1, S), (F2, S), ("Soak-loading — Mozilla Firefox", AS)], F1)
kontrol("geçiş anı: F3 'Soak-loading' başlığında, etkin → F1", r == "ok" and v == F1, f"{r} {v}")
r, v = web_sec([("Soak-F1-p3 — Mozilla Firefox", S), (F2, S), (GECIS, AS)], F1)
kontrol("F1'in çerçeve adı pencere başlığının gerisinde (birebir eşleşme yok) → tahmin yok, Dur 6 (yeniden dene)",
        r == "dur" and v.kod == 6, f"{r} {v}")
r, v = web_sec([(F1, S), (F1, AS), (F2, S)], F1)
kontrol("aynı süreçte aynı başlıklı iki çerçeve → etkin olan SEÇİLMEZ, Dur 6 (pencere kimliği yok)", r == "dur" and v.kod == 6,
        f"{r} {v}")
r, v = web_sec([("Soak-C1-p0 - Chromium", AS)], "Soak-C1-p0 - Chromium")
kontrol("tek çerçeve, birebir → seçilir", r == "ok" and v == "Soak-C1-p0 - Chromium", f"{r} {v}")
r, v = web_sec([("Soak-C1-p0", AS)], "Soak-C1-p0 - Chromium")
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


def er_sec(adlar, baslik):
    r, v = sonuc(erisim._cerceve_bul, SahteAtspi([Uyg(PID, "Firefox", [Cerceve(a) for a in adlar])]), PID, baslik)
    return (r, v[0].ad) if r == "ok" else (r, v)


print("B) erisim._cerceve_bul: aynı süreçte 3 çerçeve")
r, v = er_sec([F1, F2, GECIS], F1)
kontrol("birebir başlık → F1", r == "ok" and v == F1, f"{r} {v}")
r, v = er_sec(["Soak-F1-p3 — Mozilla Firefox", F2, GECIS], F1)
kontrol("F1 adı geride, F3 'Mozilla Firefox' (içerme) → F3 SEÇİLMEZ, Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = er_sec(["Soak-F1-p3 — Mozilla Firefox", F2], F1)
kontrol("birebir eşleşme yok, benzerlikle tahmin yok → Dur 6", r == "dur" and v.kod == 6, f"{r} {v}")
r, v = er_sec(["Belge — KWrite"], "Belge — KWrite")
kontrol("tek çerçeve → seçilir", r == "ok" and v == "Belge — KWrite", f"{r} {v}")
r, v = er_sec(["Belge"], "Belge — KWrite")
kontrol("tek çerçeve, içerme → seçilir (gerileme yok)", r == "ok" and v == "Belge", f"{r} {v}")
DIYALOG = "File Upload - Soak-F1-p4 — Mozilla Firefox"
r, v = er_sec([F1, DIYALOG], DIYALOG)
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

t0 = time.monotonic()
print(f"\n{gecen}/{toplam} test geçti ({time.monotonic() - t0:.1f} sn)")
sys.exit(0 if gecen == toplam else 1)
