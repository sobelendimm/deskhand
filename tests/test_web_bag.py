"""Web okuma katmanının (deskhand.web) araçlara bağlanması: MCP read_text(source="web"), MCP click(element=…) / CLI
click-element web ögelerinde, CLI `web` komutu, öge konumu doğrulama (fail-closed), arka planda açılan Firefox'un
erişilebilirlik ağacı.

GÖRÜNMEZ arka plan masaüstünde (Xvfb) YALITIK Firefox (yeni boş geçici profil; tests/yardimci/web_tarayici.py), YEREL
sentetik sayfalar (tests/ornek/web/; testin açtığı 127.0.0.1 sunucusundan; dış ağ yok). Firefox GNOME_ACCESSIBILITY
OLMADAN başlatılır: ağacı sunması yalnız masaüstünün kendi erişilebilirlik hazırlığına (IsEnabled + kayıt defteri) bağlıdır.
Tıklamaların varış kanıtı sayfanın kendi günlüğüdür (ortak.js: pencere başlığı "TIK <ad> #<sıra>"). Onay paneli sahtedir
(onay.iste_sonuc): istekler kaydedilir, izin/red testten verilir; gerçek ~/.config/deskhand yazılmaz.
Kullanıcının Firefox profil kökü (profiles.ini / installs.ini sha1 + dizin adları) önce/sonra karşılaştırılır; fark
varsa test HEMEN durur (hiçbir şey düzeltilmez). Kullanıcının ekranına girdi gitmez; Firefox yoksa test atlanır.

Çalıştır:  python3 tests/test_web_bag.py"""
import argparse
import asyncio
import atexit
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
import web_tarayici as wt  # noqa: E402

if not (shutil.which("firefox") and shutil.which("Xvfb")):
    print("atlandı: firefox ya da Xvfb yok")
    sys.exit(0)
try:
    import jeepney  # noqa: F401
    from mcp import Client  # noqa: F401
except ImportError:
    print("atlandı: jeepney ya da mcp yok")
    sys.exit(0)

from deskhand import api, guvenlik, masaustu, onay, web, yollar  # noqa: E402
from deskhand import mcp_sunucu as s  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def bekle(kosul, sure=5.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


def yapi(r):
    return r.structured_content or {}


# ---------------------------------------------------------------- sahte onay paneli
ISTEKLER = []
YANIT = {"izin": False}


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


onay.iste_sonuc = sahte_iste_sonuc

# ---------------------------------------------------------------- kullanıcı Firefox profil bekçisi
bekci = wt.ProfilBekcisi()
acik_firefoxlar = []


def profil_denetle(an):
    f = bekci.fark()
    if f:
        print(f"\n!!! KULLANICI FIREFOX PROFİL KÖKÜ DEĞİŞTİ ({an}): {f}\n!!! test durduruldu; hiçbir şey düzeltilmedi",
              flush=True)
        for ff_ in acik_firefoxlar:
            ff_.kapat()
        masaustu.masaustu_durdur()
        os._exit(2)
    return True


def kapat_hepsi():
    for ff_ in acik_firefoxlar:
        try:
            ff_.kapat()
        except Exception:  # noqa: BLE001
            pass
    if masaustu.durum_oku() is not None:
        masaustu.masaustu_durdur()


atexit.register(kapat_hepsi)


def tik(k, bekle_sn=1.5):
    """Sayfanın kendi günlüğü: (son tıklanan öge adı, sıra no). Başlık güncellemesi pencere yöneticisine tıklamadan
    biraz sonra (nice 10 + ionice idle altındaki Firefox) ulaşır: henüz günlük yoksa kısa süre beklenir."""
    bitis = time.monotonic() + bekle_sn
    while True:
        m = re.match(r"TIK (.+) #(\d+)", s_au.baslik(k) or "")
        if m or time.monotonic() >= bitis:
            return (m.group(1), int(m.group(2))) if m else (None, 0)
        time.sleep(0.05)


def seviye_yaz(*satirlar):
    os.makedirs(os.path.dirname(yollar.seviye_dosya()), exist_ok=True)
    with open(yollar.seviye_dosya(), "w") as f:
        f.write("\n".join(satirlar) + "\n")


def seviye_sil():
    with contextlib.suppress(OSError):
        os.remove(yollar.seviye_dosya())


# ================================================================ 0) konum_coz: sahte geometriyle (Firefox gerekmez)
print("öge konumu doğrulama (konum_coz)")
geo = (100, 50, 800, 600)
S, W_ = web.SCREEN, web.WINDOW
r = web.konum_coz(geo, (100, 50, 800, 600), (0, 0, 800, 600))
kontrol("küresel dekorlu çerçeve: ekran sınırı geometriyle aynı", r == (S, (-100, -50), "kuresel_cerceve"), str(r))
r = web.konum_coz(geo, (101, 49, 799, 601), None)
kontrol("küresel dekorlu çerçeve: ±1 px tolerans", r and r[2] == "kuresel_cerceve", str(r))
r = web.konum_coz(geo, (104, 80, 792, 566), (0, 0, 792, 566))
kontrol("küresel istemci alanı (kenar payı 4, başlık çubuğu 30): ekran sınırı geometrinin içinde, paylar tutarlı",
        r == (S, (-100, -50), "kuresel_istemci"), str(r))
r = web.konum_coz(geo, (0, 0, 792, 566), (0, 0, 792, 566))
kontrol("pencere-yerel: ekran sınırı 0,0 (geometriye uymaz), pencere sınırı tutarlı → dekorasyon payı eklenir",
        r == (W_, (4, 30), "pencere"), str(r))
r = web.konum_coz(geo, (700, 400, 300, 300), (50, 50, 300, 300))
kontrol("uyumsuz: hiçbir çerçeveye uymuyor → None (tık yolu reddeder)", r is None, str(r))
r = web.konum_coz(geo, (0, 0, 200, 100), (0, 0, 200, 100))
kontrol("uyumsuz: yerel görünen ama boyutu pencereye uymayan sınır → None", r is None, str(r))
r = web.konum_coz(geo, (-1, -1, -1, -1), (-1, -1, -1, -1))
kontrol("uyumsuz: geçersiz (-1) sınır → None", r is None, str(r))
kontrol("uyumsuz: boş yanıt → None", web.konum_coz(geo, None, None) is None)

# ================================================================ 1) masaüstü + sunucu
print("kullanıcı profil kökü (önce):", *bekci.satirlar()[:2], sep="\n  ")
d = masaustu.masaustu_baslat()
s_au = sec(arka_bayragi=True)
srv = wt.Sunucu()


def ac(sayfa, **kw):
    ff = wt.Firefox(s_au, _yalitim.PAYLASIM, srv.url(sayfa), erisilebilirlik=False, **kw)  # GNOME_ACCESSIBILITY YOK
    acik_firefoxlar.append(ff)
    profil_denetle(f"{sayfa} açıldı")
    return ff


def kapat(ff, an):
    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle(an)


async def arac(c, ad, **kw):
    kw.setdefault("desktop", "background")
    return await c.call_tool(ad, kw)


def cli(*arg, sure=60):
    """Gerçek CLI süreci (görünmez masaüstü): (çıkış kodu, stdout, stderr)."""
    p = subprocess.run([sys.executable, "-m", "deskhand", "--arka", *arg], capture_output=True, text=True, timeout=sure,
                       cwd=_yalitim.KOK)
    return p.returncode, p.stdout, p.stderr


async def senaryo():
    async with Client(s.mcp) as c:
        # ------------------------------------------------------------ form.html
        ff = ac("form.html")
        k = ff.k
        kontrol("firefox: GNOME_ACCESSIBILITY olmadan da pencere arka plan masaüstünde, kendi süreci",
                k and k.startswith("arka:") and ff.p.pid in wt.ata_pidler(s_au.pid(k)))
        bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Form Testi", 15)
        agac = bekle(lambda: (lambda o: o if o["toplam"] > 10 else None)(web.oku(k, en_cok=0, gorunur=False)), 10)
        kontrol("arka plan Firefox: erişilebilirlik ağacını (GNOME_ACCESSIBILITY olmadan) sunuyor",
                bool(agac) and agac["toplam"] >= 17, str(agac and agac["toplam"]))

        r = await arac(c, "read_text", window=k, source="web")
        y = yapi(r)
        # at-spi2-core sürümüne göre düğme "push button" (eski) ya da "button": aynı rol
        adlar = {("button" if o["role"] == "push button" else o["role"], o["text"]) for o in y.get("items", [])}
        kontrol("read_text(web): etkileşimli ögeler rol + ad + merkezle", not r.is_error and
                ("button", "Kaydet") in adlar and ("check box", "Bülten aboneliği") in adlar and
                ("link", "Yardım") in adlar and all(len(o["center"]) == 2 for o in y["items"]), metin(r)[:300])
        kontrol("read_text(web): sayfa bilgisi (başlık, adres, konum doğrulandı), shot_id, pencere",
                y["page"]["title"] == "Deskhand Form Testi" and y["page"]["url"].endswith("/form.html") and
                y["page"]["position_verified"] is True and y.get("shot_id") and y["window"]["id"] == k and
                "sensitive_page" not in y["page"])
        kontrol("read_text(web): varsayılan yalnız görünür ögeler (gizli / kaydırma dışı yok)",
                not any(o["text"] in ("Gizli düğme", "Saklı düğme", "Sayfa sonu düğmesi") for o in y["items"]) and
                y["total"] == len(y["items"]) == 17)
        kontrol("read_text(web): bağlantı adresi (href) ve kapalı seçim kutusunun değeri",
                any(o["text"] == "Yardım" and o.get("href", "").endswith("#yardim") for o in y["items"]) and
                any(o["text"] == "Şehir" and o.get("value") == "Çınarlı" for o in y["items"]),
                str([o for o in y["items"] if o["text"] in ("Yardım", "Şehir")]))
        kontrol("read_text(web): devre dışı düğme durumu", any(o["text"] == "Gönder" and "devre_disi" in o.get("state", [])
                                                              for o in y["items"]))
        r = await arac(c, "read_text", window=k, source="web", hidden=True)
        kontrol("read_text(web, hidden): kaydırma dışı öge visible=false ile gelir",
                any(o["text"] == "Sayfa sonu düğmesi" and o.get("visible") is False for o in yapi(r)["items"]))
        r = await arac(c, "read_text", window=k, source="web", query="Kaydet")
        kontrol("read_text(web): sorgu ada göre süzer", [o["text"] for o in yapi(r)["items"]] == ["Kaydet"] and
                yapi(r)["total"] == 1, metin(r)[:200])
        r = await arac(c, "read_text", window=k, source="web", role="check box")
        kontrol("read_text(web): rol süzgeci (check box)", [o["text"] for o in yapi(r)["items"]] ==
                ["Bülten aboneliği", "Koşulları kabul ediyorum"], metin(r)[:200])
        r = await arac(c, "read_text", window=k, source="web", role="düğme")
        kontrol("read_text(web): Türkçe rol takma adı (düğme) yalnız düğmeler",
                {o["role"] for o in yapi(r)["items"]} <= {"button", "push button", "toggle button"} and
                len(yapi(r)["items"]) >= 5)
        r1 = await arac(c, "read_text", window=k, source="web", max_items=5)
        r2 = await arac(c, "read_text", window=k, source="web", max_items=5, offset=yapi(r1)["next"])
        kontrol("read_text(web): sayfalama (max_items / offset / next)", len(yapi(r1)["items"]) == 5 and
                yapi(r1)["next"] == 5 and [o["no"] for o in yapi(r2)["items"]] == [6, 7, 8, 9, 10] and
                yapi(r2)["total"] == 17, str((yapi(r1).get("next"), yapi(r2).get("next"))))
        r = await arac(c, "read_text", window=k, source="web", query="Böyle bir öge yok")
        kontrol("read_text(web): eşleşme yoksa boş liste (hata değil)", not r.is_error and yapi(r)["items"] == [] and
                yapi(r)["total"] == 0)

        # tıklama: sayfanın kendi günlüğünden doğru öge
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Kaydet", verify=False)
        kontrol("click(element, web): gerçek fare tıklaması doğru ögeye ulaştı (sayfa günlüğü)",
                not r.is_error and tik(k) == ("Kaydet", n0 + 1) and yapi(r).get("approved_by_user") is False and
                not ISTEKLER, metin(r)[:300] + str(tik(k)))
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Bülten aboneliği", role="check box", verify=False)
        kontrol("click(element, role): rol verilince onay kutusu tıklandı", not r.is_error and
                tik(k) == ("Bülten aboneliği", n0 + 1), metin(r)[:300])
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Gönder", verify=False)
        kontrol("click(element): devre dışı öge → [6], tık sayfaya ulaşmadı", r.is_error and "[6]" in metin(r) and
                "devre dışı" in metin(r) and tik(k)[1] == n0, metin(r)[:300])
        r = await arac(c, "click", window=k, element="Gizli düğme", verify=False)
        kontrol("click(element): display:none öge ağaçta yok → [6], tık yok", r.is_error and "[6]" in metin(r) and
                tik(k)[1] == n0, metin(r)[:300])
        r = await arac(c, "click", window=k, element="Kaydet", role="link", verify=False)
        kontrol("click(element, role): rol uymuyorsa tıklanmaz ([6])", r.is_error and "[6]" in metin(r) and
                tik(k)[1] == n0, metin(r)[:300])

        # DUR → 13
        guvenlik.dur_ac("cli")
        r = await arac(c, "click", window=k, element="Kaydet", verify=False)
        kontrol("DUR: click(element, web) → [13], tık yok", r.is_error and "[13]" in metin(r) and tik(k)[1] == n0,
                metin(r)[:300])
        r = await arac(c, "read_text", window=k, source="web", max_items=3)
        kontrol("DUR: okuma (girdi göndermez) serbest", not r.is_error and len(yapi(r)["items"]) == 3)
        guvenlik.dur_kapat("cli")

        # erişim seviyesi: goruntule → fare yok (10); okuma serbest
        seviye_yaz("firefox = goruntule")
        r = await arac(c, "click", window=k, element="Kaydet", verify=False)
        kontrol("erişim seviyesi goruntule: click(element, web) → [10], onay istenmedi, tık yok",
                r.is_error and "[10]" in metin(r) and tik(k)[1] == n0 and not ISTEKLER, metin(r)[:300])
        r = await arac(c, "click", window=k, element="Kaydet", via="action", verify=False)
        kontrol("erişim seviyesi goruntule: via=action de [10], tık yok", r.is_error and "[10]" in metin(r) and
                tik(k)[1] == n0, metin(r)[:300])
        r = await arac(c, "read_text", window=k, source="web", max_items=3)
        kontrol("erişim seviyesi goruntule: okuma serbest", not r.is_error and len(yapi(r)["items"]) == 3)
        seviye_sil()

        # erişilebilirlik eylemi (fare yok)
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Kaydet", via="action", verify=False)
        kontrol("click(element, via=action, web): AT-SPI eylemi çalıştı (günlük + sayfa)", not r.is_error and
                yapi(r).get("via") == "action" and "web" in yapi(r).get("message", "") and
                bekle(lambda: tik(k) == ("Kaydet", n0 + 1), 3), metin(r)[:300] + str(tik(k)))

        # konum doğrulanamıyor → fail-closed
        gercek = s_au.geometri
        X, Y, W, H = gercek(k)
        s_au.geometri = lambda _k: (X + 37, Y + 211, W // 2, H // 2)  # sahte: çerçeve sınırı hiçbir şeye uymaz
        n0 = tik(k)[1]
        try:
            ok = web.sayfa_bilgisi(k)
            r = await arac(c, "click", window=k, element="Kaydet", verify=False)
        finally:
            del s_au.geometri
        kontrol("konum doğrulanamıyor: okuma bunu bildirir (konum_dogrulandi=false)",
                ok["konum_dogrulandi"] is False and ok["konum"] is None, str(ok))
        kontrol("konum doğrulanamıyor: click(element) → [2] 'konum doğrulanamadı', tık YOK (fail-closed)",
                r.is_error and "[2]" in metin(r) and "doğrulanamadı" in metin(r) and tik(k)[1] == n0, metin(r)[:300])
        ok2 = web.sayfa_bilgisi(k)
        kontrol("konum: gerçek geometri geri gelince yine doğrulanır (sanal: küresel çerçeve)",
                ok2["konum_dogrulandi"] is True and ok2["konum"] in ("kuresel_cerceve", "kuresel_istemci"), str(ok2))

        # görünmeyen (kaydırma dışı) öge → sayfa kaydırılır, sonra tıklanır
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Sayfa sonu düğmesi", verify=False)
        kontrol("click(element): görüş alanı dışındaki öge önce kaydırılıp tıklandı", not r.is_error and
                tik(k) == ("Sayfa sonu düğmesi", n0 + 1) and "kaydırıldı" in metin(r), metin(r)[:300] + str(tik(k)))
        kapat(ff, "form kapandı")

        # ------------------------------------------------------------ bilesen.html: iframe, belirsizlik
        ff = ac("bilesen.html")
        k = ff.k
        bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Bileşen Testi", 15)
        bekle(lambda: len([o for o in web.sayfa_ogeleri(k, en_cok=0) if o["ad"].startswith("Çerçeve")]) >= 6, 10)
        r = await arac(c, "read_text", window=k, source="web", query="Çerçeve 2 düğmesi")
        o = (yapi(r)["items"] or [{}])[0]
        kontrol("read_text(web): iframe ögesi frame=1 ile", o.get("text") == "Çerçeve 2 düğmesi" and o.get("frame") == 1,
                metin(r)[:300])
        n0 = tik(k)[1]
        r = await arac(c, "click", window=k, element="Çerçeve 2 düğmesi", verify=False)
        kontrol("click(element): iframe içindeki düğme doğru tıklandı", not r.is_error and
                bekle(lambda: tik(k) == ("Çerçeve 2 düğmesi", n0 + 1), 3), metin(r)[:300] + str(tik(k)))
        r = await arac(c, "click", window=k, element="Çerçeve", verify=False)
        kontrol("click(element): birden çok eşleşme → [5] (nth ile seç), tık yok", r.is_error and "[5]" in metin(r) and
                tik(k)[1] == n0 + 1, metin(r)[:300])
        r = await arac(c, "click", window=k, element="Çerçeve", role="button", nth=1, verify=False)
        kontrol("click(element, role + nth): iframe düğmesi #1", not r.is_error and
                bekle(lambda: tik(k) == ("Çerçeve 1 düğmesi", n0 + 2), 3), metin(r)[:300] + str(tik(k)))
        kapat(ff, "bilesen kapandı")

        # ------------------------------------------------------------ satin.html: hassas ad (yazısız düğme dahil)
        ff = ac("satin.html")
        k = ff.k
        bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Mağaza Testi", 15)
        bekle(lambda: web.sayfa_ogeleri(k), 10)
        r = await arac(c, "read_text", window=k, source="web")
        kontrol("read_text(web): hassas düğme adları sensitive=true, sıradanlar değil",
                {o["text"] for o in yapi(r)["items"] if o.get("sensitive")} == {"Satın al", "Öde", "Siparişi onayla"} and
                "sensitive_page" not in yapi(r)["page"], metin(r)[:400])
        ISTEKLER.clear()
        n0 = tik(k)[1]
        # (yan yana hassas düğmeler olan satırdan değil: OCR komşu yazıyı da okur, o satır temkinli davranır)
        r = await arac(c, "click", window=k, element="İade koşulları", verify=False)
        kontrol("sıradan bağlantı: onay istenmedi, tıklandı", not r.is_error and tik(k) == ("İade koşulları", n0 + 1) and
                not ISTEKLER, metin(r)[:300])
        n0 += 1
        n0 = tik(k)[1]
        for ad in ("Satın al", "Öde"):
            ISTEKLER.clear()
            YANIT["izin"] = False
            r = await arac(c, "click", window=k, element=ad, verify=False)
            kontrol(f"hassas '{ad}': panel red → [10], tek onay isteği ({ad} adıyla), HİÇBİR tık ulaşmadı",
                    r.is_error and "[10]" in metin(r) and len(ISTEKLER) == 1 and ad in ISTEKLER[0]["eylem"] and
                    tik(k)[1] == n0, metin(r)[:300] + str(ISTEKLER)[:300])
        ISTEKLER.clear()
        YANIT["izin"] = True
        r = await arac(c, "click", window=k, element="Öde", verify=False)
        kontrol("yazısız (aria-label) 'Öde': panel izin verince BİR kez tıklandı, approved_by_user",
                not r.is_error and yapi(r).get("approved_by_user") is True and len(ISTEKLER) == 1 and
                bekle(lambda: tik(k) == ("Öde", n0 + 1), 3), metin(r)[:300] + str(tik(k)))
        time.sleep(0.5)
        kontrol("yazısız 'Öde': sayfa günlüğünde tek tık (iki kez ulaşmadı)", tik(k) == ("Öde", n0 + 1), str(tik(k)))
        ISTEKLER.clear()
        YANIT["izin"] = False
        r = await arac(c, "click", window=k, element="Siparişi onayla", via="action", verify=False)
        kontrol("hassas ad: via=action da onaysız yapılmaz ([10]), tık yok", r.is_error and "[10]" in metin(r) and
                len(ISTEKLER) == 1 and tik(k)[1] == n0 + 1, metin(r)[:300])

        # ---- birleştirme bağlamaları: bekleyen onay kapısı, onay sonrası öge doğrulaması, çerçeve = pencerenin PID ağacı
        n0 = tik(k)[1]
        onay._dizin_hazirla()
        bid = "7" * 32
        onay._yaz_atomik(onay.istek_yolu(bid), {"id": bid, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "arka",
                                               "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getppid()})
        try:
            r1 = await arac(c, "click", window=k, element="İade koşulları", verify=False)
            r2 = await arac(c, "click", window=k, element="İade koşulları", via="action", verify=False)
            kod_cli, _o, e_cli = cli("click-element", k, "İade koşulları")
            r3 = await arac(c, "read_text", window=k, source="web", max_items=2)
        finally:
            onay._sil(onay.istek_yolu(bid))
        kontrol("bekleyen onay (başka süreç, bu masaüstü): click(element, web) ve via=action → [7], tık yok",
                r1.is_error and "[7]" in metin(r1) and r2.is_error and "[7]" in metin(r2) and tik(k)[1] == n0,
                metin(r1)[:200] + " | " + metin(r2)[:200])
        kontrol("bekleyen onay: CLI click-element (web) → 7, tık yok; okuma serbest",
                kod_cli == 7 and tik(k)[1] == n0 and not r3.is_error, f"{kod_cli} {e_cli[-300:]}")

        asil_ovs = web.oge_ve_sayfa

        def kaydiran(*a_, **k_):  # onay beklenirken öge yer değiştirdi (sayfa yeniden dizildi)
            o_, sf_, su_, i_ = asil_ovs(*a_, **k_)
            if o_.get("merkez"):
                o_ = {**o_, "merkez": [o_["merkez"][0], o_["merkez"][1] + 40]}
            return o_, sf_, su_, i_

        def degistiren_onay(*a_, **k_):
            web.oge_ve_sayfa = kaydiran
            return sahte_iste_sonuc(*a_, **k_)
        ISTEKLER.clear()
        YANIT["izin"] = True
        onay.iste_sonuc = degistiren_onay
        try:
            r = await arac(c, "click", window=k, element="Satın al", verify=False)
        finally:
            web.oge_ve_sayfa = asil_ovs
        kontrol("onay sonrası (fare): web ögesi onay beklenirken yer değiştirdi → [10] 'onay verilen hedef değişti', "
                "tık yok", r.is_error and "[10]" in metin(r) and "hedef değişti" in metin(r) and tik(k)[1] == n0,
                metin(r)[:300])
        ISTEKLER.clear()
        try:
            r = await arac(c, "click", window=k, element="Siparişi onayla", via="action", verify=False)
        finally:
            web.oge_ve_sayfa = asil_ovs
            onay.iste_sonuc = sahte_iste_sonuc
        kontrol("onay sonrası (via=action): web ögesi değişti → [10], eylem yok",
                r.is_error and "[10]" in metin(r) and "hedef değişti" in metin(r) and tik(k)[1] == n0, metin(r)[:300])
        ISTEKLER.clear()
        r = await arac(c, "click", window=k, element="Siparişi onayla", via="action", verify=False)
        kontrol("onay sonrası (via=action): öge aynı → izinle BİR kez çalıştı", not r.is_error and len(ISTEKLER) == 1 and
                bekle(lambda: tik(k) == ("Siparişi onayla", n0 + 1), 3), metin(r)[:300] + str(tik(k)))
        YANIT["izin"] = False
        n0 = tik(k)[1]

        asil_pid = s_au.pid
        yabanci = subprocess.Popen(["sleep", "30"])
        try:
            s_au.pid = lambda _k: yabanci.pid  # pencere başka (ağaçta olmayan) bir sürece ait görünüyor
            r = await arac(c, "read_text", window=k, source="web")
            r2 = await arac(c, "click", window=k, element="İade koşulları", via="action", verify=False)
            s_au.pid = lambda _k: ""
            r3 = await arac(c, "read_text", window=k, source="web")
        finally:
            s_au.pid = asil_pid
            yabanci.kill()
            yabanci.wait()
        kontrol("B2 (web): pencerenin PID ağacında uygulama yoksa başlık benzerliğiyle Firefox çerçevesine DÜŞÜLMEZ → [6]",
                r.is_error and "[6]" in metin(r) and r2.is_error and tik(k)[1] == n0, metin(r)[:200] + metin(r2)[:200])
        kontrol("B2 (web): PID bilinmiyorsa → [6]", r3.is_error and "[6]" in metin(r3), metin(r3)[:200])
        from deskhand import kendi
        asil_panel = onay.panel_pid
        pencere_pid = s_au.pid(k)  # bwrap ad alanında pencere sahibi, başlatılan PID'in (bwrap) torunu
        onay.panel_pid = lambda: pencere_pid  # çerçeve Deskhand panelinin sürecine ait görünüyor
        try:
            r = await arac(c, "read_text", window=k, source="web")
            r2 = await arac(c, "click", window=k, element="İade koşulları", via="action", verify=False)
        finally:
            onay.panel_pid = asil_panel
        kontrol("çerçeve denetimi (web): panel sürecinin çerçevesi okunmaz ve eylem almaz → [10]",
                r.is_error and "[10]" in metin(r) and r2.is_error and "[10]" in metin(r2) and tik(k)[1] == n0,
                metin(r)[:200] + metin(r2)[:200])
        asil_kendi = kendi.kendi_mi
        kendi.kendi_mi = lambda pid, *a_, **k_: str(pid) == str(pencere_pid)  # yalnız çerçeve düzeyi (PID kuralı)
        try:
            with api.hedef("sanal"):
                e_tara = e_eylem = None
                try:
                    web._baglam(k, "tara")[1].kapat()
                except Dur as e:
                    e_tara = e
                try:
                    web._baglam(k, "eylem")[1].kapat()
                except Dur as e:
                    e_eylem = e
        finally:
            kendi.kendi_mi = asil_kendi
        kontrol("çerçeve denetimi (web): ajanın kendi istemcisine ait çerçeve → eylemde 10, okumada serbest",
                e_tara is None and e_eylem is not None and e_eylem.kod == 10, f"{e_tara} | {e_eylem}")
        seviye_yaz("firefox = goruntule")  # uygulama adı (sayfa başlığı tık günlüğüyle değişir)
        try:
            with api.hedef("sanal"):
                e_eylem = None
                try:
                    web._baglam(k, "eylem")[1].kapat()
                except Dur as e:
                    e_eylem = e
        finally:
            seviye_sil()
        kontrol("çerçeve denetimi (web): çerçevenin uygulama adına uyan erişim seviyesi goruntule → eylemde 10",
                e_eylem is not None and e_eylem.kod == 10, str(e_eylem))

        # belge başlığı ağaçtan (pencere başlığına EK denetim)
        ISTEKLER.clear()
        try:
            guvenlik.eylem_basladi()
            guvenlik.hassas_sayfa_engel(k, False, "tıklama", ek_basliklar=("Ödeme özeti",), goruntu_al=False)
            kod = 0
        except Dur as e:
            kod = e.kod
        kontrol("hassas_sayfa_engel: pencere başlığı sıradan olsa da ağaçtan gelen belge başlığı ödeme sayfasıysa onay "
                "ister", kod == 10 and len(ISTEKLER) == 1, f"{kod} {ISTEKLER}")
        kapat(ff, "satın alma kapandı")

        # ------------------------------------------------------------ odeme.html: sıradan düğme, hassas SAYFA
        ff = ac("odeme.html")
        k = ff.k
        bekle(lambda: web.sayfa_bilgisi(k)["baslik"].startswith("Ödeme"), 15)
        r = await arac(c, "read_text", window=k, source="web")
        kontrol("read_text(web): ödeme başlıklı sayfa → page.sensitive_page", yapi(r)["page"].get("sensitive_page") is True,
                metin(r)[:300])
        n0 = tik(k)[1]
        ISTEKLER.clear()
        YANIT["izin"] = False
        r = await arac(c, "click", window=k, element="Kuponu uygula", verify=False)
        kontrol("ödeme sayfasında sıradan düğme: onay istendi, red → [10], tık yok", r.is_error and "[10]" in metin(r) and
                len(ISTEKLER) == 1 and "Hassas sayfada" in ISTEKLER[0]["eylem"] and tik(k)[1] == n0, metin(r)[:300])
        ISTEKLER.clear()
        YANIT["izin"] = True
        r = await arac(c, "click", window=k, element="Kuponu uygula", verify=False)
        kontrol("ödeme sayfasında sıradan düğme: izin → bir kez tıklandı", not r.is_error and len(ISTEKLER) == 1 and
                yapi(r).get("approved_by_user") is True and bekle(lambda: tik(k) == ("Kuponu uygula", n0 + 1), 3),
                metin(r)[:300] + str(tik(k)))
        YANIT["izin"] = False

        # ------------------------------------------------------------ CLI (gerçek süreç)
        ISTEKLER.clear()
        kod, cikti, hata_ = cli("web", k)
        kontrol("CLI web: başlık satırı + #no (merkez) rol: ad satırları, ödeme uyarısı",
                kod == 0 and "Ödeme özeti (test)" in cikti and "Kuponu uygula" in cikti and "DİKKAT" in cikti and
                re.search(r"#1 \(\d+,\d+\) button: Kuponu uygula", cikti), f"{kod} {cikti[:300]} {hata_[-200:]}")
        kod, cikti, hata_ = cli("web", k, "Adresi", "--rol", "düğme")
        kontrol("CLI web <sorgu> --rol: süzülmüş", kod == 0 and "Adresi düzenle" in cikti and
                "Kuponu" not in "\n".join(l for l in cikti.splitlines() if not l.startswith("#")),
                f"{kod} {cikti[:300]}")
        kod, cikti, hata_ = cli("web", k, "Böyle bir öge yok")
        kontrol("CLI web: eşleşme yoksa çıkış 6", kod == 6, f"{kod} {cikti[:200]} {hata_[-200:]}")
        kod, cikti, hata_ = cli("click-element", k, "Adresi düzenle", "--approved")
        kontrol("CLI click-element (web, --approved): tıklandı", kod == 0 and "bulundu: web" in cikti and
                bekle(lambda: tik(k)[0] == "Adresi düzenle", 3), f"{kod} {cikti[:300]} {hata_[-300:]}")
        n0 = tik(k)[1]
        kod, cikti, hata_ = cli("click-element", k, "Kuponu uygula")
        kontrol("CLI click-element (web): ödeme sayfası, panel kapalı → 10, tık yok", kod == 10 and tik(k)[1] == n0,
                f"{kod} {hata_[-300:]}")
        kapat(ff, "odeme kapandı")

        ff = ac("form.html")
        k = ff.k
        bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Form Testi", 15)
        bekle(lambda: web.sayfa_ogeleri(k), 10)
        # sayfalama (CLI içi): sayfa boyutu 5'e indirilir
        eski = web.SAYFA_BOYUTU
        web.SAYFA_BOYUTU = 5
        try:
            with api.hedef("sanal"):
                tampon = io.StringIO()
                with contextlib.redirect_stdout(tampon):
                    web.k_web(argparse.Namespace(kimlik=k, desen=None, rol=None, hepsi=False, sayfa=1))
                sayfa1 = tampon.getvalue()
                tampon = io.StringIO()
                with contextlib.redirect_stdout(tampon):
                    web.k_web(argparse.Namespace(kimlik=k, desen=None, rol=None, hepsi=False, sayfa=2))
                sayfa2 = tampon.getvalue()
        finally:
            web.SAYFA_BOYUTU = eski
        kontrol("CLI web --sayfa: 1. sayfa 5 öge + 'devamı: --sayfa 2'; 2. sayfa #6…#10",
                len(re.findall(r"^\s+#\d+ ", sayfa1, re.M)) == 5 and "--sayfa 2" in sayfa1 and
                re.findall(r"^\s+#(\d+) ", sayfa2, re.M)[:5] == ["6", "7", "8", "9", "10"], sayfa1 + sayfa2)
        kod, cikti, hata_ = cli("web", k, "--hepsi")
        kontrol("CLI web --hepsi: görünmeyen (kaydırma dışı) ögeler de, sayfalama yok",
                kod == 0 and "Sayfa sonu düğmesi" in cikti and "(görünmüyor)" in cikti, f"{kod} {cikti[:200]}")
        n0 = tik(k)[1]
        kod, cikti, hata_ = cli("click-element", k, "Yazdır")
        kontrol("CLI click-element (web, yazısız simge düğmesi 'Yazdır' = title)", kod == 0 and
                bekle(lambda: tik(k) == ("Yazdır", n0 + 1), 3), f"{kod} {cikti[:300]} {hata_[-300:]}")
        # tarayıcı arayüzü ögesi (sayfada yok) genel ağaç yoluna düşer: hata iletisi web ipucunu taşır
        kod, cikti, hata_ = cli("click-element", k, "Böyle bir öge yok")
        kontrol("CLI click-element: ne sayfada ne arayüzde → 6 (web ipucu iletide)", kod == 6 and
                "web " in hata_, f"{kod} {hata_[-300:]}")
        kapat(ff, "form (CLI) kapandı")


s._DONGU.temizle()
try:
    asyncio.run(senaryo())

    # ------------------------------------------------------------ `ac --arka` ile açılan Firefox (CLI yolu)
    print("ac --arka (ham komut, yalıtık profil) ile açılan Firefox")
    prof = os.path.join(_yalitim.PAYLASIM, "ac-profil")
    xdg = os.path.join(_yalitim.PAYLASIM, "ac-xdg")
    os.makedirs(prof, mode=0o700)
    os.makedirs(xdg, mode=0o700)
    with open(os.path.join(prof, "user.js"), "w") as f:
        from deskhand.oturum.firefox import _USER_JS
        f.write(_USER_JS)
        for a_, v_ in wt.TEST_PREFS.items():
            f.write(wt._pref(a_, v_))
    kom = (f"XDG_CONFIG_HOME={xdg} XDG_CACHE_HOME={xdg}/c XDG_DATA_HOME={xdg}/d MOZ_LEGACY_PROFILES=1 "
           f"MOZ_CRASHREPORTER_DISABLE=1 exec firefox --profile {prof} --no-remote --new-instance {srv.url('form.html')}")
    kod, cikti, hata_ = cli("ac", "--komut", f"sh -c '{kom}'", "-b", "Mozilla Firefox", sure=90)
    kontrol("ac --arka: Firefox açıldı", kod == 0 and cikti.startswith("arka:"), f"{kod} {cikti[:200]} {hata_[-300:]}")
    kid = cikti.split("|")[0].strip() if kod == 0 else None
    try:
        if kid:
            bekle(lambda: "Form" in (s_au.baslik(kid) or ""), 15)
            agac = bekle(lambda: (lambda o: o if o["toplam"] > 10 and o["sayfa"]["baslik"] else None)(
                web.oku(kid, en_cok=0, gorunur=False)), 15)
            kontrol("ac --arka ile açılan Firefox erişilebilirlik ağacını sunuyor (ek ortam değişkeni olmadan)",
                    bool(agac) and agac["sayfa"]["baslik"] == "Deskhand Form Testi", str(agac and agac["toplam"]))
    finally:
        if kid:
            pid = s_au.pid(kid)
            with contextlib.suppress(Exception):
                s_au.kapat(kid)
            if pid:
                for _i in range(80):
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        break
                    time.sleep(0.1)
                else:
                    with contextlib.suppress(OSError):
                        os.kill(pid, 15)
    profil_denetle("ac --arka Firefox kapandı")
finally:
    kapat_hepsi()
    srv.kapat()

print("kullanıcı Firefox profil kökü (önce/sonra):")
for s_ in bekci.satirlar():
    print("  " + s_)
kontrol("kullanıcı profil kökü DEĞİŞMEDİ (profiles.ini, installs.ini, dizin adları)", not bekci.fark(), str(bekci.fark()))
print(f"\n{gecen}/{toplam} web bağlama testi geçti")
sys.exit(0 if gecen == toplam else 1)
