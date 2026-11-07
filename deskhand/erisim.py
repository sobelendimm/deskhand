"""Erişilebilirlik ağacı (AT-SPI): Qt/GTK düğmeleri AD ve KONUMLA. Komutlar: erisim, agac, ogeye-tikla."""
from __future__ import annotations

import difflib
import re
import subprocess
import time

from .arka_uc import EKRAN, sec
from .eylem import girdi_al, girdi_birak, tikla_ic
from .gunluk import gunluk
from .guvenlik import denetle
from .hata import Dur
from .i18n import _
from .ocr import katla, nokta_metni, norm


def calis(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


ETKILESIMLI = {"push button", "toggle button", "check box", "radio button", "menu item", "check menu item",
               "radio menu item", "link", "page tab", "combo box", "entry", "text", "password text", "spin button",
               "list item", "tree item", "table cell", "slider", "menu", "button", "switch", "toggle switch"}


def _atspi_veri_yolu_saglam():
    """Erişilebilirlik veri yolunun soketine gerçekten bağlanılabiliyor mu? libatspi bağlanamayınca süreci
    abort() ile ÖLDÜRÜYOR (kod -6) — önce biz denetleyip anlaşılır bir hata verelim. → (tamam, ayrıntı)."""
    import socket
    adres = calis("busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress")
    m = re.search(r'unix:path=([^,"]+)', adres or "")
    if not m:
        return False, adres or "org.a11y.Bus yanıt vermedi"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(m.group(1))
        return True, m.group(1)
    except OSError as e:
        return False, f"{m.group(1)}: {e}"
    finally:
        s.close()


def _atspi():
    tamam, ayrinti = _atspi_veri_yolu_saglam()
    if not tamam:
        raise Dur(9, _("erişilebilirlik veri yoluna bağlanılamıyor ({ayrinti}); oturumu yeniden açmak ya da "
                       "at-spi-bus-launcher'ı yeniden başlatmak gerekir").format(ayrinti=ayrinti))
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        return Atspi
    except (ImportError, ValueError) as e:
        raise Dur(9, _("AT-SPI kullanılamıyor (python-gobject + at-spi2-core): {hata}").format(hata=e))


def erisim_acik():
    return calis("busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                 "IsEnabled") == "b true"


def k_erisim(a):
    """Erişilebilirlik veri yolunu aç/kapat (oturum boyunca; çıkışta sıfırlanır). Açıkken Qt/GTK uygulamaları
    düğmelerini AD ve KONUMLA bildirir → ekran agac / ogeye-tikla. Chromium tabanlı tarayıcılar ayrıca
    --force-renderer-accessibility ister."""
    if a.islem in ("ac", "kapat"):
        subprocess.run(["busctl", "--user", "set-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                        "IsEnabled", "b", "true" if a.islem == "ac" else "false"], capture_output=True)
        gunluk(f"erisim | {a.islem}")
        time.sleep(0.3)
    acik = erisim_acik()
    print(_("erişilebilirlik: AÇIK") if acik else _("erişilebilirlik: KAPALI"))
    if acik:
        Atspi = _atspi()
        masa = Atspi.get_desktop(0)
        for i in range(masa.get_child_count()):
            app = masa.get_child_at_index(i)
            if app is not None:
                try:
                    print(_("  {ad} (pid {pid}, {sayi} pencere)").format(
                        ad=app.get_name() or "?", pid=app.get_process_id(), sayi=app.get_child_count()))
                except Exception:
                    pass
        if a.islem == "ac":
            print(_("not: zaten açık uygulamaların bir kısmı ağaca ancak yeniden başlatılınca girer"))


def erisim_penceresi(k):
    """kdotool penceresi → AT-SPI çerçevesi (önce aynı PID'nin pencereleri, başlık benzerliğiyle)."""
    Atspi = _atspi()
    if not erisim_acik():
        raise Dur(1, _("erişilebilirlik kapalı: önce `ekran erisim ac`, sonra uygulamayı yeniden başlat"))
    if k == EKRAN:
        raise Dur(1, _("erişilebilirlik ağacı pencere ister (masaüstü kipi değil)"))
    au = sec()
    pid = au.pid(k) if hasattr(au, "pid") else ""
    b = au.baslik(k)
    adaylar = []
    masa = Atspi.get_desktop(0)
    for i in range(masa.get_child_count()):
        app = masa.get_child_at_index(i)
        if app is None:
            continue
        try:
            ayni = bool(pid) and str(app.get_process_id()) == pid
            cerceveler = [app.get_child_at_index(j) for j in range(app.get_child_count())]
        except Exception:
            continue
        for f in cerceveler:
            if f is None:
                continue
            try:
                ad = f.get_name() or ""
            except Exception:
                continue
            benz = 1.0 if ad and (ad == b or ad in b or b in ad) else difflib.SequenceMatcher(None, katla(ad), katla(b)).ratio()
            adaylar.append((ayni, benz, f))
    ayni_pid = [x for x in adaylar if x[0]]
    if len(ayni_pid) == 1:
        return ayni_pid[0][2]
    secim = sorted(ayni_pid or [x for x in adaylar if x[1] >= 0.9], key=lambda x: -x[1])
    if not secim:
        raise Dur(6, _("pencere erişilebilirlik ağacında yok ({baslik}, pid {pid}): uygulama erişilebilirlik "
                       "açılmadan önce başladıysa yeniden başlat; tarayıcılar --force-renderer-accessibility ister"
                       ).format(baslik=repr(b), pid=pid))
    return secim[0][2]


def erisim_ogeleri(k, en_cok=4000, sure=8.0, cocuk_siniri=400):
    """Penceredeki GÖRÜNEN ögeler: rol, ad, pencere koordinatlı kutu, etkin mi. Wayland'de ekran koordinatı yok →
    çerçeveye göre (WINDOW) konum + pencere dekorasyonu payı (kdotool çerçeve boyutu − AT-SPI çerçeve boyutu)."""
    Atspi = _atspi()
    cerceve = erisim_penceresi(k)
    X, Y, W, H = sec().geometri(k)
    WIN = Atspi.CoordType.WINDOW
    fe = cerceve.get_extents(WIN)
    ox = max(0, round((W - fe.width) / 2)) if W > fe.width else 0
    oy = max(0, H - fe.height - ox) if H > fe.height else 0
    S = Atspi.StateType
    t0 = time.monotonic()
    sonuc, yigin, sayi = [], [(cerceve, 0)], 0
    while yigin and sayi < en_cok and time.monotonic() - t0 < sure:
        o, d = yigin.pop()
        sayi += 1
        try:
            ss = o.get_state_set()
            if d > 0 and not ss.contains(S.SHOWING):
                continue  # görünmeyen dal (kapalı menü, gizli sekme)
            rol, ad = o.get_role_name(), (o.get_name() or "").strip()
            n = min(o.get_child_count(), cocuk_siniri)
        except Exception:
            continue
        try:
            e = o.get_extents(WIN)
            kutu_ = (e.x - fe.x + ox, e.y - fe.y + oy, e.width, e.height)
        except Exception:
            kutu_ = None
        if d > 0 and kutu_ and kutu_[2] > 0 and kutu_[3] > 0:
            sonuc.append({"rol": rol, "ad": ad, "x": kutu_[0], "y": kutu_[1], "w": kutu_[2], "h": kutu_[3],
                          "cx": kutu_[0] + kutu_[2] / 2, "cy": kutu_[1] + kutu_[3] / 2,
                          "etkin": ss.contains(S.ENABLED) and ss.contains(S.SENSITIVE), "derinlik": d})
        for i in range(n - 1, -1, -1):
            try:
                c = o.get_child_at_index(i)
            except Exception:
                c = None
            if c is not None:
                yigin.append((c, d + 1))
    return [o for o in sonuc if 0 <= o["cx"] < W and 0 <= o["cy"] < H], time.monotonic() - t0


def erisim_ara(ogeler, ad, rol=None):
    """Ada göre: tam (Türkçe harf/büyük-küçük duyarsız) > içerir > benzer (≥0,85). Yalnız en iyi kademe döner."""
    q = norm(ad)
    aday = [o for o in ogeler if o["ad"] and (not rol or rol.lower() in o["rol"])]
    tam = [o for o in aday if norm(o["ad"]) == q]
    if tam:
        return tam, "tam"
    icerir = [o for o in aday if len(q) > 3 and q in norm(o["ad"])]
    if icerir:
        return icerir, "içerir"
    benzer = [o for o in aday if len(q) > 4 and difflib.SequenceMatcher(None, norm(o["ad"]), q).ratio() >= 0.85]
    return benzer, "benzer"


def oge_yaz(o, no=None):
    on = f"#{no} " if no else ""
    durum = "" if o["etkin"] else " [devre dışı]"
    print(f"  {on}({o['cx']:.0f},{o['cy']:.0f}) {o['rol']}: {o['ad'] or '(adsız)'}{durum}  {o['w']}x{o['h']}")


def k_agac(a):
    ogeler, sure = erisim_ogeleri(a.kimlik)
    if a.desen:
        bulunan, kademe = erisim_ara(ogeler, a.desen, a.rol)
        print(_("# '{desen}': {sayi} öge ({kademe} eşleşme, {sn} sn)").format(
            desen=a.desen, sayi=len(bulunan), kademe=kademe, sn=f"{sure:.2f}"))
        for i, o in enumerate(bulunan, 1):
            oge_yaz(o, i)
        if not bulunan:
            raise Dur(6, _("bulunamadı"))
        return
    secili = [o for o in ogeler if (a.hepsi or (o["rol"] in ETKILESIMLI or (o["ad"] and o["rol"] == "label")))
              and (not a.rol or a.rol.lower() in o["rol"])]
    print(_("# {sayi} öge ({gorunen} görünen, {sn} sn); (merkez x,y) rol: ad").format(
        sayi=len(secili), gorunen=len(ogeler), sn=f"{sure:.2f}"))
    for o in secili:
        oge_yaz(o)


def k_ogeye_tikla(a):
    """Erişilebilirlik ağacındaki ögeye ADIYLA tıkla: OCR'ın okuyamadığı düğmeler (renkli/orta ton zemin) dahil.
    Tıklama gerçek fare girdisidir; tüm denetimler (pencere, başlık, yasak, hassas düğme, insan önceliği) aynen."""
    g = girdi_al(f"ogeye-tikla '{a.ad}' {a.dugme}")
    try:
        sec().one_getir(a.kimlik)
        denetle(a.kimlik, a.baslik)
        ogeler, sure = erisim_ogeleri(a.kimlik)
        bulunan, kademe = erisim_ara(ogeler, a.ad, a.rol)
        if not bulunan:
            raise Dur(6, _("'{ad}' erişilebilirlik ağacında yok ({sayi} öge, {sn} sn). İpucu: `ekran agac {kimlik}`"
                           ).format(ad=a.ad, sayi=len(ogeler), sn=f"{sure:.2f}", kimlik=a.kimlik))
        if a.sira is None and len(bulunan) > 1:
            print(_("# '{ad}' için {sayi} öge:").format(ad=a.ad, sayi=len(bulunan)))
            for i, o in enumerate(bulunan, 1):
                oge_yaz(o, i)
            raise Dur(5, _("birden çok öge; --sira N ile seç"))
        sira = a.sira or 1
        if not 1 <= sira <= len(bulunan):
            raise Dur(1, _("--sira 1..{en_cok} olmalı").format(en_cok=len(bulunan)))
        o = bulunan[sira - 1]
        if not o["etkin"]:
            raise Dur(6, _("'{ad}' devre dışı (tıklanamaz)").format(ad=o["ad"]))
        # öge bulunduktan SONRA tek onay: istek ögenin adını, noktadaki yazıyı ve çevresinin görüntüsünü taşır
        from .eylem import hassas_nokta
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), o["cx"], o["cy"],
                     nokta_metni(a.kimlik, o["cx"], o["cy"]), ek_metinler=(a.ad, o["ad"]))
        print(_("bulundu: {rol} '{ad}' ({x},{y}) {kademe} eşleşme, {sn} sn").format(
            rol=o["rol"], ad=o["ad"], x=f"{o['cx']:.0f}", y=f"{o['cy']:.0f}", kademe=kademe, sn=f"{sure:.2f}"))
        tikla_ic(g, a.kimlik, a.baslik, o["cx"], o["cy"], a.dugme, sec().geometri(a.kimlik))
    finally:
        girdi_birak(g)
