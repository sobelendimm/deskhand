"""KWin görünmez masaüstü + XWayland (Firefox): klavye yolunda karakter kaybı (K1) regresyon testi.

Kök neden: tr düzeninde `$` ve `€` hem AltGr+4 / AltGr+E'de hem de değiştiricisiz KEY_DOLLAR / KEY_EURO "inet" tuşlarında
(xkb kodu 442/443) durur. deskhand-eis "en az değiştirici" kuralıyla yüksek tuşu seçiyordu; X11 tuş kodu 255'i aşamadığı
için XWayland istemcisine (Firefox) HİÇBİR şey ulaşmıyor, araç yine "yazıldı" diyordu.

1. Birim (EIS'siz): `deskhand-eis --harita-sina` + xkbcli ile derlenen tr haritası → tüm yazdırılabilir ASCII + € ₺ X11'de
   var olan tuşa (evdev ≤ 247) eşlenir; `$` = AltGr+4, `€` = AltGr+E.
2. Canlı (yalıtık KWin + gerçek Firefox, geçici profil): yardımcının `plan` yanıtı (oturumun gerçek EIS haritası) aynı
   kuralı sağlar; ASCII 33-126 + € ₺ Firefox giriş alanına yazılır ve AT-SPI'den geri okunur → birebir.
Kullanıcının ekranına girdi gitmez. KWin < 6.8, yardımcı, firefox ya da xkbcli yoksa ilgili bölüm atlanır.

Çalıştır:  python3 tests/test_kwin_firefox_yazi.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import atexit
import os
import shutil
import subprocess
import sys
import time

os.environ["DESKHAND_ARKA_TUR"] = "kwin"
from deskhand import api, masaustu, web, yollar  # noqa: E402

gecen = toplam = 0
X11_AZAMI = 255 - 8
METIN = "".join(chr(c) for c in range(33, 127)) + "€₺"


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def plan_coz(satirlar):
    """'U+0024 5 2' / 'U+0024:5:2' → {karakter: (kod, mod) | None}"""
    sonuc = {}
    for p in satirlar:
        p = p.replace(":", " ").split()
        ch = chr(int(p[0][2:], 16))
        sonuc[ch] = None if p[1] in ("-", "yazilamaz") else (int(p[1]), int(p[2]))
    return sonuc


def plan_denetle(etiket, plan):
    eksik = [c for c in METIN if plan.get(c) is None]
    kontrol(f"{etiket}: tüm ASCII 33-126 + € ₺ yazılabilir", not eksik, repr(eksik))
    yuksek = {c: v for c, v in plan.items() if v and v[0] > X11_AZAMI}
    kontrol(f"{etiket}: hiçbir karakter X11 dışı tuşa (evdev > 247) eşlenmez", not yuksek, repr(yuksek))
    kontrol(f"{etiket}: $ = AltGr+4, € = AltGr+E, # = AltGr+3 (tr)",
            plan.get("$") == (5, 2) and plan.get("€") == (18, 2) and plan.get("#") == (4, 2),
            f"$={plan.get('$')} €={plan.get('€')} #={plan.get('#')}")


# ---------------------------------------------------------------- 1) birim: --harita-sina
eis = yollar.eis_bin()
if not eis or not shutil.which("xkbcli"):
    print("atlandı (birim): deskhand-eis ya da xkbcli yok")
else:
    harita = os.path.join(_yalitim.GECICI, "tr.xkb")
    with open(harita, "w") as f:
        f.write(subprocess.run(["xkbcli", "compile-keymap", "--layout", "tr"], capture_output=True, text=True,
                               check=True).stdout)
    r = subprocess.run([eis, "--harita-sina", harita, METIN], capture_output=True, text=True, timeout=10)
    kontrol("birim: --harita-sina çalışır (EIS'siz)", r.returncode == 0, r.stderr[-300:])
    if r.returncode == 0:
        plan_denetle("birim (tr haritası)", plan_coz(r.stdout.splitlines()))


# ---------------------------------------------------------------- 2) canlı: yalıtık KWin + gerçek Firefox
def canli():
    from deskhand import kwin_oturum
    ok, neden = kwin_oturum.kullanilabilir() if hasattr(kwin_oturum, "kullanilabilir") else (True, "")
    if not shutil.which("firefox") or not ok:
        print(f"atlandı (canlı): firefox ya da KWin oturumu yok {neden}")
        return
    sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
    import web_tarayici as wt
    from deskhand.arka_uc import sec
    bekci = wt.ProfilBekcisi()
    masaustu.masaustu_baslat("1280x800")
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
    if getattr(au, "tur", "") != "kwin":
        print(f"atlandı (canlı): arka uç türü {getattr(au, 'tur', '?')}")
        kapat()
        return
    try:
        parcalar = [au.eis_satir("plan " + METIN[i:i + 16]) for i in range(0, len(METIN), 16)]  # "tamam" sonrası
    except Exception as e:  # noqa: BLE001 - eski yardımcı: 'plan' yok (Firefox bölümü yine koşar)
        print(f"plan sorgusu başarısız: {e}")
        parcalar = []
    plan = plan_coz(" ".join(parcalar).split())
    kontrol("canlı: yardımcı 'plan' yanıtı her karakter için", set(plan) == set(METIN), " ".join(parcalar)[:200])
    plan_denetle("canlı (oturumun EIS haritası)", plan)
    srv = wt.Sunucu()
    try:
        ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("yazi_alani.html"))
        acik.append(ff)
        k = ff.k
        bitis = time.monotonic() + 20
        while time.monotonic() < bitis and "Yazi Testi" not in (au.baslik(k) or ""):
            time.sleep(0.2)
        time.sleep(1.0)
        deger = None
        for tur_ in range(2):  # ilk deneme odak/yükleme yarışında boşa gidebilir: alanı temizleyip bir kez daha
            with api.hedef("sanal"):  # YALNIZ görünmez masaüstü (kullanıcının ekranı değil)
                api.ogeye_tikla(k, "Yazı alanı")
                api.tus(k, "ctrl+a")
                api.tus(k, "BackSpace")
                api.yaz(k, METIN)
            bitis = time.monotonic() + 5
            while time.monotonic() < bitis:
                try:
                    ogeler = {o["ad"]: o for o in web.oku(k, gorunur=False, en_cok=0)["ogeler"]}
                    deger = (ogeler.get("Yazı alanı") or {}).get("deger")
                except Exception:  # noqa: BLE001
                    deger = None
                if deger and len(deger) >= len(METIN):
                    break
                time.sleep(0.2)
            if deger == METIN:
                break
        eksik = sorted(set(METIN) - set(deger or ""))
        kontrol("canlı: Firefox (XWayland) ASCII 33-126 + € ₺ birebir yazıldı (# $ € kaybolmaz)", deger == METIN,
                f"eksik={eksik!r} okunan={deger!r}")
        f = bekci.fark()
        kontrol("canlı: kullanıcının Firefox profil kökü değişmedi", not f, str(f))
    finally:
        srv.kapat()
        kapat()


canli()
print(f"\n{gecen}/{toplam} geçti")
raise SystemExit(0 if gecen == toplam else 1)
