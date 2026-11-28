"""`deskhand doctor`: kurulum ve oturum sağlığı. SALT OKUNUR: hiçbir şey başlatmaz, açmaz, yazmaz (yalnız `which`,
`--version`, dosya/soket varlığı, D-Bus'ta ad sahibi sorgusu, durum dosyaları). Bağımlılık denetimleri panelin Sağlık
sekmesiyle ortaktır (gui/saglik.py, Qt'siz); buradaki satırlar onların üstüne oturum/kurulum durumunu ekler.

Her satır: {ad, durum: "tamam" | "uyari" | "eksik", zorunlu: bool, ayrinti, oneri}. Çıkış kodu: zorunlu bir bağımlılık
eksikse 9 (hata.ARAC_EKSIK), yoksa 0. Uyarılar çıkış kodunu etkilemez."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess

from . import __version__, hata, yollar
from .gui import saglik
from .i18n import _

# install.sh'de "rec": eksikse çalışır (yedek yol / küçük kayıp). Tek dizeden: ham araç taraması (tests/test_mantik.py)
OPSIYONEL = set("spectacle xdotool scipy kwin_wayland".split())
IMGE = {"tamam": "✓", "uyari": "!", "eksik": "✗"}


def _satir(ad, durum, ayrinti, oneri="", zorunlu=False):
    return {"ad": ad, "durum": durum, "zorunlu": bool(zorunlu), "ayrinti": ayrinti, "oneri": oneri}


def _komut_ciktisi(*argv, sure=3.0):
    """Salt okunur sürüm sorgusu: ilk satır, yoksa "". Alt süreç QT_QPA_PLATFORM=offscreen ile çalışır (yalnız onda):
    ekransız ortamda `plasmashell --version` Qt platform eklentisi bulamayıp SIGABRT ile çöküyor ve coredump bırakıyor."""
    if not shutil.which(argv[0]):
        return ""
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=sure,
                           env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    except (OSError, subprocess.SubprocessError):
        return ""
    satirlar = (r.stdout or "").strip().splitlines()
    return satirlar[0].strip() if r.returncode == 0 and satirlar else ""


# ---------------------------------------------------------------- bağımlılıklar (Sağlık sekmesiyle ortak)

def _paket(notu: str) -> tuple[str, bool]:
    """Sağlık notundaki "(AUR: kdotool-bin)" / "(tesseract)" → (paket, AUR mu)."""
    m = re.search(r"\((AUR: )?([\w.+-]+)\)", notu or "")
    return (m.group(2), bool(m.group(1))) if m else ("", False)


def bagimlilik_satirlari() -> list[dict]:
    sonuc = []
    for d in saglik.denetle():
        ad = d["ad"]
        zorunlu = ad not in OPSIYONEL
        paket, aur = _paket(_(d["not"]))
        ayrinti = _(d["not"])
        if d["ok"]:
            sonuc.append(_satir(ad, "tamam", ayrinti, zorunlu=zorunlu))
            continue
        oneri = _modul_onerisi(d, (_("AUR paketini kur: {paket}") if aur else _("paketi kur: {paket}")).format(paket=paket) \
            + _dagitim_eki(paket) if paket else _("./install.sh eksikleri listeler"))
        sonuc.append(_satir(ad, "eksik" if zorunlu else "uyari",
                            (_("eksik") if zorunlu else _("eksik (isteğe bağlı)")) + f": {ayrinti}", oneri, zorunlu))
    return sonuc


# ---------------------------------------------------------------- oturum ve kurulum

def satir_surum():
    return _satir(_("Deskhand sürümü"), "tamam", __version__)


def satir_oturum():
    tur = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    masaustu_adi = os.environ.get("XDG_CURRENT_DESKTOP") or "?"
    ayrinti = f"{tur.capitalize() if tur else '?'} ({masaustu_adi})"
    if tur == "wayland" and "KDE" in masaustu_adi.upper():
        return _satir(_("Masaüstü oturumu"), "tamam", ayrinti)
    return _satir(_("Masaüstü oturumu"), "uyari", ayrinti + " — " + _("ön plan (kendi ekranın) yalnız KDE Plasma 6 "
                                                                   "Wayland'de desteklenir; görünmez masaüstü çalışır"),
                  _("Plasma (Wayland) oturumu aç"))


def satir_kwin():
    kwin = _komut_ciktisi("kwin_wayland", "--version") or _komut_ciktisi("kwin_x11", "--version")
    plasma = _komut_ciktisi("plasmashell", "--version")
    parcalar = [p for p in (kwin, plasma) if p]
    if parcalar:
        return _satir(_("KWin / Plasma sürümü"), "tamam", ", ".join(parcalar))
    return _satir(_("KWin / Plasma sürümü"), "uyari", _("sürüm okunamadı (kwin/plasmashell bulunamadı)"))


def satir_gercek_ekran():
    """DESKHAND_GERCEK_EKRAN ayarlıysa bu SÜREÇTE gerçek ekranın kilitli olduğunu gösterir (ayarsızken satır yok)."""
    kip = hata.gercek_ekran_kipi()
    if kip == "acik":
        return None
    if kip == "salt-okuma":
        return _satir(_("Gerçek ekran"), "tamam", _("bu süreçte kapalı: yalnız okuma serbest (ekran görüntüsü, pano) "
                                                    "(DESKHAND_GERCEK_EKRAN=salt-okuma)"))
    return _satir(_("Gerçek ekran"), "tamam", _("bu süreçte kapalı (DESKHAND_GERCEK_EKRAN=kapali)"))


def satir_panel():
    from . import onay
    pid = onay.panel_pid()
    if pid:
        tani = onay.panel_kanal_tanisi()  # 0.9.1: kayıt eskiyse neden açıkça (önceden yalnız "panel teyit etmiyor")
        if tani:
            return _satir(_("Panel"), "uyari", _("çalışıyor (pid {pid}) ama {neden}").format(pid=pid, neden=tani),
                          _("paneli yeniden başlatın (tepsi → Çık, sonra deskhand panel --tepsi)"))
        t = onay.kayit_tazelendi_bilgisi()
        if t:
            import time
            return _satir(_("Panel"), "tamam", _("çalışıyor (pid {pid}); kimlik kaydı {saat}'te kendiliğinden tazelendi "
                                                 "({neden})").format(
                pid=pid, saat=time.strftime("%H:%M", time.localtime(float(t.get("zaman") or 0))), neden=t.get("neden")))
        return _satir(_("Panel"), "tamam", _("çalışıyor (pid {pid})").format(pid=pid))
    return _satir(_("Panel"), "uyari", _("çalışmıyor: hassas eylem onayı ve DUR/Devral düğmeleri yok"),
                  "deskhand panel --tepsi")


def satir_mcp_surecleri():
    """Bu kullanıcının çalışan `deskhand mcp` süreçleri; güncellemeden ÖNCE başlamış olan (eski kod) uyarı verir."""
    import time

    from . import surum
    ss = surum.mcp_surecleri()
    if not ss:
        return _satir(_("MCP sunucuları"), "tamam", _("çalışan yok"))
    parcalar = []
    for p in ss:
        ne = time.strftime("%d.%m %H:%M", time.localtime(p["started"])) if p["started"] else "?"
        surum_m = p["version"] or _("{kurulu} öncesi (eski kod)").format(kurulu=p["installed"] or "?")
        parcalar.append(f"pid {p['pid']} [{p['args']}] {surum_m}, {ne}")
    eski = [p for p in ss if p["stale"]]
    if eski:
        return _satir(_("MCP sunucuları"), "uyari", "; ".join(parcalar),
                      _("{n} sunucu kurulum güncellenmeden önce başlamış: istemcide MCP'yi yeniden bağla (/mcp)")
                      .format(n=len(eski)))
    return _satir(_("MCP sunucuları"), "tamam", "; ".join(parcalar))


def satir_onay_kapsami():
    from . import guvenlik
    kap = guvenlik.onay_kapsami(taze=True)
    if kap == "kart":
        return _satir(_("Onay kapsamı"), "tamam",
                      _("kart: yalnız kartla ödeme (para düğmesi/ödeme sayfası, kart bilgisi yazma) onay ister; "
                        "diğer onaylar kapalı"))
    from . import ayarlar
    try:
        dosyada = ayarlar.al("guvenlik", "onaylar")
    except Exception:  # noqa: BLE001
        dosyada = None
    if dosyada == "kart":  # dosyada kart ama panel teyit etmiyor (kapalı / panel dışında yazılmış)
        return _satir(_("Onay kapsamı"), "uyari",
                      _("hepsi: ayar dosyasında 'kart' var ama panel teyit etmiyor (panel kapalı ya da panel dışında "
                        "yazılmış); tüm onaylar açık"), "deskhand panel")
    return _satir(_("Onay kapsamı"), "tamam", _("hepsi: tüm onaylar açık (varsayılan)"))


def satir_hesap_oturumlari():
    """Hesap oturumu izinleri (panel yetkili; liste_koruma.kimlik_izinleri): Microsoft / Google / e-Devlet açık-kapalı
    + son Firefox kopyasının kimlik özeti (yalnız bilgi; oturum/firefox.kimlik_son_oku)."""
    from . import liste_koruma
    from .oturum.politika import KIMLIK_ADLARI
    try:
        izin = liste_koruma.kimlik_izinleri()
    except Exception:  # noqa: BLE001 - doğrulanamadı: güvenli taraf
        izin = frozenset()
    acik, kapali = _("açık"), _("kapalı")
    metin = ", ".join(f"{KIMLIK_ADLARI[s]} {acik if s in izin else kapali}" for s in liste_koruma.KIMLIK_SAGLAYICILARI)
    try:
        from .oturum import firefox
        son = firefox.kimlik_son_oku()
        son_metin = firefox.kimlik_ozeti_metni(son["ozet"], son.get("gorev", False)) if son else ""
    except Exception:  # noqa: BLE001 - bilgi satırı: okunamazsa yok
        son, son_metin = None, ""
    if son_metin:
        import time
        metin += _(" | son kopya ({saat}): {ozet}").format(saat=time.strftime("%H:%M", time.localtime(son["zaman"])),
                                                          ozet=son_metin)
    try:
        teyitsiz = liste_koruma.kimlik_dosyada() - izin
    except Exception:  # noqa: BLE001
        teyitsiz = frozenset()
    if teyitsiz:  # dosyada açık ama panel teyit etmiyor (kapalı / panel dışında yazılmış): izin YOK
        from . import onay
        tani = onay.panel_kanal_tanisi()
        if tani:  # 0.9.1: neden kayıt eskimesi (panel açık ama doğrulanamıyor): açıkça söyle
            return _satir(_("Hesap oturumları"), "uyari",
                          metin + _(" (ayar dosyasında {saglayici} açık ama panel doğrulanamıyor: {neden}; kimlik "
                                    "çerezleri süzülüyor)").format(
                              saglayici=", ".join(KIMLIK_ADLARI[s] for s in sorted(teyitsiz)), neden=tani),
                          _("paneli yeniden başlatın"))
        return _satir(_("Hesap oturumları"), "uyari",
                      metin + _(" (ayar dosyasında {saglayici} açık ama panel teyit etmiyor: panel kapalı ya da panel "
                                "dışında yazılmış; kimlik çerezleri süzülüyor)").format(
                                    saglayici=", ".join(KIMLIK_ADLARI[s] for s in sorted(teyitsiz))), "deskhand panel")
    return _satir(_("Hesap oturumları"), "tamam", metin)


def satir_kalici_oturum():
    """Persistent background sessions ([oturum] kalici; oturum/kalici.py): per listed site whether a record exists,
    when it was saved and when it expires (never a value); a warning with the reason when the key ring cannot be used
    (locked wallet, no Secret Service). Reads the key ring, never creates a key."""
    import time
    from .oturum import kalici
    from . import ayarlar, liste_koruma
    from .gorev_kipi import site_ayristir_ayrintili
    ad = _("Kalıcı oturumlar")
    siteler = sorted(kalici.ayar_siteleri())  # panel-authoritative (liste_koruma.kalici_siteleri)
    ham = (ayarlar.ham_oku().get("oturum") or {}).get("kalici")
    gecersiz = site_ayristir_ayrintili(ham)[1] if isinstance(ham, str) else []
    try:
        onaysiz = sorted(liste_koruma.kalici_dosyada() - set(siteler))
    except Exception:  # noqa: BLE001 - information only
        onaysiz = []
    ek = ""
    if gecersiz:
        ek += " " + _("(ayar dosyasında geçersiz girdi atlandı: {girdiler})").format(girdiler="; ".join(gecersiz))
    if onaysiz:
        ek += " " + _("(ayar dosyasında var ama panelde onaylı değil, kullanılmıyor: {siteler})").format(
            siteler=", ".join(onaysiz))
    if not siteler:
        return _satir(ad, "uyari" if ek else "tamam", _("kapalı ([oturum] kalici boş)") + ek,
                      "deskhand panel" if onaysiz else "")
    parcalar, neden = [], None
    for s in siteler:
        d = kalici.durum(s, siteler=siteler)
        if d.get("reddedildi"):
            parcalar.append(_("{site}: banka/ödeme/devlet/kimlik alanı, alınmaz").format(site=s))
        elif d.get("neden"):
            neden = d["neden"]
            parcalar.append(_("{site}: okunamadı").format(site=s))
        elif d.get("kayit"):
            gun = max(0, int((time.time() - d["kayit"]) // 86400))
            bitis = time.strftime("%Y-%m-%d", time.localtime(d["bitis"])) if d.get("bitis") else "-"
            parcalar.append(_("{site}: {gun} gün önce kaydedildi, son kullanma {bitis}").format(
                site=s, gun=gun, bitis=bitis))
        else:
            parcalar.append(_("{site}: kayıt yok").format(site=s))
    metin = "; ".join(parcalar)
    if neden:
        from .anahtar_deposu import secili_tur
        oneri = (_("KDE Cüzdanı'nı açın (kilidi açık olmalı)") if secili_tur() == "cuzdan"
                 else _("deskhand secret list ile kasayı denetleyin; gerekirse Ayarlar'dan anahtar deposunu seçin"))
        return _satir(ad, "uyari", _("{neden}: kalıcı oturum bu açılışta kullanılmadı").format(neden=neden) +
                      f" ({metin})" + ek, oneri)
    return _satir(ad, "uyari" if ek else "tamam", metin + ek)


def satir_anahtar_deposu():
    """The selected key store (anahtar_deposu): kasa → systemd-creds present + TPM2 or host key (no D-Bus call);
    cuzdan → the Secret Service answers and the wallet is unlocked. Never reads a value."""
    from . import anahtar_deposu as ad_
    ad = _("Anahtar deposu")
    try:
        d = ad_.secili_depo().durum()
    except Exception as e:  # noqa: BLE001 - information only
        return _satir(ad, "uyari", str(e))
    tur = _(ad_.TUR_ADLARI.get(d.get("tur"), d.get("tur") or "?"))
    if d.get("tur") == "kasa":
        tur += " · " + (_("TPM2 + makine anahtarı") if d.get("tpm") else _("makine anahtarı (TPM2 yok)"))
    if d.get("hazir"):
        return _satir(ad, "tamam", tur)
    oneri = _("KDE Cüzdanı'nı açın ya da Ayarlar'dan Deskhand kasasını seçin") if d.get("tur") == "cuzdan" \
        else _("Ayarlar'dan KDE Cüzdanı'nı seçin")
    return _satir(ad, "uyari", f"{tur}: {d.get('neden')}", oneri)


def satir_girdi_merkezi():
    from . import girdi_merkezi
    yol = girdi_merkezi.soket_yolu()
    try:
        soket_mu = stat.S_ISSOCK(os.stat(yol).st_mode)
    except OSError:
        soket_mu = False
    if soket_mu:
        return _satir(_("Girdi merkezi soketi"), "tamam", _("var (panel hazır girdi sunuyor)"))
    return _satir(_("Girdi merkezi soketi"), "uyari",
                  _("yok: panel kapalıyken her komut kendi girdi sürecini açar (ilk girdi ~0,7 sn gecikir)"),
                  "deskhand panel --tepsi")


def _calistirilabilir(yol):
    return bool(yol) and os.path.isfile(yol) and os.access(yol, os.X_OK)


def satir_yardimcilar():
    """Üç C yardımcısı (deskhand-etkinlik, deskhand-goruntu, deskhand-eis): eksik her biri SONUCUYLA anılır."""
    etkinlik, goruntu, eis = yollar.etkinlik_bin(), yollar.goruntu_bin(), yollar.eis_bin()
    eksik = []
    if not _calistirilabilir(etkinlik):
        eksik.append(_("deskhand-etkinlik yok: insan önceliği yalnız fareye bakar"))
    if not _calistirilabilir(goruntu):
        eksik.append(_("deskhand-goruntu yok: ekran görüntüsü yavaş yedek yolla alınır; KWin arka planı kullanılamaz, "
                       "Xvfb kullanılacak"))
    if not _calistirilabilir(eis):
        eksik.append(_("deskhand-eis yok (libei + libxkbcommon + libsystemd geliştirme dosyaları gerekir): KWin arka "
                       "planı kullanılamaz, Xvfb kullanılacak"))
    if not eksik:
        return _satir(_("C yardımcıları"), "tamam", _("derli (etkinlik, ekran görüntüsü, girdi/EIS)"))
    return _yardimci_satiri(_satir(_("C yardımcıları"), "uyari", _("derli değil: {liste}").format(liste="; ".join(eksik)),
                  _("./install.sh derler (make -C deskhand/yardimci; kitaplıklar kurulunca yeniden çalıştır)")))


def satir_erisim():
    """AT-SPI: önce D-Bus'ta org.a11y.Bus'ın sahibi var mı (NameHasOwner etkinleştirmez); sahibi yoksa özellik
    sorgusu hizmeti BAŞLATIRDI, o yüzden sorulmaz."""
    ad = _("Erişilebilirlik (AT-SPI)")
    sahip = _komut_ciktisi("busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                           "org.freedesktop.DBus", "NameHasOwner", "s", "org.a11y.Bus")
    if sahip != "b true":
        return _satir(ad, "uyari", _("erişilebilirlik veri yolu çalışmıyor (oturumda at-spi yok)"),
                      _("at-spi2-core kur, oturumu yeniden aç"))
    durum = _komut_ciktisi("busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                           "IsEnabled")
    if durum == "b true":
        if os.path.exists(yollar.erisim_isareti()):
            return _satir(ad, "tamam", _("açık (Deskhand açtı; agac / ogeye-tikla çalışır; kapatmak: deskhand a11y off)"))
        return _satir(ad, "tamam", _("açık (agac / ogeye-tikla çalışır)"))
    return _satir(ad, "uyari", _("kapalı: uygulama düğmeleri ad ile bulunamaz (OCR yedekte)"), "deskhand a11y on")


# Tarayıcı ana süreç adları (comm, 15 karakter). Alt süreçler (Firefox "Isolated Web Co", Chromium zygote) ana sürecin
# torunu olarak sayılır: ana süreç = adı listede olup atası listede olmayan.
TARAYICI_SURECLERI = {"firefox", "firefox-bin", "firefox-esr", "librewolf", "floorp", "waterfox", "zen", "zen-bin",
                      "chromium", "chrome", "brave", "vivaldi-bin", "msedge", "opera", "thorium"}


def _a11y_bagli_pidler() -> set[int] | None:
    """Kullanıcı oturumunun erişilebilirlik veri yolundaki bağlantıların PID'leri; veri yolu çalışmıyorsa None.
    Salt okunur: org.a11y.Bus sahibi yoksa hiçbir şey sorulmaz (sorgu hizmeti BAŞLATIRDI)."""
    if _komut_ciktisi("busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                      "org.freedesktop.DBus", "NameHasOwner", "s", "org.a11y.Bus") != "b true":
        return None
    cikti = _komut_ciktisi("busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress")
    m = re.fullmatch(r's "([^"]+)"', cikti)
    if not m:
        return None
    try:
        r = subprocess.run(["busctl", f"--address={m.group(1)}", "list", "--json=short", "--no-pager"],
                           capture_output=True, text=True, timeout=3.0)
        return {int(x["pid"]) for x in json.loads(r.stdout or "[]") if isinstance(x, dict) and x.get("pid")}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def _calisan_tarayicilar(proc: str) -> list[tuple[int, str]]:
    """Kullanıcının GERÇEK oturumunda çalışan tarayıcı ana süreçleri [(pid, ad)]. Görünmez masaüstündekiler (cgroup
    deskhand-sanal-* / deskhand-kwin-*) sayılmaz. Yalnız /proc okunur."""
    from . import kendi
    sonuc = []
    try:
        adlar = [a for a in os.listdir(proc) if a.isdigit()]
    except OSError:
        return []
    for a in adlar:
        st = kendi._stat(a, proc)
        if not st or st[3] not in TARAYICI_SURECLERI:
            continue
        ata = kendi._stat(st[0], proc) if st[0] > 1 else None
        if ata and ata[3] in TARAYICI_SURECLERI:
            continue
        try:
            if os.stat(os.path.join(proc, a)).st_uid != os.getuid():
                continue
            with open(os.path.join(proc, a, "cgroup")) as f:
                if re.search(r"/deskhand-(sanal|kwin)-[^/]*\.scope", f.read()):
                    continue
        except OSError:
            continue
        sonuc.append((int(a), st[3]))
    return sorted(sonuc)


def satir_tarayici_erisim(proc: str | None = None, bagli_pidler=None):
    """Çalışan tarayıcı erişilebilirlik ağacına bağlı mı (web.py _cerceve_bul ile aynı PID kalıbı: bağlantının PID'i
    tarayıcının kendisi ya da torunu). Bağlı değilse kalıcı çözüm ÖNERİLİR; Deskhand ortam/profil dosyası YAZMAZ."""
    from . import kendi
    ad = _("Tarayıcı erişilebilirliği")
    proc = proc or kendi.PROC
    tarayicilar = _calisan_tarayicilar(proc)
    if not tarayicilar:
        return _satir(ad, "tamam", _("çalışan tarayıcı yok"))
    bagli = (bagli_pidler or _a11y_bagli_pidler)() or set()

    def agacta(pid):
        return any(p == pid or any(a_ == pid for a_, _c in kendi.atalar(p, proc)[1:]) for p in bagli)
    eksik = [(p, a) for p, a in tarayicilar if not agacta(p)]
    if not eksik:
        return _satir(ad, "tamam", _("çalışan tarayıcılar erişilebilirlik ağacında"))
    liste = ", ".join(f"{a} (pid {p})" for p, a in eksik)
    return _satir(ad, "uyari", _("erişilebilirlik ağacında olmayan tarayıcı: {liste} (sayfa ögeleri ad ile bulunamaz, "
                                 "OCR yedekte)").format(liste=liste),
                  _("kalıcı çözüm: oturum ortamına GNOME_ACCESSIBILITY=1 ekle (ör. ~/.config/environment.d/"
                    "a11y.conf dosyasına GNOME_ACCESSIBILITY=1 satırı; Chromium için --force-renderer-accessibility) "
                    "ve tarayıcıyı yeniden başlat; Deskhand bu dosyayı kendisi yazmaz"))


def satir_arka_plan():
    from . import masaustu
    ad = _("Arka plan masaüstü")
    d = masaustu.durum()
    if d is None:
        return _satir(ad, "tamam", _("kapalı (gerektiğinde açılır: deskhand desktop start)"))
    b = "x".join(str(v) for v in (d.get("boyut") or [])[:2])
    saglik_ = d.get("saglik") or {}
    bozuk = sorted(a for a, ok in saglik_.items() if not ok)
    if bozuk:
        return _satir(ad, "uyari", _("çalışıyor ({ekran}, {boyut}) ama bileşen yanıt vermiyor: {liste}").format(
            ekran=d.get("ekran", "?"), boyut=b, liste=", ".join(bozuk)),
            _("deskhand desktop stop; deskhand desktop start"))
    return _satir(ad, "tamam", _("çalışıyor ({ekran}, {boyut})").format(ekran=d.get("ekran", "?"), boyut=b))


def satir_calisma_dizini():
    """Deskhand'in çalışma dizini (RUNTIME_DIR): kullanıcıya ait, sembolik bağ olmayan, 0700 olmalı. Gevşek izinli dizin
    sessizce düzeltilmez (arka plan masaüstü Dur 14 verir); burada nedeni ve çaresi görünür. Salt okunur."""
    from . import arka_ortak
    ad = _("Çalışma dizini")
    yol = yollar.runtime_dir()
    neden = arka_ortak.runtime_durumu(yol)
    if neden:
        return _satir(ad, "uyari", neden, _("chmod 700 {yol} (sahibi siz değilseniz dizini silin)").format(yol=yol))
    return _satir(ad, "tamam", _("{yol} (0700)").format(yol=yol) if os.path.isdir(yol) else
                  _("{yol} (henüz yok)").format(yol=yol))


def satir_oturum_kopyalari():
    """Arka plan tarayıcılarının oturum kopyaları (tüm masaüstleri, RUNTIME_DIR tmpfs): sayı + toplam boyut; önce
    sahibi ölmüş ve kimsenin kullanmadığı kopyalar süpürülür (canlı kopyaya dokunulmaz). Geçici alan %90'dan doluysa
    uyarı (22 Kas 2026: kopyalar /run/user/<uid>'i doldurdu, durum dosyaları yazılamadı)."""
    from .oturum import kopya
    ad = _("Oturum kopyaları")
    silinen = kopya.supur()
    sayi, bayt, _olu = kopya.ozet()
    metin = _("{sayi} adet, {mb} MB").format(sayi=sayi, mb=bayt // (1024 * 1024))
    if silinen:
        metin += _(" ({n} sahipsiz kopya silindi)").format(n=len(silinen))
    yol = yollar.runtime_dir()
    try:
        st = os.statvfs(yol if os.path.isdir(yol) else os.path.dirname(yol))
        toplam, bos = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    except OSError:
        toplam = bos = 0
    if toplam:
        metin += _("; geçici alan: {bos} MB boş / {toplam} MB").format(bos=bos // (1024 * 1024),
                                                                       toplam=toplam // (1024 * 1024))
        if bos < toplam * 0.10:
            return _satir(ad, "uyari", metin + _(" (neredeyse dolu)"),
                          _("kullanılmayan arka plan tarayıcılarını kapatın (deskhand masaustu durdur)"))
    return _satir(ad, "tamam", metin)


def satir_arka_tur():
    """Arka plan masaüstü hangi türle açılır (KWin oturumu / Xvfb) ve KWin türünün ön koşulları: ScreenShot2 sanal
    arka uçta /dev/udmabuf okuma-yazma ister (yoksa görüntü alınamaz). Salt okunur; süreç başlatmaz."""
    from . import kwin_oturum
    ad = _("Arka plan masaüstü türü")
    ok, neden = kwin_oturum.kullanilabilir()
    if not ok:
        return _satir(ad, "tamam", _("Xvfb + openbox (KWin oturumu kullanılamıyor: {neden})").format(neden=neden))
    gpu = kwin_oturum.render_sec()
    ayrinti = _("yalıtık KWin oturumu (GPU: {gpu})").format(
        gpu=_("tümleşik {dugum}").format(dugum=gpu["dugum"]) if gpu else _("varsayılan"))
    if not os.access("/dev/udmabuf", os.R_OK | os.W_OK):
        return _satir(ad, "uyari", ayrinti + " — " + _("/dev/udmabuf okunamıyor/yazılamıyor: KWin ekran görüntüsü "
                                                       "alamaz, Xvfb'ye düşülür"),
                      _("kullanıcıya /dev/udmabuf rw izni (ör. kvm grubu ya da udev ACL)"))
    return _satir(ad, "tamam", ayrinti + " · udmabuf rw")


def satir_gpu_ocr():
    from . import ocr_gpu
    ad = _("GPU metin okuma (OCR)")
    eksik = ocr_gpu.eksikler()
    if not eksik:
        return _satir(ad, "tamam", _("kurulu (EasyOCR ekran kartında; tesseract tabanı korunur)"))
    if "gpu" in eksik:  # kart yoksa diğer eksikler anlamsız
        return _satir(ad, "tamam", _("ekran kartı yok: yalnız tesseract kullanılır"))
    neden = {"python": _("EasyOCR/torch yok"), "model": _("modeller indirilmemiş"),
             "hata": _("son açılış başarısız")}
    return _gpu_ocr_satiri(_satir(ad, "uyari", _("kurulu değil: {liste}").format(liste=", ".join(neden.get(e, e) for e in eksik
                                                                             if e != "gpu")),
                  _("./install.sh eksikleri ve kurulum komutlarını listeler")), eksik)


def satir_dinleme():
    """Dinleme (listen): konuşma tanıma motoru + model + özel ses sunucusu araçları. Salt okunur."""
    from . import dinleme, ses
    ad = _("Dinleme")
    eksik = dinleme.eksikler()
    ses_eksik = ses.eksik_araclar()
    if not eksik and not ses_eksik:
        return _satir(ad, "tamam", _("hazır (motor: {motor}, model: {model})").format(
            motor=os.path.basename(dinleme.motor_yolu() or ""), model=os.path.basename(dinleme.model_yolu())))
    if eksik:
        return _satir(ad, "uyari", _("motor yok") + f": {dinleme.ipucu(eksik)}",
                      _("isteğe bağlı: yalnız listen aracı için"))
    return _satir(ad, "uyari", _("özel ses sunucusu için eksik araç: {araclar}").format(araclar=", ".join(ses_eksik)),
                  _("pipewire, wireplumber, pipewire-pulse ve libpulse araçlarını kur"))


SATIRLAR = (satir_surum, satir_gercek_ekran, satir_oturum, satir_kwin, satir_panel, satir_mcp_surecleri, satir_onay_kapsami, satir_hesap_oturumlari, satir_anahtar_deposu, satir_kalici_oturum, satir_girdi_merkezi, satir_yardimcilar,
            satir_erisim, satir_tarayici_erisim, satir_arka_plan, satir_calisma_dizini, satir_oturum_kopyalari, satir_arka_tur, satir_gpu_ocr, satir_dinleme)


def topla() -> list[dict]:
    """Tüm denetimler (bağımlılıklar + ek satırlar). Bir denetim çökerse satırı uyarı olur, doktor çökmez."""
    sonuc = []
    try:
        sonuc += bagimlilik_satirlari()
    except Exception as e:  # noqa: BLE001
        sonuc.append(_satir(_("Bağımlılıklar"), "uyari", _("denetlenemedi: {hata}").format(hata=e)))
    for f in SATIRLAR:
        try:
            satir = f()
            if satir is not None:  # satir_gercek_ekran: ayarsızken satır yok (çıktı öncekiyle aynı)
                sonuc.append(satir)
        except Exception as e:  # noqa: BLE001
            sonuc.append(_satir(f.__name__.removeprefix("satir_"), "uyari", _("denetlenemedi: {hata}").format(hata=e)))
    return sonuc


def ozet(satirlar: list[dict]) -> dict:
    """{"tamam": n, "uyari": n, "eksik": n}; "eksik" yalnız zorunlu bağımlılıklar."""
    return {d: sum(1 for s in satirlar if s["durum"] == d) for d in ("tamam", "uyari", "eksik")}


def metin(satirlar: list[dict]) -> str:
    genislik = max(len(s["ad"]) for s in satirlar)
    cikti = []
    for s in satirlar:
        l = f"{IMGE[s['durum']]} {s['ad']:<{genislik}}  {s['ayrinti']}"
        if s["oneri"] and s["durum"] != "tamam":
            l += f"  → {s['oneri']}"
        cikti.append(l)
    o = ozet(satirlar)
    cikti.append(_("Özet: {tamam} tamam, {uyari} uyarı, {eksik} eksik zorunlu bağımlılık").format(**o))
    return "\n".join(cikti)


def k_doktor(a):
    """Salt okunur sağlık denetimi. Çıkış: zorunlu bağımlılık eksikse 9, yoksa 0 (uyarılar etkilemez)."""
    satirlar = topla()
    o = ozet(satirlar)
    if a.json:
        print(json.dumps({"surum": __version__, "tamam": o["eksik"] == 0, "ozet": o, "denetimler": satirlar},
                         ensure_ascii=False))
    else:
        print(metin(satirlar))
    if o["eksik"]:
        raise SystemExit(hata.ARAC_EKSIK)


# ---------------------------------------------------------------- pip / pipx kurulumu (dosya sonunda: i18n kataloğundaki
# satır numaraları kaymasın, tools/i18n_cikar.py)

# pipx/pip yalnız Python modüllerini getirir; sistem araçları dağıtımdan gelir. Arch adı (sağlık notundaki parantez,
# install.sh ile aynı) → Debian/Ubuntu, Fedora karşılığı. "-" = o dağıtımda paket yok ya da sürümü yetmez (öneride
# anılmaz; uydurma ad yok). Doğrulama 28 Kas 2026: Debian 13 trixie (qa.debian.org madison), Fedora 43 (mdapi).
# Tek dize: ham araç taraması (tests/test_mantik.py) tırnaklı araç adına izin vermez.
_DAGITIM_TABLOSU = """
kdotool-bin          -                      kdotool
dotool               -                      dotool
spectacle            kde-spectacle          spectacle
tesseract            tesseract-ocr          tesseract
tesseract-data-tur   tesseract-ocr-tur      tesseract-langpack-tur
tesseract-data-eng   tesseract-ocr-eng      tesseract-langpack-eng
xorg-server-xvfb     xvfb                   xorg-x11-server-Xvfb
xdotool              xdotool                xdotool
openbox              openbox                openbox
bubblewrap           bubblewrap             bubblewrap
kwin                 kwin-wayland           kwin
libei                libei-dev              libei-devel
python-pyqt6         python3-pyqt6          python3-pyqt6
python-xlib          python3-xlib           python3-xlib
python-numpy         python3-numpy          python3-numpy
python-scipy         python3-scipy          python3-scipy
python-pillow        python3-pil            python3-pillow
python-jeepney       python3-jeepney        python3-jeepney
python-secretstorage python3-secretstorage  python3-secretstorage
python-cryptography  python3-cryptography   python3-cryptography
python-mcp           -                      -
"""
DAGITIM_PAKETLERI = {s[0]: (s[1], s[2]) for s in (x.split() for x in _DAGITIM_TABLOSU.strip().splitlines())}


def _dagitim_eki(paket: str) -> str:
    """" · Debian/Ubuntu: x · Fedora: y" (bilinen karşılıklar; yoksa "")."""
    deb, fed = DAGITIM_PAKETLERI.get(paket, ("-", "-"))
    return "".join(f" · {d}: {p}" for d, p in (("Debian/Ubuntu", deb), ("Fedora", fed)) if p != "-")


def _kaynak_kurulumu() -> bool:
    """Git klonundan mı çalışıyor (paketin yanında install.sh var) yoksa pip/pipx kurulumundan mı."""
    return os.path.isfile(os.path.join(os.path.dirname(yollar.PAKET_DIZIN), "install.sh"))


def _surum_demeti(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", s))


def libei_en_az() -> str:
    """deskhand-eis'in istediği en düşük libei sürümü: tek kaynak yardimci/Makefile (LIBEI_EN_AZ); okunamazsa ""."""
    try:
        with open(os.path.join(yollar.PAKET_DIZIN, "yardimci", "Makefile"), encoding="utf-8") as f:
            m = re.search(r"^LIBEI_EN_AZ\s*=\s*(\S+)", f.read(), re.M)
    except OSError:
        return ""
    return m.group(1) if m else ""


def libei_eski() -> tuple[str, str] | None:
    """Kurulu libei (pkg-config) deskhand-eis için eskiyse (kurulu, gereken); değilse ya da bilinmiyorsa None."""
    kurulu, gereken = _komut_ciktisi("pkg-config", "--modversion", "libei-1.0"), libei_en_az()
    if kurulu and gereken and _surum_demeti(kurulu) < _surum_demeti(gereken):
        return kurulu, gereken
    return None


def _yardimci_satiri(satir: dict) -> dict:
    """C yardımcıları derli değilken satırı kurulum türüne göre tamamlar. pip/pipx C derlemez: kaynaklar paketle gelir
    (yardimci/*.c + Makefile), yollar.*_bin() aynı dizinde arar → kaynak ağacı dışında öneri YALNIZ çalıştırılabilir
    `make -C <paket>/yardimci` komutudur (kopyalanıp yapıştırılabilir); açıklamalar ayrıntıya eklenir: yükseltme
    derlenmiş yardımcıları siler, deskhand-eis eksik ve libei eskiyse nedeni + paket adı (Makefile hedefi atlar)."""
    import shlex
    if not _kaynak_kurulumu():
        satir["oneri"] = shlex.join(["make", "-C", os.path.join(yollar.PAKET_DIZIN, "yardimci")])
        satir["ayrinti"] += " — " + _("pip/pipx ile yükseltme derlenmiş yardımcıları siler: yükseltmeden sonra komutu "
                                      "yeniden çalıştırın")
    eski = None if _calistirilabilir(yollar.eis_bin()) else libei_eski()
    if eski:
        satir["ayrinti"] += f" — libei {eski[0]} < {eski[1]} (ei_ping): libei{_dagitim_eki('libei')}"
    return satir


def _sanal_ortam() -> bool:
    """Sanal ortamda mı: pyvenv.cfg (venv/virtualenv ≥ 20, uv), eski virtualenv'in sys.real_prefix'i ya da gerçek yolu
    farklı base_prefix. Yalnız metin karşılaştırması yanılır: pyenv/uv sürüm bağı prefix ile base_prefix'i aynı Python
    için farklı yazabilir."""
    import sys
    if os.path.isfile(os.path.join(sys.prefix, "pyvenv.cfg")) or hasattr(sys, "real_prefix"):
        return True
    return os.path.realpath(sys.prefix) != os.path.realpath(sys.base_prefix)


def _sistem_python() -> str:
    """GPU OCR venv'inin tabanı: dağıtımın python3'ü (install.sh'nin PY'si gibi; dağıtımın torch'unu yalnız o görür).
    Arama kullanıcının PATH'i değil sistemin öntanımlı yolu (os.defpath): pyenv/uv kabukları ve base_prefix
    (pyenv/uv Python'u) dağıtım paketlerini görmez. Bulunamazsa base_prefix'in python3'ü, o da yoksa python3."""
    import shutil
    import sys
    bulunan = shutil.which("python3", path=os.defpath)
    if bulunan:
        return bulunan
    py = os.path.join(sys.base_prefix, "bin", "python3")
    return py if os.path.isfile(py) else "python3"


def _pipx_venv() -> bool:
    """pipx kurulumu mu: pipx her uygulamayı <PIPX_HOME>/venvs/<ad> sanal ortamına kurar."""
    import sys
    return _sanal_ortam() and os.path.basename(os.path.dirname(sys.prefix)) == "venvs"


def _modul_onerisi(d: dict, dagitim_onerisi: str) -> str:
    """Eksik Python modülü: git klonunda (install.sh) ya da sistem Python'unda dağıtım paketi; sanal ortamda (pip/pipx
    kurulumu) modül deskhand'in pip bağımlılığıdır, sistem paketi venv'e görünmez → bağımlılıkları geri getiren komut."""
    import shlex
    import sys
    if d.get("tur") != "modul" or _kaynak_kurulumu() or not _sanal_ortam():
        return dagitim_onerisi
    if _pipx_venv():
        return shlex.join(["pipx", "reinstall", os.path.basename(sys.prefix)])
    return shlex.join([sys.executable, "-m", "pip", "install", "deskhand"])


def _gpu_ocr_satiri(satir: dict, eksik: list[str]) -> dict:
    """GPU OCR outside a source checkout (pip/pipx): install.sh's ocr-venv steps as commands (there is no
    ./install.sh): a venv on the system Python that sees the distribution's torch, EasyOCR into it, then the models.
    The download runs the venv interpreter with -I (no current directory, PYTHON* or user site on sys.path) and loads
    only THIS deskhand package from its folder: putting the pipx site-packages on sys.path (install.sh's `cd` into
    the source folder) would let that venv's packages shadow the system ones the OCR venv must use."""
    import shlex

    from . import ocr_gpu
    if _kaynak_kurulumu():
        return satir
    py = _sistem_python()
    venv_py = os.path.join(ocr_gpu.venv_dizin(), "bin", "python")
    adimlar = []
    if "python" in eksik:
        adimlar += [shlex.join([py, "-m", "venv", "--system-site-packages", ocr_gpu.venv_dizin()]),
                    shlex.join([venv_py, "-m", "pip", "install", "--no-deps", "easyocr", "python-bidi"])]
        satir["ayrinti"] += " — " + _("önce dağıtım paketleri: torch (ROCm ya da CUDA), torchvision, opencv, scikit-image, "
                                      "shapely, pyclipper, scipy (Arch: python-pytorch-opt-rocm | python-pytorch-opt-cuda, "
                                      "python-torchvision, python-opencv, python-scikit-image, python-shapely, "
                                      "python-pyclipper, python-scipy)")
    if "model" in eksik:
        kod = (ocr_gpu.paket_yukleme_kodu(yollar.PAKET_DIZIN) +
               "\nimport sys\nfrom deskhand import ocr_gpu\nocr_gpu.indir(sys.argv[1])")
        adimlar.append(shlex.join([venv_py, "-I", "-c", kod, ocr_gpu.model_dizin()]))
    satir["oneri"] = " && ".join(adimlar) if adimlar else _("günlüğe bakın: {yol}").format(yol=ocr_gpu.gunluk_yolu())
    return satir


def satir_masaustu():
    """pip/pipx: menu entry and panel-at-login written by `deskhand install-desktop` (masaustu_kur)? In a source
    checkout install.sh writes them: no row."""
    if _kaynak_kurulumu():
        return None
    from . import masaustu_kur
    ad = _("Masaüstü girdileri")
    h = masaustu_kur.hedefler()
    menu, acilis = os.path.isfile(h["menu"]), os.path.isfile(h["acilis"])
    if menu and acilis and masaustu_kur.acilis_kapali(h["acilis"]):
        return _satir(ad, "tamam", _("menü girdisi var; oturum açılışında panel kapalı (tercih; açmak için: "
                                     "deskhand install-desktop --autostart)"))
    if menu and acilis:
        return _satir(ad, "tamam", _("menü girdisi ve oturum açılışında panel var"))
    if not menu:
        return _satir(ad, "uyari", _("uygulama menüsünde Deskhand yok ({yol})").format(yol=h["menu"]),
                      "deskhand install-desktop")
    return _satir(ad, "uyari", _("panel oturum açılışında başlamıyor: onaylar için panel açık olmalı ({yol} yok)").format(
        yol=h["acilis"]), _("deskhand install-desktop (ya da her oturumda: deskhand panel --tepsi)"))


def _yardimci_python() -> str:
    """The interpreter Deskhand's helper scripts really run under (notification catcher, clipboard owner, guards):
    arka_ortak.python_yolu() — in a pipx/venv install the system python3, not this one."""
    from . import arka_ortak
    return arka_ortak.python_yolu()


def _yardimci_eksikleri(py: str, moduller: list[str]) -> list[str] | None:
    """Which of `moduller` `py` cannot find (find_spec: nothing is imported or run); None: `py` did not run."""
    import subprocess
    kod = "import importlib.util as u, sys; print(' '.join(m for m in sys.argv[1:] if u.find_spec(m) is None))"
    try:
        r = subprocess.run([py, "-I", "-c", kod, *moduller], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=15, cwd="/")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.split() if r.returncode == 0 else None


def satir_yardimci_modulleri():
    """pip/pipx: the helper scripts run under the system python3 (arka_ortak.python_yolu), which does not see this
    environment's packages: without the distribution's jeepney / python-xlib notifications and the clipboard silently
    do nothing. No row in a source checkout (install.sh checks) or when the helpers run under this interpreter (the
    module rows above cover it)."""
    import sys
    if _kaynak_kurulumu():
        return None
    try:
        py = _yardimci_python()
    except Exception:  # noqa: BLE001 - Dur(9): no safe python3
        py = None
    if py and os.path.realpath(py) == os.path.realpath(sys.executable or ""):
        return None
    ad = _("Yardımcı Python modülleri")
    moduller = (("jeepney", "python-jeepney", _("bildirim yakalama")), ("Xlib", "python-xlib", _("pano")))
    eksik = _yardimci_eksikleri(py, [m for m, _p, _n in moduller]) if py else None
    if eksik is None:
        return _satir(ad, "uyari", _("yardımcı betiklerin yorumlayıcısı çalıştırılamadı: {py}").format(py=py or "python3"),
                      _("paketi kur: {paket}").format(paket="python"))
    if not eksik:
        return _satir(ad, "tamam", _("{py}: jeepney, Xlib var").format(py=py))
    secilen = [(m, p, n) for m, p, n in moduller if m in eksik]
    arch = [p for _m, p, _n in secilen]
    oneri = _("paketi kur: {paket}").format(paket=" ".join(arch))
    for i, dagitim in ((0, "Debian/Ubuntu"), (1, "Fedora")):
        adlar = [DAGITIM_PAKETLERI.get(p, ("-", "-"))[i] for p in arch]
        if "-" not in adlar:
            oneri += f" · {dagitim}: {' '.join(adlar)}"
    return _satir(ad, "uyari", _("{py} ile çalışan yardımcılarda eksik: {liste} (sessizce çalışmaz)").format(
        py=py, liste=", ".join(f"{m} ({n})" for m, _p, n in secilen)), oneri)


SATIRLAR = (*SATIRLAR, satir_masaustu, satir_yardimci_modulleri)
