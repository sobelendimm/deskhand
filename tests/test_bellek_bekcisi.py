"""Bellek bekçisi (deskhand/bellek_bekcisi.py, ABM-F1) birim testleri: sahte cgroup dizini, sahte masaüstü kaydı. Gerçek
yeniden başlatma yolu (öldür → kurtarma denetimi → user.js → başlat → doğrulama → eski bekçi) SAHTE Firefox süreçleriyle
sınanır (argv[0] "firefox", --profile <kopya>; masaustu.baslat taklit). Gerçek KWin kanıtı: ABM-F1 raporundaki deney.

Çalıştır:  python3 tests/test_bellek_bekcisi.py"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import arka_ortak as ao, bellek_bekcisi as bb, masalar, masaustu, yollar
from deskhand.hata import Dur
from deskhand.oturum import firefox, kopya_bekcisi

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


KOK = tempfile.mkdtemp(prefix="bb-cg-", dir=_yalitim.GECICI)
CG = "/user.slice/deskhand-kwin-test-1.scope"
CGD = os.path.join(KOK, CG.lstrip("/"))
os.makedirs(CGD)
bb.CGROUP_KOK = KOK
MAX = 8 << 30
SHMEM = 12345


def cg_yaz(oran, azami=MAX, onbellek=0.0):
    """oran: anon+shmem / max (bekçinin oranı); onbellek: ek sayfa önbelleği (memory.current'a girer, orana girmez)."""
    kullanim = int(azami * oran) if azami else int(MAX * oran)
    with open(os.path.join(CGD, "memory.current"), "w") as f:
        f.write(str(kullanim + int((azami or MAX) * onbellek)))
    with open(os.path.join(CGD, "memory.max"), "w") as f:
        f.write(str(azami) if azami else "max")
    with open(os.path.join(CGD, "memory.stat"), "w") as f:
        f.write(f"anon {kullanim - SHMEM}\nfile {int((azami or MAX) * onbellek) + SHMEM}\nshmem {SHMEM}\n")
    if not os.path.exists(os.path.join(CGD, "memory.reclaim")):
        with open(os.path.join(CGD, "memory.reclaim"), "w"):
            pass


def reclaim_icerik():
    with open(os.path.join(CGD, "memory.reclaim")) as f:
        return f.read()


def reclaim_bosalt():
    with open(os.path.join(CGD, "memory.reclaim"), "w"):
        pass


def gunluk_metni():
    yol = os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))
    try:
        with open(yol, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


AD = masalar.secili()
os.makedirs(masalar.kok(AD), exist_ok=True)
CALISMA = tempfile.mkdtemp(prefix="bb-calisma-", dir=_yalitim.GECICI)
D = {"cgroup": CG, "calisma": CALISMA, "kimlik": "test"}
SON = {"t": None}
DURDURULDU = []
YENIDEN = []
GERCEK_YENIDEN = bb.firefox_yeniden_baslat
GERCEK_ENGEL = bb._engel
masaustu.durum = lambda *a, **k: dict(D)
masaustu.son_kullanim = lambda ad=None: SON["t"]
masaustu.masaustu_durdur = lambda *a, **k: (DURDURULDU.append(a), (True, []))[1]
masaustu.devral_var = lambda *a, **k: False
ETKI = {"sonra": 0.5}  # taklit yeniden başlatmadan sonraki oran (None: değişmez)


def taklit_yeniden(d, g, son=None):
    YENIDEN.append(g["kopya"])
    if ETKI["sonra"] is not None:
        cg_yaz(ETKI["sonra"])
    return {"ok": True, "pid": 1, "sekme": 3, "kopya": g["kopya"]}


bb.firefox_yeniden_baslat = taklit_yeniden
bb._engel = lambda ad, d=None: None
GERCEK_CANLI = bb._kayit_canli
bb._kayit_canli = lambda g, cg: True  # taklit bölümü: kayıtlar (/k/a) canlı sayılır; gerçek yol bölümünde gerçeği
T = time.time()  # duvar saati (boşta denetimi: son_kullanim bir mtime)
M = bb._mono()   # süre saati (CLOCK_BOOTTIME): 10 dk / geri çekilme / 24 sa


def bakim_at(ofs=0.0, duvar=None):
    """ofs sn sonrası bakım (iki saat birlikte ilerler; duvar: duvar saatini ayrıca kaydır)."""
    return bb.bakim(AD, simdi=T + ofs + (duvar or 0.0), mono=M + ofs)


def sifirla():
    for yol in (bb._durum_yolu(AD),):
        if os.path.exists(yol):
            os.unlink(yol)
    DURDURULDU.clear()
    YENIDEN.clear()
    bb._ONBELLEK.clear()
    ETKI["sonra"] = 0.5
    reclaim_bosalt()


def kayit_yaz(kayitlar):
    with open(os.path.join(CALISMA, bb.KAYIT_DOSYA), "w") as f:
        json.dump(kayitlar, f)


# ---------------------------------------------------------------- durum + uyarı
cg_yaz(0.5)
du = bb.bellek_durumu(CG)
kontrol("bellek_durumu: current/max/oran/shmem/anon/kullanim",
        du["max"] == MAX and du["oran"] == 0.5 and du["shmem"] == SHMEM and du["kullanim"] == int(MAX * 0.5)
        and du["anon"] == int(MAX * 0.5) - SHMEM, du)
kontrol("oran 0,5 → uyarı yok", bb.bellek_uyarisi(du) is None and "memory_warning" not in bb.uyari_ekle({"status": "ok"}))
cg_yaz(0.5, azami=0)
kontrol("sınırsız kafes → oran 0, uyarı yok", bb.bellek_durumu(CG)["oran"] == 0.0 and bb.bellek_uyarisi(bb.bellek_durumu(CG)) is None)
kontrol("geçersiz kafes yolu (..) → None", bb.bellek_durumu("/user.slice/../../etc") is None and bb.bellek_durumu("") is None)

# B3: oran sayfa önbelleği hariç (anon + shmem)
sifirla()
cg_yaz(0.30, onbellek=0.62)
du = bb.bellek_durumu(CG)
SON["t"] = T - 1000
kontrol("B3: oran anon+shmem üzerinden (memory.current %92 ama önbellek hariç %30 → uyarı yok, bakım yok)",
        abs(du["oran"] - 0.30) < 0.001 and du["current"] > 0.9 * MAX and bb.bellek_uyarisi(du) is None
        and bakim_at(0) is None and reclaim_icerik() == "", du)

sifirla()
cg_yaz(0.85)
SON["t"] = T  # şimdi kullanılıyor (boşta değil)
r = bb.uyari_ekle({"status": "ok"})
kontrol("kayıtlı Firefox yokken uyarı yeniden başlatma vaat etmez", "Firefox" not in (r.get("memory_warning") or "Firefox"), r)
kayit_yaz([{"argv": ["firefox", "--profile", "/k/a", "--no-remote"], "env": {}, "kopya": "/k/a", "ev": [], "pid": 5}])
bb._ONBELLEK.clear()
r = bb.uyari_ekle({"status": "ok"})
kontrol("oran 0,85 → memory_warning dolu", "85" in (r.get("memory_warning") or "") and "Firefox" in r["memory_warning"],
        r)
kontrol("oran 0,85 → masaüstü açık kalır (görev ortasında bakım yok, kapatma yok)",
        bakim_at(5) is None and not DURDURULDU and not YENIDEN and reclaim_icerik() == "")
kontrol("uyarı yalnız sözlüğe eklenir; hata sonucu (CallToolResult vb.) dokunulmaz",
        bb.uyari_ekle("metin") == "metin" and bb.uyari_ekle({"memory_warning": "x"}) == {"memory_warning": "x"})

# ---------------------------------------------------------------- Firefox yeniden başlatma (taklit)
sifirla()
cg_yaz(0.86)
SON["t"] = T - 200
os.environ.pop(bb.ORTAM_FF, None)
s = bakim_at(0)
kontrol("boşta + ≥0,85 → yalnız Firefox yeniden başlar, masaüstü açık kalır",
        s and s["is"] == "firefox_yeniden" and YENIDEN == ["/k/a"] and not DURDURULDU and reclaim_icerik() == "", s)
r = bb.uyari_ekle({})
kontrol("yeniden başlatma memory_warning'de bildirilir (sekme sayısı, yeniden gözlem)",
        "yeniden başlatıldı" in (r.get("memory_warning") or "") and "3 sekme" in r["memory_warning"]
        and "azaltmadı" not in r["memory_warning"], r)
YENIDEN.clear()
cg_yaz(0.86)
s2 = bakim_at(120)
kontrol("Firefox yeniden başlatma 10 dk içinde ikinci kez yapılmaz (yerine reclaim)",
        not YENIDEN and s2 and s2["is"] == "reclaim", s2)

sifirla()
cg_yaz(0.9)
os.environ[bb.ORTAM_FF] = "kapali"
s = bakim_at(0)
kontrol("DESKHAND_FF_YENIDEN=kapali → yeniden başlatma yok (reclaim yapılır)",
        not YENIDEN and s and s["is"] == "reclaim" and reclaim_icerik() == bb.RECLAIM_MIKTAR, s)
kontrol("DESKHAND_FF_YENIDEN=kapali → uyarı yeniden başlatma vaat etmez",
        "Firefox" not in (bb.uyari_ekle({}).get("memory_warning") or "Firefox"))
os.environ.pop(bb.ORTAM_FF, None)

# NIT: DESKHAND_FF_YENIDEN değerleri
kapatanlar = ["kapali", "KAPALI", "false", "False", "0", "no", "NO", "off", "Off"]
kapatilan = []
for v in kapatanlar:
    os.environ[bb.ORTAM_FF] = v
    kapatilan.append(bb.ff_yeniden_acik())
kontrol("NIT: kapali/false/0/no/off (büyük-küçük harf duyarsız) kapatır", not any(kapatilan), kapatilan)
os.environ[bb.ORTAM_FF] = "acik"
acik1 = bb.ff_yeniden_acik()
os.environ[bb.ORTAM_FF] = "disabledd"
acik2 = bb.ff_yeniden_acik()
kontrol("NIT: tanınmayan değer açık kalır ama günlüğe uyarı yazılır",
        acik1 and acik2 and "DESKHAND_FF_YENIDEN" in gunluk_metni() and "disabledd" in gunluk_metni())
os.environ.pop(bb.ORTAM_FF, None)

# B3: etkisiz yeniden başlatma → geri çekilme (60 dk, iki katı)
sifirla()
cg_yaz(0.9)
SON["t"] = T - 1000
ETKI["sonra"] = 0.88  # %10'dan az düşüş
s = bakim_at(0)
k = bb._durum_oku(AD)
r = bb.uyari_ekle({})
kontrol("B3: oran %10'dan az düştü → 'etkisiz' uyarısı + 60 dk geri çekilme",
        s and s["is"] == "firefox_yeniden" and k.get("geri_cekilme_sn") == 3600
        and "azaltmadı" in (r.get("memory_warning") or ""), (s, k, r))
YENIDEN.clear()
cg_yaz(0.9)
s = bakim_at(700)
kontrol("B3: geri çekilme süresinde (10 dk geçti, 60 dk dolmadı) yeniden başlatma yok (reclaim yapılır)",
        not YENIDEN and s and s["is"] == "reclaim", s)
cg_yaz(0.9)
s = bakim_at(3700)
k = bb._durum_oku(AD)
kontrol("B3: geri çekilme sonrası yine etkisiz → geri çekilme iki katı (120 dk)",
        YENIDEN == ["/k/a"] and k.get("geri_cekilme_sn") == 7200, (s, k))
bb._ONBELLEK.clear()
kontrol("B3: geri çekilmedeyken uyarı yeniden başlatma vaat etmez",
        "boşta kalınca Firefox" not in (bb.uyari_metni(AD) or ""), bb.uyari_metni(AD))

# B3: 24 saatte en çok 3 yeniden başlatma (bosta_kapat_dk=0 olsa da)
sifirla()
ETKI["sonra"] = 0.5
yapilan = []
for i in range(5):
    cg_yaz(0.9)
    YENIDEN.clear()
    s = bakim_at(i * 700)
    yapilan.append(bool(YENIDEN))
kontrol("B3: 24 saatte en çok 3 yeniden başlatma (sonrakiler yalnız reclaim)", yapilan == [True, True, True, False, False],
        yapilan)
cg_yaz(0.9)
YENIDEN.clear()
bakim_at(86400 + 10)
kontrol("B3: 24 saat dolunca sınır açılır", YENIDEN == ["/k/a"])

# ---------------------------------------------------------------- reclaim
sifirla()
cg_yaz(0.65)
SON["t"] = T - 130
s1 = bakim_at(0)
reclaim_bosalt()
s2 = bakim_at(300)
s3 = bakim_at(601)
kontrol("reclaim 10 dk'da bir (boşta + ≥0,60): 0. sn evet, 300. sn hayır, 601. sn evet",
        s1 and s1["is"] == "reclaim" and s2 is None and s3 and s3["is"] == "reclaim" and reclaim_icerik() == "512M",
        (s1, s2, s3))
sifirla()
os.unlink(os.path.join(CGD, "memory.reclaim"))
os.mkdir(os.path.join(CGD, "memory.reclaim"))  # yazılamaz → reclaim başarısız
cg_yaz(0.65)
s = bakim_at(0)
os.rmdir(os.path.join(CGD, "memory.reclaim"))
cg_yaz(0.65)
kontrol("NIT: başarısız reclaim günlüğe başarısız diye yazılır", s and s["ok"] is False
        and re.search(r"memory\.reclaim .*başarısız", gunluk_metni()), (s, gunluk_metni()[-300:]))
sifirla()
cg_yaz(0.65)
SON["t"] = T - 60
kontrol("boşta değilken (60 sn) reclaim yok", bakim_at(0) is None and reclaim_icerik() == "")
cg_yaz(0.5)
SON["t"] = T - 1000
kontrol("oran 0,5 → reclaim yok", bakim_at(0) is None and reclaim_icerik() == "")
bb._engel = lambda ad, d=None: "devral"
cg_yaz(0.95)
kontrol("Devral / bekleyen onay → bakım yok", bakim_at(0) is None and not YENIDEN and reclaim_icerik() == "")

# B2: görev masaüstünde yeniden başlatma/reclaim yok
bb._engel = GERCEK_ENGEL
sifirla()
cg_yaz(0.95)
SON["t"] = T - 1000
D["gorev"] = {"kimlik": "g1"}
kontrol("B2: görevli masaüstünde (d.gorev) _engel 'gorev', yeniden başlatma ve reclaim yok",
        bb._engel(AD, dict(D)) == "gorev" and bakim_at(0) is None and not YENIDEN and reclaim_icerik() == "")
D.pop("gorev")
kontrol("B2: görev yokken gerçek _engel engellemez", bb._engel(AD, dict(D)) is None)
bb._engel = lambda ad, d=None: None

# B5: durum dosyası temizliği + başka masaüstünün olayı gösterilmez
sifirla()
bb._durum_yaz(AD, {"son_yeniden_olay": {"zaman": time.time(), "once_mb": 9, "sonra_mb": 1, "sekme": 2, "kimlik": "eski"}})
cg_yaz(0.1)
kontrol("B5: önceki masaüstünün (farklı kimlik) yeniden başlatma olayı yeni masaüstünde bildirilmez",
        "yeniden başlatıldı" not in (bb.uyari_metni(AD) or ""), bb.uyari_metni(AD))
bb.durum_temizle(AD)
kontrol("B5: durum_temizle bekçi durum dosyasını siler", not os.path.exists(bb._durum_yolu(AD)))
kaynak_m = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deskhand", "masaustu.py"),
                encoding="utf-8").read()
kontrol("B5: masaustu_durdur bekçi durumunu temizler",
        re.search(r"def masaustu_durdur.*?bellek_bekcisi\.durum_temizle\(ad\).*?\ndef ", kaynak_m, re.S) is not None)

# N2: sayaçlar masaüstü kimliğine bağlı (çökmüş masaüstünden kalan durum dosyası yeni masaüstüne geçmez)
for kim, beklenen, ad_ in (("eski", ["/k/a"], "başka kimliğin (çökmüş masaüstü) sayaçları yok sayılır → yeniden başlatılır"),
                           ("test", [], "aynı kimliğin sayaçları geçerli → yeniden başlatma yok")):
    sifirla()
    cg_yaz(0.9)
    SON["t"] = T - 1000
    bb._durum_yaz(AD, {"kimlik": kim, "acilis": bb._acilis(), "geri_cekilme_sn": 7200.0, "geri_cekilme_bitis": M + 7000,
                       "yeniden_gecmis": [M - 10, M - 20, M - 30], "son_yeniden": M - 10})
    bakim_at(0)
    kontrol(f"N2: {ad_}", beklenen == YENIDEN, (YENIDEN, bb._durum_oku(AD)))
sifirla()
cg_yaz(0.9)
bb._durum_yaz(AD, {"kimlik": "test", "acilis": "baska-acilis", "geri_cekilme_bitis": M + 7000, "son_yeniden": M - 10})
bakim_at(0)
kontrol("N2: önceki açılışın (boot) süre damgaları yok sayılır", YENIDEN == ["/k/a"], YENIDEN)

# N3: geri çekilmeye üst sınır (24 sa); süreler süre saatiyle (duvar saati sıçraması etkilemez)
sifirla()
cg_yaz(0.9)
SON["t"] = T - 1000
ETKI["sonra"] = 0.88
bb._durum_yaz(AD, {"kimlik": "test", "acilis": bb._acilis(), "geri_cekilme_sn": 4 * 86400.0})
bakim_at(0)
k = bb._durum_oku(AD)
kontrol("N3: geri çekilme 24 sa'yı geçmez (önceki 4 gün → 24 sa)", YENIDEN == ["/k/a"]
        and k.get("geri_cekilme_sn") == bb.GERI_CEKILME_AZAMI_SN == 86400.0
        and k.get("geri_cekilme_bitis") == M + 86400.0, k)
sifirla()
cg_yaz(0.9)
bb._durum_yaz(AD, {"kimlik": "test", "acilis": bb._acilis(), "geri_cekilme_sn": 3600.0, "geri_cekilme_bitis": M + 10 * 86400})
bakim_at(0)
kontrol("N3: sınırı aşan (bozuk/ileri) geri çekilme damgası geçersiz sayılır", YENIDEN == ["/k/a"], bb._durum_oku(AD))
sifirla()
cg_yaz(0.9)
ETKI["sonra"] = 0.88
bakim_at(0)  # etkisiz → 60 dk geri çekilme
YENIDEN.clear()
cg_yaz(0.9)
SON["t"] = T + 365 * 86400 - 1000
bakim_at(700, duvar=365 * 86400)  # duvar saati 1 yıl ileri sıçradı, süre saatinde 700 sn geçti
ileri = list(YENIDEN)
cg_yaz(0.9)
SON["t"] = T - 30 * 86400 - 1000
bakim_at(3700, duvar=-30 * 86400)  # duvar saati 30 gün geri; süre saatinde 3700 sn geçti
kontrol("N3: duvar saati ileri sıçraması geri çekilmeyi atlatmaz, geri sıçraması uzatmaz",
        ileri == [] and YENIDEN == ["/k/a"], (ileri, YENIDEN))
ETKI["sonra"] = 0.5

# N5: bosta_neden bekleyen yeniden başlatmayı görür (doğrulama sürerken masaüstü boşta kapatılmaz)
sifirla()
SON["t"] = T - 7200
bos_once = masaustu.bosta_neden(AD, simdi=T)
bb._durum_yaz(AD, {"kimlik": "test", "acilis": bb._acilis(), "bekleyen": {"mono": bb._mono(), "kimlik": "test",
                                                                        "id": "b1", "kopyalar": []}})
bos_bekle = masaustu.bosta_neden(AD, simdi=T)
kontrol("N5: bekleyen yeniden başlatma varken bosta_neden kapatmaz", bos_once is None and bos_bekle == "bellek-yeniden",
        (bos_once, bos_bekle))
sifirla()

# ---------------------------------------------------------------- başlatma kaydı
kopya = tempfile.mkdtemp(prefix="kopya-", dir=_yalitim.GECICI)
os.unlink(os.path.join(CALISMA, bb.KAYIT_DOSYA))
bb.tarayici_kaydet(D, ["kwrite"], {}, kopya, (), os.getpid())
kontrol("kayıt: Firefox olmayan uygulama kaydedilmez", not os.path.exists(os.path.join(CALISMA, bb.KAYIT_DOSYA)))
bb.tarayici_kaydet(D, ["firefox", "--profile", "/baska", "--no-remote"], {}, kopya, (), os.getpid())
kontrol("kayıt: --profile kopyadan farklıysa kaydedilmez", not os.path.exists(os.path.join(CALISMA, bb.KAYIT_DOSYA)))
bb.tarayici_kaydet(D, ["firefox", "--profile", kopya, "--no-remote", "https://example.org"], {"GNOME_ACCESSIBILITY": "1"},
                   kopya, (), os.getpid())
k = bb._kayitlar(CALISMA)
kontrol("kayıt: kopyalı Firefox kaydedilir (adres hariç, 0600)",
        len(k) == 1 and k[0]["argv"] == ["firefox", "--profile", kopya, "--no-remote"] and k[0]["pid"] == os.getpid()
        and oct(os.stat(os.path.join(CALISMA, bb.KAYIT_DOSYA)).st_mode & 0o777) == "0o600", k)
bb.tarayici_kaydet(D, ["firefox", "--profile", kopya], {}, kopya, (), 1)
kontrol("kayıt: aynı kopya yeniden kaydedilince eskisinin yerine geçer", len(bb._kayitlar(CALISMA)) == 1)

# ---------------------------------------------------------------- GERÇEK yeniden başlatma yolu, sahte Firefox (B1, B4, B7)
SAHTE_KOD = ("import os, signal, sys, time\n"
             "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
             "if os.environ.get('SAHTE_MOD') == 'cok':\n    time.sleep(0.4)\n    sys.exit(3)\n"
             "while True:\n    time.sleep(1)\n")
SUREC = []
SAHTE = {"mod": "normal", "baslat": 0}
OTURUM_KOK = os.path.join(_yalitim.GECICI, "bbk", "oturum")
os.makedirs(OTURUM_KOK, exist_ok=True)


def sahte_firefox(kopya_yolu, mod="normal"):
    env = dict(os.environ, SAHTE_MOD=mod)
    p = subprocess.Popen(["firefox", "-c", SAHTE_KOD, "--profile", kopya_yolu, "--no-remote"], executable=sys.executable,
                         env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=p.wait, daemon=True).start()  # toplayıcı (zombi kalmasın)
    SUREC.append(p)
    with open(os.path.join(CGD, "cgroup.procs"), "a") as f:
        f.write(f"{p.pid}\n")
    for _ in range(100):  # exec bitsin (cmdline görünsün)
        if "--profile" in bb._argv(p.pid):
            break
        time.sleep(0.01)
    return p


def sahte_baslat(argv, env=None, kopya=None, ev=(), **k):
    SAHTE["baslat"] += 1
    if SAHTE["mod"] == "dur":
        raise Dur(14, "görev masaüstü: kipsiz istemci (taklit)")
    if SAHTE["mod"] == "sarmal":  # sarmalayıcı yaşıyor ama Firefox hiç açılmıyor
        p = subprocess.Popen(["sleep", "30"], stdin=subprocess.DEVNULL)
        threading.Thread(target=p.wait, daemon=True).start()
        SUREC.append(p)
        return p
    return sahte_firefox(kopya, SAHTE["mod"])


masaustu.baslat = sahte_baslat
bb.firefox_yeniden_baslat = GERCEK_YENIDEN
bb._kayit_canli = GERCEK_CANLI
bb.KAPANIS_PAYI_SN = 0.5
bb.ACILIS_SN = 3.0
bb.DOGRULA_SN = 1.0
bb.KAPANIS_SN = 3.0
_say = [0]


def kurulum(n=1, kurtarma=True, eski_kurtarma=False):
    """n sahte Firefox (her biri kendi kopyasıyla) + kayıtlar. → [(kopya, süreç)]"""
    sifirla()
    with open(os.path.join(CGD, "cgroup.procs"), "w"):
        pass
    cikti, kayitlar = [], []
    for _i in range(n):
        _say[0] += 1
        ky = os.path.join(OTURUM_KOK, f"firefox-20261127-12{_say[0]:04d}-4242-{os.urandom(3).hex()}")
        os.makedirs(ky, mode=0o700)
        p = sahte_firefox(ky)
        time.sleep(0.05)
        if kurtarma:
            rec = os.path.join(ky, "sessionstore-backups", "recovery.jsonlz4")
            _mozlz4_yaz(rec, {"windows": [{"tabs": [{}, {}]}]})
            if eski_kurtarma:
                os.utime(rec, (time.time() - 3600, time.time() - 3600))
        kayitlar.append({"argv": ["firefox", "--profile", ky], "env": {}, "kopya": ky, "ev": [], "pid": p.pid,
                         "bas": ao.surec_baslangic(p.pid)})
        cikti.append((ky, p))
    kayit_yaz(kayitlar)
    cg_yaz(0.9)
    SON["t"] = time.time() - 1000
    return cikti


def _mozlz4_yaz(yol, obj):
    import struct

    import lz4.block
    ham = json.dumps(obj).encode()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "wb") as f:
        f.write(b"mozLz40\0" + struct.pack("<I", len(ham)) + lz4.block.compress(ham, store_size=False))


def bitir():
    t = getattr(bb, "_SON_IS", None)
    if t is not None:
        t.join(15)


def olu(p):
    for _ in range(50):
        if p.poll() is not None:
            return True
        time.sleep(0.05)
    return p.poll() is not None


# B1: kurtarma dosyası yok → öldürme yok
(ky, p0), = kurulum(kurtarma=False)
SAHTE["mod"] = "normal"
s = bb.bakim(AD, simdi=time.time())
bitir()
bb._ONBELLEK.clear()
u = bb.uyari_metni(AD) or ""
kontrol("B1: kurtarma dosyası yok → Firefox ÖLDÜRÜLMEZ, başlatılmaz, uyarı verilir",
        p0.poll() is None and SAHTE["baslat"] == 0 and "yeniden başlatılmadı" in u and "kurtarma" in u, (s, u))
p0.kill()

(ky, p0), = kurulum(eski_kurtarma=True)
s = bb.bakim(AD, simdi=time.time())
bitir()
kontrol("B1: kurtarma dosyası bu Firefox açılmadan önceden kalma (eski) → öldürme yok",
        p0.poll() is None and SAHTE["baslat"] == 0, s)
p0.kill()

# B7 + B4: başarılı yol; doğrulama kilit dışında (bakım hemen döner, araçlar "yeniden başlıyor" görür)
(ky, p0), = kurulum()
SAHTE["baslat"] = 0
t0 = time.monotonic()
s = bb.bakim(AD, simdi=time.time())
sure = time.monotonic() - t0
bb._ONBELLEK.clear()
u_bekle = bb.uyari_metni(AD) or ""
korundu = kopya_bekcisi.korunuyor(ky)
bitir()
bb._ONBELLEK.clear()
u = bb.uyari_metni(AD) or ""
yeni = [q for q in SUREC if q is not p0 and q.poll() is None]
kontrol("B7: gerçek yol: eski Firefox öldü, aynı kopyayla yeni Firefox açıldı, user.js'e geri yükleme eklendi",
        olu(p0) and SAHTE["baslat"] == 1 and len(yeni) == 1 and "--profile" in bb._argv(yeni[0].pid)
        and bb._GERI_YUKLE in open(os.path.join(ky, "user.js"), encoding="utf-8").read(), (s, SAHTE))
kontrol("B4: bakım doğrulamayı beklemeden döner; o sırada uyarı 'yeniden başlıyor' der, kopya korunur",
        sure < bb.ACILIS_SN and "yeniden başlıyor" in u_bekle and korundu, (sure, u_bekle, korundu))
kontrol("B7: doğrulama sonrası başarı bildirilir, koruma işareti kalkar, oturum yedeği alınmış",
        "yeniden başlatıldı" in u and not kopya_bekcisi.korunuyor(ky)
        and os.path.isfile(os.path.join(ky, "sessionstore-backups", bb.YEDEK_AD)), u)
for q in yeni:
    q.kill()

# B1: Dur → uyarı + kopya korunur
(ky, p0), = kurulum()
SAHTE["mod"], SAHTE["baslat"] = "dur", 0
s = bb.bakim(AD, simdi=time.time())
bitir()
bb._ONBELLEK.clear()
u = bb.uyari_metni(AD) or ""
kontrol("B1: yeniden açılış Dur fırlatır → istisna yutulmaz: uyarı + günlük, oturum yedeğinin yolu verilir",
        olu(p0) and "yeniden başlatılamadı" in u and "oturum yedeği" in u and bb.YEDEK_AD in u
        and "Firefox yeniden başlatılamadı" in gunluk_metni(), (s, u))
kontrol("B1: başarısız yeniden başlatmanın kopyası korunur (bekçi/süpürme silmez)",
        kopya_bekcisi.korunuyor(ky) and not kopya_bekcisi.silinebilir_yol(ky, OTURUM_KOK)
        and kopya_bekcisi.bekle_ve_sil(OTURUM_KOK, ky, p0.pid, None, aralik=0.05, azami=2, son_pay=0) is False
        and os.path.isdir(ky))
bb.bakim(AD, simdi=time.time())
kontrol("B1: başarısız deneme de sayılır; 10 dk içinde yeniden denenmez, 24 sa geçmişine girer",
        SAHTE["baslat"] == 1 and len(bb._durum_oku(AD).get("yeniden_gecmis") or []) == 1)

# B1: ok=False (açılmadı) ve açılıştan sonra çökme
for mod, ad_ in (("cok", "açılıştan sonra çökme"), ("sarmal", "açılmadı (ok=False: ana Firefox hiç görünmedi)")):
    (ky, p0), = kurulum()
    SAHTE["mod"], SAHTE["baslat"] = mod, 0
    s = bb.bakim(AD, simdi=time.time())
    bitir()
    bb._ONBELLEK.clear()
    u = bb.uyari_metni(AD) or ""
    kontrol(f"B1: {ad_} → uyarı (yeniden başlatılamadı + yedek), kopya korunur",
            olu(p0) and SAHTE["baslat"] == 1 and "yeniden başlatılamadı" in u and kopya_bekcisi.korunuyor(ky), (s, u))

# B4: 3 kayıt → kilitli kısım KILIT_BEKLE'yi aşmaz
SAHTE["mod"], SAHTE["baslat"] = "normal", 0
uc = kurulum(n=3)
t0 = time.monotonic()
s = bb.bakim(AD, simdi=time.time())
sure = time.monotonic() - t0
bitir()
kaynak_mcp = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deskhand", "mcp_sunucu.py"),
                  encoding="utf-8").read()
kilit_bekle = float(re.search(r"^KILIT_BEKLE = ([\d.]+)", kaynak_mcp, re.M).group(1))
en_kotu = bb.AZAMI_KAYIT * (bb.KAPANIS_AZAMI_SN + bb.ESKI_BEKLE_SN)
kontrol("B4: 3 kayıtta kilitli kısım KILIT_BEKLE'yi aşmaz (ölçülen + en kötü durum sınırı)",
        SAHTE["baslat"] == 3 and sure < 10 and en_kotu < kilit_bekle and all(olu(p_) for _k, p_ in uc),
        (sure, en_kotu, kilit_bekle, SAHTE))
for q in SUREC:
    if q.poll() is None:
        q.kill()


def kayit_kopyalari():
    return [g.get("kopya") for g in bb._kayitlar(CALISMA)]


# N1: ölü kayıtlar bakım yuvalarını yemez: 3 Firefox kapandı, 4. canlı Firefox yeniden başlatılır; ölüler budanır
SAHTE["mod"], SAHTE["baslat"] = "normal", 0
dort = kurulum(n=4)
import shutil  # noqa: E402
for i, (k_, p_) in enumerate(dort[:3]):
    p_.kill()
    olu(p_)
    if i < 2:
        shutil.rmtree(k_)  # kopya silinmiş (kopya-yok); üçüncünün kopyası duruyor ama Firefox'u kapalı
canli_ky, canli_p = dort[3]
bb._ONBELLEK.clear()
u_once = bb.uyari_metni(AD) or ""
s = bb.bakim(AD, simdi=time.time())
bitir()
kontrol("N1: 3 Firefox kapandı, 4. canlı Firefox yeniden başlatılır",
        s and s.get("is") == "firefox_yeniden" and SAHTE["baslat"] == 1 and olu(canli_p)
        and "boşta kalınca Firefox" in u_once, (s, SAHTE, u_once))
kontrol("N1: ölü kayıtlar tarayicilar.json'dan budanır (canlı kayıt kalır)",
        kayit_kopyalari() == [canli_ky], kayit_kopyalari())
for q in SUREC:
    if q.poll() is None:
        q.kill()
time.sleep(0.2)
bb._durum_yaz(AD, {})  # 10 dk / 24 sa sayaçları sıfır: yalnız kayıtların canlılığı belirlesin
bb._ONBELLEK.clear()
cg_yaz(0.9)
u_olu = bb.uyari_metni(AD) or ""
kontrol("N1: yalnız ölü kayıt varken uyarı 'yeniden başlatılır' demez",
        "boşta kalınca Firefox" not in u_olu and "gereksiz sekme" in u_olu, u_olu)

# N6: kurtarma dosyası eski (boşta Firefox) → günlük 10 dk'da bir değil, yalnız durum değişince
(ky, p0), = kurulum(kurtarma=False)
SAHTE["baslat"] = 0
say0 = gunluk_metni().count("yeniden başlatılmadı")
bb.bakim(AD, simdi=time.time())
say1 = gunluk_metni().count("yeniden başlatılmadı")
bb.bakim(AD, simdi=time.time(), mono=bb._mono() + 700)
bb.bakim(AD, simdi=time.time(), mono=bb._mono() + 1400)
say2 = gunluk_metni().count("yeniden başlatılmadı")
bb._ONBELLEK.clear()
kontrol("N6: aynı 'kurtarma yok' durumu günlüğe bir kez yazılır (uyarı sürer)",
        say1 == say0 + 1 and say2 == say1 and "yeniden başlatılmadı" in (bb.uyari_metni(AD) or ""), (say0, say1, say2))
p0.kill()

# N4: bayat-bekleyen dalı canlı doğrulama iş parçacığını bekler; doğrulama tek kez sonuçlanır
(ky, p0), = kurulum()
SAHTE["mod"], SAHTE["baslat"] = "normal", 0
bb.DOGRULA_SN = 2.0
say0 = gunluk_metni().count("Firefox yeniden başlatıldı")
bb.bakim(AD, simdi=time.time())
gercek_mono = bb._mono
bb._mono = lambda: gercek_mono() + 400  # uyku / saat sıçraması: bekleyen 180 sn'den eski görünür
s_bayat = bb.bakim(AD, simdi=time.time())
bb._mono = gercek_mono
bitir()
say1 = gunluk_metni().count("Firefox yeniden başlatıldı")
kontrol("N4: iş parçacığı canlıyken bayat-bekleyen dalı sonuçlandırmaz; sonuç tek kez yazılır",
        s_bayat is None and say1 == say0 + 1 and "bekleyen" not in bb._durum_oku(AD), (s_bayat, say0, say1))
bb.DOGRULA_SN = 1.0
k_ = bb._durum_oku(AD)
k_["bekleyen"] = {"mono": bb._mono() - 1000, "kimlik": "test", "id": "x1", "once_current": 1, "once_kullanim": 1,
                  "kopyalar": [{"kopya": ky, "pid": 1, "sekme": 1, "olduruldu": True}]}
bb._durum_yaz(AD, k_)
say0 = gunluk_metni().count("Firefox yeniden başlatıldı")
bb.bakim(AD, simdi=time.time())  # iş parçacığı yok (süreç ölmüş gibi): bayat dal sonuçlandırır
ikinci = bb._sonuclandir(AD, dict(D), {"current": 1, "kullanim": 1}, [({"pid": 1}, {"ok": True, "kopya": ky})],
                         bb._mono(), bekleyen_id="x1")
kontrol("N4: aynı bekleyen ikinci kez sonuçlandırılmaz (bayat dal + geç gelen iş parçacığı)",
        ikinci is None and gunluk_metni().count("Firefox yeniden başlatıldı") == say0 + 1,
        (ikinci, gunluk_metni().count("Firefox yeniden başlatıldı") - say0))
for q in SUREC:
    if q.poll() is None:
        q.kill()

# N5: doğrulama bitmeden masaüstü kapandı → sahte "yeniden başlatılamadı" yok; başarılı açılışın işareti kalkar
(ky, p0), = kurulum()
SAHTE["mod"], SAHTE["baslat"] = "normal", 0
bb.DOGRULA_SN = 3.0
bb.bakim(AD, simdi=time.time())
bb._bekle(lambda: kopya_bekcisi.koru_durum(ky) == "acildi", 3.0)
acildi = kopya_bekcisi.koru_durum(ky)
GERCEK_DURUM = masaustu.durum
masaustu.durum = lambda *a, **k: None  # masaüstü kapandı (durum kaydı yok)
for q in SUREC:  # kapanış uygulamaları öldürür
    if q.poll() is None:
        q.kill()
bitir()
masaustu.durum = GERCEK_DURUM
bb._ONBELLEK.clear()
h = bb._durum_oku(AD).get("son_hata_olay")
kontrol("N5: açıldıktan sonra masaüstü kapandı → hata kaydı/uyarısı yok; işaret 'acildi' (kapanış olağan siler)",
        acildi == "acildi" and h is None and "yeniden başlatılamadı" not in (bb.uyari_metni(AD) or ""), (acildi, h))
(ky, p0), = kurulum()
bb._sonuclandir(AD, dict(D), {"current": 1, "kullanim": 1}, [({"pid": 1}, {"ok": True, "kopya": ky})], bb._mono())
kopya_bekcisi.koru_isaretle(ky, "bellek-yeniden")
masaustu.durum = lambda *a, **k: None
bb._sonuclandir(AD, dict(D), {"current": 1, "kullanim": 1}, [({"pid": 1}, {"ok": True, "kopya": ky})], bb._mono())
masaustu.durum = GERCEK_DURUM
kontrol("N5: başarılı yeniden başlatmanın koruma işareti masaüstü kapanmış olsa da kalkar",
        not kopya_bekcisi.korunuyor(ky))
bb.DOGRULA_SN = 1.0
for q in SUREC:
    if q.poll() is None:
        q.kill()

# D1: geri çekilme üst sınırı kayan nokta hatasıyla yok sayılmaz
import random  # noqa: E402
_s = 4187507.9414002034
kontrol("D1: simdi=4187507.94… + 86400 → geri çekilme uygulanır",
        bb._uzun_engel({"geri_cekilme_bitis": _s + 86400.0}, _s) == "geri-cekilme")
_rng = random.Random(1127)
_kacan = []
for _i in range(20000):
    _s = _rng.uniform(0, 1e9)
    _gc = _rng.choice([bb.GERI_CEKILME_AZAMI_SN, _rng.uniform(1, bb.GERI_CEKILME_AZAMI_SN)])
    if bb._uzun_engel({"geri_cekilme_bitis": _s + _gc}, _s) != "geri-cekilme":
        _kacan.append((_s, _gc))
kontrol("D1: rastgele simdi/süre (≤ üst sınır) → geri çekilme her zaman uygulanır", not _kacan, _kacan[:3])
kontrol("D1: üst sınırı çok aşan bitiş hâlâ bozuk sayılır",
        bb._uzun_engel({"geri_cekilme_bitis": 1000.0 + 2 * bb.GERI_CEKILME_AZAMI_SN}, 1000.0) is None)

# D2: kapanış payı gerçekten beklenir (durum None ile atlatılmadan)
GERCEK_DOGRULA = bb.dogrula
bb.dogrula = lambda *a, **k: (False, "acilmadi")
_cagri = [0]


def _kapanan_durum(*a, **k):
    _cagri[0] += 1
    return dict(D) if _cagri[0] <= 2 else None  # pay içinde (3. yoklamada) masaüstü kapanıyor


sifirla()
bb._durum_yaz(AD, {"kimlik": "test", "acilis": bb._acilis(), "bekleyen": {"id": "d2"}})
masaustu.durum = _kapanan_durum
bb._dogrula_is(AD, dict(D), {"current": 1, "kullanim": 1}, [({"pid": 1}, {"kopya": "/yok/k", "popen": None})], [],
               bb._mono(), "d2")
masaustu.durum = GERCEK_DURUM
bb._ONBELLEK.clear()
kontrol("D2: pay içinde masaüstü kapandı → sahte hata kaydı yok", bb._durum_oku(AD).get("son_hata_olay") is None,
        (_cagri, bb._durum_oku(AD)))
sifirla()
bb._durum_yaz(AD, {"kimlik": "test", "acilis": bb._acilis(), "bekleyen": {"id": "d2"}})
t0 = time.monotonic()
bb._dogrula_is(AD, dict(D), {"current": 1, "kullanim": 1}, [({"pid": 1}, {"kopya": "/yok/k", "popen": None})], [],
               bb._mono(), "d2")
sure = time.monotonic() - t0
bb._ONBELLEK.clear()
h = bb._durum_oku(AD).get("son_hata_olay")
kontrol("D2: masaüstü yaşıyor → pay dolunca hata yazılır", sure >= bb.KAPANIS_PAYI_SN and h and h.get("neden") == "acilmadi",
        (sure, h))
bb.dogrula = GERCEK_DOGRULA
kontrol("D3: KAPANIS_PAYI_SN varsayılanı 20 sn", "KAPANIS_PAYI_SN = 20.0" in
        open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deskhand", "bellek_bekcisi.py"),
             encoding="utf-8").read())

# ---------------------------------------------------------------- ABM-KARAR değerleri
kontrol("ABM-KARAR (a): varsayılan MemoryMax 8G, DESKHAND_SANAL_BELLEK ezer", ao.VARSAYILAN_BELLEK == "8G" and (
    os.environ.__setitem__("DESKHAND_SANAL_BELLEK", "3G") or ao._bellek_siniri() == "3G"))
os.environ.pop("DESKHAND_SANAL_BELLEK", None)
kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
kaynak = "".join(open(os.path.join(kok, "deskhand", a), encoding="utf-8").read()
                 for a in ("kwin_oturum.py", "masaustu.py", "arka_ortak.py"))
kontrol("ABM-KARAR (d): memory.high/MemoryHigh kafese konmaz", "MemoryHigh" not in kaynak and "memory.high" not in kaynak)
P = {"dom.ipc.processCount.webIsolated": "1", "dom.ipc.processCount": "2", "dom.ipc.processPrelaunch.fission.number": "0"}
prefs = dict(re.findall(r'user_pref\("([^"]+)",\s*([^)]+)\);', firefox._USER_JS))
P_ALINDI = all(prefs.get(k) == v for k, v in P.items())
P_HIC = not any(k in prefs for k in P)
kontrol("ABM-KARAR (c): user.js tercih paketi P ya hep ya hiç; max_total_viewers yok, Fission kapatılmaz",
        (P_ALINDI or P_HIC) and "browser.sessionhistory.max_total_viewers" not in prefs and "fission.autostart" not in prefs,
        prefs)
kontrol("ABM-KARAR (b alınmadı): ev tmpfs kalır (ev_boyut 8G kafeste 2 GiB)", ao.ev_boyut("8G") == 2 << 30)

print(f"\n{gecen}/{toplam} bellek bekçisi testi geçti")
sys.exit(0 if gecen == toplam else 1)
