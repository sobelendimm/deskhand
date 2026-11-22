"""Çoklu görünmez masaüstü birim testleri (deskhand/masalar.py + masaüstü başına yollar): süreç/ekran başlatmaz.

1) varsayılan yollar eskisiyle bayt bayt aynı  2) ad doğrulama + bağlam  3) sahiplik (canlı/ölü/PID yeniden kullanımı/
bozuk dosya) + kapı (aynı oturum kuralı)  4) otomatik ad  5) oturum.kapanis(ad) başkasının kopyasına dokunmuyor
6) arka_uc.sec() önbellek anahtarı (masa, tür)  7) onay isteğinde `masa` + bekleyen_var  8) dinleme.oturum_kaydi başka
masaüstünün kaydını almıyor  9) denetim: masaustu.py/masalar.py dışında "sanal.json"/"sanal.lock"/"devral" sabiti yok
10) sınır ayarı + CLI --desktop-name.

Çalıştır:  python3 tests/test_masalar.py"""
import ast
import json
import os
import subprocess
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import masalar, masaustu, onay, yollar
from deskhand.hata import Dur

KOK = _yalitim.KOK
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


RT = yollar.runtime_dir()

# ---------------------------------------------------------------- 1) varsayılan yollar
print("1) varsayılan yollar (geriye uyum)")
os.environ.pop(masalar.ORTAM, None)
kontrol("durum_yolu() = RUNTIME_DIR/sanal.json", masaustu.durum_yolu() == os.path.join(RT, "sanal.json"))
kontrol("devral_yolu() = RUNTIME_DIR/devral", masaustu.devral_yolu() == os.path.join(RT, "devral"))
kontrol("kilit = RUNTIME_DIR/sanal.lock", masalar.kilit_yolu() == os.path.join(RT, "sanal.lock"))
from deskhand.arka_uc import sanal as sanal_au  # noqa: E402
kontrol("girdi kilidi = RUNTIME_DIR/sanal-girdi.lock", sanal_au._girdi_kilidi_yolu() == os.path.join(RT, "sanal-girdi.lock"))
from deskhand.oturum import politika  # noqa: E402
kontrol("kopya_dizini() = RUNTIME_DIR/oturum", politika.kopya_dizini() == os.path.join(RT, "oturum"))
kontrol("flatpak_kayit() = RUNTIME_DIR/oturum/flatpak.json",
        politika.flatpak_kayit() == os.path.join(RT, "oturum", "flatpak.json"))
kontrol("varsayılan sahip = RUNTIME_DIR/sanal-sahip", masalar.sahip_yolu("") == os.path.join(RT, "sanal-sahip"))
with masalar.masa_sabit("b"):
    kontrol("adlı: durum_yolu = masa/b/sanal.json", masaustu.durum_yolu() == os.path.join(RT, "masa", "b", "sanal.json"))
    kontrol("adlı: girdi kilidi = masa/b/girdi.lock", sanal_au._girdi_kilidi_yolu() == os.path.join(RT, "masa", "b", "girdi.lock"))
    kontrol("adlı: kopya_dizini = masa/b/oturum", politika.kopya_dizini() == os.path.join(RT, "masa", "b", "oturum"))
    kontrol("adlı: devral = masa/b/devral", masaustu.devral_yolu() == os.path.join(RT, "masa", "b", "devral"))
    kontrol("adlı: sahip = masa/b/sahip", masalar.sahip_yolu() == os.path.join(RT, "masa", "b", "sahip"))

# ---------------------------------------------------------------- 2) ad doğrulama + bağlam
print("\n2) ad doğrulama + bağlam")
for iyi in ("", "a", "b", "oturum-1", "x9", "a" * 16):
    kontrol(f"geçerli ad {iyi!r}", masalar.dogrula(iyi) == iyi)
for kotu in ("-a", "A", "a" * 17, "a/b", "..", "a b", "ş", "a.b", "gorev"):
    kontrol(f"geçersiz ad {kotu!r} → Dur 1", dur_kodu(masalar.dogrula, kotu) == 1)
kontrol("gorev ayrılmış ama ayrilmis_serbest ile geçer", masalar.dogrula("gorev", ayrilmis_serbest=True) == "gorev")
kontrol("bağlam yok → ''", masalar.secili() == "")
os.environ[masalar.ORTAM] = "c"
kontrol("ortam DESKHAND_MASAUSTU=c → c", masalar.secili() == "c")
with masalar.masa_sabit("d"):
    kontrol("masa_sabit ortamdan üstün", masalar.secili() == "d")
    diger = []
    t = threading.Thread(target=lambda: diger.append(masalar.secili()))
    t.start(); t.join()
    kontrol("masa_sabit iş parçacığı yereli (başka iş parçacığı ortamı görür)", diger == ["c"])
kontrol("masa_sabit çıkınca ortam", masalar.secili() == "c")
os.environ[masalar.ORTAM] = "../x"
kontrol("bozuk ortam değeri → '' (yola girmez)", masalar.secili() == "")
os.environ.pop(masalar.ORTAM, None)

# ---------------------------------------------------------------- 3) sahiplik + kapı
print("\n3) sahiplik + kapı")
kontrol("sahipsiz → izinli", masalar.izinli_mi("s1"))
kontrol("sahiplen (bu süreç)", masalar.sahiplen("s1"))
s = masalar.sahip_oku("s1")
kontrol("sahip_oku canlı → bu süreç", s is not None and s["pid"] == os.getpid() and s["ebeveyn"] == os.getppid())
kontrol("sahip kendisi → izinli", masalar.izinli_mi("s1"))
kontrol("kapı: sahip kendisi → geçer", dur_kodu(masalar.erisim_kapisi, "s1") is None)
# başka oturum: sahibi ayrı bir süreç (ebeveyni bu süreç DEĞİL, zincirimizde değil)
yabanci = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
try:
    bas = masalar._baslangic(yabanci.pid)
    # ebeveyn alanına zincirimizde OLMAYAN bir süreç (yabancının kendisi) yazılır: başka Claude oturumu benzetimi
    os.makedirs(masalar.kok("s2"), exist_ok=True)
    with open(masalar.sahip_yolu("s2"), "w") as f:
        f.write(f"mcp {yabanci.pid} {bas} {yabanci.pid} {bas} 0\n")
    kontrol("başka oturumun sahibi → sahip_oku canlı", (masalar.sahip_oku("s2") or {}).get("pid") == yabanci.pid)
    kontrol("başka oturum → izinli değil", not masalar.izinli_mi("s2"))
    kontrol("kapı: başka oturum → Dur 14", dur_kodu(masalar.erisim_kapisi, "s2") == 14)
    kontrol("başkasının sahipliği alınamaz", not masalar.sahiplen("s2"))
    kontrol("başkasının sahipliği bırakılamaz", not masalar.birak("s2") and os.path.exists(masalar.sahip_yolu("s2")))
    from deskhand import gorev_kipi
    gorev_kipi.GOZLEMCI = True
    kontrol("kapı: panel (GOZLEMCI) → geçer", dur_kodu(masalar.erisim_kapisi, "s2") is None)
    gorev_kipi.GOZLEMCI = False
    with masalar.masa_sabit("s2"):
        kontrol("gorev_kipi.masaustu_kapisi da sahiplik kapısından geçer → Dur 14",
                dur_kodu(gorev_kipi.masaustu_kapisi, {"tur": "kwin"}) == 14)
        kontrol("masaustu_durdur başkasınınkini → Dur 14", dur_kodu(masaustu.masaustu_durdur) == 14)
    # aynı Claude oturumu: sahibin EBEVEYNİ bizim atamız (sahip = yabancı süreç, ebeveyn alanı = bu sürecin ebeveyni)
    eb = os.getppid()
    masalar.kok_hazirla("s3")
    with open(masalar.sahip_yolu("s3"), "w") as f:
        f.write(f"mcp {yabanci.pid} {bas} {eb} {masalar._baslangic(eb)} 0\n")
    kontrol("aynı oturum (sahibin ebeveyni ata zincirimizde) → izinli", masalar.izinli_mi("s3"))
    with open(masalar.sahip_yolu("s3"), "w") as f:  # ebeveyn başlangıcı tutmuyor (PID yeniden kullanımı)
        f.write(f"mcp {yabanci.pid} {bas} {eb} 1 0\n")
    kontrol("ebeveyn PID yeniden kullanılmış (başlangıç farklı) → izinli değil", not masalar.izinli_mi("s3"))
finally:
    yabanci.kill()
    yabanci.wait()
kontrol("sahip ölünce → sahip_oku None", masalar.sahip_oku("s2") is None)
kontrol("sahip ölünce → serbest (izinli)", masalar.izinli_mi("s2") and dur_kodu(masalar.erisim_kapisi, "s2") is None)
kontrol("ölü sahibin yerine sahiplenilir", masalar.sahiplen("s2"))
# PID yeniden kullanımı: canlı PID ama başlangıç zamanı farklı
masalar.kok_hazirla("s4")
with open(masalar.sahip_yolu("s4"), "w") as f:
    f.write(f"mcp {os.getppid()} 1 1 - 0\n")
kontrol("PID yeniden kullanımı (başlangıç tutmuyor) → sahipsiz", masalar.sahip_oku("s4") is None)
for bozuk in ("", "mcp", "mcp x y z w 0", "panel 1 2 3 4 0", "mcp 1 - 1 - 0", "\x00\x01"):
    with open(masalar.sahip_yolu("s4"), "w") as f:
        f.write(bozuk)
    kontrol(f"bozuk sahip dosyası {bozuk!r} → sahipsiz", masalar.sahip_oku("s4") is None and masalar.izinli_mi("s4"))
kontrol("bırak (kendi)", masalar.birak("s1") and not os.path.exists(masalar.sahip_yolu("s1")))
masalar.sahiplen("s5", oto=True)
kontrol("oto bayrağı", masalar.oto_mu("s5") and not masalar.oto_mu("s2"))

# ---------------------------------------------------------------- 4) otomatik ad
print("\n4) otomatik ad")
kontrol("boş → oturum-1", masalar.oto_ad(set()) == "oturum-1")
kontrol("oturum-1 dolu → oturum-2", masalar.oto_ad({"", "oturum-1"}) == "oturum-2")
kontrol("en küçük boş", masalar.oto_ad({"oturum-1", "oturum-3"}) == "oturum-2")
kontrol("adlar(): sahibi olanlar listelenir", {"s2", "s5"} <= set(masalar.adlar()))

# ---------------------------------------------------------------- 5) kapanis(ad)
print("\n5) oturum.kapanis(ad): başka masaüstünün kopyaları ve Flatpak kaydı korunur")
from deskhand import oturum  # noqa: E402
ka = politika.kopya_dizini("ka")
kb = politika.kopya_dizini("kb")
for k in (ka, kb):
    os.makedirs(os.path.join(k, "firefox-1"), mode=0o700)
with open(politika.flatpak_kayit("kb"), "w") as f:
    json.dump([], f)
kontrol("kopya kökleri ayrı", ka != kb and not ka.startswith(kb) and not kb.startswith(ka))
oturum.kapanis("ka")
kontrol("kapanis('ka') kendi kopyasını sildi", not os.path.exists(os.path.join(ka, "firefox-1")))
kontrol("kapanis('ka') B'nin kopyasına dokunmadı", os.path.isdir(os.path.join(kb, "firefox-1")))
kontrol("kapanis('ka') B'nin flatpak.json'una dokunmadı", os.path.isfile(politika.flatpak_kayit("kb")))
with masalar.masa_sabit("kb"):
    kontrol("kapanis(ad) bağlamı geri bırakır", masalar.secili() == "kb")
    oturum.kapanis("ka")
    kontrol("bağlam kb iken kapanis('ka') yine B'ye dokunmaz", os.path.isdir(os.path.join(kb, "firefox-1")))
os.makedirs(os.path.join(politika.kopya_dizini(""), "firefox-9"), mode=0o700)
oturum.kapanis("kb")
kontrol("kapanis('kb') varsayılanın kopyasına dokunmadı", os.path.isdir(os.path.join(politika.kopya_dizini(""), "firefox-9")))

# ---------------------------------------------------------------- 6) sec() anahtarı
print("\n6) arka_uc.sec() önbelleği (masa, tür)")
from deskhand import arka_uc  # noqa: E402
os.environ["DESKHAND_HEDEF"] = "arka"
a0 = arka_uc.sec()
with masalar.masa_sabit("sa"):
    a1 = arka_uc.sec()
    a1b = arka_uc.sec()
with masalar.masa_sabit("sb"):
    a2 = arka_uc.sec()
kontrol("varsayılan + iki adlı masaüstü: üç ayrı örnek", len({id(a0), id(a1), id(a2)}) == 3)
kontrol("aynı masaüstü → aynı örnek", a1 is a1b)
kontrol("anahtarlar (masa, tür)", ("sa", "xvfb") in arka_uc._TUR_ORNEKLERI and ("", "xvfb") in arka_uc._TUR_ORNEKLERI)
kontrol("varsayılan _ORNEKLER['sanal'] adlı masaüstünden etkilenmedi", arka_uc.sec() is a0)
os.environ.pop("DESKHAND_HEDEF", None)

# ---------------------------------------------------------------- 7) onay masa
print("\n7) onay isteğinde masa + bekleyen_var")
os.makedirs(onay.dizin(), mode=0o700, exist_ok=True)
pid_yabanci = os.getppid()
for i, (masaustu_, masa_) in enumerate((("arka", "oa"), ("arka", ""), ("ekran", ""))):
    istek = {"id": f"{i:032x}", "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": masaustu_, "zaman": time.time(),
             "son_zaman": time.time() + 30, "pid": pid_yabanci, "goruntu": None, "masa": masa_}
    with open(onay.istek_yolu(istek["id"]), "w") as f:
        json.dump(istek, f)
kontrol("A'daki (oa) bekleyen onay A'yı kilitler", onay.bekleyen_var("arka", masa="oa"))
kontrol("A'daki bekleyen onay B'yi (ob) kilitlemez", not onay.bekleyen_var("arka", masa="ob"))
with masalar.masa_sabit("ob"):
    kontrol("masa None → bağlam (ob): kilit yok", not onay.bekleyen_var("sanal"))
kontrol("varsayılan masaüstünün bekleyeni (masa '')", onay.bekleyen_var("arka", masa=""))
kontrol("ekran masaüstü masa'dan bağımsız", onay.bekleyen_var("ekran", masa="zz"))
with open(onay.istek_yolu(f"{9:032x}"), "w") as f:
    json.dump({"id": f"{9:032x}", "eylem": "e", "hedef": "h", "masaustu": "arka", "zaman": time.time(),
               "son_zaman": time.time() + 30, "pid": pid_yabanci, "masa": "../kotu"}, f)
kontrol("bozuk masa alanı → '' sayılır", any(d["id"] == f"{9:032x}" and d["masa"] == "" for d in onay.bekleyenler()))
for d in onay.bekleyenler():
    os.remove(onay.istek_yolu(d["id"]))
from deskhand import mcp_sunucu  # noqa: E402
with masalar.masa_sabit("ma"):
    with mcp_sunucu._OnayKaydi("sanal"):
        kontrol("MCP _BEKLEYEN anahtarı (sanal, ma)", ("sanal", "ma") in mcp_sunucu._BEKLEYEN)
        kontrol("MCP: ma'da bekleyen var", mcp_sunucu.onay_bekliyor_mu("sanal"))
        with masalar.masa_sabit("mb"):
            kontrol("MCP: mb kilitlenmez", not mcp_sunucu.onay_bekliyor_mu("sanal"))
kontrol("MCP _BEKLEYEN boşaldı", not mcp_sunucu._BEKLEYEN)

# ---------------------------------------------------------------- 8) dinleme kaydı
print("\n8) dinleme.oturum_kaydi: başka masaüstünün kaydı alınmaz")
from deskhand import dinleme  # noqa: E402
for ad_, cd in (("da", "/yok/da"), ("db", "/yok/db")):
    masalar.kok_hazirla(ad_)
    with open(masaustu.durum_yolu(ad_), "w") as f:
        json.dump({"tur": "xvfb", "no": 90, "calisma": cd}, f)
with masalar.masa_sabit("da"):
    kontrol("A'ya bağlı süreç B'nin kaydını okumaz (ad=None → A)", masaustu.durum_oku()["calisma"] == "/yok/da")
    kontrol("A'ya bağlı süreç B'nin dizinini dinleyemez → Dur 14", dur_kodu(dinleme.oturum_kaydi, "/yok/db") == 14)
masalar.kok_sil("da")
masalar.kok_sil("db")

# ---------------------------------------------------------------- 9) denetim: sabit yol yok
print("\n9) denetim: masaustu.py/masalar.py dışında tekil yol sabiti yok")
YASAK = {"sanal.json", "sanal.lock", "devral", "sanal-girdi.lock", "sanal-sahip"}
ihlal = []
for kok_, _d, dosyalar in os.walk(os.path.join(KOK, "deskhand")):
    for ad_ in dosyalar:
        if not ad_.endswith(".py"):
            continue
        yol = os.path.join(kok_, ad_)
        if os.path.relpath(yol, KOK) in ("deskhand/masaustu.py", "deskhand/masalar.py"):
            continue
        with open(yol, encoding="utf-8") as f:
            agac = ast.parse(f.read())
        for n in ast.walk(agac):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in YASAK:
                ihlal.append(f"{os.path.relpath(yol, KOK)}:{n.lineno} {n.value!r}")
kontrol("yasak sabit yok", not ihlal, "; ".join(ihlal))

# ---------------------------------------------------------------- 10) sınır + CLI
print("\n10) sınır ayarı + CLI")
from deskhand import ayarlar  # noqa: E402
kontrol("azami varsayılan 3", masalar.azami() == 3)
ayarlar.ayarla("masaustu", "azami", 5)
kontrol("azami ayardan 5", masalar.azami() == 5)
try:
    ayarlar.dogrula("masaustu", "azami", 9)
    kontrol("azami 9 → ValueError", False)
except ValueError:
    kontrol("azami 9 → ValueError", True)
ayarlar.ayarla("masaustu", "azami", 3)
# sınır aşılınca Dur 7: iki sahte AÇIK kayıt (durum() canlı) benzetimi
_gercek_durum = masaustu.durum
masaustu.durum = lambda dogrula=True, saglik=True, ad=None: ({"tur": "kwin", "boyut": [1, 1, 24]}
                                                             if (masalar.secili() if ad is None else ad) in ("l1", "l2", "l3") else None)
for a_ in ("l1", "l2", "l3"):
    masalar.sahiplen(a_)
try:
    kontrol("azami 3 dolu → masaustu_baslat Dur 7", dur_kodu(masaustu.masaustu_baslat, ad="l4") == 7)
finally:
    masaustu.durum = _gercek_durum
    for a_ in ("l1", "l2", "l3"):
        masalar.birak(a_)
        masalar.kok_sil(a_)
# sahipsiz (ölü sahipli) oto masaüstü: list onu durdurup dizinini siler
olu = subprocess.Popen([sys.executable, "-c", "pass"])
olu.wait()
masalar.kok_hazirla("s9")
with open(masalar.sahip_yolu("s9"), "w") as f:
    f.write(f"mcp {olu.pid} 12345 1 - 1\n")
ortam = dict(os.environ)
r = subprocess.run([sys.executable, os.path.join(KOK, "bin", "deskhand"), "--desktop-name", "Kotu", "desktop", "list"],
                   capture_output=True, text=True, env=ortam, timeout=60)
kontrol("CLI --desktop-name geçersiz ad → çıkış 1", r.returncode == 1, r.stderr[-200:])
r = subprocess.run([sys.executable, os.path.join(KOK, "bin", "deskhand"), "--desktop-name", "s5", "desktop", "status",
                    "--json"], capture_output=True, text=True, env=ortam, timeout=60)
kontrol("CLI --desktop-name s5 status → kapalı (null), kapıdan geçti (sahibi ata zincirinde)",
        r.stdout.strip() == "null" and "oturumun" not in r.stderr, r.stderr[-200:])
r = subprocess.run([sys.executable, os.path.join(KOK, "bin", "deskhand"), "desktop", "list", "--json"],
                   capture_output=True, text=True, env=ortam, timeout=60)
try:
    liste = json.loads(r.stdout)
except ValueError:
    liste = None
kontrol("CLI desktop list --json", isinstance(liste, list) and any(m["ad"] == "s5" for m in liste), r.stdout[-300:])
kontrol("list: sahipsiz oto masaüstü temizlenir", liste is not None and not any(m["ad"] == "s9" for m in liste)
        and not os.path.exists(masalar.kok("s9")))

print(f"\n{gecen}/{toplam} çoklu masaüstü birim testi geçti")
sys.exit(0 if gecen == toplam else 1)
