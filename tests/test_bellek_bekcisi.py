"""Bellek bekçisi (deskhand/bellek_bekcisi.py, ABM-F1) birim testleri: sahte cgroup dizini, sahte masaüstü kaydı; süreç
başlatılmaz. Gerçek KWin'de Firefox yeniden başlatma / reclaim kanıtı: ABM-F1 raporundaki deney.

Çalıştır:  python3 tests/test_bellek_bekcisi.py"""
import json
import os
import re
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import arka_ortak as ao, bellek_bekcisi as bb, masalar, masaustu
from deskhand.oturum import firefox

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


def cg_yaz(oran, azami=MAX):
    with open(os.path.join(CGD, "memory.current"), "w") as f:
        f.write(str(int(azami * oran)))
    with open(os.path.join(CGD, "memory.max"), "w") as f:
        f.write(str(azami) if azami else "max")
    with open(os.path.join(CGD, "memory.stat"), "w") as f:
        f.write("anon 100\nfile 200\nshmem 12345\n")
    with open(os.path.join(CGD, "memory.reclaim"), "w"):
        pass


def reclaim_icerik():
    with open(os.path.join(CGD, "memory.reclaim")) as f:
        return f.read()


AD = masalar.secili()
os.makedirs(masalar.kok(AD), exist_ok=True)
CALISMA = tempfile.mkdtemp(prefix="bb-calisma-", dir=_yalitim.GECICI)
D = {"cgroup": CG, "calisma": CALISMA, "kimlik": "test"}
SON = {"t": None}
DURDURULDU = []
YENIDEN = []
masaustu.durum = lambda *a, **k: dict(D)
masaustu.son_kullanim = lambda ad=None: SON["t"]
masaustu.masaustu_durdur = lambda *a, **k: (DURDURULDU.append(a), (True, []))[1]
masaustu.devral_var = lambda *a, **k: False
bb.firefox_yeniden_baslat = lambda d, g: (YENIDEN.append(g["kopya"]), {"ok": True, "pid": 1, "sekme": 3})[1]
bb._engel = lambda ad: None
T = time.time()


def sifirla():
    for yol in (bb._durum_yolu(AD),):
        if os.path.exists(yol):
            os.unlink(yol)
    DURDURULDU.clear()
    YENIDEN.clear()
    bb._ONBELLEK.clear()


# ---------------------------------------------------------------- durum + uyarı
cg_yaz(0.5)
du = bb.bellek_durumu(CG)
kontrol("bellek_durumu: current/max/oran/shmem", du == {"current": int(MAX * 0.5), "max": MAX, "oran": 0.5, "shmem": 12345}, du)
kontrol("oran 0,5 → uyarı yok", bb.bellek_uyarisi(du) is None and "memory_warning" not in bb.uyari_ekle({"status": "ok"}))
cg_yaz(0.5, azami=0)
kontrol("sınırsız kafes → oran 0, uyarı yok", bb.bellek_durumu(CG)["oran"] == 0.0 and bb.bellek_uyarisi(bb.bellek_durumu(CG)) is None)
kontrol("geçersiz kafes yolu (..) → None", bb.bellek_durumu("/user.slice/../../etc") is None and bb.bellek_durumu("") is None)

sifirla()
cg_yaz(0.85)
SON["t"] = T  # şimdi kullanılıyor (boşta değil)
r = bb.uyari_ekle({"status": "ok"})
kontrol("oran 0,85 → memory_warning dolu", "85" in (r.get("memory_warning") or "") and "Firefox" in r["memory_warning"],
        r)
kontrol("oran 0,85 → masaüstü açık kalır (görev ortasında bakım yok, kapatma yok)",
        bb.bakim(AD, simdi=T + 5) is None and not DURDURULDU and not YENIDEN and reclaim_icerik() == "")
kontrol("uyarı yalnız sözlüğe eklenir; hata sonucu (CallToolResult vb.) dokunulmaz",
        bb.uyari_ekle("metin") == "metin" and bb.uyari_ekle({"memory_warning": "x"}) == {"memory_warning": "x"})

# ---------------------------------------------------------------- Firefox yeniden başlatma
kayit = [{"argv": ["firefox", "--profile", "/k/a", "--no-remote"], "env": {}, "kopya": "/k/a", "ev": [], "pid": 5}]
with open(os.path.join(CALISMA, bb.KAYIT_DOSYA), "w") as f:
    json.dump(kayit, f)
sifirla()
cg_yaz(0.86)
SON["t"] = T - 200
os.environ.pop(bb.ORTAM_FF, None)
s = bb.bakim(AD, simdi=T)
kontrol("boşta + ≥0,85 → yalnız Firefox yeniden başlar, masaüstü açık kalır",
        s and s["is"] == "firefox_yeniden" and YENIDEN == ["/k/a"] and not DURDURULDU and reclaim_icerik() == "", s)
r = bb.uyari_ekle({})
kontrol("yeniden başlatma memory_warning'de bildirilir (sekme sayısı, yeniden gözlem)",
        "yeniden başlatıldı" in (r.get("memory_warning") or "") and "3 sekme" in r["memory_warning"], r)
YENIDEN.clear()
s2 = bb.bakim(AD, simdi=T + 120)
kontrol("Firefox yeniden başlatma 10 dk içinde ikinci kez yapılmaz (yerine reclaim)",
        not YENIDEN and s2 and s2["is"] == "reclaim", s2)

sifirla()
cg_yaz(0.9)
os.environ[bb.ORTAM_FF] = "kapali"
s = bb.bakim(AD, simdi=T)
kontrol("DESKHAND_FF_YENIDEN=kapali → yeniden başlatma yok (reclaim yapılır)",
        not YENIDEN and s and s["is"] == "reclaim" and reclaim_icerik() == bb.RECLAIM_MIKTAR, s)
kontrol("DESKHAND_FF_YENIDEN=kapali → uyarı yeniden başlatma vaat etmez",
        "Firefox" not in (bb.uyari_ekle({}).get("memory_warning") or "Firefox"))
os.environ.pop(bb.ORTAM_FF, None)

# ---------------------------------------------------------------- reclaim
sifirla()
cg_yaz(0.65)
SON["t"] = T - 130
s1 = bb.bakim(AD, simdi=T)
with open(os.path.join(CGD, "memory.reclaim"), "w"):
    pass
s2 = bb.bakim(AD, simdi=T + 300)
s3 = bb.bakim(AD, simdi=T + 601)
kontrol("reclaim 10 dk'da bir (boşta + ≥0,60): 0. sn evet, 300. sn hayır, 601. sn evet",
        s1 and s1["is"] == "reclaim" and s2 is None and s3 and s3["is"] == "reclaim" and reclaim_icerik() == "512M",
        (s1, s2, s3))
sifirla()
cg_yaz(0.65)
SON["t"] = T - 60
kontrol("boşta değilken (60 sn) reclaim yok", bb.bakim(AD, simdi=T) is None and reclaim_icerik() == "")
cg_yaz(0.5)
SON["t"] = T - 1000
kontrol("oran 0,5 → reclaim yok", bb.bakim(AD, simdi=T) is None and reclaim_icerik() == "")
bb._engel = lambda ad: "devral"
cg_yaz(0.95)
kontrol("Devral / bekleyen onay → bakım yok", bb.bakim(AD, simdi=T) is None and not YENIDEN and reclaim_icerik() == "")

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
