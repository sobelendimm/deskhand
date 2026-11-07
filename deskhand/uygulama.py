"""Uygulama başlatma: .desktop girdileri, ad ile bulma, başlat → YENİ penceresini bekle. Komut: ac."""
from __future__ import annotations

import inspect
import os
import re
import sys
import time

from . import yollar
from .arka_uc import sec
from .gunluk import gunluk
from .guvenlik import baslatma_yasak_denetle
from .hata import Dur
from .i18n import _
from .ocr import norm

UYGULAMA_DIZINLERI = (os.path.expanduser("~/.local/share/applications"), "/usr/local/share/applications",
                      "/usr/share/applications", os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
                      "/var/lib/flatpak/exports/share/applications")


def masaustu_girdileri():
    """Başlatılabilir .desktop girdileri; kullanıcınınki (önce gelen) aynı kimlikli sistem girdisini örter."""
    sonuc, gorulen = [], set()
    for d in UYGULAMA_DIZINLERI:
        for kok, _, dosyalar in os.walk(d):
            for f in sorted(dosyalar):
                if not f.endswith(".desktop"):
                    continue
                yol = os.path.join(kok, f)
                kimlik = os.path.relpath(yol, d).replace("/", "-")
                if kimlik in gorulen:
                    continue
                gorulen.add(kimlik)
                alan, bolum = {}, None
                try:
                    with open(yol, errors="replace") as fp:
                        for l in fp:
                            l = l.strip()
                            if l.startswith("["):
                                bolum = l
                            elif bolum == "[Desktop Entry]" and "=" in l:
                                anahtar, deger = l.split("=", 1)
                                alan.setdefault(anahtar.strip(), deger.strip())
                except OSError:
                    continue
                if alan.get("Type", "Application") != "Application" or alan.get("Hidden") == "true":
                    continue
                sonuc.append({"yol": yol, "kimlik": kimlik[:-8], "ad": alan.get("Name[tr]") or alan.get("Name", ""),
                              "ad_en": alan.get("Name", ""), "exec": alan.get("Exec", ""),
                              "gizli": alan.get("NoDisplay") == "true"})
    return sonuc


def _girdi_adlari(g):
    return {norm(g["kimlik"]), norm(g["kimlik"].split(".")[-1]), norm(g["ad"]), norm(g["ad_en"])} - {""}


def uygulama_adaylari(ad, girdiler=None):
    """uygulama_bul'un seçeceği grup: tam eşleşenler, yoksa kısmi eşleşenler (gizli olmayanlar öncelikli).
    Tek öğe = uygulama_bul bunu başlatır; birden çok = belirsiz (uygulama_bul 5 verir); boş = bulunamadı.
    Oturum politikası (oturum.cozum) aynı eşlemeyi kullanır ki karar başlatılacak uygulamadan hesaplansın."""
    q = norm(ad or "")
    if not q:
        return []
    girdiler = masaustu_girdileri() if girdiler is None else girdiler
    tam = [g for g in girdiler if q in _girdi_adlari(g)]
    kismi = [g for g in girdiler if g not in tam and any(q in x for x in _girdi_adlari(g))]
    for grup in (tam, kismi):
        if grup:
            return [g for g in grup if not g["gizli"]] or grup
    return []


def uygulama_bul(ad):
    if not norm(ad or ""):
        raise Dur(1, _("uygulama adı boş"))
    gorunur = uygulama_adaylari(ad)
    if len(gorunur) == 1:
        return gorunur[0]
    if len(gorunur) > 1:
        liste = "\n".join(f"  {g['kimlik']} | {g['ad']} | {g['exec']}" for g in gorunur[:15])
        raise Dur(5, _("'{ad}' {sayi} uygulamaya uyuyor; tam adını ya da kimliğini ver:\n{liste}").format(
            ad=ad, sayi=len(gorunur), liste=liste))
    raise Dur(6, _("'{ad}' adlı uygulama bulunamadı (.desktop); komutla başlatmak için: ekran ac --komut \"…\""
                   ).format(ad=ad))


def tum_pencereler():
    au = sec()
    kimlikler = getattr(au, "kimlikler", None)  # ucuz liste (kde); yoksa tam liste
    return set(kimlikler()) if kimlikler else {w for w, _, _ in au.pencereler()}


def _baslat(au, komut, fp, env=None):
    """Arka ucun oturumunda başlat; arka uç çıktı dosyası destekliyorsa stdout/stderr oraya."""
    if "cikti" in inspect.signature(au.baslat).parameters:
        return au.baslat(komut, env=env, cikti=fp)
    return au.baslat(komut, env=env)


def oturum_hazirla(uygulama, siteler=None, ham_komut=False):
    """Görünmez masaüstünde açılacak uygulama için oturum politikası (docs: oturum.toml). Politika ÇÖZÜLMÜŞ
    uygulamadan hesaplanır (oturum.hazirla: .desktop kimliği, Exec ikilisi, Flatpak kimliği, kısmi ad, yol).
    ham_komut: `ac --komut` satırının ilk öğesi (bilinen bir uygulamaya uymuyorsa olduğu gibi çalışır).
    → (komut veya None, ek ortam, not). Açılamıyorsa Dur: kapali → 10, bekle/on → 16."""
    from . import oturum
    from .hata import OTURUM_POLITIKASI
    h = oturum.hazirla(uygulama, siteler or None, ham_komut=ham_komut)
    if h.karar == "kapali":
        raise Dur(10, _("{uygulama}: oturum politikası 'kapali'").format(uygulama=uygulama)
                  + (f" ({h.aciklama})" if h.aciklama else ""))
    if h.karar in ("bekle", "on"):
        raise Dur(OTURUM_POLITIKASI, h.aciklama or _("{uygulama} arka planda açılamaz ({karar})").format(
            uygulama=uygulama, karar=h.karar))
    if h.karar == "kopya":
        oturum.parmak_kaydet(h.kopya_yolu)
    return (list(h.argv) or None), dict(h.env_ek or {}), (_("oturum: {karar}").format(karar=h.karar)
                                                          + (f" ({h.aciklama})" if h.aciklama else ""))


def k_ac(a):
    """Uygulamayı başlat, YENİ penceresini bekle, kimliğini yaz. -b/-s verilirse ona uyan pencere beklenir
    (açılış ekranı / Steam ara pencereleri atlanır). Tek örnekli uygulama yeni pencere açmayıp mevcut
    penceresini öne getirirse o döner."""
    import shlex
    if a.komut_satiri:
        komut, ad = shlex.split(a.komut_satiri), a.komut_satiri
        baslatma_yasak_denetle(a.komut_satiri)
    elif a.uygulama:
        g = uygulama_bul(a.uygulama)
        baslatma_yasak_denetle(g["ad"], g["ad_en"], g["exec"], g["kimlik"])
        komut, ad = ["gio", "launch", g["yol"]], f"{g['ad']} ({g['kimlik']})"
    else:
        raise Dur(1, _("uygulama adı ya da --komut gerekli"))
    au = sec()
    env = None
    if au.ad == "sanal" and a.uygulama and not a.komut_satiri:
        yeni, env, notu = oturum_hazirla(a.uygulama, getattr(a, "site", None))
        if yeni:
            komut = yeni
        print(notu, file=sys.stderr)
    elif au.ad == "sanal" and a.komut_satiri and komut:
        # ham komut da politikadan geçer: /usr/bin/telegram-desktop, flatpak run org.telegram.desktop … (bilinen
        # uygulamaya uymayan komut olduğu gibi çalışır: test pencereleri vb.)
        from .oturum.cozum import _flatpak_kimligi
        fk = _flatpak_kimligi(komut)[0]
        _yeni, env_ek, notu = oturum_hazirla(fk or komut[0], None, ham_komut=True)
        env = env_ek or None
        if fk:  # flatpak run kendi scope'una geçer: kayıt + bellek sınırı + kapanışta kapatma için sarmala
            from . import oturum
            komut = oturum._flatpak_sarmala(komut, fk, None)
        print(notu, file=sys.stderr)
    once, onceki_aktif = tum_pencereler(), au.aktif()
    os.makedirs(yollar.cikti(), exist_ok=True)
    log = os.path.join(yollar.cikti(), f"ac-{time.strftime('%H%M%S')}-{os.getpid()}.log")
    with open(log, "w") as fp:
        _baslat(au, komut, fp, env)
    gunluk(f"ac | {ad} | {' '.join(komut)}")
    print(_("başlatıldı: {ad}").format(ad=ad), file=sys.stderr)
    t0 = time.monotonic()
    gorulen = {}

    def uyar(b, s):
        return (not a.baslik or re.search(a.baslik, b, re.I)) and (not a.sinif or re.search(a.sinif, s, re.I))
    while time.monotonic() - t0 < a.sure:
        time.sleep(0.25)
        for w in tum_pencereler() - once:
            b, s = au.baslik(w), au.sinif(w)
            if b or s:
                gorulen[w] = (b, s)
        uygun = [w for w, (b, s) in gorulen.items() if uyar(b, s)]
        if uygun:
            w = uygun[0]
            b, s = gorulen[w]
            print(f"{w} | {b} | {s} | " + _("açıldı ({sn} sn)").format(sn=f"{time.monotonic() - t0:.1f}"))
            return
        ak = au.aktif()
        if (a.baslik or a.sinif) and ak and ak != onceki_aktif and ak in once and \
                uyar(au.baslik(ak), au.sinif(ak)):
            print(f"{ak} | {au.baslik(ak)} | {au.sinif(ak)} | "
                  + _("zaten açıktı, öne geldi ({sn} sn)").format(sn=f"{time.monotonic() - t0:.1f}"))
            return
    diger = "; ".join(f"{w} {b!r} [{s}]" for w, (b, s) in gorulen.items())
    raise Dur(7, _("{sn} sn içinde uygun pencere açılmadı").format(sn=f"{a.sure:.0f}")
              + (_("; açılan başka pencereler: {pencereler}").format(pencereler=diger) if diger else
                 _("; çıktı: {log}").format(log=log)))
