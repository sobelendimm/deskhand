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
from .guvenlik import baslatma_komut_engel, baslatma_yasak_denetle
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


# ---------------------------------------------------------------- Chromium/Electron: erişilebilirlik bayrağı

# Chromium tabanlı uygulamalar erişilebilirlik ağacını yalnız bu bayrakla (ya da bir ekran okuyucu algılarsa) kurar;
# Qt/GTK'nin aksine veri yolundaki IsEnabled'a bakmazlar. Görünmez masaüstünde başlatılanlara eklenir (agac/ogeye-tikla).
ERISIM_BAYRAGI = "--force-renderer-accessibility"
CHROMIUM_IKILILERI = {
    "chromium", "chromium-browser", "ungoogled-chromium", "google-chrome", "google-chrome-stable", "google-chrome-beta",
    "google-chrome-unstable", "chrome", "brave", "brave-browser", "brave-browser-stable", "vivaldi", "vivaldi-stable",
    "vivaldi-snapshot", "microsoft-edge", "microsoft-edge-stable", "opera", "thorium-browser",
    "code", "code-oss", "codium", "vscodium", "cursor", "discord", "vesktop", "slack", "signal-desktop", "obsidian",
    "spotify", "teams-for-linux", "ferdium", "element-desktop", "bitwarden", "postman", "insomnia", "typora",
    "mattermost-desktop", "joplin-desktop", "figma-linux", "notion-app",
}
CHROMIUM_FLATPAKLARI = {
    "com.discordapp.Discord", "com.spotify.Client", "com.visualstudio.code", "com.visualstudio.code-oss",
    "md.obsidian.Obsidian", "org.ferdium.Ferdium", "com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser",
    "com.vivaldi.Vivaldi", "com.microsoft.Edge", "com.slack.Slack", "org.signal.Signal", "io.element.Element",
    "com.github.IsmaelMartinez.teams_for_linux", "com.bitwarden.desktop", "com.getpostman.Postman",
    "dev.vencord.Vesktop", "com.vscodium.codium", "com.opera.Opera",
}


def _asil_komut(argv):
    """Sarmalayıcıları at: Deskhand'in Flatpak sarmalayıcısı (`python flatpak_ornek.py … -- komut`), env/nice/…"""
    from .oturum.cozum import _sarmalayicilari_at
    argv = list(argv)
    if "--" in argv[:16] and any(os.path.basename(x) == "flatpak_ornek.py" for x in argv[:4]):
        argv = argv[argv.index("--") + 1:]
    return _sarmalayicilari_at(argv)


def chromium_ailesi_mi(argv):
    """Komut Chromium/Electron ailesinden mi? Küçük bilinen liste (ikili adı, Flatpak kimliği) + yolunda "electron"
    geçenler. Yalnız ilk program ve Flatpak kimliğine bakılır (argümanlar değil)."""
    from .oturum.cozum import _flatpak_kimligi
    asil = _asil_komut(argv)
    if not asil:
        return False
    kimlik = _flatpak_kimligi(asil)[0]
    if kimlik:
        return kimlik in CHROMIUM_FLATPAKLARI
    yol = asil[0].lower()
    ad = os.path.basename(yol)
    return ad in CHROMIUM_IKILILERI or "electron" in yol


def _desktop_exec(yol):
    """.desktop dosyasının alan kodsuz Exec'i (argv); okunamazsa []."""
    from .oturum.cozum import exec_argv
    bolum = None
    try:
        with open(yol, errors="replace") as fp:
            for satir in fp:
                satir = satir.strip()
                if satir.startswith("["):
                    bolum = satir
                elif bolum == "[Desktop Entry]" and satir.startswith("Exec="):
                    return exec_argv(satir[5:])
    except OSError:
        pass
    return []


def erisim_bayragi_ekle(argv):
    """Chromium/Electron ailesi uygulamanın komutuna --force-renderer-accessibility ekle (aksi halde aynen döner).
    `gio launch X.desktop` bayrak alamaz: aileden ise .desktop'un Exec'i doğrudan çalıştırılır. Flatpak'ta bayrak
    uygulama kimliğinden SONRA gelir (flatpak run bunu uygulamaya iletir) ve Deskhand'in Flatpak sarmalayıcısının sonunda."""
    argv = list(argv)
    if ERISIM_BAYRAGI in argv:
        return argv
    if len(argv) == 3 and os.path.basename(argv[0]) == "gio" and argv[1] == "launch" and argv[2].endswith(".desktop"):
        komut = _desktop_exec(argv[2])
        return [*komut, ERISIM_BAYRAGI] if komut and chromium_ailesi_mi(komut) else argv
    return [*argv, ERISIM_BAYRAGI] if chromium_ailesi_mi(argv) else argv


def tum_pencereler():
    au = sec()
    kimlikler = getattr(au, "kimlikler", None)  # ucuz liste (kde); yoksa tam liste
    return set(kimlikler()) if kimlikler else {w for w, _, _ in au.pencereler()}


def _baslat(au, komut, fp, env=None, kopya=None):
    """Arka ucun oturumunda başlat; arka uç çıktı dosyası destekliyorsa stdout/stderr oraya. kopya: oturum
    politikasının kopyası (yalnız arka plan arka uçları alır; ad alanına yalnız o bağlanır)."""
    p = inspect.signature(au.baslat).parameters
    ek = {"kopya": kopya} if kopya and "kopya" in p else {}
    if "cikti" in p:
        return au.baslat(komut, env=env, cikti=fp, **ek)
    return au.baslat(komut, env=env, **ek)


def oturum_hazirla(uygulama, siteler=None, ham_komut=False):
    """Görünmez masaüstünde açılacak uygulama için oturum politikası (docs: oturum.toml). Politika ÇÖZÜLMÜŞ
    uygulamadan hesaplanır (oturum.hazirla: .desktop kimliği, Exec ikilisi, Flatpak kimliği, kısmi ad, yol).
    ham_komut: `ac --komut` satırının ilk öğesi (bilinen bir uygulamaya uymuyorsa olduğu gibi çalışır).
    → (komut veya None, ek ortam, not, kopya yolu veya None). Açılamıyorsa Dur: kapali → 10, bekle/on → 16."""
    from . import oturum
    from .hata import OTURUM_POLITIKASI
    h = oturum.hazirla(uygulama, siteler or None, ham_komut=ham_komut)
    if h.karar == "kapali":
        raise Dur(10, _("{uygulama}: oturum politikası 'kapali'").format(uygulama=uygulama)
                  + (f" ({h.aciklama})" if h.aciklama else ""))
    if h.karar in ("bekle", "on"):
        raise Dur(OTURUM_POLITIKASI, h.aciklama or _("{uygulama} arka planda açılamaz ({karar})").format(
            uygulama=uygulama, karar=h.karar))
    kopya = h.kopya_yolu if h.karar == "kopya" else None
    if kopya:
        oturum.parmak_kaydet(kopya)
    return (list(h.argv) or None), dict(h.env_ek or {}), (_("oturum: {karar}").format(karar=h.karar)
                                                          + (f" ({h.aciklama})" if h.aciklama else "")), kopya


def k_ac(a):
    """Uygulamayı başlat, YENİ penceresini bekle, kimliğini yaz. -b/-s verilirse ona uyan pencere beklenir
    (açılış ekranı / Steam ara pencereleri atlanır). Tek örnekli uygulama yeni pencere açmayıp mevcut
    penceresini öne getirirse o döner."""
    import shlex
    if a.komut_satiri:
        komut, ad = shlex.split(a.komut_satiri), a.komut_satiri
        baslatma_yasak_denetle(a.komut_satiri)
        baslatma_komut_engel(a.komut_satiri, getattr(a, "onayli", False))  # rm -r / sudo / curl | sh…: insan onayı
    elif a.uygulama:
        g = uygulama_bul(a.uygulama)
        baslatma_yasak_denetle(g["ad"], g["ad_en"], g["exec"], g["kimlik"])
        komut, ad = ["gio", "launch", g["yol"]], f"{g['ad']} ({g['kimlik']})"
    else:
        raise Dur(1, _("uygulama adı ya da --komut gerekli"))
    au = sec()
    env = None
    kopya = None
    if au.ad == "sanal" and a.uygulama and not a.komut_satiri:
        yeni, env, notu, kopya = oturum_hazirla(a.uygulama, getattr(a, "site", None))
        if yeni:
            komut = yeni
        print(notu, file=sys.stderr)
    elif au.ad == "sanal" and a.komut_satiri and komut:
        # ham komut da politikadan geçer: /usr/bin/telegram-desktop, flatpak run org.telegram.desktop … (bilinen
        # uygulamaya uymayan komut olduğu gibi çalışır: test pencereleri vb.)
        from .oturum.cozum import _flatpak_kimligi
        fk = _flatpak_kimligi(komut)[0]
        _yeni, env_ek, notu, _kopya = oturum_hazirla(fk or komut[0], None, ham_komut=True)
        env = env_ek or None
        if fk:  # flatpak run kendi scope'una geçer: kayıt + bellek sınırı + kapanışta kapatma için sarmala
            from . import oturum
            komut = oturum._flatpak_sarmala(komut, fk, None)
        print(notu, file=sys.stderr)
    if au.ad == "sanal":  # Chromium/Electron ağaca yalnız bu bayrakla girer (agac / ogeye-tikla arka planda çalışsın)
        komut = erisim_bayragi_ekle(komut)
    once, onceki_aktif = tum_pencereler(), au.aktif()
    os.makedirs(yollar.cikti(), exist_ok=True)
    log = os.path.join(yollar.cikti(), f"ac-{time.strftime('%H%M%S')}-{os.getpid()}.log")
    with open(log, "w") as fp:
        _baslat(au, komut, fp, env, kopya)
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
