"""web.py güvenlik süzgeçleri:
1) _ayrinti_ekle giriş alanı değer maskesi (masaüstü yoluyla AYNI erisim._deger_temizle): one-time-code, cc-number, CVC,
   PIN/parola/doğrulama kodu adlı ya da ipuçlu alanlar "***"; sıradan alan değeri aynen; yalnız maske karakteri → değer yok.
   Sahte Yol.toplu ile (D-Bus yok) + GERÇEK Firefox (görünmez Xvfb masaüstü, geçici profil; firefox/Xvfb yoksa atlanır).
   Sınır (ölçüldü, Firefox): HTML autocomplete belirteci AT-SPI niteliklerinde YOK (yalnız id, placeholder-text,
   text-input-type); yalnız autocomplete ile işaretli, adı/id'si sıradan alan maskelenemez (BİLGİ satırı).
2) tarayici_mi sınıf deseni sınırlı: zenity, hedgewars, knowledge-base, citizen, operator, chromatic tarayıcı DEĞİL.
Kullanıcının ekranına girdi gitmez; Firefox kısmı kullanıcının profil kökünü önce/sonra karşılaştırır.

Çalıştır:  python3 tests/test_web_maske.py"""
import atexit
import os
import shutil
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import web  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ---------------------------------------------------------------- 1) sahte Yol.toplu ile değer maskesi
class SahteYol:
    """Mesajın nesne yolu + üyesine (Get için özellik adına) göre yanıt; bilinmeyen → None (hata yanıtı)."""

    def __init__(self, veri):
        self.veri = veri

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        from jeepney.low_level import HeaderFields
        sonuc = []
        for m in mesajlar:
            f = m.header.fields
            yol, uye = f[HeaderFields.path], f[HeaderFields.member]
            if uye == "Get":
                uye = m.body[1]
            sonuc.append(self.veri.get((yol, uye)))
        return sonuc


ALANLAR = [  # (ad, değer, açıklama, nitelikler, beklenen)
    ("Kod", "482913", "", {"autocomplete": "one-time-code"}, "***"),
    ("Numara", "4111111111111111", "", {"autocomplete": "cc-number"}, "***"),
    ("Üç hane", "737", "", {"id": "cc-csc"}, "***"),
    ("CVC", "737", "", {}, "***"),
    ("Parola", "s3cret", "", {}, "***"),
    ("PIN", "1234", "", {}, "***"),
    ("Alan", "999111", "Tek kullanımlık kod", {}, "***"),
    ("Alan altı", "gizli", "", {"placeholder": "Şifre"}, "***"),
    ("Kutu", "abc", "", {"text-input-type": "password"}, "***"),
    ("Doğrulama kodu", "55667", "", {}, "***"),
    ("Şehir", "Çınarlı", "", {"id": "sehir"}, "Çınarlı"),
    # gerçek tarayıcı nitelikleri hiç boş değil (ölçüldü); id/autocomplete/placeholder/text-input-type'sız alan doğrulanamaz
    ("Not", "a\x1bb\nc", "", {"tag": "input", "id": "not"}, "ab c"),
    ("Maske", "••••", "", {}, None),
]

veri, ogeler, ham = {}, [], []
for i, (ad, deger, aciklama, nit, _b) in enumerate(ALANLAR):
    yol = f"/o/{i}"
    veri[(yol, "GetText")] = (deger,)
    veri[(yol, "Description")] = (("s", aciklama),)
    veri[(yol, "GetAttributes")] = (nit,)
    ogeler.append({"ad": ad[:3] if i == 0 else ad, "rol": "entry" if i % 3 else "spin button"})  # ilk: kırpılmış ad
    ham.append({"_yol": yol, "ad": ad})
web._ayrinti_ekle(SahteYol(veri), ":1.5", ogeler, ham)
for (ad, deger, aciklama, nit, beklenen), o in zip(ALANLAR, ogeler):
    kontrol(f"maske (sahte): {ad!r} {nit or aciklama or ''} → {beklenen!r}", o.get("deger") == beklenen, repr(o.get("deger")))

# ipuçları okunamasa (hata yanıtı) da ad tek başına maskeler; değer okunamazsa alan yok
veri2 = {("/p", "GetText"): ("4242",)}
o2 = [{"ad": "PIN", "rol": "entry"}, {"ad": "X", "rol": "entry"}]
web._ayrinti_ekle(SahteYol(veri2), ":1.5", o2, [{"_yol": "/p", "ad": "PIN"}, {"_yol": "/yok", "ad": "X"}])
kontrol("maske (sahte): açıklama/nitelik hata yanıtı → ad yine maskeler", o2[0].get("deger") == "***", repr(o2[0]))
kontrol("maske (sahte): değer okunamadı → deger alanı yok", "deger" not in o2[1], repr(o2[1]))



class IlkBosYol(SahteYol):
    """Firefox gibi: ögenin nitelikleri ilk sorguda {} (ölçüldü), ikincide gerçek."""

    def __init__(self, veri):
        super().__init__(veri)
        self.sorulan = set()

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        from jeepney.low_level import HeaderFields
        r = super().toplu(mesajlar, sure, yeniden)
        for i, m in enumerate(mesajlar):
            f = m.header.fields
            if f[HeaderFields.member] == "GetAttributes" and f[HeaderFields.path] not in self.sorulan:
                self.sorulan.add(f[HeaderFields.path])
                r[i] = ({},)
        return r


veri3 = {("/q", "GetText"): ("482913",), ("/q", "Description"): (("s", ""),), ("/q", "GetAttributes"): ({"id": "otp-input"},)}
o3 = [{"ad": "Kod", "rol": "entry"}]
web._ayrinti_ekle(IlkBosYol(veri3), ":1.5", o3, [{"_yol": "/q", "ad": "Kod"}])
kontrol("maske (sahte): nitelikler ilk sorguda boş (Firefox) → bir kez daha sorulur, id=otp-input maskeler",
        o3[0].get("deger") == "***", repr(o3[0]))


class EtkinlesmeYol(SahteYol):
    """Firefox nitelik önbelleği yarışı (ölçüldü: oturumdaki İLK Accessible.GetAttributes {} döner, önbelleği açar). AYNI
    toplu istekteki öteki yanıtlar önbellek dolana dek EKSİK gelebilir (id/autocomplete yok; tag/placeholder-text var):
    -j 4 yükte (kart-DHV) Kod ve Alan altı maskeli, Numara (id=cc-number) ile Üç hane (id=cvc) MASKESİZ döndü.
    dolum: kaç toplu çağrı daha eksik yanıt verilsin (1 = yalnız ilk toplu; 99 = hiç dolmaz)."""

    def __init__(self, veri, dolum=1):
        super().__init__(veri)
        self.ilk, self.kalan = True, dolum

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        from jeepney.low_level import HeaderFields
        r = super().toplu(mesajlar, sure, yeniden)
        nitelik = [i for i, m in enumerate(mesajlar) if m.header.fields[HeaderFields.member] == "GetAttributes"]
        if nitelik and self.kalan > 0:
            self.kalan -= 1
            for i in nitelik:
                if self.ilk:
                    self.ilk, r[i] = False, ({},)
                elif r[i]:
                    r[i] = ({a: d for a, d in r[i][0].items() if a not in ("id", "autocomplete")},)
        return r


def maske_html_verisi():
    """tests/ornek/web/maske.html alanlarının Firefox'taki (ölçülen) nitelikleriyle sahte veri."""
    alanlar = [("Kod", "482913", {"id": "otp-input"}), ("Numara", "4111111111111111", {"id": "cc-number"}),
               ("Üç hane", "737", {"id": "cvc"}), ("Alan altı", "gizli-deger-6", {"id": "x6", "placeholder-text": "Parola tekrar"}),
               ("Şehir", "Çınarlı", {"id": "sehir"})]
    v, og, hm = {}, [], []
    for i, (ad, deger, nit) in enumerate(alanlar):
        y = f"/e/{i}"
        v[(y, "GetText")] = (deger,)
        v[(y, "Description")] = (("s", ""),)
        v[(y, "GetAttributes")] = ({**nit, "explicit-name": "true", "tag": "input", "display": "inline-block"},)
        og.append({"ad": ad, "rol": "entry"})
        hm.append({"_yol": y, "ad": ad})
    return v, og, hm


v4, o4, h4 = maske_html_verisi()
web._ayrinti_ekle(EtkinlesmeYol(v4), ":1.5", o4, h4)
d4 = {o["ad"]: o.get("deger") for o in o4}
kontrol("maske (yarış): önbellek açılırken aynı toplu yanıtta id eksik → Kod/Numara/Üç hane/Alan altı yine ***",
        all(d4[a] == "***" for a in ("Kod", "Numara", "Üç hane", "Alan altı")), repr(d4))
kontrol("maske (yarış): sıradan alan değeri korunur (Şehir = Çınarlı)", d4["Şehir"] == "Çınarlı", repr(d4))
kontrol("maske (yarış): kart numarası çıktıda hiç yok", "4111111111111111" not in repr(o4), repr(o4))

v5, o5, h5 = maske_html_verisi()
web._ayrinti_ekle(EtkinlesmeYol(v5, dolum=2), ":1.5", o5, h5)
d5 = {o["ad"]: o.get("deger") for o in o5}
kontrol("maske (yarış, önbellek bir tur geç dolar): Kod/Numara/Üç hane/Alan altı ***, Şehir korunur, sızıntı yok",
        all(d5[a] == "***" for a in ("Kod", "Numara", "Üç hane", "Alan altı")) and d5["Şehir"] == "Çınarlı"
        and "4111111111111111" not in repr(o5) and "737" not in repr(o5), repr(d5))

# önbelleği açan {} yanıtı DEĞERSİZ (boş) bir alana düşer, dolum bir tur geç: ilk toplu yanıt kıyasa girmemeli
v8, o8, h8 = maske_html_verisi()
v8[("/e/bos", "GetText")], v8[("/e/bos", "Description")] = ("",), (("s", ""),)
v8[("/e/bos", "GetAttributes")] = ({"id": "arama", "tag": "input"},)
o8.insert(0, {"ad": "Arama", "rol": "entry"})
h8.insert(0, {"_yol": "/e/bos", "ad": "Arama"})
web._ayrinti_ekle(EtkinlesmeYol(v8, dolum=2), ":1.5", o8, h8)
d8 = {o["ad"]: o.get("deger") for o in o8}
kontrol("maske (yarış, {} değersiz alana düştü, dolum geç): Kod/Numara/Üç hane ***, Şehir korunur",
        all(d8[a] == "***" for a in ("Kod", "Numara", "Üç hane")) and d8["Şehir"] == "Çınarlı"
        and "4111111111111111" not in repr(o8) and "737" not in repr(o8), repr(d8))

# nitelikler hiç okunamıyor (her sorguda {}): ad sıradan olsa da değer doğrulanamaz → *** (kapalı-başarısız)
v6 = {("/r", "GetText"): ("737",), ("/r", "Description"): (("s", ""),), ("/r", "GetAttributes"): ({},),
      ("/s", "GetText"): ("Çınarlı",), ("/s", "Description"): (("s", ""),),
      ("/s", "GetAttributes"): ({"id": "sehir", "tag": "input"},)}
o6 = [{"ad": "Üç hane", "rol": "entry"}, {"ad": "Şehir", "rol": "entry"}]
web._ayrinti_ekle(SahteYol(v6), ":1.5", o6, [{"_yol": "/r", "ad": "Üç hane"}, {"_yol": "/s", "ad": "Şehir"}])
kontrol("maske (sahte): nitelikler hep boş → değer ***; nitelikli sıradan alan etkilenmez",
        o6[0].get("deger") == "***" and o6[1].get("deger") == "Çınarlı", repr(o6))

# ipucundan bağımsız: Luhn'lu kart numarası değeri sıradan adlı/nitelikli alanda da maskeli
v7 = {("/t", "GetText"): ("4111 1111 1111 1111",), ("/t", "Description"): (("s", ""),),
      ("/t", "GetAttributes"): ({"id": "siparis", "tag": "input"},)}
o7 = [{"ad": "Sipariş", "rol": "entry"}]
web._ayrinti_ekle(SahteYol(v7), ":1.5", o7, [{"_yol": "/t", "ad": "Sipariş"}])
kontrol("maske (sahte): sıradan alanda Luhn'lu kart numarası değeri → ***", o7[0].get("deger") == "***", repr(o7))


class PlanYol(SahteYol):
    """K2 PoC (INCELEME-MASKE P1–P3): GetAttributes içeren her toplu çağrı plandaki kipe göre yanıt verir: "ilkbos" (ilk
    öge {}, öteki ögeler kısmi), "kismi" (id/autocomplete yok; tag/display kalır), "tam" (plan bitince de tam)."""

    def __init__(self, veri, plan):
        super().__init__(veri)
        self.plan = list(plan)

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        from jeepney.low_level import HeaderFields
        r = super().toplu(mesajlar, sure, yeniden)
        nitelik = [i for i, m in enumerate(mesajlar) if m.header.fields[HeaderFields.member] == "GetAttributes"]
        if nitelik:
            kip = self.plan.pop(0) if self.plan else "tam"
            for k, i in enumerate(nitelik):
                if kip == "ilkbos" and k == 0:
                    r[i] = ({},)
                elif kip in ("ilkbos", "kismi") and r[i]:
                    r[i] = ({a: d for a, d in r[i][0].items() if a not in ("id", "autocomplete")},)
        return r


def poc_verisi():
    alanlar = [("Kod", "482913", {"id": "otp-input"}), ("Numara", "4111111111111111", {"id": "cc-number"}),
               ("Üç hane", "737", {"id": "cvc"}), ("Şehir", "Çınarlı", {"id": "sehir"})]
    v, og, hm = {}, [], []
    for i, (ad, deger, nit) in enumerate(alanlar):
        y = f"/p/{i}"
        v[(y, "GetText")] = (deger,)
        v[(y, "Description")] = (("s", ""),)
        v[(y, "GetAttributes")] = ({**nit, "tag": "input", "display": "inline-block"},)
        og.append({"ad": ad, "rol": "entry"})
        hm.append({"_yol": y, "ad": ad})
    return v, og, hm


for poc, plan in (("P1 ilk toplu {}+kısmi, iki tur kısmi", ["ilkbos", "kismi", "kismi", "tam"]),
                  ("P2 ilk toplu {}+kısmi, üç tur kısmi", ["ilkbos", "kismi", "kismi", "kismi", "tam"]),
                  ("P3 hiç {} yok, yalnız ilk toplu kısmi", ["kismi", "tam", "tam"])):
    vp, op, hp = poc_verisi()
    web._ayrinti_ekle(PlanYol(vp, plan), ":1.5", op, hp)
    dp = {o["ad"]: o.get("deger") for o in op}
    kontrol(f"maske (K2 {poc}): Kod/Numara/Üç hane ***, gizli değer çıktıda yok",
            all(dp[a] == "***" for a in ("Kod", "Numara", "Üç hane"))
            and not any(g in repr(op) for g in ("482913", "4111111111111111", "737")), repr(dp))
vp, op, hp = poc_verisi()
web._ayrinti_ekle(PlanYol(vp, ["kismi", "tam", "tam"]), ":1.5", op, hp)
kontrol("maske (K2 P3): yeniden sorulup tam gelen sıradan alan korunur (Şehir = Çınarlı)",
        op[3].get("deger") == "Çınarlı", repr(op[3]))


def tek_alanlar(alanlar):
    """[(ad, değer, nitelikler)] → kararlı (her sorguda aynı) sahte veri, ögeler, ham."""
    v, og, hm = {}, [], []
    for i, (ad, deger, nit) in enumerate(alanlar):
        y = f"/k/{i}"
        v[(y, "GetText")] = (deger,)
        v[(y, "Description")] = (("s", ""),)
        v[(y, "GetAttributes")] = (nit,)
        og.append({"ad": ad, "rol": "entry"})
        hm.append({"_yol": y, "ad": ad})
    return v, og, hm


# doğrulanamaz: kararlı ama id/autocomplete/placeholder(-text)/text-input-type yok → ***
v9, o9, h9 = tek_alanlar([("Şehir", "Çınarlı", {"tag": "input", "display": "inline-block", "explicit-name": "true"}),
                          ("Köy", "Akçaören", {"tag": "input", "text-input-type": "text"})])
web._ayrinti_ekle(SahteYol(v9), ":1.5", o9, h9)
kontrol("maske (sahte): kararlı ama tanıtıcı niteliksiz (yalnız tag/display/explicit-name) → ***; text-input-type'lı korunur",
        o9[0].get("deger") == "***" and o9[1].get("deger") == "Akçaören", repr(o9))

# ipucusuz (id/placeholder/autocomplete yok) yalnız rakam 3–8 hane → *** (yanlış pozitif kabul: adet alanı)
v10, o10, h10 = tek_alanlar([("Üç hane", "737", {"tag": "input", "text-input-type": "tel"}),
                             ("Giriş", "48291300", {"tag": "input", "text-input-type": "text"}),
                             ("Uzun", "123456789", {"tag": "input", "text-input-type": "text"}),
                             ("Kısa", "12", {"tag": "input", "text-input-type": "number"}),
                             ("Adet", "250", {"id": "adet", "tag": "input"}),
                             ("Yazı", "Çınar 12", {"tag": "input", "text-input-type": "text"})])
web._ayrinti_ekle(SahteYol(v10), ":1.5", o10, h10)
d10 = {o["ad"]: o.get("deger") for o in o10}
kontrol("maske (sahte): ipucusuz 3–8 haneli rakam değeri ***; 9 hane, 2 hane, id'li ve harfli değer korunur",
        d10 == {"Üç hane": "***", "Giriş": "***", "Uzun": "123456789", "Kısa": "12", "Adet": "250", "Yazı": "Çınar 12"},
        repr(d10))

# bölünmüş kart numarası (4+4+4+4 ardışık alan, id'li): birleşimi Luhn'lu → hepsi ***; Luhn'suz birleşim korunur
v11, o11, h11 = tek_alanlar([("Ad", "Ayşe", {"id": "ad"})] +
                            [(f"Kart {i}", "4111", {"id": f"kart{i}"}) if i == 1 else (f"Kart {i}", "1111", {"id": f"kart{i}"})
                             for i in range(1, 5)] +
                            [("Tel 1", "1234", {"id": "t1"}), ("Tel 2", "5678", {"id": "t2"})])
web._ayrinti_ekle(SahteYol(v11), ":1.5", o11, h11)
d11 = {o["ad"]: o.get("deger") for o in o11}
kontrol("maske (sahte): 4+4+4+4 bölünmüş Luhn'lu kart numarası → dört alan ***; komşu sıradan alanlar korunur",
        all(d11[f"Kart {i}"] == "***" for i in range(1, 5)) and d11["Ad"] == "Ayşe"
        and d11["Tel 1"] == "1234" and d11["Tel 2"] == "5678", repr(d11))

# ---------------------------------------------------------------- 2) tarayıcı sınıf deseni (tablo)
class SahteAU:
    def __init__(self, sinif):
        self._s = sinif

    def sinif(self, k):
        return self._s


eski_sec = web.sec
EVET = ["firefox", "org.mozilla.firefox", "firefoxdeveloperedition", "firefox-esr", "librewolf",
        "io.gitlab.librewolf-community", "waterfox", "one.ablaze.floorp", "zen", "zen-alpha", "app.zen_browser.zen",
        "chromium", "Chromium-browser", "google-chrome", "chrome-abcdefgh-Default", "brave-browser", "vivaldi-stable",
        "opera", "microsoft-edge-dev", "msedge", "thorium-browser", "org.gnome.Epiphany", "org.kde.falkon", "electron",
        "electron25", "code", "discord"]
HAYIR = ["zenity", "hedgewars", "knowledge-base", "citizen", "operator", "chromatic", "org.kde.konsole",
         "org.kde.dolphin", "kwrite", "steam", ""]
try:
    for sinif in EVET + HAYIR:
        web.sec = lambda k, _s=sinif: SahteAU(_s)
        beklenen = sinif in EVET
        kontrol(f"tarayici_mi({sinif!r}) = {beklenen}", web.tarayici_mi("{1234}") is beklenen)
finally:
    web.sec = eski_sec


# ---------------------------------------------------------------- 3) GERÇEK Firefox (görünmez masaüstü, geçici profil)
def firefox_bolumu():
    if not (shutil.which("firefox") and shutil.which("Xvfb")):
        print("atlandı (Firefox bölümü): firefox ya da Xvfb yok")
        return
    sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
    import web_tarayici as wt
    from deskhand import masaustu
    from deskhand.arka_uc import sec
    bekci = wt.ProfilBekcisi()
    d = masaustu.masaustu_baslat()  # noqa: F841
    acik = []

    def kapat():
        for ff_ in acik:
            try:
                ff_.kapat()
            except Exception:  # noqa: BLE001
                pass
        if masaustu.durum_oku() is not None:
            masaustu.masaustu_durdur()
    atexit.register(kapat)
    au = sec(arka_bayragi=True)
    srv = wt.Sunucu()
    try:
        ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("maske.html"))
        acik.append(ff)
        k = ff.k
        kontrol("firefox: pencere arka plan masaüstünde", bool(k) and k.startswith("arka:"), str(k))
        bitis, ogeler = time.monotonic() + 15, {}
        while time.monotonic() < bitis:
            try:
                ogeler = {o["ad"]: o for o in web.oku(k, gorunur=False, en_cok=0)["ogeler"]}
            except Exception:  # noqa: BLE001
                ogeler = {}
            if ogeler.get("Şehir", {}).get("deger") == "Çınarlı":
                break
            time.sleep(0.2)
        kontrol("firefox: sıradan alan değeri okunuyor (Şehir = Çınarlı)", ogeler.get("Şehir", {}).get("deger") == "Çınarlı",
                str(ogeler.get("Şehir")))
        for ad, gizli in (("Kod", "482913"), ("Numara", "4111111111111111"), ("Üç hane", "737"), ("PIN", "1234"),
                          ("Doğrulama kodu", "55667"), ("Alan altı", "gizli-deger-6"), ("Güvenlik kodu", "909")):
            o = ogeler.get(ad)
            kontrol(f"firefox: {ad!r} değeri maskeli (***)", o is not None and o.get("deger") == "***" and
                    gizli not in str(o), str(o))
        o = ogeler.get("Giriş 9")
        print("BİLGİ (sınır): yalnız autocomplete=\"one-time-code\" ile işaretli, adı/id'si sıradan alan: Firefox bu belirteci"
              " erişilebilirlik ağacına vermiyor →", "maskeli" if o and o.get("deger") == "***" else "maskelenemedi",
              flush=True)
        f = bekci.fark()
        kontrol("firefox: kullanıcının profil kökü değişmedi", not f, str(f))
    finally:
        srv.kapat()
        kapat()


firefox_bolumu()
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
