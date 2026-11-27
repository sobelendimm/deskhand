"""DH-TUR2 (1): sahibi YAŞAMAYAN boştaki görünmez masaüstünü herhangi bir canlı MCP sunucusu ya da `deskhand desktop`
CLI'si devralıp kapatır (canlıda: varsayılan masaüstü 1 sa 42 dk boşta kaldı, sahibi MCP süreci gitmişti, kimse
kapatmadı). Mevcut bosta_kapat kuralları aynen: Devral, bekleyen onay, görev kipi, DUR ve kullanımda → KAPATMAZ.
Yarış: iki devralan aynı anda → TEK kapatma (kilit). Masaüstü sahte (durum/durdurma yerine geçen işlevler), saat sahte
(simdi), sahip PID sahte (ölü süreç). Çalıştır:  python3 tests/test_sahipsiz_bosta.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import json
import os
import subprocess
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("DESKHAND_GOZETIMSIZ", None)

from deskhand import hata, masalar, masaustu, mcp_sunucu, yollar  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def gunluk_metni() -> str:
    try:
        with open(os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))) as f:
            return f.read()
    except OSError:
        return ""


def bildirimler() -> list[dict]:
    try:
        with open(masaustu.bildirim_yolu()) as f:
            return [json.loads(s) for s in f if s.strip()]
    except OSError:
        return []


def olu_pid() -> int:
    """Bitmiş bir sürecin PID'i (sahibi ölmüş MCP sunucusu gibi)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


sahte = {"": {"tur": "kwin", "ad": ""}, "isci": {"tur": "kwin", "ad": "isci"}}
durdurulan: list = []
devral = [False]
gercek = (masaustu.durum, masaustu.masaustu_durdur, masaustu.devral_var)


def sahte_durum(dogrula=True, saglik=True, ad=None):
    ad = masalar.secili() if ad is None else ad
    d = sahte.get(ad)
    return dict(d) if d is not None else None


def sahte_durdur(ad=None):
    time.sleep(0.3)  # gerçek kapanış zaman alır: yarış penceresi
    durdurulan.append(ad)
    sahte[ad] = None
    try:
        os.remove(masalar.durum_yolu(ad))
    except OSError:
        pass
    return True, []


def hazirla(ad: str, sahip: int | None = None, yas_sn: float = 0) -> None:
    """Kaydı olan masaüstü; sahip: None → sahip dosyası yok, -1 → ölü PID, diğer → o (canlı) PID."""
    sahte[ad] = {"tur": "kwin", "ad": ad}
    masalar.kok_hazirla(ad)
    with open(masalar.durum_yolu(ad), "w") as f:
        f.write("{}")
    try:
        os.remove(masalar.sahip_yolu(ad))
    except OSError:
        pass
    if sahip is not None:
        masalar.sahiplen(ad, pid=olu_pid() if sahip == -1 else sahip, ebeveyn=1)
    t = time.time() - yas_sn
    for yol in (masalar.durum_yolu(ad), masaustu.kullanim_yolu(ad)):
        with open(yol, "a"):
            pass
        os.utime(yol, (t, t))


masaustu.durum = sahte_durum
masaustu.masaustu_durdur = sahte_durdur
masaustu.devral_var = lambda yol=None: devral[0]
GELECEK = time.time() + 31 * 60
try:
    print("== sahipsiz boştaki masaüstü devralınıp kapatılır")
    kontrol("işlev var", hasattr(masaustu, "sahipsiz_bosta_kapat"))
    hazirla("", sahip=-1)
    kontrol("ölü PID'li sahip kaydı sahipsiz sayılır", masalar.sahip_oku("") is None)
    k = masaustu.sahipsiz_bosta_kapat(simdi=GELECEK, devralan="test")
    kontrol("sahibi ölmüş + 31 dk boşta → kapatılır", k == [""] and durdurulan == [""], f"{k} {durdurulan}")
    kontrol("kapanış günlüğe yazıldı (sahipsiz)", "sahipsiz" in gunluk_metni(), gunluk_metni()[-300:])
    kontrol("kapanış bildirim akışına yazıldı",
            any(b.get("uygulama") == "deskhand" and b.get("olay") == "masaustu-bosta-kapatildi" for b in bildirimler()),
            str(bildirimler())[-300:])
    kontrol("ölü sahibin kaydı kaldırıldı", not os.path.exists(masalar.sahip_yolu("")))

    durdurulan.clear()
    hazirla("")  # sahip dosyası HİÇ yok (CLI'den açılmış / eski sürüm)
    kontrol("sahip dosyası yok + boşta → kapatılır",
            masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [""] and durdurulan == [""])

    durdurulan.clear()
    hazirla("", sahip=os.getppid())
    kontrol("CANLI sahibi olan masaüstüne dokunulmaz",
            masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [] and durdurulan == [])

    hazirla("", sahip=-1)
    kontrol("sahipsiz ama yeni kullanılmış → kapatılmaz",
            masaustu.sahipsiz_bosta_kapat(simdi=time.time()) == [] and durdurulan == [])
    devral[0] = True
    kontrol("Devral açık (kontrol kullanıcıda) → kapatılmaz",
            masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [] and durdurulan == [])
    devral[0] = False
    sahte[""]["gorev"] = True
    kontrol("görev kipi → kapatılmaz", masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [] and durdurulan == [])
    sahte[""].pop("gorev")
    os.makedirs(os.path.dirname(hata.dur_dosyasi()), exist_ok=True)
    with open(hata.dur_dosyasi(), "w"):
        pass
    kontrol("DUR açık → kapatılmaz (bosta_neden 'dur')",
            masaustu.bosta_neden("", simdi=GELECEK) == "dur" and masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == []
            and durdurulan == [])
    os.remove(hata.dur_dosyasi())
    sahipli = masaustu.bosta_neden
    masaustu.bosta_neden = lambda ad=None, simdi=None: "onay"  # bekleyen onay: bosta_neden'in kuralı aynen geçer
    kontrol("bekleyen onay → kapatılmaz", masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [] and durdurulan == [])
    masaustu.bosta_neden = sahipli

    print("== yarış: iki devralan aynı anda → tek kapatma")
    hazirla("", sahip=-1)
    sonuclar: list = []
    engel = threading.Barrier(2)

    def devral_dene():
        engel.wait()
        sonuclar.append(masaustu.sahipsiz_bosta_kapat(simdi=GELECEK))
    isler = [threading.Thread(target=devral_dene) for _ in range(2)]
    for t in isler:
        t.start()
    for t in isler:
        t.join(10)
    kontrol("iki eşzamanlı devralma → masaüstü bir kez kapatıldı", durdurulan == [""], f"{durdurulan} {sonuclar}")

    print("== MCP bekçisi ve CLI devralır")
    durdurulan.clear()
    hazirla("", sahip=-1, yas_sn=31 * 60)
    mcp_sunucu._MASA.update(bagli=True, ad="isci", sahip=True)
    hazirla("isci", sahip=os.getpid())
    os.utime(masaustu.kullanim_yolu("isci"))  # kendi masaüstü yeni kullanıldı
    kontrol("MCP bekçisi (başka masaüstünün sahibi) sahipsiz varsayılanı kapatır",
            mcp_sunucu.bosta_denetle() and durdurulan == [""], str(durdurulan))
    durdurulan.clear()
    mcp_sunucu._MASA.update(bagli=False, sahip=False, ad="")
    hazirla("", sahip=-1, yas_sn=31 * 60)
    kontrol("bağlanmamış MCP sunucusunun bekçisi de devralır", mcp_sunucu.bosta_denetle() and durdurulan == [""])
    durdurulan.clear()
    hazirla("", sahip=-1, yas_sn=31 * 60)
    masalar.birak("isci", pid=os.getpid())
    # UX-FIX D-3: salt okuma alt komutları (list/status) süpürmez; stop süpürür
    import contextlib
    import io
    for komut in (["list", "--json"], ["status", "--desktop-name", "isci", "--json"]):
        with contextlib.redirect_stdout(io.StringIO()):
            masaustu.main(komut)
        kontrol(f"UX-FIX D-3: `deskhand desktop {komut[0]}` (salt okuma) süpürmez", durdurulan == [], str(durdurulan))
    hazirla("isci", sahip=os.getpid())
    with contextlib.redirect_stdout(io.StringIO()):
        masaustu.main(["stop", "--desktop-name", "isci"])
    kontrol("`deskhand desktop stop` sahipsiz boştaki masaüstlerini de kapatır", "" in durdurulan, str(durdurulan))
    masalar.birak("isci", pid=os.getpid())

    print("== UX-FIX O-1: DUR açıkken bakım (tarayıcı öldürme/yeniden başlatma) ve süpürme HİÇ çalışmaz")
    from deskhand import bellek_bekcisi
    gercek_bakim = bellek_bekcisi.bakim
    bakimlar: list = []
    bellek_bekcisi.bakim = lambda ad=None, simdi=None, **k: bakimlar.append(ad)
    try:
        durdurulan.clear()
        hazirla("", sahip=-1, yas_sn=31 * 60)
        with open(hata.dur_dosyasi(), "w"):
            pass
        kontrol("DUR açık → bosta_kapat bakım çağırmaz, kapatmaz",
                masaustu.bosta_kapat("", simdi=GELECEK) is False and bakimlar == [] and durdurulan == [],
                f"{bakimlar} {durdurulan}")
        kontrol("DUR açık → sahipsiz süpürme bakım çağırmaz, kapatmaz",
                masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [] and bakimlar == [] and durdurulan == [],
                f"{bakimlar} {durdurulan}")
        mcp_sunucu._MASA.update(bagli=True, ad="", sahip=True)
        kontrol("DUR açık → MCP bekçisi bakım çağırmaz, kapatmaz",
                not mcp_sunucu.bosta_denetle() and bakimlar == [] and durdurulan == [], f"{bakimlar} {durdurulan}")
        try:
            r = mcp_sunucu.manage_desktop(action="stop")
        except Exception as e:  # noqa: BLE001 - ToolError [13]
            r = str(e)
        kontrol("DUR açık → MCP manage_desktop stop reddedilir [13], masaüstü kapatılmaz",
                "[13]" in str(r) and durdurulan == [], f"{r} {durdurulan}")
        mcp_sunucu._MASA.update(bagli=False, sahip=False, ad="")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            kod = masaustu.main(["stop"])
        kontrol("DUR açık → `deskhand desktop stop` 13 döner, kapatmaz/süpürmez", kod == 13 and durdurulan == [],
                f"{kod} {durdurulan}")
        os.remove(hata.dur_dosyasi())
        kontrol("DUR kalkınca bakım yine çalışır (sahipsiz süpürme)",
                masaustu.sahipsiz_bosta_kapat(simdi=GELECEK) == [""] and "" in bakimlar,f"{bakimlar} {durdurulan}")
    finally:
        bellek_bekcisi.bakim = gercek_bakim
        if os.path.exists(hata.dur_dosyasi()):
            os.remove(hata.dur_dosyasi())

    print("== UX-FIX D-3: bir masaüstündeki hata (OSError) kalanların süpürülmesini kesmez")
    durdurulan.clear()
    hazirla("", sahip=-1, yas_sn=31 * 60)
    hazirla("isci", sahip=-1, yas_sn=31 * 60)
    gercek_kapat = masaustu.bosta_kapat
    ilk = [True]

    def bozuk_kapat(ad=None, simdi=None, devralan=None):
        if ilk[0]:
            ilk[0] = False
            raise OSError("test: disk hatası")
        return gercek_kapat(ad, simdi, devralan=devralan)
    masaustu.bosta_kapat = bozuk_kapat
    try:
        k = masaustu.sahipsiz_bosta_kapat(simdi=GELECEK, devralan="test")
    finally:
        masaustu.bosta_kapat = gercek_kapat
    kontrol("ilk masaüstünde OSError → döngü sürer, ikincisi kapatılır", len(k) == 1 and len(durdurulan) == 1,
            f"{k} {durdurulan}")
    kontrol("OSError günlüğe yazıldı", "test: disk hatası" in gunluk_metni(), gunluk_metni()[-300:])
finally:
    masaustu.durum, masaustu.masaustu_durdur, masaustu.devral_var = gercek

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
