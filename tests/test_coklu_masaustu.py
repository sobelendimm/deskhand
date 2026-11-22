# test_kos: tek-basina (iki KWin oturumu + iki MCP sunucusu aynı anda; paralel takımlar ölçümü bozar)
"""Çoklu görünmez masaüstü bütünleşik testi (Aşama 1 çekirdeği): aynı RUNTIME_DIR'de varsayılan ("") ve "b" KWin
masaüstleri aynı anda; kullanıcının GERÇEK oturumuna HİÇBİR girdi gitmez (kwin_wayland --virtual, özel soketler).

1) iki masaüstü açılır (ayrı çalışma dizini/soket/PID)  2) her birinde test penceresi; pencere listeleri ayrık
3) A'ya girdi B'ye düşmez (ve tersi)  4) A durunca B'nin PID/soket/oturum kopyaları duruyor (HATA 1)
5) başka oturumun masaüstü → CLI Dur 14  6) sınır (azami)  7) MCP uçtan uca: iki sunucu eşzamanlı
manage_desktop start → adlar "" ve "oturum-1"; sunucular kapanınca oto masaüstü ayrık temizleyiciyle kapanır.
KWin < 6.8 ya da yardımcılar derlenmemişse "atlandı" der ve 0 ile çıkar.

Çalıştır:  python3 tests/test_coklu_masaustu.py"""
import asyncio
import json
import os
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["DESKHAND_ARKA_TUR"] = "kwin"
os.environ["DESKHAND_HEDEF"] = "arka"
os.environ["DESKHAND_OTO_BEKLE"] = "1"
from deskhand import api, arka_uc, kwin_oturum as ko, masalar, masaustu  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from deskhand.oturum import politika  # noqa: E402

KOK = _yalitim.KOK
PENCERE = os.path.join(KOK, "tests", "yardimci", "kwin_test_pencere.py")
SUNUCU = os.path.join(KOK, "tests", "yardimci", "mcp_test_sunucu.py")
DESKHAND = os.path.join(KOK, "bin", "deskhand")
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


def bekle(kosul, sure=8.0, aralik=0.05):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def loglar(yol):
    try:
        with open(yol, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def tuslar(yol):
    return [s for s in loglar(yol) if s.startswith("tus_bas")]


ok, neden = ko.kullanilabilir()
if not ok:
    print(f"ATLANDI: KWin çoklu masaüstü testleri çalışamaz ({neden})")
    sys.exit(0)

ACIK = []


def kapat_hepsi():
    for ad in list(ACIK):
        try:
            masaustu.masaustu_durdur(ad)
        except Exception as e:  # noqa: BLE001
            print(f"NOT: {ad!r} kapatılamadı: {e}")


try:
    # ---------------------------------------------------------------- 1) iki masaüstü
    print("1) iki KWin masaüstü aynı RUNTIME_DIR'de")
    dA = masaustu.masaustu_baslat("800x600", ad="")
    ACIK.append("")
    dB = masaustu.masaustu_baslat("800x600", ad="b")
    ACIK.append("b")
    kontrol("A: varsayılan kayıt RUNTIME_DIR/sanal.json", os.path.isfile(os.path.join(masalar.kok(""), "sanal.json")))
    kontrol("B: kayıt masa/b/sanal.json", os.path.isfile(os.path.join(masalar.masa_koku(), "b", "sanal.json")))
    kontrol("tür kwin (ikisi)", dA["tur"] == "kwin" and dB["tur"] == "kwin", f"{dA['tur']} {dB['tur']}")
    kontrol("ayrı çalışma dizini, kimlik, Wayland soketi, KWin PID",
            dA["calisma"] != dB["calisma"] and dA["kimlik"] != dB["kimlik"] and dA["wayland_yol"] != dB["wayland_yol"]
            and dA["pid"]["kwin"] != dB["pid"]["kwin"])
    with masalar.masa_sabit("b"):
        kontrol("bağlam b: durum() B'nin", (masaustu.durum(saglik=False) or {}).get("kimlik") == dB["kimlik"])
    kontrol("bağlam '': durum() A'nın", (masaustu.durum(saglik=False) or {}).get("kimlik") == dA["kimlik"])
    lst = {m["ad"]: m for m in masaustu.liste()}
    kontrol("liste(): '' ve 'b' açık", lst.get("", {}).get("acik") and lst.get("b", {}).get("acik"), str(lst))
    r = subprocess.run([sys.executable, DESKHAND, "desktop", "list", "--json"], capture_output=True, text=True, timeout=60)
    kontrol("CLI desktop list: iki açık", sorted(m["ad"] for m in json.loads(r.stdout or "[]") if m["acik"]) == ["", "b"],
            r.stdout[-300:] + r.stderr[-200:])

    # ---------------------------------------------------------------- 2) pencereler
    print("\n2) her masaüstünde test penceresi; listeler ayrık")
    LA = os.path.join(_yalitim.PAYLASIM, "a.log")
    LB = os.path.join(_yalitim.PAYLASIM, "b.log")
    auA = arka_uc.sec()
    with masalar.masa_sabit("b"):
        auB = arka_uc.sec()
    kontrol("arka uç örnekleri ayrı", auA is not auB)
    pA = auA.baslat([sys.executable, PENCERE], {"LOG": LA, "BASLIK": "coklu A"})
    with masalar.masa_sabit("b"):
        pB = auB.baslat([sys.executable, PENCERE], {"LOG": LB, "BASLIK": "coklu B"})
    kA = bekle(lambda: next((w for w, _b, _ in auA.pencereler("coklu")), None), 15)
    with masalar.masa_sabit("b"):
        kB = bekle(lambda: next((w for w, _b, _ in auB.pencereler("coklu")), None), 15)
        bListe = [b for _w, b, _ in auB.pencereler("coklu")]
    aListe = [b for _w, b, _ in auA.pencereler("coklu")]
    kontrol("A'nın listesinde yalnız 'coklu A'", aListe == ["coklu A"], str(aListe))
    kontrol("B'nin listesinde yalnız 'coklu B'", bListe == ["coklu B"], str(bListe))
    kontrol("pencereler hazır", bekle(lambda: "hazir" in loglar(LA) and "hazir" in loglar(LB), 10))

    # ---------------------------------------------------------------- 3) girdi
    print("\n3) A'ya girdi B'ye düşmüyor")
    time.sleep(0.3)
    nA, nB = len(tuslar(LA)), len(tuslar(LB))
    with api.hedef("sanal"):
        r = api.tus(kA, "x")
    kontrol("A'ya tuş → A'nın günlüğünde", bekle(lambda: len(tuslar(LA)) > nA, 3), str(r))
    time.sleep(0.4)
    kontrol("A'ya tuş B'ye DÜŞMEDİ", len(tuslar(LB)) == nB, str(tuslar(LB)[-3:]))
    nA = len(tuslar(LA))
    with masalar.masa_sabit("b"), api.hedef("sanal"):
        r = api.tus(kB, "y")
    kontrol("B'ye tuş → B'nin günlüğünde", bekle(lambda: len(tuslar(LB)) > nB, 3), str(r))
    time.sleep(0.4)
    kontrol("B'ye tuş A'ya DÜŞMEDİ", len(tuslar(LA)) == nA, str(tuslar(LA)[-3:]))
    with masalar.masa_sabit("b"):
        kontrol("B bağlamında A'nın kimliği bulunamaz (pencere yok → Dur 8)",
                dur_kodu(auB.geometri, kA) == 8)

    # ---------------------------------------------------------------- 4) A durur, B yaşar
    print("\n4) A durunca B'nin süreçleri/soketi/kopyaları duruyor (HATA 1)")
    for ad in ("", "b"):
        os.makedirs(os.path.join(politika.kopya_dizini(ad), "firefox-test"), mode=0o700, exist_ok=True)
    with open(politika.flatpak_kayit("b"), "w") as f:
        json.dump([], f)
    ok_, _notlar = masaustu.masaustu_durdur("")
    ACIK.remove("")
    kontrol("A durdu", ok_ and masaustu.durum(ad="") is None)
    kontrol("A'nın penceresi kapandı", bekle(lambda: pA.poll() is not None, 5))
    kontrol("A'nın kopyası silindi", not os.path.exists(os.path.join(politika.kopya_dizini(""), "firefox-test")))
    kontrol("B'nin kopyası DURUYOR", os.path.isdir(os.path.join(politika.kopya_dizini("b"), "firefox-test")))
    kontrol("B'nin flatpak.json'u DURUYOR", os.path.isfile(politika.flatpak_kayit("b")))
    kontrol("B'nin KWin'i yaşıyor", masaustu._canli(dB["pid"]["kwin"]))
    kontrol("B'nin Wayland soketi duruyor", os.path.exists(dB["wayland_yol"]))
    kontrol("B'nin penceresi yaşıyor", pB.poll() is None)
    with masalar.masa_sabit("b"):
        kontrol("B durum() canlı + pencere listesi", masaustu.durum(saglik=False) is not None
                and [b for _w, b, _ in auB.pencereler("coklu")] == ["coklu B"])

    # ---------------------------------------------------------------- 5) başka oturum kapısı
    print("\n5) başka oturumun masaüstü → Dur 14")
    yabanci = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        bas = masalar._baslangic(yabanci.pid)
        with open(masalar.sahip_yolu("b"), "w") as f:
            f.write(f"mcp {yabanci.pid} {bas} {yabanci.pid} {bas} 0\n")
        # başka bir Claude oturumunun Bash'i: sahte `claude` sarmalayıcısının altında (insan kuralı: claude atası olmayan
        # çağrı izinlidir; test claude altında koşmasa da belirlenimci)
        sahte_claude = os.path.join(_yalitim.GECICI, "claude")
        if not os.path.exists(sahte_claude):
            os.symlink(sys.executable, sahte_claude)
        sarm = [sahte_claude, "-c", "import subprocess, sys; sys.exit(subprocess.run(sys.argv[1:]).returncode)"]
        for arg in (["desktop", "status"], ["windows"], ["desktop", "stop"]):
            r = subprocess.run([*sarm, sys.executable, DESKHAND, "--desktop-name", "b", *arg], capture_output=True,
                               text=True, timeout=60, env={**os.environ, "DESKHAND_HEDEF": "arka"})
            kontrol(f"CLI {' '.join(arg)} (başka oturum) → 14 'başka bir oturumun'",
                    r.returncode == 14 and "oturumun" in r.stderr, f"{r.returncode} {r.stderr[-200:]}")
        kontrol("B hâlâ açık (durdurma reddedildi)", masaustu._canli(dB["pid"]["kwin"]))
        # aynı Claude oturumu: sahibin ebeveyni bu testin süreci → CLI (testin çocuğu) erişir
        with open(masalar.sahip_yolu("b"), "w") as f:
            f.write(f"mcp {yabanci.pid} {bas} {os.getpid()} {masalar._baslangic(os.getpid())} 0\n")
        r = subprocess.run([sys.executable, DESKHAND, "--desktop-name", "b", "desktop", "status", "--json"],
                           capture_output=True, text=True, timeout=60)
        kontrol("aynı oturum (ebeveyn ata zincirinde) → status açık",
                r.returncode == 0 and (json.loads(r.stdout or "null") or {}).get("ad") == "b", r.stderr[-200:])
    finally:
        yabanci.kill()
        yabanci.wait()
        try:
            os.remove(masalar.sahip_yolu("b"))
        except OSError:
            pass

    # ---------------------------------------------------------------- 6) sınır
    print("\n6) sınır: [masaustu] azami")
    from deskhand import ayarlar
    ayarlar.ayarla("masaustu", "azami", 1)
    kontrol("azami 1, B açık → ikinci masaüstü Dur 7", dur_kodu(masaustu.masaustu_baslat, "800x600", ad="c") == 7)
    ayarlar.ayarla("masaustu", "azami", 3)
    os.environ["DESKHAND_ARKA_TUR"] = "xvfb"
    kontrol("adlı masaüstü Xvfb türünde açılmaz (Dur 9)", dur_kodu(masaustu.masaustu_baslat, "800x600", ad="c") == 9)
    os.environ["DESKHAND_ARKA_TUR"] = "kwin"
    masalar.kok_sil("c")

    masaustu.masaustu_durdur("b")
    ACIK.remove("b")
    kontrol("B durdu", masaustu.durum(ad="b") is None and pB.poll() is not None or bekle(lambda: pB.poll() is not None, 5))

    # ---------------------------------------------------------------- 7) MCP uçtan uca
    print("\n7) MCP: iki sunucu eşzamanlı → '' ve 'oturum-1'")

    async def mcp_iki():
        from mcp import Client, StdioServerParameters
        env = {**os.environ}
        env.pop("DESKHAND_HEDEF", None)
        env.pop(masalar.ORTAM, None)
        param = StdioServerParameters(command=sys.executable, args=[SUNUCU], env=env, cwd=_yalitim.GECICI)
        async with Client(param) as c1, Client(param) as c2:
            r1, r2 = await asyncio.gather(c1.call_tool("manage_desktop", {"action": "start", "size": "800x600"}),
                                          c2.call_tool("manage_desktop", {"action": "start", "size": "800x600"}))
            y1, y2 = r1.structured_content or {}, r2.structured_content or {}
            kontrol("iki start başarılı", not r1.is_error and not r2.is_error,
                    f"{getattr(r1.content[0], 'text', '')[:200]} | {getattr(r2.content[0], 'text', '')[:200]}")
            kontrol("adlar '' ve 'oturum-1'", sorted([y1.get("name"), y2.get("name")]) == ["", "oturum-1"],
                    f"{y1.get('name')!r} {y2.get('name')!r}")
            s1 = await c1.call_tool("get_status", {"desktop": "background"})
            kontrol("get_status: background.name", (s1.structured_content or {}).get("background", {}).get("name")
                    == y1.get("name"), str((s1.structured_content or {}).get("background")))
            lst_ = {m["ad"]: m for m in masaustu.liste(temizle=False)}
            kontrol("ikisi de açık; oturum-1 oto, sahipleri farklı", lst_.get("", {}).get("acik")
                    and lst_.get("oturum-1", {}).get("acik") and lst_["oturum-1"]["oto"]
                    and lst_[""]["sahip_pid"] != lst_["oturum-1"]["sahip_pid"], str(lst_))
            m1 = await c1.call_tool("manage_desktop", {"action": "status"})
            kontrol("status: kendi masaüstü, name", (m1.structured_content or {}).get("name") == y1.get("name")
                    and (m1.structured_content or {}).get("running") is True, str(m1.structured_content)[:200])

    asyncio.run(mcp_iki())
    kontrol("sunucular kapandı: sahiplikler bırakıldı", bekle(lambda: masalar.sahip_oku("") is None
                                                            and masalar.sahip_oku("oturum-1") is None, 10))
    kontrol("oto masaüstü (oturum-1) ayrık temizleyiciyle kapandı + dizini silindi",
            bekle(lambda: masaustu.durum(ad="oturum-1") is None and not os.path.exists(masalar.kok("oturum-1")), 20))
    kontrol("varsayılan masaüstü kendiliğinden KAPANMADI", masaustu.durum(ad="", saglik=False) is not None)
    masaustu.masaustu_durdur("")
    kontrol("kalıntı yok: KWin oturum dizini kalmadı", bekle(lambda: not [
        d for d in os.listdir(masalar.kok("")) if d.startswith(ko.OTURUM_ONEK)], 5),
        str(os.listdir(masalar.kok(""))))
finally:
    kapat_hepsi()
    for ad in ("", "oturum-1"):
        try:
            masaustu.masaustu_durdur(ad)
        except Exception:  # noqa: BLE001
            pass

print(f"\n{gecen}/{toplam} çoklu masaüstü bütünleşik testi geçti")
sys.exit(0 if gecen == toplam else 1)
