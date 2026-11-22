"""web.py güvenlik süzgeçleri:
1) _ayrinti_ekle giriş alanı değer maskesi (masaüstü yoluyla AYNI erisim._deger_temizle): one-time-code, cc-number, CVC,
   PIN/parola/doğrulama kodu adlı ya da ipuçlu alanlar "***"; sıradan alan değeri aynen; yalnız maske karakteri → değer yok.
   Sahte Yol.toplu ile (D-Bus yok) + GERÇEK Firefox (görünmez Xvfb masaüstü, geçici profil; firefox/Xvfb yoksa atlanır).
   Sınır (ölçüldü, Firefox): HTML autocomplete belirteci AT-SPI niteliklerinde YOK (yalnız id, placeholder-text,
   text-input-type); yalnız autocomplete ile işaretli, adı/id'si sıradan alan maskelenemez (BİLGİ satırı).
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
    ("Şehir", "Niğde", "", {"id": "sehir"}, "Niğde"),
    ("Not", "a\x1bb\nc", "", {}, "ab c"),
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

# ---------------------------------------------------------------- 2) GERÇEK Firefox (görünmez masaüstü, geçici profil)
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
            if ogeler.get("Şehir", {}).get("deger") == "Niğde":
                break
            time.sleep(0.2)
        kontrol("firefox: sıradan alan değeri okunuyor (Şehir = Niğde)", ogeler.get("Şehir", {}).get("deger") == "Niğde",
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
