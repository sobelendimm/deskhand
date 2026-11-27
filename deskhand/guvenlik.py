"""Güvenlik katmanı (iki arka uçta da AYNEN, docs/ARCHITECTURE.md §4):

- Yasak pencereler (CONFIG_DIR/yasak-pencereler.txt): hiçbir girdi gönderilmez, uygulama başlatılmaz (10).
- Hassas düğme (ödeme/yetki/hesap silme) ve ödeme sayfası başlığı: --onayli olmadan tıklanmaz (10).
  --onayli YALNIZ kullanıcı o adımı sohbette açıkça onayladıysa verilir.
- Başlık (-b) ve sınıf (-s) kilidi: her girdiden hemen önce (4).
- DUR anahtarı (RUNTIME_DIR/dur): her girdi satırından önce (13); `dur` oluşturur; `devam` yalnız kullanıcının panel onayıyla
  siler (dur_kaldir_iste). Yazma/kaldırma
  atomik: kullanıcının (arayüzden) koyduğu DUR'u ajan hiçbir yarışta kaldıramaz ya da ezemez.
- Riskli tuş kombinasyonları (oturumu/sistemi sonlandıran, ekrandan çıkaran) ve uçbirime yazılan yıkıcı komutlar:
  YASAK değil, insan onayı (hassas düğmeyle aynı yol; --onayli yoksa panelden onay, panel kapalıysa 10).
- Uygulama erişim seviyeleri (CONFIG_DIR/uygulama-seviyeleri.txt; varsayılan: dosya yok = kısıt yok):
  goruntule (girdi yok) | tikla (yalnız fare) | tam. Gözetimsiz kip (DESKHAND_GOZETIMSIZ=1): onay sorulmaz, red (10).
"""
from __future__ import annotations

import os
import re
import tempfile
import threading

from . import yollar
from .arka_uc import EKRAN, sec
from .hata import KULLANICI_DUR, Dur, dur_dosyasi, gozetimsiz
from .i18n import N_, _
from .ocr import katla

SINIF_DESEN = None  # -s: hedef (masaüstü kipinde etkin) pencerenin SINIFI bu desene uymalı (başlıksız pencereler: krunner)

VARSAYILAN_YASAK = N_("""# Bu desenlere (regex, büyük/küçük harf duyarsız) uyan pencere BAŞLIĞI ya da SINIFINA hiçbir girdi
# (tıklama/tuş/yazı/kaydırma) gönderilmez ve uygulama başlatılmaz. Okuma serbesttir. Varsayılan: boş.
# Örnekler (başındaki # işaretini kaldırarak açın):
# KeePassXC
# ^Online Banking
""")  # dosyaya ilk açılışta, seçili dilde yazılır
# Ödeme / yetki verme / hesap silme: kullanıcının kararı. Türkçe harfler katlanmış (ş→s, ı→i…) metinde aranır.
_PARA_KALIPLARI = (r"satin al\w*|simdi al|hemen al|ode|odeme yap\w*|odemeyi (tamamla|onayla)\w*|siparis ver\w*|"
                   r"siparisi (tamamla|onayla)\w*|alisverisi tamamla\w*|buy( now)?|purchase|pay( now)?|place order|"
                   r"complete (order|purchase|payment)|confirm (order|payment|purchase)")
_YETKI_KALIPLARI = (r"authori[sz]e|yetkilendir\w*|izin ver\w*|allow|grant( access)?|hesab\w* sil\w*|"
                    r"delete (my )?account|kalici olarak sil\w*|permanently delete")
HASSAS = re.compile(r"\b(" + _PARA_KALIPLARI + "|" + _YETKI_KALIPLARI + r")\b")
# onay kapsamı "kart": onay istemeye devam eden YALNIZ para alt kümesi (satın alma/ödeme/sipariş onayı düğmeleri)
# + ödeme sayfası DIŞINDA da son sipariş/abonelik/bağış düğmeleri (HASSAS'a girmez: "hepsi" kipi değişmez). "Devam Et" /
# "Continue" / "Confirm" para düğmesi SAYILIR DEĞİL (çok yaygın); ödeme sayfasında zaten her tıklama onay ister.
# katla "&" işaretini boşluğa çevirir ("Confirm & Pay" → "confirm pay").
_PARA_EK_KALIPLARI = (r"(place|submit|complete) (your )?order|confirm (and )?pay|siparis(i|inizi) (ver|gonder|tamamla)\w*|"
                      r"onayla ve ode\w*|abonelik(i)? (baslat|onayla)\w*|bagis yap\w*|"
                      r"donate|odeme(yi)? (yap|tamamla)\w*")
# NOT: "abone ol", "subscribe", "onayla ve bitir", "siparişiniz onaylandı" (durum yazısı) para düğmesi SAYILMAZ: YouTube
# "Abone ol", "Subscriptions" gibi parasız düğmeler `kart` kipinde onay istemesin (kullanıcı: yalnız kart kullanırken)
PARA_DUGMESI = re.compile(r"\b(" + _PARA_KALIPLARI + "|" + _PARA_EK_KALIPLARI + r")\b")
# başlığı ödeme/sipariş onayı olan sayfada HER tıklama ve Enter/boşluk onay ister: OCR'ın okuyamadığı
# ödeme düğmesine (ör. orta ton zeminde beyaz yazı) koordinatla basılmasın. Form doldurmak (yaz) serbest; ama
# yazı Enter/Tab/boşluk içeriyorsa (\n = gönder, Tab+boşluk = odaktaki düğmeye bas) o da onay ister.
HASSAS_SAYFA = re.compile(r"\b(odeme|checkout|payment|siparisi (onayla|tamamla)\w*|siparis ozeti|"
                          r"order (review|summary)|kasa|billing)\b")
# onay kapsamı "kart": kart kipinde sayfadaki HER tıklama onay istediği için DAR kalıp (yalnız gerçek ödeme/sipariş adımı;
# "PC Kasa Modelleri", "Kasa fanı", "Payment Request API", "Google Cloud Billing", "Ödeme Geçmişi" eşleşmez). katla: küçük harf, ASCII.
HASSAS_SAYFA_KART = re.compile(
    r"\b(checkout|odeme(?![\s\-\u2013\u2014:|]*(gecmis|history|yontemlerim|yontemleri\b))|siparis ozeti|"
    r"siparisi (onayla|tamamla)\w*|order (review|summary)|place order|"
    r"payment (details|information|page|step)|billing (details|information)|3d[ -]?(secure|dogrulama)\w*)\b")


def hassas_sayfa_kalibi():
    """Geçerli onay kapsamına göre sayfa-başlığı kalıbı: hepsi → HASSAS_SAYFA (geniş), kart → HASSAS_SAYFA_KART (dar)."""
    return HASSAS_SAYFA_KART if onay_kapsami() == "kart" else HASSAS_SAYFA

# Enter/boşluk eşdeğerleri (tus_coz SONRASI çözülmüş tuş): ad, X keysym (x:…) ve evdev kodu (k:…). Hassas sayfada
# bunlardan biri onay ister; çözülemeyen x:/k: tuşu da (güvenli taraf) onay ister.
ONAY_TUS_ADLARI = {"enter", "kpenter", "space", "linefeed", "return", "kp_enter", "kp_space", "iso_enter"}
# Return, KP_Enter, ISO_Enter, space, KP_Space, Linefeed, 3270_Enter, nobreakspace
ONAY_KEYSYM = {0xff0d, 0xff8d, 0xfe34, 0x20, 0xff80, 0xff0a, 0xfd1e, 0xa0}
ONAY_EVDEV = {28, 57, 96, 101}  # KEY_ENTER, KEY_SPACE, KEY_KPENTER, KEY_LINEFEED


def _keysym(ad):
    """x:AD → keysym sayısı | None (çözülemedi). Ad (Return), 0xff0d, U+000D / U000D, tek karakter."""
    m = re.fullmatch(r"0x([0-9a-f]+)", ad, re.I)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"U\+?([0-9a-f]{1,6})", ad, re.I)
    if m:
        return 0x1000000 + int(m.group(1), 16)
    if len(ad) == 1:
        return ord(ad) if ord(ad) < 0x100 else 0x1000000 + ord(ad)
    try:
        from Xlib import XK
        return XK.string_to_keysym(ad) or None
    except Exception:  # noqa: BLE001 - python-xlib yoksa çözülemedi say (güvenli taraf)
        return None


def onay_tusu_mu(kombinasyon):
    """Çözülmüş tuş dizisinde (eylem.tus_coz çıktısı: 'ctrl+enter x:Return k:28') Enter/boşluk eşdeğeri var mı?"""
    for akor in (kombinasyon or "").split():
        for t in akor.split("+"):
            if t.startswith("k:"):
                try:
                    if int(t[2:]) in ONAY_EVDEV:
                        return True
                except ValueError:
                    return True
            elif t.startswith("x:"):
                ks = _keysym(t[2:])
                if ks is None or t[2:].lower() in ONAY_TUS_ADLARI or ks in ONAY_KEYSYM:
                    return True
                kod = ks - 0x1000000 if ks >= 0x1000000 else ks  # Unicode keysym → kod noktası
                if kod < 0x110000 and chr(kod).isspace():  # U+000D, U+000A, U+0020, U+00A0…
                    return True
            elif t.lower() in ONAY_TUS_ADLARI:
                return True
    return False


def yazi_onay_ister_mi(metin):
    """Yazı onay gerektirebilir mi? (1) Enter (\\n), Tab ya da boşluk içeriyor (her tür Unicode boşluk: nbsp da Space
    tuşuyla yazılır): hassas sayfada formu gönderme / odaktaki düğmeye basma olabilir; (2) yıkıcı bir uçbirim komutu
    kalıbına uyuyor (riskli_komut). Yalnız METİNLE karar verilir (ucuz ön eleme); hedef pencerenin uçbirim olup
    olmadığına eylem._yazi_hassas bakar (ucbirim_komut_engel)."""
    return any(c.isspace() for c in metin) or riskli_komut(metin) is not None


# ---------------------------------------------------------------- riskli tuş kombinasyonları

# Tuş adı → kanonik ad (ctrl/alt/super/delete/backspace/sysrq/l/fN). tus_coz çıktısındaki x:… (keysym) ve k:… (evdev)
# biçimleri ve X/xdotool eş adları da çözülür; böylece 'x:Delete', 'k:111', 'Control_L' gibi yazımlar kaçmaz.
_TUS_ESANLAM = {
    "control": "ctrl", "leftctrl": "ctrl", "rightctrl": "ctrl", "lctrl": "ctrl", "rctrl": "ctrl",
    "control_l": "ctrl", "control_r": "ctrl",
    "leftalt": "alt", "rightalt": "alt", "altgr": "alt", "alt_l": "alt", "alt_r": "alt", "iso_level3_shift": "alt",
    "meta": "super", "win": "super", "windows": "super", "cmd": "super", "leftmeta": "super", "rightmeta": "super",
    "super_l": "super", "super_r": "super", "meta_l": "super", "meta_r": "super",
    "del": "delete", "bksp": "backspace", "sys_req": "sysrq", "sysreq": "sysrq",
}
_TUS_ESANLAM.update({"kpinsert": "insert", "xf86paste": "paste", "apps": "menu", "multi_key": "compose",
                     "return": "enter", "kp_enter": "kpenter", "iso_enter": "enter", "3270_enter": "enter",
                     "leftshift": "shift", "rightshift": "shift", "shift_l": "shift", "shift_r": "shift",
                     "escape": "esc", "ins": "insert", "kp_insert": "insert"})
# Güç / uyku / kilit / oturum kapatma tuşları (dotool adları, XF86 keysym adları; değiştiricisiz tek tuş da riskli)
_TUS_ESANLAM.update({"pgup": "pageup", "pgdown": "pagedown", "page_up": "pageup", "page_down": "pagedown",
                     "prior": "pageup", "next": "pagedown", "kp_prior": "pageup", "kp_next": "pagedown",
                     "poweroff": "power", "xf86poweroff": "power", "powerdown": "power", "xf86powerdown": "power",
                     "xf86sleep": "sleep", "standby": "sleep", "xf86standby": "sleep",
                     "xf86wakeup": "wakeup", "wake": "wakeup",
                     "coffee": "screenlock", "screensaver": "screenlock", "xf86screensaver": "screenlock",
                     "xf86coffee": "screenlock", "lock": "screenlock",
                     "xf86suspend": "suspend", "xf86hibernate": "hibernate", "hibernate": "hibernate",
                     "logoff": "logoff", "xf86logoff": "logoff", "logout": "logoff"})
_GUC_TUSLARI = {"power", "sleep", "wakeup", "screenlock", "suspend", "hibernate", "logoff"}
_EVDEV_AD = {29: "ctrl", 97: "ctrl", 56: "alt", 100: "alt", 125: "super", 126: "super", 111: "delete", 14: "backspace",
             99: "sysrq", 38: "l", **{59 + i: f"f{i + 1}" for i in range(10)}, 87: "f11", 88: "f12",
             28: "enter", 96: "kpenter", 101: "linefeed", 47: "v", 110: "insert", 36: "j", 50: "m", 24: "o",
             42: "shift", 54: "shift", 1: "esc", 46: "c", 22: "u", 15: "tab", 207: "paste", 127: "menu",
             139: "menu", 25: "p", 21: "y", 18: "e", 41: "grave", 20: "t", 62: "f4",
             104: "pageup", 109: "pagedown", 116: "power", 142: "sleep", 143: "wakeup", 152: "screenlock",
             205: "suspend"}
_KEYSYM_AD = {0xffe3: "ctrl", 0xffe4: "ctrl", 0xffe9: "alt", 0xffea: "alt", 0xfe03: "alt", 0xffe7: "super",
              0xffe8: "super", 0xffeb: "super", 0xffec: "super", 0xffff: "delete", 0xff08: "backspace",
              0xff15: "sysrq", 0x6c: "l", 0x4c: "l", **{0xffbe + i: f"f{i + 1}" for i in range(12)},
              0xff0d: "enter", 0xff8d: "kpenter", 0xfe34: "enter", 0xfd1e: "enter", 0xff0a: "linefeed",
              0x76: "v", 0x56: "v", 0xff63: "insert", 0xff9e: "insert", 0x6a: "j", 0x4a: "j", 0x6d: "m", 0x4d: "m",
              0x6f: "o", 0x4f: "o", 0xffe1: "shift", 0xffe2: "shift", 0xff1b: "esc", 0x63: "c", 0x43: "c",
              0x75: "u", 0x55: "u", 0xff09: "tab", 0x1008ff6d: "paste", 0xff67: "menu", 0xff20: "compose",
              0x70: "p", 0x50: "p", 0x79: "y", 0x59: "y", 0x65: "e", 0x45: "e", 0xffc7: "f10", 0x60: "grave",
              0xff55: "pageup", 0xff56: "pagedown", 0xff9a: "pageup", 0xff9b: "pagedown",
              0x1008ff2a: "power", 0x1008ff21: "power", 0x1008ff2f: "sleep", 0x1008ff10: "sleep",
              0x1008ff2b: "wakeup", 0x1008ff2d: "screenlock", 0x1008ff2c: "screenlock", 0x1008ffa7: "suspend",
              0x1008ffa8: "hibernate", 0x1008ff61: "logoff"}
_FTUS = re.compile(r"f([1-9]|1[0-2])")


def _tus_kanonik(t):
    """Tek tuş adı (kombinasyonun '+' ile bölünmüş parçası) → kanonik ad (küçük harf); tanınmayan aynen küçük harf."""
    t = (t or "").strip()
    if t.startswith("k:"):
        try:
            return _EVDEV_AD.get(int(t[2:]), t.lower())
        except ValueError:
            return t.lower()
    if t.startswith("x:"):
        ad = t[2:].lower()
        if ad in _TUS_ESANLAM:
            return _TUS_ESANLAM[ad]
        ks = _keysym(t[2:])
        return _KEYSYM_AD.get(ks, ad) if ks is not None else ad
    t = t.lower()
    return _TUS_ESANLAM.get(t, t)


def _akor_riski(tuslar):
    """Birlikte basılan kanonik tuş kümesi → neden | None."""
    ctrl, alt, ust = "ctrl" in tuslar, "alt" in tuslar, "super" in tuslar
    guc = sorted(tuslar & _GUC_TUSLARI)
    if guc:  # değiştiricisiz tek tuş da: kapatır/uyutur/kilitler/oturumu kapatır
        return _("{tus} tuşu: bilgisayarı kapatabilir, uyutabilir, ekranı kilitleyebilir ya da oturumu kapatabilir").format(
            tus=guc[0].capitalize())
    if ctrl and alt and "shift" in tuslar and tuslar & {"delete", "pageup", "pagedown"}:
        return _("Ctrl+Alt+Shift+Delete/PageUp/PageDown: onaysız oturum kapatma / yeniden başlatma / kapatma")
    if ctrl and alt:
        if "delete" in tuslar:
            return _("Ctrl+Alt+Delete: oturum/güç menüsünü açar")
        if "backspace" in tuslar:
            return _("Ctrl+Alt+Backspace: grafik oturumunu sonlandırır")
        f = next((t for t in sorted(tuslar) if _FTUS.fullmatch(t)), None)
        if f:
            return _("Ctrl+Alt+{tus}: sanal uçbirime geçer (masaüstü oturumundan çıkar)").format(tus=f.upper())
        if "l" in tuslar:
            return _("Ctrl+Alt+L: ekranı kilitler")
    if ust and "l" in tuslar:
        return _("Meta+L: ekranı kilitler")
    if alt and "sysrq" in tuslar and any(t not in ("alt", "sysrq", "ctrl", "shift", "super") for t in tuslar):
        return _("Alt+SysRq+tuş: çekirdek müdahale (SysRq) kısayolu; sistemi yeniden başlatabilir/kapatabilir")
    return None


def _akor_kumeleri(kombinasyon):
    """Çözülmüş tuş dizisi → [(kanonik tuş kümesi, çözülemeyen x:/k: var mı)] (akor başına)."""
    sonuc = []
    for akor in (kombinasyon or "").split():
        kume, bilinmeyen = set(), False
        for t in akor.split("+"):
            if not t:
                continue
            if t.startswith("x:") and _keysym(t[2:]) is None and t[2:].lower() not in _TUS_ESANLAM:
                bilinmeyen = True
            if t.startswith("k:") and not t[2:].isdigit():
                bilinmeyen = True
            kume.add(_tus_kanonik(t))
        sonuc.append((kume, bilinmeyen))
    return sonuc


ENTER_ADLARI = {"enter", "kpenter", "linefeed"}


def enter_tusu_mu(kombinasyon):
    """Kabukta satırı ÇALIŞTIRAN tuş var mı (Enter kapısı): enter, kpenter, linefeed (x:Return, k:28 dahil) ya da
    ctrl+j / ctrl+m / ctrl+o (bash: satırı çalıştır). Çözülemeyen x:/k: tuşu güvenli tarafta True."""
    for kume, bilinmeyen in _akor_kumeleri(kombinasyon):
        if bilinmeyen or kume & ENTER_ADLARI or ("ctrl" in kume and kume & {"j", "m", "o"}):
            return True
    return False


_YAPISTIR_TUSU = {"paste", "xf86paste"}  # klavyedeki Paste tuşu (KEY_PASTE = 207, XF86Paste)
_MENU_AKORLARI = ({"shift", "f10"}, {"menu"}, {"compose"}, {"alt", "e"})  # klavye menüsü / Düzen menüsü


def menu_tusu_mu(akor):
    """Bağlam/Düzen menüsünü açan akor mu (shift+F10, menu/compose tuşu, alt+e)?"""
    kume = {_tus_kanonik(t) for t in akor.split("+") if t}
    return any(kume == m for m in _MENU_AKORLARI)


def yapistir_tusu_mu(kombinasyon, menu_acik=False):
    """Panodan yapıştıran tuş(lar) var mı: ctrl+v, ctrl+shift+v, shift+insert / shift+kpinsert, Paste tuşu (XF86Paste,
    k:207), klavye menüsü (shift+F10 / menu / alt+e) ardından p ya da y (aynı çağrıda; menu_acik=True: menü az önce
    — MENU_SN içinde — açılmıştı). x:/k: biçimleri dahil."""
    menu = menu_acik
    for kume, _b in _akor_kumeleri(kombinasyon):
        if ("ctrl" in kume and "v" in kume) or ("shift" in kume and "insert" in kume) or kume & _YAPISTIR_TUSU:
            return True
        if menu and kume & {"p", "y"} and not kume & {"ctrl", "alt", "super"}:
            return True
        if menu and kume & {"enter", "kpenter", "space"}:  # menüde gezinip seçmek: seçilen öge yapıştır olabilir
            return True
        menu = any(kume == m for m in _MENU_AKORLARI) or (menu and kume <= {"down", "up", "shift", "left", "right"})
    return False


def riskli_tus(kombinasyon, birlikte=False):
    """Oturumu/sistemi sonlandıran ya da ekrandan çıkaran tuş kombinasyonu mu? → neden metni | None.
    Yasak DEĞİL: çağıran insan onayı ister (riskli_tus_engel). kombinasyon: eylem.tus_coz çıktısı ya da ham metin
    ('ctrl+alt+delete', 'x:Delete', 'k:111', boşlukla ayrılmış akorlar).
    Dar kapsam: ctrl+alt+delete, ctrl+alt+backspace, ctrl+alt+f1…f12 (sanal uçbirim), meta+l ve ctrl+alt+l (ekran
    kilidi), alt+sysrq+tuş, ctrl+alt+shift+delete/pageup/pagedown (KDE: onaysız oturum kapatma/yeniden başlatma/
    kapatma) ve değiştiricisiz tek başına güç/uyku/uyandırma/kilit/askıya alma/hazırda bekletme/oturum kapatma tuşları
    (power, sleep, wakeup, coffee/screensaver, suspend, XF86PowerOff…, k:116/142/143/152/205). birlikte=True (bas: boşlukla ayrılmış tuşlar AYNI ANDA basılı kalır): tek küme sayılır."""
    akorlar = [[_tus_kanonik(t) for t in akor.split("+") if t] for akor in (kombinasyon or "").split()]
    kumeler = [set(a) for a in akorlar]
    if birlikte and len(akorlar) > 1:
        kumeler.append({t for a in akorlar for t in a})
    for kume in kumeler:
        neden = _akor_riski(kume)
        if neden:
            return neden
    return None


# ---------------------------------------------------------------- uçbirime yıkıcı komut yazma

# Uçbirim öykünücüsü pencere sınıfları (tek sabit liste; sınıf adında sözcük olarak aranır: org.kde.konsole,
# com.mitchellh.ghostty, gnome-terminal-server, Alacritty…). Başka bir pencerede (tarayıcı, düzenleyici) yazılan
# "rm -rf" metni sıradan yazıdır: tetiklenmez.
UCBIRIM_SINIFLARI = (
    "konsole", "yakuake", "ghostty", "kitty", "alacritty", "foot", "footclient", "wezterm", "wezterm-gui", "xterm",
    "uxterm", "gnome-terminal", "tilix", "terminator", "ptyxis", "kgx", "gnome-console", "xfce4-terminal",
    "lxterminal", "qterminal", "mate-terminal", "urxvt", "rxvt", "guake", "tilda", "terminology", "sakura",
    "cool-retro-term", "contour", "rio", "terminal", "st-256color",
)
_UCBIRIM = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(a) for a in UCBIRIM_SINIFLARI) + r")(?![a-z0-9])", re.I)


def ucbirim_mi(sinif):
    """Pencere sınıfı bir uçbirim öykünücüsü mü (UCBIRIM_SINIFLARI)?"""
    return bool(_UCBIRIM.search(sinif or ""))


# Uçbirim GÖMEBİLEN uygulamalar (Dolphin F4, Kate/KWrite uçbirim paneli, IDE'ler): pencere PID'i bilinmiyorsa güvenli
# tarafta uçbirim sayılır; PID biliniyorsa süreç ağacına (tty'li kabuk torunu) bakılır.
GOMULU_UCBIRIM_SINIFLARI = (
    "dolphin", "kate", "kdevelop", "krusader", "code", "code-oss", "codium", "vscodium", "cursor", "windsurf",
    "zed", "lapce", "sublime_text", "geany", "qtcreator", "gnome-builder", "emacs", "spyder", "idea", "pycharm",
    "clion", "goland", "webstorm", "phpstorm", "rider", "rustrover", "android-studio", "jetbrains", "nautilus",
    "thunar", "nemo", "caja", "pcmanfm", "doublecmd", "neovide", "nvim-qt", "gvim", "kile", "kmail", "yakuake",
)
_GOMULU = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(a) for a in GOMULU_UCBIRIM_SINIFLARI) + r")(?![a-z0-9])",
                     re.I)
_UCBIRIM_ONBELLEK = {}  # (arka uç, kimlik) → (zaman, bool)


def ucbirim_penceresi_mi(k):
    """Pencere bir UÇBİRİM barındırıyor mu? (1) sınıfı uçbirim öykünücüsü; (2) penceresinin sahibi sürecin torunlarında
    denetim uçbirimi (tty) olan bir kabuk var (gömülü uçbirim: Dolphin F4, Kate paneli, VS Code…); (3) PID bilinmiyor ve
    sınıf uçbirim gömebilen bir uygulama (güvenli taraf); (4) erişilebilirlik zaten açıksa pencerede rolü `terminal`
    olan bir öge var (PID'siz ya da gömebilen sınıflarda). Yalnız "uçbirim" sonucu 2 sn önbellekte; "değil" sonucu
    önbelleğe alınmaz (yarış: F4'ten hemen sonra kabuk henüz doğmamış olabilir)."""
    if not k or k == EKRAN:
        return False
    import time as _t
    au = sec()
    sinif = au.sinif(k)
    anahtar = (au.ad, k, sinif)  # sınıf da anahtarda: kimlik yeniden kullanılırsa eski sonuç taşınmasın
    kayit = _UCBIRIM_ONBELLEK.get(anahtar)
    if kayit and _t.monotonic() - kayit[0] < 2.0:
        return kayit[1]
    sonuc = ucbirim_mi(sinif)
    bilinmiyor = False  # erişilebilirlik algısı belirsiz (sayfa belirsiz/Dur): uçbirim say ama önbelleğe ALMA
    if not sonuc:
        from . import kendi
        pid = _pencere_pid(au, k)
        if pid:
            sonuc = bool(kendi.kabuk_torunlari(pid))
        else:
            sonuc = bool(_GOMULU.search(sinif or ""))
        if not sonuc and (not pid or _GOMULU.search(sinif or "")):
            try:
                from . import erisim
                v = erisim.ucbirim_ogesi_var_mi(k) if erisim.erisim_acik() else False
                bilinmiyor = v is None  # SON-FIX: belirsizlik "uçbirim değil" sayılmaz (Enter kapısı açık kalmaz)
                sonuc = v is not False
            except Exception:  # noqa: BLE001 - erişilebilirlik isteğe bağlı (kapalı/yok: önceki davranış)
                sonuc = False
    if sonuc and not bilinmiyor:  # yalnız kesin "uçbirim" tutulur: "değil"/"bilinmiyor" her çağrıda yeniden hesaplanır
        if len(_UCBIRIM_ONBELLEK) > 256:
            _UCBIRIM_ONBELLEK.clear()
        _UCBIRIM_ONBELLEK[anahtar] = (_t.monotonic(), True)
    return bool(sonuc)


_SARMALAYICI = {"env", "time", "nohup", "nice", "ionice", "command", "builtin", "exec", "stdbuf", "setsid", "xargs",
                "watch", "timeout", "chrt", "unbuffer", "taskset", "flock", "caffeinate", "systemd-inhibit"}
# sarmalayıcı → (argüman ALAN seçenekler, komuttan önceki konumsal argüman sayısı): `nice -n 5 X`, `timeout -s 9 5 X`
_SARMALAYICI_SECENEK = {
    "env": ({"-u", "--unset", "-C", "--chdir"}, 0), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1), "chrt": ({"-T", "-P", "-D"}, 1),
    "stdbuf": ({"-i", "-o", "-e"}, 0), "watch": ({"-n", "--interval", "-q", "--equexit"}, 0),
    "xargs": ({"-I", "-i", "-n", "-P", "-d", "-L", "-l", "-s", "-a", "-E", "-e", "--max-args", "--max-procs",
               "--delimiter", "--arg-file", "--replace", "--max-lines", "--max-chars", "--eof"}, 0),
    "time": ({"-f", "-o", "--format", "--output"}, 0), "exec": ({"-a"}, 0), "taskset": (set(), 1),
    "flock": ({"-w", "-E", "--timeout", "--conflict-exit-code"}, 1),
    "systemd-inhibit": ({"--what", "--who", "--why", "--mode"}, 0),
}
_KABUK = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "csh", "tcsh", "yash", "busybox-sh"}
_YETKI = {"sudo", "doas", "pkexec", "run0"}
_GUC = {"shutdown", "reboot", "poweroff", "halt"}
_SISTEMD_GUC = {"poweroff", "reboot", "suspend", "halt", "hibernate", "hybrid-sleep", "suspend-then-hibernate", "kexec"}
# kabuk anahtar sözcükleri: asıl komut bunlardan SONRA gelir (`if true; then sudo reboot; fi`, `{ sudo x; }`, `! sudo x`)
_ANAHTAR = {"{", "}", "!", "if", "then", "do", "else", "elif", "while", "until", "time", "fi", "done", "esac", "coproc",
            "(", ")", "[[", "]]"}
_ATAMA = re.compile(r"([A-Za-z_]\w*)(\+?=)(.*)", re.S)
_ATAMA_KOMUT = {"export", "declare", "typeset", "local", "readonly"}
# betik yorumlayıcıları: `python3 -c KOD`, `perl -e KOD` … → KOD dosya silme / komut çalıştırma / dinamik kod içeriyor mu
_YORUMLAYICI = re.compile(r"(?:python|pypy)[\d.]*|perl[\d.]*|ruby[\d.]*|node|nodejs|deno|bun|php[\d.]*|lua[\d.]*|"
                          r"luajit|tclsh[\d.]*|osascript|Rscript")
_YORUMLAYICI_KOD = re.compile(
    r"rmtree|remove_tree|rm_r|rm_rf|rmSync|rmdirSync|unlinkSync|unlink|\bremove\s*\(|removedirs|\brmdir\b|"
    r"\bos\s*\.\s*(?:system|popen|exec\w*|spawn\w*|kill\w*|remove|truncate)|subprocess|child_process|\bpty\b|"
    r"\bsystem\s*\(|\bexec\s*\(|\beval\s*\(|__import__|importlib|\bcompile\s*\(|\bqx\b|%x|`|FileUtils|"
    r"execSync|spawnSync|\bspawn\s*\(|File\s*\.\s*delete|shell_exec|passthru|proc_open", re.I)
# kök / ev dizini ya da sistem dizini hedefleri (rm, chmod -R, chown -R); rm için ayrıca * ve ./*
_KOK_HEDEF = re.compile(r"/|/\*|~/?|~/\*|\$HOME/?|\$\{HOME\}/?|/(?:etc|usr|bin|sbin|lib|lib64|var|boot|home|root|opt|sys|dev|srv)/?\*?")
_RM_HEDEF = re.compile(r"\*|\./\*|" + _KOK_HEDEF.pattern)
_ZARARSIZ_AYGIT = re.compile(r"/dev/(?:null|zero|full|stdout|stderr|stdin|tty\w*|pts/\w+|fd/\d+)$")
_DISK_AYGIT = re.compile(r"/dev/(?:sd[a-z]|hd[a-z]|vd[a-z]|xvd[a-z]|nvme\d|mmcblk\d|md\d|dm-\d|disk\d)\S*")
_DISK_YONLENDIR = re.compile(r">>?\s*/dev/(?:sd[a-z]|hd[a-z]|vd[a-z]|xvd[a-z]|nvme\d|mmcblk\d|md\d|dm-\d|disk\d)")
_CATAL_BOMBASI = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:|"
                            r"\b(\w+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}")
_BORU_KABUK = re.compile(r"\b(?:curl|wget)\b[^\n;&]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:/usr/bin/env\s+)?(?:\S*/)?"
                         r"(?:ba|z|da|k|c|fi)?sh\b|"
                         r"\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*<\(\s*(?:curl|wget)\b|"
                         r"\b(?:ba|z|da|k)?sh\s+-c\s+[\"']?\$\(\s*(?:curl|wget)\b")
_VIM_SUDO = re.compile(r":\s*w\s*!\s*sudo\b")
_ISARET = "\x00"  # komut ikamesinin (bilinmeyen değer) yer tutucusu
_ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "v": "\v",
         "\\": "\\", "'": "'", '"': '"', "?": "?"}
_ANSI_SAYI = re.compile(r"x([0-9a-fA-F]{1,2})|u([0-9a-fA-F]{1,4})|U([0-9a-fA-F]{1,8})|([0-7]{1,3})|c(.)", re.S)


# ---- küçük kabuk sözcük çözümleyicisi (bash'in sözcük bölme/tırnak kurallarının riskli komut denetimine yeten kısmı)

def _ters_tirnak_sonu(s, i):
    j = i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "`":
            return j
        j += 1
    return len(s)


def _cift_tirnak_sonu(s, i):
    """i: açılış "'ndan sonrası → kapanış "'ndan SONRAKİ dizin (yoksa len)."""
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == '"':
            return j + 1
        if c == "$" and s[j + 1:j + 2] == "(":
            j = _kapanis(s, j + 2) + 1
            continue
        if c == "`":
            j = _ters_tirnak_sonu(s, j + 1) + 1
            continue
        j += 1
    return len(s)


def _kapanis(s, i):
    """i: '(' sonrası → eşleşen ')' dizini (tırnaklar atlanır) | len(s)."""
    derin, j = 1, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = s.find("'", j + 1)
            j = len(s) if k < 0 else k + 1
            continue
        if c == '"':
            j = _cift_tirnak_sonu(s, j + 1)
            continue
        if c == "(":
            derin += 1
        elif c == ")":
            derin -= 1
            if derin == 0:
                return j
        j += 1
    return len(s)


def _ansi_c(s, i):
    """$'…' (i: açılış tırnağından sonrası) → (çözülmüş metin, kapanıştan sonraki dizin)."""
    out, j = [], i
    while j < len(s):
        c = s[j]
        if c == "'":
            return "".join(out), j + 1
        if c == "\\" and j + 1 < len(s):
            d = s[j + 1]
            m = _ANSI_SAYI.match(s, j + 1)
            if d in _ANSI:
                out.append(_ANSI[d])
                j += 2
            elif m:
                if m.group(5) is not None:
                    out.append(chr(ord(m.group(5)) & 0x1F))
                else:
                    deger = m.group(1) or m.group(2) or m.group(3)
                    try:
                        out.append(chr(int(deger, 16) if deger else int(m.group(4), 8)))
                    except (ValueError, OverflowError):
                        pass
                j = m.end()
            else:
                out.append("\\" + d)
                j += 2
            continue
        out.append(c)
        j += 1
    return "".join(out), len(s)


class _Komut:
    __slots__ = ("kelimeler", "ic", "yon", "stdin_kabuk")

    def __init__(self):
        self.kelimeler, self.ic, self.yon = [], [], []  # sözcükler, komut ikamesi içleri, (işleç, hedef) yönlendirmeler
        self.stdin_kabuk = False  # kabuk, komutunu standart girdiden okuyor (… | sh)


def _ayristir(s):
    """Kabuk metni → boru hatları [[_Komut]]. Tırnaklar/ters bölüler kaldırılır, $'…' açılır, komut ikamesi ($(…),
    `…`, <(…), >(…)) içeriği ayrıca saklanır (yerinde _ISARET), yorumlar atlanır. Kapanmamış tırnak metnin sonuna dek."""
    hatlar, hat = [], []
    kom = _Komut()
    kel = None  # None = sözcük başlamadı
    yon_op = None  # bir sonraki sözcük bu yönlendirmenin hedefi
    i, n = 0, len(s)

    def sozcuk_bitir():
        nonlocal kel, yon_op
        if kel is not None:
            if yon_op is not None:
                kom.yon.append((yon_op, kel))
                yon_op = None
            else:
                kom.kelimeler.append(kel)
            kel = None

    def komut_bitir():
        nonlocal kom
        sozcuk_bitir()
        if kom.kelimeler or kom.ic or kom.yon:
            hat.append(kom)
        kom = _Komut()

    def hat_bitir():
        nonlocal hat
        komut_bitir()
        if hat:
            hatlar.append(hat)
        hat = []

    def ekle(t):
        nonlocal kel
        kel = (kel or "") + t

    while i < n:
        c = s[i]
        if c in " \t":
            sozcuk_bitir()
            i += 1
        elif c in "\n\r;":
            hat_bitir()
            i += 1
        elif c == "&":
            if s[i + 1:i + 2] == "&":
                hat_bitir()
                i += 2
            elif s[i + 1:i + 2] == ">":  # &> / &>> dosya
                sozcuk_bitir()
                j = i + 2 + (s[i + 2:i + 3] == ">")
                yon_op = s[i:j]
                i = j
            else:
                hat_bitir()
                i += 1
        elif c == "|":
            if s[i + 1:i + 2] == "|":
                hat_bitir()
                i += 2
            else:
                komut_bitir()
                i += 2 if s[i + 1:i + 2] == "&" else 1
        elif c in "()":
            hat_bitir()
            i += 1
        elif c in "<>":
            if s[i + 1:i + 2] == "(":  # süreç ikamesi <(…) >(…)
                j = _kapanis(s, i + 2)
                kom.ic.append(s[i + 2:j])
                ekle(_ISARET)
                i = j + 1
                continue
            if kel is not None and kel.isdigit():  # 2>dosya: tanımlayıcı numarası sözcük değil
                kel = None
            sozcuk_bitir()
            j = i
            while j < n and s[j] in "<>&|-":
                j += 1
            yon_op = s[i:j]
            i = j
        elif c == "#" and kel is None:
            k = s.find("\n", i)
            i = n if k < 0 else k
        elif c == "\\":
            if s[i + 1:i + 2] == "\n":
                i += 2
            else:
                ekle(s[i + 1:i + 2])
                i += 2
        elif c == "'":
            k = s.find("'", i + 1)
            k = n if k < 0 else k
            ekle(s[i + 1:k])
            i = k + 1
        elif c == "$" and s[i + 1:i + 2] == "'":
            metin, i = _ansi_c(s, i + 2)
            ekle(metin)
        elif c == "$" and s[i + 1:i + 3] == "((":  # aritmetik: komut değil
            j = _kapanis(s, i + 2)
            ekle(_ISARET)
            i = min(n, j + 2)
        elif c == "$" and s[i + 1:i + 2] == "(":
            j = _kapanis(s, i + 2)
            kom.ic.append(s[i + 2:j])
            ekle(_ISARET)
            i = j + 1
        elif c == "`":
            j = _ters_tirnak_sonu(s, i + 1)
            kom.ic.append(s[i + 1:j])
            ekle(_ISARET)
            i = j + 1
        elif c == '"':
            j = i + 1
            parca = []
            while j < n and s[j] != '"':
                d = s[j]
                if d == "\\" and j + 1 < n:
                    parca.append(s[j + 1] if s[j + 1] in '$`"\\' else ("" if s[j + 1] == "\n" else "\\" + s[j + 1]))
                    j += 2
                elif d == "$" and s[j + 1:j + 2] == "(" and s[j + 2:j + 3] != "(":
                    k = _kapanis(s, j + 2)
                    kom.ic.append(s[j + 2:k])
                    parca.append(_ISARET)
                    j = k + 1
                elif d == "`":
                    k = _ters_tirnak_sonu(s, j + 1)
                    kom.ic.append(s[j + 1:k])
                    parca.append(_ISARET)
                    j = k + 1
                else:
                    parca.append(d)
                    j += 1
            ekle("".join(parca))
            i = j + 1
        else:
            ekle(c)
            i += 1
    hat_bitir()
    return hatlar


def _yol_adi(t):
    return t.rsplit("/", 1)[-1]


def _ozyinelemeli(belirtecler):
    return any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", t) or t == "--recursive" for t in belirtecler)


def _degisken_coz(t, degiskenler):
    """$AD / ${AD} → bu metinde atanmış değeri (S=sudo; $S reboot); bilinmeyen değişken olduğu gibi kalır."""
    if "$" not in t:
        return t
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: degiskenler.get(m.group(1) or m.group(2), m.group(0)), t)


def _kume_ac(t):
    """Küme açılımı (tek düzey): pre{a,b}post → [prea post, preb post]; `{sudo,reboot}` → sudo reboot."""
    m = re.fullmatch(r"(.*?)\{([^{}]*,[^{}]*)\}(.*)", t, re.S)
    if not m or _ISARET in t:
        return [t]
    return [m.group(1) + x + m.group(3) for x in m.group(2).split(",")]


# Kabuğa DOLAYLI girdi / kalıcılık / geniş yıkım (denetim 2): komut metni görünmeden çalışan kod da onay ister.
_GECICI_DIZIN = re.compile(r"(?:/tmp|/var/tmp|/dev/shm|/run/user/\d+|~/\.cache|\$HOME/\.cache|\$\{HOME\}/\.cache|"
                           r"\$TMPDIR|\$\{TMPDIR\})(?:/|$)")
# kabuk/oturum başlangıç dosyaları, otomatik başlatma, Deskhand'in kendi yapılandırması, ssh/gpg, kullanıcı bin dizinleri:
# buraya yazmak kodu SONRA (görünmeden) çalıştırır ya da güvenlik ayarını değiştirir
_HASSAS_DOSYA = re.compile(
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/(?:\.bashrc|\.bash_profile|\.bash_login|\.bash_logout|\.profile|\.zshrc|"
    r"\.zshenv|\.zprofile|\.zlogin|\.zlogout|\.kshrc|\.mkshrc|\.cshrc|\.tcshrc|\.xprofile|\.xinitrc|\.xsession\w*|"
    r"\.xsessionrc|\.inputrc|\.pam_environment|\.config/fish(?:/.*)?|\.config/autostart(?:/.*)?|"
    r"\.config/autostart-scripts(?:/.*)?|\.config/plasma-workspace(?:/.*)?|\.config/environment\.d(?:/.*)?|"
    r"\.config/systemd(?:/.*)?|\.config/deskhand(?:/.*)?|\.local/share/applications(?:/.*)?|\.local/bin(?:/.*)?|"
    r"bin(?:/.*)?|\.ssh(?:/.*)?|\.gnupg(?:/.*)?|\.config/git/config|\.gitconfig|\.config/kwinrc|\.config/khotkeysrc|"
    r"\.config/kglobalshortcutsrc)/?|/etc/(?:profile|bash\.bashrc|zsh/\S*|environment|sudoers\S*|cron\S*|systemd/\S*|"
    r"xdg/autostart/\S*)")
_GUVENLI_UZANTI = re.compile(r"\.(?:txt|md|log|json|csv|tsv|html?|xml|ya?ml|toml|ini|conf|cfg|out|err|bak|diff|patch|"
                             r"rst|tex|svg|png|jpe?g|gif|pdf)$", re.I)
_KABUK_BASLANGIC_DEGISKEN = {"PROMPT_COMMAND", "PS0", "BASH_ENV", "ENV", "ZDOTDIR", "LD_PRELOAD", "LD_AUDIT",
                             "PROMPT_SUBST", "precmd_functions", "preexec_functions", "fish_greeting"}
_GECMIS = re.compile(r"!(?:!|-?\d+|[^\s=(~!]\S*)|\^[^^]+\^[^^]*\^?")  # !!, !n, !-n, !dizge, ^a^b
_ISTEM_KOMUT = {"history", "fc", "r", "print"}
_AYRIK_BASLATICI = {"systemd-run", "at", "batch", "daemonize", "start-stop-daemon", "nsenter", "unshare", "chroot",
                    "machinectl", "systemd-nspawn", "script", "expect", "sshpass"}
_TMUX_KOMUT = {"new", "new-session", "new-window", "neww", "split-window", "splitw", "send-keys", "send", "respawn-pane",
               "respawn-window", "run-shell", "run", "display-popup", "popup", "pipe-pane", "if-shell", "source-file"}
_GIT_KOD_ANAHTAR = re.compile(r"(?:alias\.[^=]+=\s*!|core\.(?:sshCommand|pager|editor|fsmonitor|hooksPath|askPass|gitProxy)|"
                              r"sequence\.editor|diff\.external|credential\.helper|filter\.\S+\.(?:clean|smudge|process)|"
                              r"uploadpack\.packObjectsHook|protocol\.ext\.allow)", re.I)


def _yaz_hedefleri(komut, arg, kom):
    """Komutun YAZDIĞI dosyalar: yönlendirme (>), tee, cp/mv/install/ln/rsync hedefi, dd of=, truncate/shred."""
    hedef = [h for op, h in kom.yon if ">" in op]
    duz = [a for a in arg if not a.startswith("-")]
    if komut == "tee":
        hedef += duz
    elif komut in ("cp", "mv", "install", "ln", "rsync", "scp") and len(duz) >= 2:
        hedef.append(duz[-1])
    elif komut == "dd":
        hedef += [a[3:] for a in arg if a.startswith("of=")]
    elif komut in ("truncate", "shred"):
        hedef += duz
    elif komut == "sed" and any(a == "-i" or a.startswith(("-i", "--in-place")) for a in arg):
        hedef += duz[1:]
    return hedef


def _dolayli_riskler(komut, arg, kom, degiskenler, sarmalayicilar, derinlik):
    """Kabuğa dolaylı girdi, kalıcılık (başlangıç dosyaları, cron, takma ad), geniş yıkım ve görünmeden çalışan kod."""
    n = []
    duz = [a for a in arg if not a.startswith("-")]
    for h in _yaz_hedefleri(komut, arg, kom):
        if _HASSAS_DOSYA.fullmatch(h.rstrip("/")) or _HASSAS_DOSYA.fullmatch(h):
            n.append(_("kabuk/oturum başlangıç, otomatik başlatma ya da güvenlik dosyasına yazma ({hedef})").format(
                hedef=_ic(h)))
            break
    # yıkıcı komut metnini (sonra çalıştırılabilecek) bir dosyaya yazma: printf 'sudo reboot' > /tmp/a
    if komut in ("echo", "printf", "cat", "tee", "print") and derinlik < 3:
        for op, h in kom.yon:
            if ">" in op and (_GECICI_DIZIN.match(h) or not _GUVENLI_UZANTI.search(h)) and \
                    any(_metin_riskleri(a, derinlik + 1) for a in duz):
                n.append(_("yıkıcı komutu çalıştırılabilecek bir dosyaya yazma ({hedef})").format(hedef=_ic(h)))
                break
    if komut == "eval":
        n.append(_("eval: metni komut olarak çalıştırır (dolaylı yürütme)"))
    if komut in ("source", "."):
        n.append(_("{komut}: dosyadaki komutları bu kabukta çalıştırır (içeriği denetlenemez)").format(komut=_ic(komut)))
    if komut in _KABUK:
        c_var = any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) for a in arg)
        dosya = next((a for a in arg if not a.startswith(("-", "+"))), None)
        if any(op.startswith("<") for op, _h in kom.yon):
            n.append(_("kabuğa yönlendirilmiş girdi (<, <<, <<<): komut metni görünmeden çalışır"))
        elif not c_var and dosya is not None and (_GECICI_DIZIN.match(dosya) or "." not in _yol_adi(dosya) or
                                                  _ISARET in dosya):
            n.append(_("{komut} geçici/uzantısız betiği çalıştırır ({dosya})").format(komut=_ic(komut), dosya=_ic(dosya)))
        elif not c_var and dosya is None:
            kom.stdin_kabuk = True
    if _YORUMLAYICI.fullmatch(komut):
        j = 0
        while j < len(arg):
            a = arg[j]
            if a in ("-m", "-c", "-e", "-E", "-r", "-p", "-W", "-X", "-I", "-x") or re.fullmatch(r"-[a-zA-Z]*[ceEpr]", a):
                break  # modül / satır içi kod (ayrıca denetlenir)
            if not a.startswith("-") or a == "-":
                n.append(_("{komut} betik dosyasını çalıştırır ({dosya}): içeriği denetlenemez").format(komut=_ic(komut), dosya=_ic(a)))
                break
            j += 1
    if komut in ("awk", "gawk", "mawk", "nawk", "busybox-awk") and any(
            re.search(r"\bsystem\s*\(|\|\s*getline|\|\s*[\"']|\bprint\b[^;]*\|", a) for a in arg):
        n.append(_("{komut} programı kabuk komutu çalıştırır (system / boru)").format(komut=_ic(komut)))
    if _GECMIS.fullmatch(komut) or (komut in ("fc", "r")) or (komut == "history" and "-s" in arg) or \
            (komut == "print" and "-s" in arg):
        n.append(_("geçmişten komut çalıştırma/ekleme ({komut}): çalışacak komut görünmez").format(komut=_ic(komut)))
    if komut in ("alias", "trap") and arg:
        n.append(_("{komut}: sonradan (görünmeden) çalışacak komut tanımlar").format(komut=_ic(komut)))
    if komut in ("ln",) and any(_yol_adi(a) in _YETKI | _KABUK for a in duz[:-1]):
        n.append(_("yetki/kabuk programına bağlantı (adını gizler)"))
    if re.match(r"(?:/tmp|/var/tmp|/dev/shm)/", kom.kelimeler[0] if kom.kelimeler else "") or \
            _GECICI_DIZIN.match(next((w for w in kom.kelimeler if not _ATAMA.fullmatch(w)), "")):
        n.append(_("geçici dizinden program çalıştırma"))
    if komut == "kill" and ("-1" in arg[1:] or ("--" in arg and "-1" in arg[arg.index("--"):])):
        n.append(_("kill -1: kullanıcının TÜM süreçlerini sonlandırır"))
    if komut in ("pkill", "killall") and ("-u" in arg or any(a.startswith("--user") for a in arg)):
        n.append(_("{komut} -u: kullanıcının tüm süreçlerini sonlandırır").format(komut=_ic(komut)))
    if komut == "killall5":
        n.append(_("killall5: tüm süreçlere sinyal gönderir"))
    if komut in ("mv", "cp", "rsync") and any(_KOK_HEDEF.fullmatch(a) for a in duz[:-1]) and komut == "mv":
        n.append(_("mv kök/ev dizinini taşır"))
    if komut == "rsync" and any(a.startswith("--delete") for a in arg) and any(_KOK_HEDEF.fullmatch(a) for a in duz):
        n.append(_("rsync --delete kök/ev dizininde: eşleşmeyen her şeyi siler"))
    if komut == "crontab" and any(a != "-l" for a in arg):
        n.append(_("crontab: zamanlanmış görevleri siler/değiştirir"))
    if komut == "git" and "clean" in arg and any(re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) or a == "--force" for a in arg):
        n.append(_("git clean -f: izlenmeyen dosyaları siler (geri alınamaz)"))
    if komut == "git" and any(_GIT_KOD_ANAHTAR.search(arg[j + 1]) for j, a in enumerate(arg[:-1]) if a == "-c"):
        n.append(_("git -c ile kabuk komutu çalıştıran ayar (takma ad / komut kancası)"))
    if komut == "shred":
        n.append(_("shred: dosyayı geri alınamaz biçimde yok eder"))
    if komut == "truncate" and any(re.fullmatch(r"(?:-s|--size=?)0|0", a) for a in arg):
        n.append(_("truncate -s 0: dosyanın içeriğini siler"))
    if komut in _AYRIK_BASLATICI:
        n.append(_("{komut}: komutu uçbirimin dışında/ayrık başlatır (denetlenemez)").format(komut=_ic(komut)))
    if komut == "tmux" and any(a in _TMUX_KOMUT for a in arg) and len(duz) > 1:
        n.append(_("tmux ile ayrık oturumda komut çalıştırma"))
    if komut == "screen" and any(re.fullmatch(r"-[a-zA-Z]*[dD][a-zA-Z]*m?|-X", a) for a in arg):
        n.append(_("screen ile ayrık oturumda komut çalıştırma"))
    if komut == "flock" and any(a in ("-c", "--command") for a in arg):
        n.append(_("flock -c: komutu kabukta çalıştırır"))
    if komut == "rm" and "xargs" in sarmalayicilar:
        n.append(_("xargs rm: listedeki her dosyayı siler"))
    # D-Bus ile güç/oturum: login1 Reboot/PowerOff/Suspend…, org.kde.Shutdown, ksmserver çıkış
    if komut in ("dbus-send", "gdbus", "busctl", "qdbus", "qdbus6", "qdbus-qt5", "dbus-run-session") and any(
            re.search(r"login1|org\.kde\.Shutdown|ksmserver|LogoutPrompt|org\.freedesktop\.(?:PowerManagement|"
                      r"ScreenSaver)", a) for a in arg) and any(
            re.search(r"(?i)reboot|poweroff|power_off|suspend|hibernate|halt|kexec|logout|terminate|kill|shutdown|"
                      r"lock", a) for a in arg):
        n.append(_("D-Bus ile kapatma/yeniden başlatma/askıya alma/oturum kapatma"))
    hedefler = " ".join(arg) + " " + " ".join(kom.ic)
    if komut in ("killall", "pkill", "kill", "kquitapp5", "kquitapp6", "kquitapp", "kwin_x11", "xkill") and re.search(
            r"(?i)plasmashell|kwin|deskhand|ksmserver|kded|plasma|kglobalaccel|xdg-desktop-portal", hedefler):
        n.append(_("masaüstü kabuğunu / pencere yöneticisini / Deskhand'i sonlandırma"))
    if komut == "systemctl" and any(a in ("stop", "kill", "mask", "disable", "restart") for a in arg) and \
            re.search(r"(?i)plasma|kwin|deskhand|graphical|display-manager|sddm|gdm", " ".join(arg)):
        n.append(_("systemctl ile masaüstü/oturum hizmetini durdurma"))
    if derinlik < 3 and komut not in _KABUK and (t0 := (kom.kelimeler[0] if kom.kelimeler else "")) and \
            not _ATAMA.fullmatch(t0) and re.match(r"(?:\./|\.\./|~/|\$HOME/)", t0):
        n.append(_("betik/program dosyasını çalıştırma ({dosya}): içeriği denetlenemez").format(dosya=_ic(t0)))
    if komut in _KABUK and not any(re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) for a in arg):
        dosya = next((a for a in arg if not a.startswith(("-", "+"))), None)
        if dosya is not None and not n:
            n.append(_("{komut} betiği çalıştırır ({dosya}): içeriği denetlenemez").format(komut=_ic(komut), dosya=_ic(dosya)))
    # GTFOBins: seçenekle kabuk komutu çalıştırma
    if any(a.startswith("--checkpoint-action") or a.startswith("--to-command") or a.startswith("--use-compress-program")
           or a.startswith("--rsh-command") for a in arg):
        n.append(_("{komut}: seçenekle kabuk komutu çalıştırır").format(komut=_ic(komut)))
    if komut in ("ssh", "scp", "sftp", "rsync") and re.search(r"(?i)proxycommand|localcommand|permitlocalcommand",
                                                               " ".join(arg)):
        n.append(_("{komut}: ProxyCommand/LocalCommand ile yerel komut").format(komut=_ic(komut)))
    if komut == "rsync" and any(a in ("-e", "--rsh") or a.startswith("--rsh=") for a in arg):
        n.append(_("rsync -e: uzak kabuk yerine yerel komut çalıştırabilir"))
    if komut == "sed" and any(re.search(r"(?:^|[;\s\d/}])e(?:\s|$)|/e\b|s(.).*\1.*\1[gpiI0-9]*e", a)
                              for a in duz[:1] + [a for a in arg if not a.startswith("-")][:1]):
        n.append(_("sed e: komut çalıştırır"))
    if komut == "man" and any(a in ("-P", "--pager") or a.startswith("--pager=") or a.startswith("-P") and len(a) > 2
                              for a in arg):
        n.append(_("man -P: sayfalayıcı yerine komut çalıştırır"))
    if komut == "zip" and any(a in ("-TT", "--unzip-command") or a.startswith("--unzip-command=") for a in arg):
        n.append(_("zip -TT: komut çalıştırır"))
    if komut in ("vim", "vi", "nvim", "view", "ex") and any(re.search(r"^[-+]c?\s*:?\s*!|^\+:?!|:\s*!", a) for a in arg):
        n.append(_("{komut} içinden kabuk komutu").format(komut=_ic(komut)))
    if komut in ("make", "ninja", "cmake") and any(_GECICI_DIZIN.match(a) for a in arg):
        n.append(_("{komut}: geçici dizindeki derleme dosyası komut çalıştırır").format(komut=_ic(komut)))
    if komut == "at" or (komut == "watch" and duz):
        n.append(_("{komut}: komutu sonra/ayrık çalıştırır").format(komut=_ic(komut)))
    return n


def _atama_riski(ad, deger):
    if ad in _KABUK_BASLANGIC_DEGISKEN or (ad in ("PS1", "PS2", "PS4", "RPROMPT", "PROMPT") and
                                          re.search(r"\$\(|`", deger or "")):
        return [_("{ad}: kabuk her istemde/başlangıçta bu kodu çalıştırır").format(ad=_ic(ad))]
    return []


def _komut_riski(kom, degiskenler, derinlik):
    """Tek basit komut → (neden listesi, asıl komut adı)."""
    t = []
    for w in kom.kelimeler:
        t += _kume_ac(_degisken_coz(w, degiskenler))
    nedenler = []
    sarmalayicilar = []
    for op, hedef in kom.yon:
        if ">" in op and _DISK_AYGIT.fullmatch(_degisken_coz(hedef, degiskenler)):
            nedenler.append(_("> /dev/diskaygıtı: diskin üzerine yazar"))
    i = 0
    while i < len(t):
        w = t[i]
        if w in _ANAHTAR:
            i += 1
            continue
        m = _ATAMA.fullmatch(w)
        if m:
            if _ISARET not in m.group(3):
                degiskenler[m.group(1)] = m.group(3)
            nedenler += _atama_riski(m.group(1), m.group(3))
            i += 1
            continue
        if _GECMIS.fullmatch(w):  # !!, !-2, ^a^b: geçmişteki (görünmeyen) komutu çalıştırır
            nedenler.append(_("geçmişten komut çalıştırma/ekleme ({komut}): çalışacak komut görünmez").format(komut=_ic(w)))
            return nedenler, ""
        if "${" in w or _ISARET in w:  # komut adı parametre açılımı / komut ikamesiyle gizlenmiş: ${0:0:0}reboot
            nedenler.append(_("komut adı açılımla gizlenmiş (${{…}} / $(…)): çalışacak komut görünmez"))
        if not w or w.startswith("$") or _ISARET in w:  # bilinmeyen değer komut konumunda: sonrakine bak
            i += 1
            continue
        ad = _yol_adi(w)
        if ad in ("busybox", "toybox"):  # busybox rm -rf ~ → rm
            i += 1
            continue
        if ad == "flock" and any(a in ("-c", "--command") or a.startswith("--command=") for a in t[i + 1:]):
            nedenler.append(_("flock -c: komutu kabukta çalıştırır"))
            return nedenler, ad
        if ad in _SARMALAYICI:
            sarmalayicilar.append(ad)
            secenekler, konumsal = _SARMALAYICI_SECENEK.get(ad, (set(), 0))
            i += 1
            while i < len(t) and t[i].startswith("-") and t[i] != "-":
                o = t[i]
                i += 1
                if o == "--":
                    break
                if ad == "env" and (o in ("-S", "--split-string") or o.startswith("--split-string=")):
                    ic = o.split("=", 1)[1] if "=" in o else (t[i] if i < len(t) else "")
                    if "=" not in o:
                        i += 1
                    if derinlik < 3:
                        nedenler += _metin_riskleri(" ".join([ic, *t[i:]]), derinlik + 1)
                    return nedenler, ""
                if o in secenekler and "=" not in o:
                    i += 1
            i += min(konumsal, max(0, len(t) - i - 1))
            continue
        break
    if i >= len(t):
        for op, h in kom.yon:  # yalnız yönlendirme: `> ~/.bashrc`, `: > dosya`
            if ">" in op and _HASSAS_DOSYA.fullmatch(h):
                nedenler.append(_("kabuk/oturum başlangıç, otomatik başlatma ya da güvenlik dosyasına yazma ({hedef})"
                                  ).format(hedef=_ic(h)))
        return nedenler, ""
    komut, arg = _yol_adi(t[i]), t[i + 1:]
    if komut in _ATAMA_KOMUT:
        for a in arg:
            m = _ATAMA.fullmatch(a)
            if m and _ISARET not in m.group(3):
                degiskenler[m.group(1)] = m.group(3)
            if m:
                nedenler += _atama_riski(m.group(1), m.group(3))
        return nedenler, komut
    nedenler += _dolayli_riskler(komut, arg, kom, degiskenler, sarmalayicilar, derinlik)
    if sarmalayicilar and re.match(r"(?:\./|\.\./|~/|\$HOME/)", t[i]):  # nohup ./k, time ~/x.sh
        nedenler.append(_("betik/program dosyasını çalıştırma ({dosya}): içeriği denetlenemez").format(dosya=_ic(t[i])))
    if komut in ("rm", "mv", "cp", "ln", "chmod", "chown", "truncate", "shred", "tee", "install", "rsync", "unlink") \
            and any(re.search(r"(?:\.config|\.local/state|\.local/share|RUNTIME_DIR|run/user/\d+)/deskhand\b", a)
                    for a in arg):
        nedenler.append(_("Deskhand'in kendi ayar/durum dosyalarını değiştirme (DUR, yasak listesi…)"))
    if komut in _YETKI:
        nedenler.append(_("{komut} ile yetki yükseltme").format(komut=_ic(komut)))
    if komut in _GUC or (komut in ("init", "telinit") and any(a in ("0", "6") for a in arg)):
        nedenler.append(_("sistemi kapatma/yeniden başlatma ({komut})").format(komut=_ic(komut)))
    if komut in ("systemctl", "loginctl") and (any(a in _SISTEMD_GUC for a in arg) or (
            komut == "loginctl" and any(a.startswith(("terminate-", "kill-")) for a in arg))):
        nedenler.append(_("{komut} ile kapatma/yeniden başlatma/askıya alma/oturum sonlandırma").format(komut=_ic(komut)))
    if re.fullmatch(r"mkfs(\.\w+)?", komut):
        nedenler.append(_("mkfs: disk bölümünü biçimlendirir (veri siler)"))
    if komut == "dd" and any(a.startswith("of=/dev/") and not _ZARARSIZ_AYGIT.match(a[3:]) for a in arg):
        nedenler.append(_("dd of=/dev/…: aygıtın üzerine yazar"))
    if komut == "git" and "push" in arg:
        if any(re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) or a.startswith("--force") for a in arg):
            nedenler.append(_("git push --force: uzak geçmişi ezer"))
        elif any(a.startswith("+") and len(a) > 1 for a in arg):
            nedenler.append(_("git push +ref: zorla itme (uzak geçmişi ezer)"))
    if komut in ("chmod", "chown", "chgrp") and _ozyinelemeli(arg) and any(_KOK_HEDEF.fullmatch(a) for a in arg):
        nedenler.append(_("{komut} -R kök/ev/sistem dizininde: tüm dosyaların izin/sahipliğini değiştirir").format(komut=_ic(komut)))
    if derinlik < 3:
        if komut in _KABUK | {"eval"}:  # sh -c "sudo …" / bash -lc … / eval "rm -rf /": gömülü komut da denetlenir
            for j, a in enumerate(arg):
                if komut == "eval" or re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a):
                    nedenler += _metin_riskleri(" ".join(arg[j + (0 if komut == "eval" else 1):]), derinlik + 1)
                    break
            if any(_yol_adi(w) in ("curl", "wget") for x in kom.ic for hat in _ayristir(x) for k_ in hat
                   for w in k_.kelimeler):  # bash <(curl …), sh -c "$(curl …)" (tırnaklı/kaçışlı yazım dahil)
                nedenler.append(_("indirilen betiği doğrudan kabuğa verme (curl/wget … | sh)"))
        if _YORUMLAYICI.fullmatch(komut):  # python3 -c KOD, perl -e KOD …
            for j, a in enumerate(arg):
                if re.fullmatch(r"-[a-zA-Z]*[ceEpr]", a) and j + 1 < len(arg) and _YORUMLAYICI_KOD.search(arg[j + 1]):
                    nedenler.append(_("{komut} ile satır içi kod: dosya silme / komut çalıştırma / dinamik kod").format(
                        komut=_ic(komut)))
                    break
    if komut == "find":
        if "-delete" in arg:
            nedenler.append(_("find -delete: bulunan her şeyi siler (geri alınamaz)"))
        for j, a in enumerate(arg):
            if a in ("-exec", "-execdir", "-ok", "-okdir") and j + 1 < len(arg):
                son = next((n for n in range(j + 1, len(arg)) if arg[n] in (";", "+", "\\;")), len(arg))
                ic = arg[j + 1:son]
                if ic and _yol_adi(ic[0]) == "rm":
                    nedenler.append(_("find -exec rm: bulunan her şeyi siler (geri alınamaz)"))
                elif ic and derinlik < 3:
                    alt = _Komut()
                    alt.kelimeler = ic
                    nedenler += _komut_riski(alt, dict(degiskenler), derinlik + 1)[0]
    # rm: komut konumunda (xargs/env/time sarmalayıcıları atlanmıştı) ya da bir yürütücünün argümanı olarak
    # (sudo rm -rf). echo/grep/man gibi komutların METİN argümanındaki 'rm' sayılmaz.
    j = 0 if komut == "rm" else next((n for n, a in enumerate(arg) if _yol_adi(a) == "rm"), None) \
        if komut in _YETKI else None
    if j is not None:
        sonrasi = arg[j + (0 if komut == "rm" else 1):]
        if _ozyinelemeli(sonrasi) or "--no-preserve-root" in sonrasi:
            tehlikeli = any(_RM_HEDEF.fullmatch(x) for x in sonrasi)
            nedenler.append(_("rm -r: özyinelemeli silme (geri alınamaz)")
                            + (_("; hedef kök/ev dizini ya da *") if tehlikeli else ""))
    return nedenler, komut


def _metin_riskleri(metin, derinlik=0):
    nedenler = []
    if _CATAL_BOMBASI.search(metin):
        nedenler.append(_("çatal bombası (sistemi kilitler)"))
    if _DISK_YONLENDIR.search(metin):
        nedenler.append(_("> /dev/diskaygıtı: diskin üzerine yazar"))
    if _VIM_SUDO.search(metin):
        nedenler.append(_(":w !sudo: dosyayı yetkiyle yazar"))
    hatlar = _ayristir(metin)
    duz = " ; ".join(" | ".join(" ".join(k.kelimeler) for k in hat) for hat in hatlar)  # tırnaksız/kaçışsız hâli
    if _BORU_KABUK.search(metin) or _BORU_KABUK.search(duz):
        nedenler.append(_("indirilen betiği doğrudan kabuğa verme (curl/wget … | sh)"))
    degiskenler = {}
    for hat in hatlar:
        adlar = []
        for kom in hat:
            n_, ad = _komut_riski(kom, degiskenler, derinlik)
            nedenler += n_
            adlar.append(ad)
            if derinlik < 3:
                for ic in kom.ic:  # komut ikamesinin içi de çalışır: $(sudo reboot)
                    nedenler += _metin_riskleri(ic, derinlik + 1)
        indir = next((n for n, a in enumerate(adlar) if a in ("curl", "wget")), None)
        if indir is not None and any(a in _KABUK or a in _YETKI for a in adlar[indir + 1:]):
            nedenler.append(_("indirilen betiği doğrudan kabuğa verme (curl/wget … | sh)"))
        if any(k.stdin_kabuk for k in hat[1:]):
            nedenler.append(_("boru ile kabuğa komut verme (… | sh): çalışacak komut görünmez"))
        cozucu = next((n for n, k in enumerate(hat) if adlar[n] in ("base64", "base32", "xxd", "uudecode", "openssl")
                       and any(a in ("-d", "--decode", "-D", "-r") for a in k.kelimeler)), None)
        if cozucu is not None and cozucu < len(hat) - 1:
            nedenler.append(_("kodlanmış metni çözüp başka komuta verme (base64 -d | …)"))
    return nedenler


# Gizli yazının (secret=true, parola/kart alanı) riskli komut nedeni METİNDEN parça taşımaz: nedenler komut/dosya/geçmiş
# sözcüğünü alıntılar ("geçmişten komut çalıştırma (!Passw0rdZ)"), neden de ret iletisine, onay paneline ve (kart
# kipinde) günlüğe gider (ABM-F2 inceleme-2 P5/P5b). İş parçacığına özgü; yalnız riskli_komut(gizli=True) açar.
_RISK_GIZLI = threading.local()


def _ic(deger):
    """Neden metnine metinden gelen parça: gizli metinde "…" (kalıp adı kalır, içerik gitmez)."""
    return "…" if getattr(_RISK_GIZLI, "acik", False) else deger


def riskli_komut(metin, gizli=False):
    """Metin yıkıcı bir kabuk komutu kalıbına uyuyor mu? → neden metni | None. gizli=True: nedenler yalnız kalıp adını
    taşır (metinden gelen komut/dosya/sözcük "…" olur) ve "(gizli metin; içerik gösterilmiyor)" eki alır; ileti, panel
    ve günlük için güvenlidir. Yalnız METNE bakar; hedef pencerenin
    uçbirim olup olmadığı (ucbirim_mi) çağıranda denetlenir. Metin kabuk kurallarıyla sözcüklere ayrılır (tırnak/ters
    bölü kaldırılır, $'…' açılır, komut ikamesinin içi ayrıca denetlenir); kabuk anahtar sözcükleri ({ } ! if then do…),
    değişken atamaları ve bilinmeyen $DEĞİŞKEN komut adı atlanır, aynı metindeki atama çözülür (S=sudo; $S reboot);
    busybox X → X; sh/bash -c, eval, env -S içi ve python -c / perl -e kodu yeniden denetlenir.
    Dar, gerekçeli kalıplar: geri alınamaz silme (rm -r, find -delete, find -exec rm), yetki yükseltme
    (sudo/doas/pkexec/run0), indirileni kabuğa verme, disk biçimlendirme/üzerine yazma, çatal bombası, kökte toplu
    izin/sahiplik değişikliği, kapatma/yeniden başlatma/askıya alma, zorla git push, :w !sudo."""
    if not metin or not metin.strip():
        return None
    onceki = getattr(_RISK_GIZLI, "acik", False)
    _RISK_GIZLI.acik = onceki or bool(gizli)
    try:
        nedenler = list(dict.fromkeys(_metin_riskleri(metin)))
    finally:
        _RISK_GIZLI.acik = onceki
    if not nedenler:
        return None
    neden = "; ".join(nedenler[:3])
    return _("{neden} (gizli metin; içerik gösterilmiyor)").format(neden=neden) if gizli else neden


# ---------------------------------------------------------------- yasak pencereler

# Kullanıcı dosyasından BAĞIMSIZ, silinemeyen yasaklar: Deskhand paneli ve onay diyaloğu. Ajan bunlara girdi
# gönderebilseydi kendi isteğini onaylayabilir ya da kullanıcının DUR'unu kaldırabilirdi.
YERLESIK_YASAK = (r"^deskhand$", r"^Deskhand — Onay")


def yasak_desenler():
    return list(YERLESIK_YASAK) + _kullanici_yasaklari()


def _kullanici_yasaklari():
    """Kullanıcının yasak desenleri. Panel YETKİLİ kaynaktır (liste_koruma): panel açıksa onun bellekteki kopyası
    (onay kanalından), kapalıysa dosya; panelin işaretlediği dosya kayıp/değişmişse Dur 10 (hiçbir girdi yok).
    İlk kurulumda (işaret yok) dosya yoksa varsayılanla oluşturulur."""
    from .liste_koruma import metin
    icerik = metin("yasak") or ""
    return [l.strip() for l in icerik.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def yasak_denetle(k):
    from . import gorev_kipi
    if gorev_kipi.etkin():  # GÖREV KİPİ: yalnız görev tarayıcısının pencereleri (başka pencere: kapat + Dur 10)
        gorev_kipi.pencere_denetle(sec(), k, adres=_gorev_adresi)
    if k == EKRAN or not k:
        return  # masaüstü kipinde: klavye → etkin pencere (denetle), fare → imlecin altındaki pencere denetlenir
    au = sec()
    b, sinif = au.baslik(k), au.sinif(k)
    for d in yasak_desenler():
        if re.search(d, b, re.I) or re.search(d, sinif, re.I):
            raise Dur(10, _("YASAK pencere: {baslik} (sınıf {sinif}) /{desen}/ ile eşleşti; hiçbir girdi gönderilmez "
                            "({dosya})").format(baslik=baslik_goster(b), sinif=repr(sinif), desen=d, dosya=yollar.yasak_dosya()))


def _gorev_adresi(k) -> str | None:
    """Görev kipi: tarayıcı penceresinin web belgesi adresi (okunamazsa None; okuma araçları ayrıca denetler)."""
    try:
        from . import web
        return web.sayfa_bilgisi(k).get("adres") or None
    except Dur as e:
        if e.kod in (10, 13):
            raise
        return None
    except Exception:  # noqa: BLE001
        return None


def baslatma_yasak_denetle(*metinler):
    """Yasak listesindeki uygulama BAŞLATILMAZ. Steam oyun kimliği (rungameid/ID, -applaunch ID) pencere
    sınıfı biçimine (steam_app_ID) çevrilip o desenlerle de karşılaştırılır."""
    ek = [f"steam_app_{n}" for m in metinler for n in re.findall(r"(?:rungameid/|steam://run/|-applaunch\s+)(\d+)", m or "")]
    for d in yasak_desenler():
        for m in (*metinler, *ek):
            if m and re.search(d, m, re.I):
                raise Dur(10, _("YASAK uygulama: {uygulama} /{desen}/ ile eşleşti; başlatılmadı ({dosya})").format(
                    uygulama=repr(m), desen=d, dosya=yollar.yasak_dosya()))


# ---------------------------------------------------------------- uygulama erişim seviyeleri

# CONFIG_DIR/uygulama-seviyeleri.txt: "DESEN = goruntule | tikla | tam" (DESEN yasak listesindeki gibi başlık/sınıf
# regex'i, # yorum). Dosya yoksa/boşsa HİÇBİR kısıt yoktur (varsayılan kurulumda satır yok; araç kendiliğinden
# uygulama kısıtlamaz). goruntule = hiçbir girdi yok (okuma/ekran görüntüsü serbest); tikla = fare serbest, klavye
# (yaz/tuş/bas) yok; tam = kısıt yok. Birden çok desen uyarsa EN KISITLAYICI seviye geçerlidir. `ac` etkilenmez.
VARSAYILAN_SEVIYE = N_("""# Uygulama erişim seviyeleri: DESEN = goruntule | tikla | tam
#   DESEN: pencere BAŞLIĞI ya da SINIFI için regex (büyük/küçük harf duyarsız), yasak pencereler gibi.
#   goruntule: hiçbir girdi gönderilmez (okuma ve ekran görüntüsü serbest)
#   tikla:     fare serbest, klavye girdisi (yaz/tuş/bas) gönderilmez
#   tam:       kısıt yok (varsayılan; İngilizce eş adlar: view, click, full)
# Birden çok satır uyarsa en kısıtlayıcı olan geçerlidir. Varsayılan: boş (hiçbir kısıt yok).
# Örnekler (başındaki # işaretini kaldırarak açın):
# KeePassXC = goruntule
# konsole = tikla
""")
SEVIYELER = {"goruntule": 0, "view": 0, "tikla": 1, "click": 1, "tam": 2, "full": 2}
_SEVIYE_KOK = {0: "goruntule", 1: "tikla", 2: "tam"}


def seviye_satiri_coz(satir):
    """Bir kural satırı → (desen, seviye 0-2) | None (boş/yorum). Biçimi bozuk satır (= yok, bilinmeyen seviye)
    GÜVENLİ TARAFTA yorumlanır: en kısıtlayıcı seviye (goruntule); panel bozuk satırı kaydetmez (seviye_dogrula)."""
    s = satir.strip()
    if not s or s.startswith("#"):
        return None
    desen, ayrac, sev = s.rpartition("=")
    if not ayrac:
        return s, 0
    desen, sev = desen.strip(), sev.strip().lower()
    return (desen, SEVIYELER.get(sev, 0)) if desen else None


def seviye_kurallari():
    """[(desen, seviye)] (yoksa/boşsa []). Panel YETKİLİ kaynaktır (liste_koruma): panel açıksa onun bellekteki
    kopyası, kapalıysa dosya (OKUNURKEN oluşturulmaz); panelin işaretlediği dosya kayıp/değişmişse Dur 10."""
    from .liste_koruma import metin
    icerik = metin("seviye")
    return [k for k in (seviye_satiri_coz(l) for l in (icerik or "").splitlines()) if k]


def seviye_coz(baslik, sinif, kurallar=None):
    """Pencere başlığı/sınıfı için geçerli seviye (0 goruntule, 1 tikla, 2 tam). Uyan en kısıtlayıcı kural kazanır;
    derlenemeyen desen düz metin olarak aranır (kısıtı sessizce düşürmemek için)."""
    seviye = 2
    for desen, s in (seviye_kurallari() if kurallar is None else kurallar):
        try:
            uydu = re.search(desen, baslik, re.I) or re.search(desen, sinif, re.I)
        except re.error:
            uydu = desen.lower() in baslik.lower() or desen.lower() in sinif.lower()
        if uydu:
            seviye = min(seviye, s)
    return seviye


def seviye_denetle(k, tur):
    """Pencere k'ya `tur` girdisi ("klavye" | "fare") gönderilebilir mi? Kısıtlıysa Dur(10). Kural yoksa (varsayılan)
    arka uca hiç sorulmaz. Masaüstü kipinde (EKRAN) klavye etkin pencereye gider → o denetlenir; fare imlecin
    altındaki pencereyi imlec_alti_denetle denetler."""
    kurallar = seviye_kurallari()
    if not kurallar:
        return
    au = sec()
    if k == EKRAN or not k:
        if tur != "klavye":
            return
        k = au.aktif()
        if not k:
            return  # denetle() etkin pencere belirlenemezse zaten durur
    b, sinif = au.baslik(k), au.sinif(k)
    s = seviye_coz(b, sinif, kurallar)
    if s == 0 or (s == 1 and tur == "klavye"):
        raise Dur(10, _("UYGULAMA SEVİYESİ: {baslik} (sınıf {sinif}) '{seviye}' seviyesinde; {tur} girdisi gönderilmez "
                        "({dosya})").format(baslik=baslik_goster(b), sinif=repr(sinif), seviye=_SEVIYE_KOK[s],
                                            tur=_("klavye") if tur == "klavye" else _("fare"), dosya=yollar.seviye_dosya()))


_FARE_FIILLERI = {"mouseto", "buttondown", "buttonup", "click", "wheel", "hwheel"}
_KLAVYE_FIILLERI = {"key", "keydown", "keyup", "type"}


def girdi_turu(satirlar):
    """dotool satırları → "klavye" | "fare" | None (yalnız ayar satırları: typedelay/typehold). Karışıksa klavye."""
    fiiller = {(s.split(None, 1) or [""])[0] for s in satirlar}
    if fiiller & _KLAVYE_FIILLERI:
        return "klavye"
    if fiiller & _FARE_FIILLERI:
        return "fare"
    return None


def girdi_seviye_denetle(k, satirlar):
    """Arka uçların Girdi.gonder'i, denetle(k, desen)'ten hemen sonra çağırır (iki arka uçta aynı): gönderilecek
    satırların türüne göre uygulama erişim seviyesi. Ayar satırları (typedelay/typehold) denetlenmez. Masaüstü
    kipinde klavye girdisi etkin pencereye gider: o pencere ajanın kendi istemcisiyse ya da onaysız bir sistem
    istemiyse (polkit, KWallet, parola sorucusu…) burada durulur (fare girdisini imlec_alti_denetle denetler)."""
    tur = girdi_turu(satirlar)
    if tur:
        seviye_denetle(k, tur)
    if tur == "klavye" and (k == EKRAN or not k):
        a = sec().aktif()
        if a:
            kendi_istemci_denetle(a)
            sistem_istemi_denetle(a)


# ---------------------------------------------------------------- pencere / başlık / sınıf kilidi

class GonderilmediDur(Dur):
    """Girdi öncesi ret: ileti "<neden>; girdi gönderilmedi". Eksiz neden `.neden`'de: yazı ORTASINDA (önceki harfler
    gitmişken) çağıran eki atar ve "N karakter gönderildi" der (eylem._harf_harf_yaz kesik; ABM-F2 R2-1)."""

    def __init__(self, kod, neden, tur=None):
        super().__init__(kod, _("{neden}; girdi gönderilmedi").format(neden=neden), tur)
        self.neden = neden


# Gizli yazı (secret=true) sırasında durma iletileri pencere BAŞLIĞINI taşımaz: düzenleyiciler başlığa içerik önizlemesi
# yazar (KWrite "Başlıksız (j) *"), yoklama ile tuş arasındaki yarışta sızan gizli harf başlıktan iletiye/günlüğe/MCP
# sonucuna geçerdi (ABM-F2 inceleme P3). İş parçacığına özgü (denetle/odak yoklaması yazı iş parçacığında); gözcüler
# kendi iş parçacığında koşar, Girdi.gizli'ye kendileri bakar (kwin) ya da eylem kesintiyi yeniden kurar (kde/sanal).
_BASLIK_GIZLI = threading.local()


class baslik_gizle:  # noqa: N801 - bağlam yöneticisi, işlev gibi kullanılır
    """`with baslik_gizle(acik):` boyunca (acik doğruysa) bu iş parçacığındaki durma iletileri başlık yerine
    "(başlık gizlendi)" yazar (baslik_goster). İç içe kullanılabilir; açık olan kapanmaz."""

    def __init__(self, acik=True):
        self.acik = bool(acik)

    def __enter__(self):
        self.onceki = getattr(_BASLIK_GIZLI, "acik", False)
        _BASLIK_GIZLI.acik = self.onceki or self.acik
        return self

    def __exit__(self, *_a):
        _BASLIK_GIZLI.acik = self.onceki
        return False


def gizli_yer() -> str:
    """secret=true çıktısında (sonuç alanı, günlük/etkinlik akışı) gizli metni ya da önizlemesini taşıyabilecek her
    metnin yerine konan sabit."""
    return _("(gizli yazı: gizlendi)")


def baslik_goster(b, baska=False) -> str:
    """Durma iletisinde başlık: normalde repr(b); baslik_gizle altında gizli yer tutucu (baska: odağı çalan pencere)."""
    if getattr(_BASLIK_GIZLI, "acik", False):
        return _("başka bir pencere (başlık gizlendi)") if baska else _("(başlık gizlendi)")
    return repr(b)


def sinif_denetle(k):
    if SINIF_DESEN:
        sinif = sec().sinif(k)
        if not re.search(SINIF_DESEN, sinif, re.I):
            raise GonderilmediDur(4, _("pencere sınıfı uymadı: {sinif} (beklenen /{desen}/)").format(
                sinif=repr(sinif), desen=SINIF_DESEN))


def hedef_pencere_denetle(k):
    """Bir pencereye girdi gitmeden önceki pencere kuralları (başlık/sınıf kilidi hariç): yasak (10), ajanın kendi
    istemcisi (10), onaysız sistem istemi (10). Tıklamanın düştüğü pencere (imleç altı) için de kullanılır."""
    yasak_denetle(k)
    kendi_istemci_denetle(k)
    sistem_istemi_denetle(k)


def denetle(k, desen):
    """Girdi göndermeden HEMEN önce: pencere hâlâ aktif mi, yasak değil mi, ajanın kendi istemcisi ya da onaysız
    sistem istemi değil mi, başlık (sekme) doğru mu."""
    au = sec()
    if k == EKRAN:  # masaüstü kipi: etkin pencere yasak olmasın; -b verildiyse etkin pencerenin başlığı uysun
        a = au.aktif()
        if not a:  # boşsa yasak denetimi atlanırdı (yasak pencere öndeyken bile) → doğrulanamadı = dur
            raise GonderilmediDur(3, _("etkin pencere belirlenemedi"))
        yasak_denetle(a)
        if desen and not re.search(desen, au.baslik(a), re.I):
            raise Dur(4, _("etkin pencere başlığı uymadı: {baslik} (beklenen /{desen}/)").format(
                baslik=baslik_goster(au.baslik(a)), desen=desen))
        sinif_denetle(a)
        return
    a = au.aktif()  # boşsa doğrulanamadı → a != k → durur (güvenli taraf)
    if a != k:
        e = hedef_kayip_hatasi(k, a)
        raise GonderilmediDur(e.kod, e.mesaj)
    pencere_denetle(k, desen)


def hedef_kayip_hatasi(k, a) -> Dur:
    """Hedef `k` etkin değil (etkin: `a`): pencere kapandıysa 8 "hedef pencere kapandı" (aynı başlıklı kardeşin öne
    geçmesi "aktif değişti" diye yanıltmasın), yoksa 3 "aktif pencere değişti → başlık" (baslik_gizle altında başlık
    yerine "başka bir pencere (başlık gizlendi)"). İleti "girdi gönderilmedi" EKİ TAŞIMAZ: çağıran ekler (yazı ortasında
    önceki harfler gitmiştir). Yalnız ret yolunda ek sorgu yapar."""
    au = sec()
    try:
        au.geometri(k)
    except Dur as e:
        if e.kod == 8:
            return Dur(8, _("hedef pencere kapandı"))
    if getattr(_BASLIK_GIZLI, "acik", False):
        return Dur(3, _("aktif pencere değişti → {baslik}").format(baslik=baslik_goster(None, baska=True)))
    try:
        b = au.baslik(a) if a else ""
    except Dur:
        b = "?"
    return Dur(3, _("aktif pencere değişti → {baslik}").format(baslik=baslik_goster(b)))


# Kimlik kilidi (B2): kimlik/ref verilen eylem başlığa değil kimliğe kilitlenir; kimliğe ek olarak pencerenin SINIFI
# eylem başında tutulur (X kimliği yeniden kullanılırsa aynı kimlik başka uygulamaya geçer). İş parçacığına özgü: eylem
# denetle() çağrıları aynı iş parçacığında; gözcü kimliği (UUID) zaten yoklar.
_KIMLIK_KILIDI = threading.local()


class sinif_kilidi:  # noqa: N801 - bağlam yöneticisi, işlev gibi kullanılır
    """`with sinif_kilidi(k):` boyunca pencere_denetle(k, …) pencerenin sınıfının eylem başındakiyle aynı olduğunu da
    denetler (değiştiyse 4). AÇIK-BAŞARISIZ (bilerek): sınıf okunamaz ya da boşsa kilit KURULMAZ ve eylem durdurulmaz;
    koruma kimlik + etkin pencere denetimiyle sürer (KWin'de kimlik UUID, yeniden kullanılmaz). Sınıfı hiç bildirmeyen
    pencereye eylem bu yüzden reddedilmez; kilit yalnız X kimliği yeniden kullanımına (sanal/Xvfb) karşı ek katmandır."""

    def __init__(self, k):
        self.k = k

    def __enter__(self):
        self.onceki = getattr(_KIMLIK_KILIDI, "sinif", None)
        sinif = None
        if self.k and self.k != EKRAN:
            try:
                sinif = sec().sinif(self.k)
            except Dur:
                sinif = None
        _KIMLIK_KILIDI.sinif = (self.k, sinif) if sinif else None
        return self

    def __exit__(self, *_a):
        _KIMLIK_KILIDI.sinif = self.onceki
        return False


def _sinif_kilidi_denetle(k):
    kilit = getattr(_KIMLIK_KILIDI, "sinif", None)
    if not kilit or kilit[0] != k:
        return
    simdi = sec().sinif(k)
    if simdi != kilit[1]:
        raise GonderilmediDur(4, _("pencere sınıfı değişti: {once} → {simdi} (aynı kimlik başka uygulamanın)").format(
            once=repr(kilit[1]), simdi=repr(simdi)))


def pencere_denetle(k, desen):
    """denetle'nin pencere kilitleri, ETKİN pencere şartı OLMADAN: yasak pencere (10), ajanın kendi istemcisi (10),
    onaysız sistem istemi (10), başlık (4) ve sınıf (4) kilidi. Odağı almayan yollar (erişilebilirlik eylemi:
    erisim.py) için; fare/klavye yolunun denetle()'siyle aynı sonuç."""
    au = sec()
    hedef_pencere_denetle(k)
    if desen:
        b = au.baslik(k)
        if not re.search(desen, b, re.I):
            raise GonderilmediDur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/)").format(
                baslik=baslik_goster(b), desen=desen))
    sinif_denetle(k)
    _sinif_kilidi_denetle(k)


def imlec_alti_denetle(k, px=None, py=None):
    """mouseto'dan sonra, tıklamadan ÖNCE (tek sorgu): (1) imleç gerçekten hedef noktada mı — kullanıcı
    arada fareyi oynattıysa tıklama başka yere düşerdi → 12; (2) altındaki pencere hedef mi? Yasak / ajanın kendi
    istemcisi / onaysız sistem istemi → 10; başka uygulamanın penceresi (bildirim, üstte duran pencere) → 3. Aynı
    uygulamanın açılır menüsü serbest."""
    au = sec()
    fx, fy, w = au.fare()
    if px is not None and fx is not None and (abs(fx - px) > 2 or abs(fy - py) > 2):
        raise Dur(12, _("imleç hedefte değil ({fx},{fy} ≠ {px},{py}): kullanıcı fareyi oynattı (insan önceliği); "
                        "tıklanmadı").format(fx=fx, fy=fy, px=px, py=py))
    if not w:  # imlecin altı bilinemedi: neyin üstüne tıklanacağı doğrulanamaz → dur (güvenli taraf)
        raise Dur(3, _("imlecin altındaki pencere doğrulanamadı; tıklanmadı"))
    if w == k:
        return
    hedef_pencere_denetle(w)
    seviye_denetle(w, "fare")  # imlecin altındaki başka pencere 'goruntule' seviyesinde olabilir
    if k == EKRAN:
        return
    if au.sinif(w) != au.sinif(k):
        raise Dur(3, _("imlecin altında başka pencere var: {baslik}; tıklanmadı").format(baslik=baslik_goster(au.baslik(w))))


# ---------------------------------------------------------------- hassas düğme / ödeme sayfası

_EYLEM = threading.local()  # iş parçacığı başına: bu eylem için insan onayı alındı mı


def eylem_basladi():
    """Her eylemin başında (eylem.girdi_al) çağrılır: önceki eylemin onayı yeni eyleme TAŞINMAZ."""
    _EYLEM.onaylandi = False
    _EYLEM.sistem_onay = set()  # bu eylemde onaylanan sistem istemi pencereleri


def _panelden_onay(eylem, hedef, ayrinti, goruntu=None, ajan_eylem=None, konu=None):
    """Paneldeki insandan bir kez izin (CONTRACT §8). → (izin, neden). Panel/onay modülü yoksa (False, neden).
    Aynı eylemde ikinci hassas denetim (sayfa + düğme) yeniden sormaz: bir eylem = bir onay.
    goruntu: hedefin küçük görüntüsü (PIL) — kullanıcı NEYİ onayladığını görür.
    ajan_eylem: ajana dönen Dur iletisindeki eylem metni. eylem EKRANDAN OKUNAN metin taşıyorsa (uçbirim satırı)
    çağıran genel metin verir: ham OCR yalnız insan paneline gider (SINIF-MASKE).
    konu: isteğin türü (ONAY_KONULARI; panel türü YALNIZ bu yapısal alandan alır, UX-C-R1); verilmezse çağıranın kendi
    eylem şablonundan (onay_konusu), o da yoksa alan yazılmaz → panelde "Bilinmeyen istek"."""
    if getattr(_EYLEM, "onaylandi", False):
        return True, _("bu eylem için zaten onaylandı")
    try:
        from . import onay
    except Exception as e:  # noqa: BLE001
        return False, _("onay modülü yüklenemedi: {hata}").format(hata=e)
    try:
        if konu is None:
            konu = onay_konusu(eylem)
        ek = {"konu": konu} if konu in ONAY_KONULARI and _konu_destekli(onay.iste_sonuc) else {}
        s = onay.iste_sonuc(eylem, hedef, ayrinti, masaustu=sec().ad, goruntu=goruntu, **ek)
    except Dur as e:  # gerçek ekran kilidi (17): onayı NEYİN tetiklediği iletide görünsün
        neden_satiri = (ayrinti or "").splitlines()[0] if ayrinti else ""
        raise Dur(e.kod, e.mesaj + "; " + _("onay gerekçesi: {eylem} — {neden}").format(
            eylem=ajan_eylem or eylem, neden=neden_satiri or hedef), tur=e.tur) from None
    if s.izin:
        _EYLEM.onaylandi = True
    return s.izin, s.mesaj


def _konu_destekli(iste) -> bool:
    """onay.iste_sonuc writes the structural "konu" field (UX-C-R1 onay.py patch); an older core / a test double
    without the parameter still works (the panel then shows "Bilinmeyen istek")."""
    import inspect
    try:
        return "konu" in inspect.signature(iste).parameters
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- onay iletisi (panel diyaloğu, insan dili; UX-C, R1)
# The panel turns a request into one FIXED "what will happen" sentence (per kind; it never carries requester/page data)
# + one risk line + one visible "content" line (the button/command/key the user is approving, quoted, single line,
# cleaned of bidi/zero-width/line-break characters, cut at ONAY_ICERIK_SINIR) + one visible "requester" line; the
# full raw strings go to the folded details. The KIND comes from the request's structural field "konu" (written by the
# requester at creation, covered by the request's sha256 like every field; devir/dur from onay's own "tur"); matching
# the action text against the requester templates is only a presentation aid (content field) and a consistency check:
# no "konu", an unknown one or one that contradicts the action template → "bilinmeyen" (neutral sentence, raw action on
# top, details open). Presentation only: who approves, timeout → deny and the default button are unchanged.
ONAY_KONULARI = ("odeme", "dugme", "tus", "ucbirim", "pano", "sistem", "parola", "uygulama", "diger")
ONAY_TURLERI = (*ONAY_KONULARI, "devir", "dur", "bilinmeyen")
ONAY_ICERIK_SINIR = 80

# requester's action template (msgid; its translations are matched too) → kind
_ONAY_EYLEM_SABLON = (
    (N_("Düğmeye tıkla: “{dugme}”"), "dugme"),
    (N_("Hassas sayfada {eylem}"), "odeme"),
    (N_("Kart bilgisi yaz"), "odeme"),
    (N_("Riskli tuş: {kombinasyon}"), "tus"),
    (N_("Uçbirime komut yaz: {komut}"), "ucbirim"),
    (N_("Uçbirimde komut çalıştır: {satir}"), "ucbirim"),
    (N_("Komut başlat: {komut}"), "ucbirim"),
    (N_("Panoyu yapıştır"), "pano"),
    (N_("Panoyu oku"), "pano"),
    (N_("Sistem istemine girdi: {ad}"), "sistem"),
    (N_("Parola alanına yaz"), "parola"),
    (N_("Uygulama başlat: {ad}"), "uygulama"),
)
# MCP tool names used as the action (mcp_sunucu._onay_iste): fixed identifiers, never translated. The handoff
# ("human_verification") is NOT here: a handoff is only what onay's "tur" says (ORTA 3)
_ONAY_ARAC = {"clipboard": "pano", "run_flow": "diger"}
# MCP fallback path: action = tool name, details = the guard's stop message → kind by the message's fixed prefix
_ONAY_DUR_ONEK = (("HASSAS düğme", "dugme"), ("HASSAS sayfa", "odeme"), ("HASSAS: kart", "odeme"),
                  ("HASSAS: parola", "parola"), ("HASSAS pano", "pano"), ("RİSKLİ TUŞ", "tus"),
                  ("UÇBİRİM", "ucbirim"), ("RİSKLİ KOMUT", "ucbirim"), ("SİSTEM İSTEMİ", "sistem"))
# fields shown WHOLE (never cut) in the dialog's monospace scroll box: what the terminal/keyboard will receive
_ONAY_KUTU_ALAN = frozenset(("komut", "satir", "kombinasyon"))
# content line label per captured template field (kind-specific for "ad")
_ONAY_ICERIK_ETIKET = {"dugme": N_("Düğme"), "komut": N_("Komut"), "satir": N_("Komut"), "kombinasyon": N_("Tuş"),
                       "eylem": N_("İşlem"), ("sistem", "ad"): N_("İstem"), ("uygulama", "ad"): N_("Uygulama")}
_ONAY_TUR_CUMLE = {
    "odeme": N_("Claude, ödeme yapabilecek bir işlem için izin istiyor."),
    "dugme": N_("Claude, geri alınamaz olabilecek bir düğmeye basmak istiyor."),
    "tus": N_("Claude, riskli bir tuş kısayoluna basmak istiyor."),
    "ucbirim": N_("Claude, uçbirimde bir komut çalıştırmak istiyor."),
    "pano": N_("Claude, panonuzdaki metni kullanmak istiyor."),
    "devir": N_("Claude sizi bekliyor: bir insan doğrulamasını (CAPTCHA) sizin çözmeniz gerekiyor."),
    "sistem": N_("Claude, bir sistem izin/parola penceresine girdi göndermek istiyor."),
    "parola": N_("Claude, bir parola alanına yazmak istiyor."),
    "uygulama": N_("Claude, doğrulanmamış bir uygulamayı başlatmak istiyor."),
    "dur": N_("Bir komut DUR anahtarını kaldırmak istiyor."),
    "diger": N_("Claude bir işlem için izninizi istiyor."),
    "bilinmeyen": N_("Bilinmeyen istek: Claude'un ne yapmak istediği doğrulanamadı."),
}
_ONAY_RISK = {
    "odeme": N_("Bu bir ödeme işlemi olabilir; para çekilebilir."),
    "dugme": N_("Bu düğme yetki verme ya da hesap silme gibi geri alınamaz bir iş yapabilir."),
    "tus": N_("Bu kısayol pencereyi ya da oturumu kapatabilir; kaydedilmemiş iş kaybolabilir."),
    "ucbirim": N_("Bu komut dosyaları silebilir ya da sistemi değiştirebilir."),
    "pano": N_("Panoda parola ya da özel bilgi olabilir; Claude bu metni görebilir."),
    "devir": N_("Claude doğrulamayı çözmez; siz çözmezseniz iş burada durur."),
    "sistem": N_("Bu pencere bilgisayarınızda yönetici yetkisi verebilir."),
    "parola": N_("Parola hesabınıza erişim verir; yalnız siz istediyseniz izin verin."),
    "uygulama": N_("Bu uygulamanın ne yapacağı doğrulanamadı; tanımıyorsanız reddedin."),
    "dur": N_("DUR kalkınca Claude yeniden girdi gönderebilir; siz istemediyseniz reddedin."),
    "diger": N_("Ne yapılacağı yukarıda yazıyor; emin değilseniz reddedin."),
    "bilinmeyen": N_("Türü doğrulanamayan bu istek geri alınamaz bir iş yapabilir; tanımıyorsanız reddedin."),
}
_GIZLI_IZ = re.compile(r"\*\*\*\(\d+\)")  # _yazilacak(…, gizli=True): only the length of a secret text
_SABLON_ONBELLEK: dict = {}
_SATIR_SONU = frozenset("\r\n\v\f\x1c\x1d\x1e\x85  ")
_ALINTI = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"'})  # the content line's own quotes stay the only ones


def _gorunur(s: str, satir_sonu: str = " ⏎ ") -> str:
    """Text the page/application controls, made safe to SHOW: format characters (bidi controls U+202A–202E,
    U+2066–2069, zero-width U+200B–200F, BOM…) removed, line breaks → satir_sonu, other control characters → space."""
    import unicodedata
    out = []
    for ch in str(s):
        if ch in _SATIR_SONU:
            out.append(satir_sonu)
            continue
        k = unicodedata.category(ch)
        if k == "Cf":
            continue
        out.append(" " if k in ("Cc", "Zl", "Zp") else ch)
    return "".join(out)


def onay_tek_satir(s: str, sinir: int | None = ONAY_ICERIK_SINIR, kisaltma_eki: bool = False) -> str:
    """One display line: _gorunur + whitespace collapsed + cut at `sinir` characters ("…"; None = never cut).
    kisaltma_eki: a cut is announced visibly ("… (kısaltıldı)")."""
    s = " ".join(_gorunur(s).split())
    if sinir is None or len(s) <= sinir:
        return s
    return s[:sinir - 1].rstrip() + "…" + (" " + _("(kısaltıldı)") if kisaltma_eki else "")


def _sablon_deseni(sablon: str):
    d = _SABLON_ONBELLEK.get(sablon)
    if d is None:
        parca = re.split(r"\{(\w+)\}", sablon)
        d = re.compile("".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>.*)" for i, p in enumerate(parca)), re.S)
        _SABLON_ONBELLEK[sablon] = d
    return d


def _sablon_cevirileri(msgid: str) -> list[str]:
    """msgid + every catalog translation of it (the requester may run in another language than the panel)."""
    from . import i18n
    out = [msgid]
    for kod in getattr(i18n, "DILLER", {}):
        c = _SABLON_ONBELLEK.setdefault(("katalog", kod), i18n.katalog_oku(kod)).get(msgid)
        if c and c not in out:
            out.append(c)
    return out


def _onek_cevirileri(onek: str) -> list[str]:
    """A stop message's fixed prefix + its translations: the catalog value of every message starting with it, cut at
    the first "(" (the prefix shape: "HASSAS düğme (…" → "SENSITIVE button"). Prefixes shorter than 6 are dropped.
    Presentation/consistency aid only (the kind is the request's "konu")."""
    anahtar = ("onek", onek)
    if anahtar not in _SABLON_ONBELLEK:
        from . import i18n
        out = [onek]
        for kod in getattr(i18n, "DILLER", {}):
            for k, v in _SABLON_ONBELLEK.setdefault(("katalog", kod), i18n.katalog_oku(kod)).items():
                if k.startswith(onek):
                    p = v.split("(")[0].strip()
                    if len(p) >= 6 and p not in out:
                        out.append(p)
        _SABLON_ONBELLEK[anahtar] = out
    return _SABLON_ONBELLEK[anahtar]


def _sablon_turu(eylem: str, ayrinti: str = "") -> tuple[str | None, dict]:
    """What the action TEXT looks like (presentation aid + consistency check, never the kind decision):
    → (kind or None, fields captured from the requester's template)."""
    if eylem in _ONAY_ARAC:
        return _ONAY_ARAC[eylem], {}
    for sablon, t in _ONAY_EYLEM_SABLON:
        for metin in _sablon_cevirileri(sablon):
            m = _sablon_deseni(metin).fullmatch(eylem)
            if m:
                alan = m.groupdict()
                if t == "dugme" and para_mi(alan.get("dugme", "")):
                    t = "odeme"
                return t, alan
    ilk = ayrinti.lstrip()
    for onek, t in _ONAY_DUR_ONEK:
        for metin in _onek_cevirileri(onek):
            if ilk.startswith(metin):
                if t == "dugme" and para_mi(ayrinti):
                    t = "odeme"
                return t, {}
    return None, {}


_PARA_CIFTI = frozenset(("dugme", "odeme"))


def _onay_turu(istek: dict) -> tuple[str, dict]:
    """→ (kind, fields captured from the action text). Kind = onay's "tur" (devir/dur) or the declared "konu"; a
    missing/unknown "konu", or one the action template contradicts → "bilinmeyen". A button the template sees as a
    money button stays "odeme" (never downgraded)."""
    tur, eylem, ayrinti = istek.get("tur") or "", str(istek.get("eylem") or ""), str(istek.get("ayrinti") or "")
    if tur == "devir":
        return "devir", {}
    if tur == "dur":
        return "dur", {}
    konu = istek.get("konu")
    konu = konu if isinstance(konu, str) and konu in ONAY_KONULARI else ""
    gorunen, alan = _sablon_turu(eylem, ayrinti)
    if not konu:
        return "bilinmeyen", alan
    if gorunen and gorunen != konu and not {gorunen, konu} <= _PARA_CIFTI:
        return "bilinmeyen", alan
    if {gorunen, konu} <= _PARA_CIFTI and "odeme" in (gorunen, konu):
        return "odeme", alan
    return konu, alan


def onay_konusu(eylem: str) -> str:
    """Requester side (guvenlik._panelden_onay): the kind of a request whose caller did not declare one, from the
    caller's OWN template (built by Deskhand code a moment ago, page data only inside a quoted field). "" = unknown."""
    t, _alan = _sablon_turu(str(eylem))
    return t if t in ONAY_KONULARI else ""


def _yasak_baslik_mi(hedef: str) -> bool:
    try:
        desenler = yasak_desenler()
    except Exception:  # noqa: BLE001 - list unreadable (e.g. tampered): the built-in ones still apply
        desenler = list(YERLESIK_YASAK)
    for d in desenler:
        try:
            if re.search(d, hedef, re.I):
                return True
        except re.error:
            continue
    return False


def _surec_adi(pid, pid_bas) -> str:
    """The requester's process name (/proc/<pid>/comm, ≤ 15 characters, set by the process itself: shown, not
    trusted) — only while the process is the one that wrote the request (start time = the request's "pid_bas", against
    PID reuse); "" otherwise / unreadable."""
    from .onay import _baslangic
    if not pid_bas or _baslangic(pid) != str(pid_bas):
        return ""
    try:
        with open(f"/proc/{int(pid)}/comm", encoding="utf-8", errors="replace") as f:
            return onay_tek_satir(f.read(64).strip(), 32)
    except (OSError, ValueError, TypeError):
        return ""


def onay_iletisi(istek: dict) -> dict:
    """Panel onay diyaloğunun metni (insan dili, panelin dilinde). → {"tur", "baslik", "risk", "icerik", "isteyen",
    "hedef", "ayrinti"}: baslik = türün SABİT cümlesi (istekten veri taşımaz), risk = tek satır risk, icerik = üstte
    görünen "Düğme: “Öde”" / "Komut: 'rm -rf ~'" / "Tuş: ctrl+w" / (bilinmeyen, diğer) "Eylem: …" (temiz; ad ve eylem
    ≤ ONAY_ICERIK_SINIR + görünür "(kısaltıldı)"; komut/tuş ASLA kesilmez: icerik_kutu=True → diyalog kaydırmalı kutu;
    icerik_etiket/icerik_deger ayrı), isteyen = "<süreç adı> (PID n)", hedef = gösterilecek pencere adı, ayrinti = katlanır alanın
    metni (ham eylem, hedef, ham ayrıntı, isteyen süreç; görünmez karakterler temiz). Gizli yazı yalnız sabit yer
    tutucuyla görünür (gizli_yer); gizli yazının eşlik ettiği istekte ya da yasak pencerede başlık "(başlık gizlendi)"
    olur ve hiçbir alanda geçmez."""
    eylem, hedef = str(istek.get("eylem") or ""), str(istek.get("hedef") or "")
    ham_ayrinti = str(istek.get("ayrinti") or "")
    tur, alan = _onay_turu(istek)
    gizli_var = bool(_GIZLI_IZ.search(eylem) or _GIZLI_IZ.search(ham_ayrinti))
    baslik_gizli = bool(hedef.strip()) and (gizli_var or _yasak_baslik_mi(hedef))
    gizli_baslik = _("(başlık gizlendi)")

    def temiz(s: str) -> str:
        s = _GIZLI_IZ.sub(lambda _m: gizli_yer(), str(s))
        if baslik_gizli:
            s = s.replace(hedef, gizli_baslik)
        return s

    icerik_etiket = icerik_deger = ""
    kutu = False
    if tur in ("bilinmeyen", "diger"):  # the raw action may BE a command: whole, in the scroll box (UX-C-R1c)
        icerik_etiket, icerik_deger, kutu = _("Eylem"), onay_tek_satir(temiz(eylem), None), True
    elif tur not in ("devir", "dur"):
        for k, v in alan.items():
            etiket = _ONAY_ICERIK_ETIKET.get((tur, k)) or _ONAY_ICERIK_ETIKET.get(k)
            if etiket and v.strip():
                kutu = k in _ONAY_KUTU_ALAN
                if kutu:  # command / key: NEVER cut (the dangerous part may be at the end)
                    icerik_deger = onay_tek_satir(temiz(v.strip()), None)
                elif k == "dugme":  # page-controlled name: quoted, cut with a visible mark, whole in the details
                    d = onay_tek_satir(temiz(v.strip()).translate(_ALINTI), ONAY_ICERIK_SINIR - 2)
                    icerik_deger = f"“{d}”" + (" " + _("(kısaltıldı)") if d.endswith("…") else "")
                else:
                    icerik_deger = onay_tek_satir(temiz(v.strip()), kisaltma_eki=True)
                icerik_etiket = _(etiket)
                break
    icerik = f"{icerik_etiket}: {icerik_deger}" if icerik_etiket else ""
    pid = istek.get("pid")
    isteyen = ""
    if pid:
        ad = _surec_adi(pid, istek.get("pid_bas"))
        isteyen = f"{ad} (PID {pid})" if ad else f"PID {pid}"
    satirlar = [_("Eylem") + ": " + _gorunur(temiz(eylem))]  # temiz first: the hidden title is matched raw
    if hedef.strip():
        satirlar.append(_("Pencere") + ": " + (gizli_baslik if baslik_gizli else _gorunur(hedef)))
    if ham_ayrinti.strip():
        satirlar.append(_("Ayrıntı") + ": " + _gorunur(temiz(ham_ayrinti), "\n"))
    if isteyen:
        satirlar.append(_("İsteyen süreç") + ": " + isteyen)
    return {"tur": tur, "baslik": _(_ONAY_TUR_CUMLE[tur]), "risk": _(_ONAY_RISK[tur]), "icerik": icerik,
            "icerik_etiket": icerik_etiket, "icerik_deger": icerik_deger, "icerik_kutu": kutu,
            "isteyen": isteyen, "hedef": gizli_baslik if baslik_gizli else onay_tek_satir(hedef, 200, kisaltma_eki=True),
            "ayrinti": "\n".join(satirlar)}


ONAY_GORUNTU =(480, 200)  # onay isteğindeki küçük görüntü: tıklama noktasının çevresi (pencere pikseli)


def hedef_goruntusu(k, nokta=None):
    """Onay isteği için hedefin küçük görüntüsü: nokta verildiyse çevresi (nokta kırmızı çerçeveyle işaretli),
    yoksa pencerenin küçültülmüşü. Alınamazsa None (onay yine sorulur, yalnız görüntüsüz)."""
    try:
        from PIL import ImageDraw

        from .gorsel import pencere_goruntusu
        if nokta is None:
            im, _geo, kok = pencere_goruntusu(k)
            bolge = (kok[0], kok[1], im.width, im.height)
            im = im.copy()
            im.thumbnail((640, 400))
            im.info["deskhand_bolge"] = bolge  # kırpılan bölge (pencere pikseli): onay sonrası doğrulama için
            return im
        x, y = round(nokta[0]), round(nokta[1])
        gw, gh = ONAY_GORUNTU
        im, _geo, (bx, by) = pencere_goruntusu(k, (x - gw // 2, y - gh // 2, gw, gh))
        im = im.convert("RGB")
        im.info["deskhand_bolge"] = (bx, by, im.width, im.height)
        d = ImageDraw.Draw(im)
        px, py = x - bx, y - by
        d.rectangle([px - 14, py - 14, px + 14, py + 14], outline=(230, 30, 30), width=3)
        return im
    except Exception:  # noqa: BLE001 - görüntü isteğe bağlı
        return None


def _nokta_ayrintisi(nokta, yakin):
    if nokta is None:
        return ""
    yazi = " | ".join(t for t in yakin if t) or _("(okunamadı)")
    return "\n" + _("{x},{y} noktasındaki yazı: {yazi}").format(x=round(nokta[0]), y=round(nokta[1]), yazi=yazi)


_CIKIS = threading.local()  # goto: adres çubuğuna yazılan adres + Enter (sayfadan ÇIKIŞ) bu iş parçacığında


class sayfadan_cikis:
    """`with guvenlik.sayfadan_cikis(k, metin):` (gezin.adrese_git): bu blokta k penceresine TAM OLARAK `metin`
    yazılırken (adres + Enter) ödeme sayfası kapısı, odak erişilebilirlik ağacında DOĞRULANMIŞ biçimde belge DIŞINDAYSA
    (adres çubuğu) onay sormaz: Enter yalnız gezinir, formu gönderemez. Odak bilinmiyor/sayfa içindeyse kural aynen."""

    def __init__(self, k, metin):
        self.deger = (k, metin)

    def __enter__(self):
        self.eski = getattr(_CIKIS, "deger", None)
        _CIKIS.deger = self.deger
        return self

    def __exit__(self, *a):
        _CIKIS.deger = self.eski
        return False


def adres_cubugu_cikisi_mi(k, metin) -> bool:
    """Yazı (metin) goto'nun adres çubuğuna yazdığı adres + Enter mi VE odak şu an belge dışında mı (doğrulanmış)?"""
    d = getattr(_CIKIS, "deger", None)
    if d is None or d[0] != k or metin is None or d[1] != metin:
        return False
    try:
        from .erisim import odak_bilgisi
        odak = odak_bilgisi(k)
    except Exception:  # noqa: BLE001 - bilinmiyor: kural aynen
        return False
    return isinstance(odak, dict) and not odak.get("belge_ici", True)


def hassas_sayfa_engel(k, onayli, ne, yakin=(), nokta=None, ek="", goruntu_al=True, ek_basliklar=(), metin=None):
    """Başlığı ödeme/onay sayfası olan pencerede eylem (tıklama, Enter/boşluk, Enter/boşluklu yazı) onay ister.
    yakin: tıklanacak noktadaki yazılar, nokta: (x, y) pencere pikseli, ek: ayrıntıya eklenecek satır (tuş, yazı),
    goruntu_al: onay isteğine hedefin küçük görüntüsü eklensin mi (pencereyi öne getirir).
    ek_basliklar: pencere başlığına EK olarak denetlenecek başlıklar (web: erişilebilirlik ağacından gelen belge başlığı).
    Onay isteği noktadaki yazıyı, hassas düğme metnini ve hedefin küçük görüntüsünü taşır (kullanıcı NEYİ
    onayladığını görür); aynı eylemdeki hassas düğme denetimi yeniden sormaz. → sayfa hassas mı."""
    b = sec().baslik(k)
    kalip = hassas_sayfa_kalibi()
    m = kalip.search(katla(b))
    for eb in ek_basliklar:
        if m:
            break
        m = kalip.search(katla(eb or ""))
        if m:
            b = eb
    onayli = onayli_gecerli_kati(onayli)
    if m and not onayli and adres_cubugu_cikisi_mi(k, metin):  # goto: sayfadan çıkış, odak adres çubuğunda
        from .gunluk import gunluk
        gunluk(f"hassas sayfa | [{b}] | goto: odak adres çubuğunda (belge dışı) → onaysız gezinme")
        return False  # onay alınmadı (gerekmedi): çağıran eylemi "onaylı" diye etiketlemesin
    if m and not onayli:
        ayrinti = _("Sayfa başlığı ödeme/onay sayfası gibi: {eslesen}").format(eslesen=repr(m.group(0)))
        ayrinti += _nokta_ayrintisi(nokta, yakin)
        dugme = next((t for t in yakin if t and HASSAS.search(katla(t))), None)
        if dugme:
            ayrinti += "\n" + _("Hassas düğme: “{dugme}”").format(dugme=dugme)
        if ek:
            ayrinti += "\n" + ek
        # goruntu_al=False: görüntü pencereyi öne getirirdi (odak çalmayan yollarda istenmez)
        goruntu = None if getattr(_EYLEM, "onaylandi", False) or not goruntu_al else hedef_goruntusu(k, nokta)
        izin, neden = _panelden_onay(_("Hassas sayfada {eylem}").format(eylem=ne), b, ayrinti, goruntu, konu="odeme")
        if not izin:
            raise Dur(10, _("HASSAS sayfa ({eslesen} ← {baslik}): bu sayfada {eylem} kullanıcının onayını ister "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=repr(m.group(0)), baslik=baslik_goster(b), eylem=ne, neden=neden), tur="hassas")
    return bool(m)


def para_mi(*metinler):
    """Metinlerden biri para düğmesi (satın al / öde / siparişi onayla…) mi? (onay kapsamı "kart")"""
    for t in metinler:
        m = PARA_DUGMESI.search(katla(t or ""))
        if m:
            return m.group(0)
    return None


def hassas_mi(*metinler):
    for t in metinler:
        m = HASSAS.search(katla(t or ""))
        if m:
            return m.group(0)
    return None


DUZENLEME_PAYI = 2  # px: OCR satır kutusu ↔ erişilebilirlik kutusu karşılaştırmasında yuvarlama payı


def _kapsar(dis, ic, pay=DUZENLEME_PAYI) -> bool:
    """dis (x, y, w, h) kutusu ic (x, y, w, h) kutusunu (pay ile) tamamen içeriyor mu?"""
    return (dis[0] - pay <= ic[0] and dis[1] - pay <= ic[1] and ic[0] + ic[2] <= dis[0] + dis[2] + pay
            and ic[1] + ic[3] <= dis[1] + dis[3] + pay)


def _kesisir(a, b) -> bool:
    """İki (x, y, w, h) kutusu pozitif alanla kesişiyor mu?"""
    return min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0]) and min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1])


def _eylem_adi(a) -> str:
    return re.sub(r"[^a-z]", "", str(a or "").lower())


# Tıklama SAYILMAYAN eylemler: odak, bağlam menüsü, kaydırma. ÜST ögenin tıklaması ("click ancestor" / Firefox
# "clickAncestor") TIKLAMA SAYILIR: Firefox onclick'li atanın position:absolute çocuğuna da verir, çocuk atanın
# kutusundan taşıp alanı örtebilir (gerçek Firefox 161, SONKAPI-B B4). Bedeli: kökünde tıklama dinleyicisi olan
# sayfalarda (React #root, body onclick) alan içeriği ayıklanmaz, onay sorulur (güvenli taraf; ARCHITECTURE bilinen sınır).
_ZARARSIZ_EYLEM = re.compile(r"^(?:setfocus|focus|grabfocus|showmenu|scroll\w*)$")
_ALAN_EYLEMI = frozenset({"activate"})  # metin alanının olağan eylemi (Firefox/Chromium textarea, GTK entry)


def tiklanir_mi(eylemler, alan=False) -> bool:
    """Ögenin KENDİ tıklama eylemi var mı? eylemler None (okunamadı / bilinmiyor) → True (kanıt yok = tıklanır say);
    adı boş eylem → True. alan=True: metin alanının olağan "activate" eylemi tıklama sayılmaz."""
    if eylemler is None:
        return True
    for a in eylemler:
        n = _eylem_adi(a)
        if n and (_ZARARSIZ_EYLEM.search(n) or (alan and n in _ALAN_EYLEMI)):
            continue
        return True
    return False


def alan_kanitli_mi(ad, eylemler) -> bool:
    """Düzenlenebilir alan (rol/durum sağlayıcıda denetlendi) hassas düğme bağlamında ALAN sayılabilir mi: erişilebilir
    adı hassas/para kalıbına uymuyor (role=textbox + aria-label="Pay now" → sayfa rolü/durumu belirler;
    INCELEME-HASSAS D1) VE kendi tıklama eylemi yok (contenteditable + onclick); eylemler okunamadıysa alan değil."""
    ad = ad or ""
    return not (hassas_mi(ad) or para_mi(ad) or tiklanir_mi(eylemler, alan=True))


def duzenleme_kabi_mi(kutu, eylemler, alanlar) -> bool:
    """Etkileşimsiz öge bir düzenlenebilir alanın zararsız KABI mı (alana değen satırı geçersiz kılmaz): kutusu bir alanı
    tamamen kapsıyor VE tıklanmadığı kanıtlı (eylemleri okundu; kendi ya da atasının tıklaması yok). Alanı saran/örten
    tıklanır öge (onclick'li div, şeffaf örtü) HİÇBİR BOYUTTA kap sayılmaz: görüş alanını (ya da bir iframe'i) dolduran
    onclick'li sarmalayıcı ile sayfa düzeyi dinleyici (React kökü) ağaçtan ayırt edilemez (INCELEME-HASSAS O2,
    SONKAPI-A B2 P1/P1b)."""
    if not alani_kapsar_mi(kutu, alanlar):
        return False
    return not tiklanir_mi(eylemler)


def alani_kapsar_mi(kutu, alanlar) -> bool:
    """(x, y, w, h) kutusu alanlardan birini (ilk dört öge: kutu) tamamen kapsıyor mu?"""
    return any(_kapsar(kutu, a) for a in alanlar)


def _hassas_terimler(metin) -> set:
    """Satırdaki hassas düğme / para / yapıştırma kalıbı eşleşmeleri (katlanmış metin parçaları; 📋 olduğu gibi)."""
    s = str(metin or "")
    k = katla(s)
    terimler = {m.group(0) for kalip in (HASSAS, PARA_DUGMESI) for m in kalip.finditer(k)}
    terimler.update(m.group(0) for m in _YAPISTIR_METIN.finditer(katla(s.replace("&", ""))))
    if "\U0001f4cb" in s:
        terimler.add("\U0001f4cb")
    return terimler


def _sozcukle(metin: str, parca: str) -> bool:
    """parca katlanmış metinde kelime sınırlı geçiyor mu?"""
    return re.search(r"(?<!\w)" + re.escape(parca) + r"(?!\w)", metin) is not None


def _degerde_mi(satir, deger: str) -> bool:
    """OCR satırı alanın DEĞERİNİN ekrandaki parçası olarak kanıtlanıyor mu? Terimsiz satır (hassas/para/yapıştırma
    eşleşmesi yok) hiçbir zaman (boş küme tuzağı: SONKAPI-A B3). Kanıt (katlanmış metinde): satır değerin bir mantıksal
    satırına TAM eşit, YA DA satırdaki her terim satırdaki komşu sözcüğüyle (sol ya da sağ) değerde de BİTİŞİK geçiyor
    (yumuşak kaydırma satırı keser, OCR uçları bozabilir: biri yeter). Değerin başka bir yerinde geçen terim yetmez:
    alana boyanmış tek "Pay" + değer "I will pay later" → kanıt yok (P6)."""
    terimler = _hassas_terimler(satir)
    if not terimler:
        return False
    ks, kd = katla(str(satir).replace("&", "")), katla(deger.replace("&", ""))
    if "\U0001f4cb" in terimler and "\U0001f4cb" not in deger:
        return False
    if ks and any(ks == katla(s.replace("&", "")) for s in deger.splitlines()):
        return True
    yazili = terimler - {"\U0001f4cb"}
    if not yazili:
        return False  # yalnız 📋: bağlamı yazıyla doğrulanamaz (tam satır eşleşmesi yukarıda)
    for t in yazili:
        kanit = False
        for m in re.finditer(r"(?<!\w)" + re.escape(t) + r"(?!\w)", ks):
            sol, sag = ks[:m.start()].split()[-1:], ks[m.end():].split()[:1]
            if (sol and _sozcukle(kd, f"{sol[0]} {t}")) or (sag and _sozcukle(kd, f"{t} {sag[0]}")):
                kanit = True
                break
        if not kanit:
            return False
    return True


def duzenleme_icerigini_ayikla(yakin, alanlar, digerleri=(), dugmeler=(), kaplar=()):
    """Hassas düğme bağlamı: tıklanan noktanın OCR komşu satırlarından (ocr.NoktaYazisi, kutu = x, y, x2, y2 pencere
    pikseli) bir DÜZENLENEBİLİR ALANIN İÇERİĞİ olduğu KANITLANANLARI ayıkla (textarea'daki "Buy/Pay buttons…" yazısı
    düğme değildir). Kutular (x, y, w, h) pencere pikseli, erişilebilirlik ağacından:
      alanlar   — kanıtlı düzenlenebilir alanlar (x, y, w, h, değer): değer alanın metni (okunamadı → None / yok);
      dugmeler  — etkileşimli ögeler (düğme, bağlantı, salt okunur ya da kanıtsız alan…);
      digerleri — etkileşimsiz ögeler (metin, bölüm, tıklanır ya da eylemi bilinmeyen kap…);
      kaplar    — alanı kapsayan, tıklanmadığı kanıtlı kaplar (duzenleme_kabi_mi).
    Kanıt: satır kutusu bir alanın içinde VE satıra hiçbir düğme ya da etkileşimsiz öge değmiyor (alanı saran/örten
    tıklanır öge dahil) VE satıra değen her kap o alanı kapsıyor VE satır alanın DEĞERİNİN parçası (_degerde_mi: tam
    satır ya da her terim komşu sözcüğüyle; terimsiz satır hiç; değer bilinmiyorsa kanıt yok).
    Kutusuz yazı (düz str: hedefin kendi adı, ajanın aradığı metin, eski çağıranlar) HİÇBİR ZAMAN ayıklanmaz.
    → (kalan, ayıklanan)."""
    kalan, ayiklanan = [], []
    for t in yakin:
        k = getattr(t, "kutu", None)
        satir = (k[0], k[1], k[2] - k[0], k[3] - k[1]) if k and len(k) == 4 else None
        icerik = False
        if (satir is not None and satir[2] > 0 and satir[3] > 0
                and not any(_kesisir(d, satir) for d in (*dugmeler, *digerleri))):
            for a in alanlar:
                if not _kapsar(a, satir):
                    continue
                if any(_kesisir(o, satir) and not _kapsar(o, a) for o in kaplar):
                    continue  # alanın içinde/üstünde başka bir öge satıra değiyor: içerik olduğu kanıtlanamadı
                deger = a[4] if len(a) > 4 else None
                if not isinstance(deger, str):
                    continue  # alanın değeri bilinmiyor: satırın alanın yazısı olduğu kanıtlanamadı
                if not _degerde_mi(t, deger):
                    continue  # terimsiz satır ya da hassas sözcük değerde bağlamıyla yok: boyanmış/bindirilmiş yazı
                icerik = True
                break
        (ayiklanan if icerik else kalan).append(t)
    return kalan, ayiklanan


# Menüden yapıştırma (Yapıştır / Paste / Einfügen … ya da "Ctrl+V" kısayol ipucu): kısayolla yapıştırma ile aynı kural.
_YAPISTIR_METIN = re.compile(r"^\W{0,2}(?:yapistir|paste|einfugen|coller|pegar|incolla|plakken|wklej|vlozit|"
                             r"beillesztes|klistra in|lim inn|indsaet|liita)\b|\b(?:ctrl|strg)[\s+]*(?:shift[\s+]*)?v\b|"
                             r"\bshift[\s+]*ins(?:ert)?\b|\bpanodan\b|\bfrom (?:the )?clipboard\b|\bozel yapistir|"
                             r"\bpaste (?:as|special|without)\b|\baus der zwischenablage\b|\bdu presse-papiers\b", re.I)
_YAPISTIR_OGE = re.compile(r"paste|yapistir|einfug|coller|pegar|incolla|plakken|wklej|clipboard|pano", re.I)


def yapistirma_metni_mi(*metinler):
    """Tıklanacak hedefin yazısı (OCR) bir yapıştırma eylemi mi (kısa metin; menü ögesi, "Panodan ekle", "Paste as…",
    "Özel yapıştır", "Ctrl+V" ipucu, 📋)?"""
    return any(t and len(t) <= 48 and ("\U0001f4cb" in t or _YAPISTIR_METIN.search(katla(t.replace("&", ""))))
               for t in metinler)


def yapistirma_ogesi_mi(*adlar):
    """AT-SPI ögesinin adı / eylem adı (simgeli düğmenin erişilebilir adı dahil) yapıştırma İÇERİYOR mu?"""
    return any(a and len(a) <= 64 and (_YAPISTIR_OGE.search(katla(a.replace("&", ""))) or "\U0001f4cb" in a)
               for a in adlar)


def hassas_engel(onayli, *metinler, hedef="", k=None, nokta=None):
    """Hassas düğme (Satın al / Öde / Yetkilendir / Hesabı sil…) onay ister. k + nokta verildiyse onay isteği
    noktadaki yazıyı ve çevresinin küçük görüntüsünü taşır."""
    if k is not None:
        kart_tampon_sifirla(k)  # tıklama: odak/alan değişti, parça parça yazılan numara birleştirilmez
    if yapistirma_metni_mi(*metinler):  # kde: menüden yapıştırma da kullanıcının panosunu taşır
        yapistirma_engel(k, onayli)
    eslesen = para_mi(*metinler) if onay_kapsami() == "kart" else hassas_mi(*metinler)  # kart: yalnız para düğmesi
    onayli = onayli_gecerli_kati(onayli)
    if eslesen and not onayli:
        yakin = [m for m in metinler if m]
        asil = next((m for m in yakin if (PARA_DUGMESI if onay_kapsami() == "kart" else HASSAS).search(katla(m))),
                    eslesen)  # kullanıcıya ekrandaki yazı gösterilir
        ayrinti = _("Ödeme/yetki/hesap silme gibi hassas bir düğme") + _nokta_ayrintisi(nokta, yakin)
        goruntu = None if k is None or getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k, nokta)
        izin, neden = _panelden_onay(_("Düğmeye tıkla: “{dugme}”").format(dugme=asil), hedef or " / ".join(yakin[:2]),
                                     ayrinti, goruntu, konu="odeme" if para_mi(asil) else "dugme")
        if not izin:
            raise Dur(10, _("HASSAS düğme ('{eslesen}' ← {yakin}): ödeme/yetki/hesap silme kullanıcının kararı "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=eslesen, yakin=yakin, neden=neden), tur="hassas")
    return eslesen


def _yazilacak(metin, gizli):
    """Onay isteğinde gösterilecek yazı: TAMAMI (repr; kesilmez — uzun komutun tehlikeli SON kısmı görünmeden izin
    verilmesin, UX-C-R1b); --gizli ise yalnız uzunluk. Yalnız insan paneline gider (ajana dönen iletiye konmaz)."""
    return f"***({len(metin)})" if gizli else repr(metin)


def riskli_tus_engel(k, onayli, kombinasyon, birlikte=False):
    """Oturumu/sistemi sonlandıran ya da ekrandan çıkaran tuş kombinasyonu (riskli_tus) onay ister: --onayli yoksa
    panelden insan onayı, panel kapalıysa/red/gözetimsiz kipte Dur(10). → kombinasyon riskli mi (onaylandı)."""
    neden = riskli_tus(kombinasyon, birlikte)
    if not neden:
        return False
    if onaysiz_serbest("riskli tuş", kombinasyon):
        return False
    if not onayli_gecerli(onayli):
        b = sec().baslik(k) if k and k != EKRAN else ""
        goruntu = None if getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k)
        izin, onay_neden = _panelden_onay(_("Riskli tuş: {kombinasyon}").format(kombinasyon=kombinasyon), b,
                                          neden + "\n" + _("tuş: {kombinasyon}").format(kombinasyon=kombinasyon), goruntu,
                                          konu="tus")
        if not izin:
            raise Dur(10, _("RİSKLİ TUŞ ({kombinasyon}): {neden}; kullanıcının onayını ister ({onay_neden}); kullanıcı "
                            "sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                kombinasyon=kombinasyon, neden=neden, onay_neden=onay_neden), tur="hassas")
    return True


def ucbirim_komut_engel(k, onayli, metin, gizli=False, goruntu_al=True):
    """Hedef pencere bir uçbirimse (ucbirim_mi) ve yazılacak metin yıkıcı komut kalıbına uyuyorsa (riskli_komut)
    onay ister (riskli_tus_engel ile aynı yol). Komut, yazılmadan ÖNCE yakalanır: Enter ayrı gönderilse bile.
    Onay isteği komutu (kısaltılmış) taşır. Yazıda Enter (\n) varsa sorulmaz: her Enter zaten Enter kapısında onay
    ister (ucbirim.enter_kapisi) ve bu uyarıyı taşır — iki diyalog açılmasın. → uçbirimde riskli komut mu (onaylandı)."""
    if "\n" in metin:
        return False
    neden = riskli_komut(metin, gizli=gizli)  # ucuz ön eleme: sınıf sorgusu (kde: kdotool) yalnız eşleşince; gizli:
    # neden yalnız kalıp adı (ileti, panel ve kart kipinde günlük metinden parça taşımaz)
    if not neden:
        return False
    au = sec()
    pen = k if k and k != EKRAN else au.aktif()
    sinif = au.sinif(pen) if pen else ""
    if not pen or not ucbirim_penceresi_mi(pen):  # sınıf ya da gömülü uçbirim (süreç ağacı)
        return False
    if onaysiz_serbest("uçbirime yıkıcı komut yazma", neden):
        return False
    if not onayli_gecerli(onayli):
        b = au.baslik(pen)
        ayrinti = neden + "\n" + _("uçbirim: {sinif}").format(sinif=sinif) + "\n" + \
            _("yazılacak: {metin}").format(metin=_yazilacak(metin, gizli))
        goruntu = None if getattr(_EYLEM, "onaylandi", False) or not goruntu_al else hedef_goruntusu(pen)
        # secret text: the title may preview it (editors/terminals) → the request (panel + log) carries no title
        izin, onay_neden = _panelden_onay(_("Uçbirime komut yaz: {komut}").format(komut=_yazilacak(metin, gizli)),
                                          _("(başlık gizlendi)") if gizli else b, ayrinti, goruntu, konu="ucbirim")
        if not izin:
            with baslik_gizle(gizli):  # CLI yolu da: gizli yazının iletisinde başlık (önizleme) yok
                bg = baslik_goster(b)
            raise Dur(10, _("UÇBİRİM KOMUTU ({neden} ← {baslik}): yıkıcı olabilecek komutu uçbirime yazmak kullanıcının "
                            "onayını ister ({onay_neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile "
                            "tekrarla").format(neden=neden, baslik=bg, onay_neden=onay_neden), tur="hassas")
    return True


def baslatma_komut_engel(komut_metni, onayli=False):
    """Ham komut satırıyla uygulama başlatma (CLI `ac --komut`, MCP open_app args): komut yıkıcı bir kabuk kalıbına
    uyuyorsa (riskli_komut: rm -r, sudo, curl | sh…) insan onayı ister (uçbirime yazmayla aynı kalıp ve aynı onay yolu;
    gözetimsiz kipte --onayli geçmez). Red → Dur(10), HİÇBİR şey başlatılmaz. → riskli miydi (onaylandı)."""
    neden = riskli_komut(komut_metni)
    if not neden:
        return False
    if onaysiz_serbest("ac --komut yıkıcı komut", neden):
        return False
    eylem_basladi()  # başlatma kendi eylemi: önceki eylemin onayı taşınmaz
    if not onayli_gecerli(onayli):
        izin, onay_neden = _panelden_onay(_("Komut başlat: {komut}").format(komut=_yazilacak(komut_metni, False)),
                                          _("uygulama başlatma"), neden + "\n" + _("komut: {komut}").format(
                                              komut=_yazilacak(komut_metni, False)), konu="ucbirim")
        if not izin:
            raise Dur(10, _("RİSKLİ KOMUT BAŞLATMA ({neden}): yıkıcı olabilecek komutu başlatmak kullanıcının onayını "
                            "ister ({onay_neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile "
                            "tekrarla").format(neden=neden, onay_neden=onay_neden), tur="hassas")
    return True


def onayli_gecerli(onayli):
    """--onayli (kullanıcı sohbette açıkça onayladı) geçerli mi? Gözetimsiz kipte sohbet/insan yoktur: --onayli
    sayılmaz, onay gerektiren her eylem reddedilir (onay.iste_sonuc 'gozetimsiz')."""
    return bool(onayli) and not gozetimsiz()


# ---------------------------------------------------------------- onay kapsamı (ayarlar.toml [guvenlik] onaylar)

ONAY_KAPSAMLARI = ("hepsi", "kart")
_KAPSAM = {"zaman": -1e9, "deger": "hepsi"}
KAPSAM_ONBELLEK_SN = 1.0


def onay_kapsami(taze=False) -> str:
    """Hangi eylemler insan onayı ister: "hepsi" (VARSAYILAN: ARCHITECTURE §4'teki tüm onaylar) | "kart"
    (yalnız kartla ödeme: para düğmesi/ödeme sayfası ve kart bilgisi yazma). Kipi okuyan TEK yer. Değer PANEL
    YETKİLİDİR (liste_koruma.kapsam): panelin doğrulanmış onay kanalından alınır, ayarlar.toml'a elle yazılmış `kart`
    geçmez; panel kapalı / kanal doğrulanamıyor → "hepsi" (güvenli taraf). Süreç içinde kısa önbellek."""
    import time as _t
    if not taze and _t.monotonic() - _KAPSAM["zaman"] < KAPSAM_ONBELLEK_SN:
        return _KAPSAM["deger"]
    try:
        from . import liste_koruma
        d = liste_koruma.kapsam()
    except Exception:  # noqa: BLE001 - doğrulanamadı: güvenli taraf
        d = "hepsi"
    if d not in ONAY_KAPSAMLARI:
        d = "hepsi"
    _KAPSAM.update(zaman=_t.monotonic(), deger=d)
    return d


def onay_kapsami_sifirla():
    """Önbelleği at (ayar yazıldıktan sonra / testler)."""
    _KAPSAM["zaman"] = -1e9


def onaysiz_serbest(ne: str, ayrinti: str = "") -> bool:
    """kart kipinde SERBEST bırakılan onay noktaları için tek koşul: True → onay sorulmaz (tek satır günlük
    yazılır; ayrıntıda gizli içerik olmamalı). "hepsi" kipinde False (bugünkü davranış). GÖREV KİPİNDE
    (DESKHAND_GOREV=1, gorev_kipi.ONAYI_ACIK: parola alanı + sistem istemi) kapsam `kart` olsa da False: "hepsi" gibi."""
    if onay_kapsami() != "kart":
        return False
    from . import gorev_kipi
    if gorev_kipi.etkin() and ne in gorev_kipi.ONAYI_ACIK:
        return False
    from .gunluk import gunluk
    gunluk(f"onay kapsamı kart: onaysız geçti | {ne}" + (f" | {ayrinti}" if ayrinti else ""))
    return True


def onayli_gecerli_kati(onayli) -> bool:
    """Kart sınıfı (para düğmesi, ödeme sayfası, kart bilgisi yazma) için --onayli geçerli mi? "kart" kipinde
    CLI --onayli YOK SAYILIR: onay HER ZAMAN panelden (terminali serbest ajan CLI'yi --onayli ile çağırıp atlatamasın).
    "hepsi" kipinde onayli_gecerli ile aynı."""
    if onay_kapsami() == "kart":
        return False
    return onayli_gecerli(onayli)


# ---------------------------------------------------------------- ajanın kendi istemcisi (deskhand/kendi.py)

def _pencere_pid(au, k):
    f = getattr(au, "pid", None)
    if f is None:
        return None
    try:
        return f(k) or None
    except Dur:
        return None


def kendi_istemci_denetle(k):
    """Pencere, Deskhand'i çalıştıran ajanın KENDİ istemcisi mi (sahibi ata süreç: Claude Code'un uçbirimi…)? → Dur 10.
    Ajan kendi izin istemine tuş/yazı/tık gönderip kendini onaylayamasın. Okuma/ekran görüntüsü serbesttir."""
    if not k or k == EKRAN:
        return
    from . import kendi
    au = sec()
    pid = _pencere_pid(au, k)
    sinif = au.sinif(k)
    r = kendi.kendi_mi(pid, sinif, au.ad, ucbirim_mi)
    if not r:
        return
    tur, ayr = r
    neden = {"pid": _("pencerenin sahibi süreç ({pid}) bu ajanı çalıştıran süreç zincirinde").format(pid=ayr),
             "coklayici": _("uçbirim çoklayıcısı (tmux/screen/zellij) çözülemedi: tüm uçbirim pencereleri korunur"),
             "sinif": _("PID'i bilinmeyen uçbirim penceresi, ajanın uçbirimiyle aynı türde")}[tur]
    raise Dur(10, _("AJANIN KENDİ İSTEMCİSİ: {baslik} (sınıf {sinif}): {neden}; ajan kendi izin istemini "
                    "onaylayamasın diye bu pencereye hiçbir girdi gönderilmez (okuma serbest)").format(
        baslik=baslik_goster(au.baslik(k)), sinif=repr(sinif), neden=neden))


# ---------------------------------------------------------------- sistem yetki/parola istemleri

# Sistem yetki / parola / izin istemleri: YASAK değil, her girdi insan onayı ister (onaysız 10, gözetimsiz kipte ret).
# Tek sabit liste; pencere SINIFINDA ve sahibi sürecin adında (comm 15 karakterle kısalır: polkit-kde-auth,
# xdg-desktop-por) sözcük olarak aranır.
SISTEM_ISTEMLERI = (
    r"polkit[\w-]*", r"lxpolkit", r"lxqt-policykit[\w-]*", r"hyprpolkitagent", r"kwalletd\d*", r"ksecretd",
    r"kwallet-query", r"ksshaskpass\d*", r"(?:x11-)?ssh-askpass[\w-]*", r"pinentry[\w-]*", r"xdg-desktop-por[\w-]*",
    r"org\.freedesktop\.impl\.portal[\w.-]*", r"kdesu(?:do)?", r"gcr-prompter", r"sudo", r"pkexec", r"run0",
)
_SISTEM_ISTEMI = re.compile(r"(?<![a-z0-9])(?:" + "|".join(SISTEM_ISTEMLERI) + r")(?![a-z0-9])", re.I)
_SISTEM_ONBELLEK = {}  # (arka uç, kimlik) → (zaman, ad | None)


def sistem_istemi_mi(k):
    """Pencere bir sistem yetki/parola/izin istemi mi (polkit aracısı, KWallet, ksshaskpass/pinentry, xdg-desktop-portal
    izin diyaloğu, kdesu)? → tanınan ad | None. Sınıf + sahibi sürecin adı (comm/exe); 2 sn önbellek."""
    if not k or k == EKRAN:
        return None
    import time as _t
    au = sec()
    sinif = au.sinif(k)
    anahtar = (au.ad, k, sinif)
    kayit = _SISTEM_ONBELLEK.get(anahtar)
    if kayit and _t.monotonic() - kayit[0] < 2.0:
        return kayit[1]
    adlar = [sinif]
    pid = _pencere_pid(au, k)
    if pid:
        from . import kendi
        adlar += list(kendi.surec_adi(pid))
    ad = next((m.group(0) for m in (_SISTEM_ISTEMI.search(a or "") for a in adlar) if m), None)
    if len(_SISTEM_ONBELLEK) > 256:
        _SISTEM_ONBELLEK.clear()
    _SISTEM_ONBELLEK[anahtar] = (_t.monotonic(), ad)
    return ad


def sistem_istemi_denetle(k):
    """Girdiden HEMEN önce: sistem istemine bu eylemde onay alınmadıysa Dur 10 (onay eylem başında
    sistem_istemi_engel ile sorulur; sorulmamış her yol burada güvenli tarafta durur)."""
    if onay_kapsami() == "kart":  # kart kipi: sistem istemleri onaysız (kullanıcı kararı)
        return
    ad = sistem_istemi_mi(k)
    if ad and k not in getattr(_EYLEM, "sistem_onay", set()):
        raise Dur(10, _("SİSTEM İSTEMİ: {baslik} ({ad}) bir yetki/parola/izin istemi; girdi kullanıcının onayını ister "
                        "(bu eylem için onay alınmadı)").format(baslik=baslik_goster(sec().baslik(k)), ad=ad), tur="hassas")


def sistem_istemi_engel(k, onayli, ne, goruntu_al=True):
    """Hedef pencere sistem istemiyse insan onayı (--onayli yoksa panelden; gözetimsiz kipte ret) → Dur 10. Onay bu
    eylem boyunca o pencere için geçerlidir. → sistem istemi mi (onaylandı)."""
    ad = sistem_istemi_mi(k)
    if not ad:
        return False
    if not hasattr(_EYLEM, "sistem_onay"):
        _EYLEM.sistem_onay = set()
    if k in _EYLEM.sistem_onay:
        return True
    if onaysiz_serbest("sistem istemi girdisi", ad):
        return False
    if not onayli_gecerli(onayli):
        b = sec().baslik(k)
        goruntu = None if getattr(_EYLEM, "onaylandi", False) or not goruntu_al else hedef_goruntusu(k)
        izin, neden = _panelden_onay(_("Sistem istemine girdi: {ad}").format(ad=ad), b,
                                     _("Bu pencere bir sistem yetki/parola/izin istemi ({ad}). Ajan ona {ne} göndermek "
                                       "istiyor.").format(ad=ad, ne=ne), goruntu, konu="sistem")
        if not izin:
            raise Dur(10, _("SİSTEM İSTEMİ ({ad} ← {baslik}): yetki/parola/izin istemine {ne} kullanıcının onayını "
                            "ister ({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                ad=ad, baslik=baslik_goster(b), ne=ne, neden=neden), tur="hassas")
    _EYLEM.sistem_onay.add(k)
    return True


# ---------------------------------------------------------------- pano: Deskhand'in yazdığı metinler, yapıştırma

PANO_OZET_SAYI = 32
_KENDI_PANO_BELLEK = []


def _pano_ozeti(metin):
    import hashlib
    return hashlib.sha256(metin.encode()).hexdigest()


def _pano_ozet_yolu():
    return os.path.join(yollar.runtime_dir(), "pano-ozetleri")


def kendi_pano_ekle(metin):
    """Deskhand'in (bu oturumda: MCP sunucusu ya da CLI `pano yaz`) panoya yazdığı metnin ÖZETİ (içerik tutulmaz):
    süreç belleğinde + RUNTIME_DIR/pano-ozetleri (0600, son PANO_OZET_SAYI). Bu metni okumak/yapıştırmak onay istemez."""
    if not metin:
        return
    oz = _pano_ozeti(metin)
    _KENDI_PANO_BELLEK.append(oz)
    del _KENDI_PANO_BELLEK[:-PANO_OZET_SAYI]
    try:
        import fcntl
        yol = _pano_ozet_yolu()
        os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
        fd = os.open(yol, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            satirlar = [l.strip() for l in f.read().split() if l.strip()]
            satirlar = (satirlar + [oz])[-PANO_OZET_SAYI:]
            f.seek(0)
            f.truncate()
            f.write("\n".join(satirlar) + "\n")
    except OSError:
        pass


def kendi_pano_mu(metin):
    """Metin Deskhand'in bu oturumda panoya yazdığı metinlerden biri mi?"""
    if metin is None:
        return False
    oz = _pano_ozeti(metin)
    if oz in _KENDI_PANO_BELLEK:
        return True
    try:
        with open(_pano_ozet_yolu()) as f:
            return oz in f.read().split()
    except OSError:
        return False


_OKUNAMADI = object()


def yapistirma_engel(k, onayli, kaynak="pano"):
    """kde (kullanıcının gerçek panosu): yapıştırma kısayolu (ctrl+v, ctrl+shift+v, shift+insert) ya da orta tık
    (kaynak="secim": birincil seçim) panodaki metni hedefe yazar → pano okuma onayının arka kapısı olmasın: pano boş
    değilse ve Deskhand'in yazdığı metin değilse insan onayı (okunamıyorsa da). Deskhand'in kendi yapıştırarak yazma
    yolu (eylem._yapistirarak_yaz) bu denetimden geçmez. → onay gerekti mi (onaylandı)."""
    au = sec()
    if au.ad != "kde":
        return False
    if onaysiz_serbest("yapıştırma (pano okuma)", kaynak):
        return False
    try:
        metin = au.pano_oku() if kaynak == "pano" else getattr(au, "secim_oku", lambda: _OKUNAMADI)()
    except Dur:
        metin = _OKUNAMADI
    if metin is None or (metin is not _OKUNAMADI and kendi_pano_mu(metin)):
        return False
    if onayli_gecerli(onayli):
        return True
    b = au.baslik(k) if k and k != EKRAN else ""
    uzunluk = "?" if metin is _OKUNAMADI else len(metin)
    ne = _("panodan yapıştırma") if kaynak == "pano" else _("orta tıkla seçimi yapıştırma")
    izin, neden = _panelden_onay(_("Panoyu yapıştır"), b, _("Ajan kullanıcının panosundaki metni ({n} karakter) bu "
                                                          "pencereye yapıştırmak istiyor ({ne}).").format(n=uzunluk, ne=ne),
                                 konu="pano")
    if not izin:
        raise Dur(10, _("HASSAS pano: {ne} kullanıcının panosunu ajanın görebileceği yere taşır; kullanıcının onayını "
                        "ister ({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
            ne=ne, neden=neden), tur="hassas")
    return True


_KART_ALANI = re.compile(
    r"kart numaras|kredi kart|banka kart|kart no\b|card[\s_-]?number|credit[\s_-]?card|debit[\s_-]?card|cc[\s_-]?(?:num|csc|exp|cvc)|"
    r"\bcvc\d?\b|\bcvv\d?\b|\bcvn\b|guvenlik kodu|security code|son kullanma|expir|\bskt\b")
# rakam dizisi: ayırıcı YALNIZ boşluk/nokta/tire/bölü, en çok 3 karakter; satır sonu/Tab diziyi BİTİRİR (tampon da böyle:
# alt alta sayı tablosu, iki ayrı alan, "22.11.2026\t23.11.2026" tek numara sayılmaz). Çift boşluk/"4111.1111…" atlatmasın.
_KART_ADAYI = re.compile(r"\d(?:[ .\-/]{0,3}\d)*")
_KART_SON_DIZI = re.compile(r"\d(?:[ .\-/]{0,3}\d)*[ .\-/]{0,3}\Z")  # metnin SONUNDAKİ rakam dizisi (tampon; Tab/Enter ile biter → boş)
_KART_TARIH = re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}[./]\d{2,4}(?!\d)")  # 22.11.2026, 3/4/26: aday DEĞİL
KART_AZAMI_HANE = 23  # 19 haneli numara + 4 hane SKT/CVV bitişik; daha uzun dizi (IBAN, sayı tablosu, rastgele) aday değil
KART_TAMPON_SN = 60  # aynı pencereye bu süre içinde gelen yazı parçaları birleştirilip sınanır
_KART_TAMPON = {}  # pencere → (zaman, metnin sonundaki rakam dizisi): YALNIZ süreç belleği, "kart" kipinde, ≤48 karakter


def _kart_biciminde(w):
    """Rakam penceresi bilinen bir kart ailesinin ön eki + uzunluğuna uyuyor mu (Visa 16/19, Mastercard 16, Amex 15, Troy 16,
    Diners 14/16–19, JCB/Discover/UnionPay 16–19, Maestro 16–19)? TÜM pencereler için aranır (rastgele 13–14 haneli
    sipariş/takip numarasında ve uzun rakam dizisinde sahte alarmı keser)."""
    n = len(w)
    ilk2, ilk4 = int(w[:2]), int(w[:4])
    if w[0] == "4":
        return n in (16, 19)
    if 51 <= ilk2 <= 55 or 2221 <= ilk4 <= 2720:
        return n == 16
    if ilk2 in (34, 37):
        return n == 15
    if ilk2 in (36, 38) or 3000 <= ilk4 <= 3059:
        return n == 14 or 16 <= n <= 19
    if ilk4 == 9792:
        return n == 16
    if ilk2 == 35 or w[0] == "6" or ilk2 == 50 or 56 <= ilk2 <= 58:
        return 16 <= n <= 19
    return False


def _luhn_gecer(w):
    t = 0
    for i, c in enumerate(reversed(w)):
        x = int(c)
        if i % 2:
            x = x * 2 - 9 if x > 4 else x * 2
        t += x
    return t % 10 == 0


def _luhn_son4(rakam, baslar=(0,)):
    """Rakam dizisinde kart numarası: dizi en çok KART_AZAMI_HANE hane; 13–19 haneli, kart ailesine uyan (_kart_biciminde) ve
    Luhn'u geçen bir pencere, YALNIZ `baslar` indekslerinde (grup başları: ayırıcıdan sonraki ilk rakam) başlıyorsa
    ve SON hariç her grubu 4–6 haneliyse (_grup_boylari_uygun) ("4111 1111 1111 1111 12", "…111112/26": ek rakam/SKT/CVV yakalanır). → ilk uyan pencerenin son 4 hanesi | None."""
    n = len(rakam)
    if n < 13 or n > KART_AZAMI_HANE:
        return None
    for s in baslar:
        for uz in range(13, min(19, n - s) + 1):
            w = rakam[s:s + uz]
            if _grup_boylari_uygun(baslar, n, s, s + uz) and _kart_biciminde(w) and _luhn_gecer(w):
                return w[-4:]
    return None


def _grup_boylari_uygun(baslar, n, s, e):
    """[s, e) penceresinin SON hariç her grubu 4–6 haneli mi (4-4-4-4, 4-6-5, 4-6-4, 4-4-4-4-3)? Rastgele küçük sayıların
    boşlukla dizilmesi ("12 7 3456 89 …") kart sayılmasın; tek parça numara ve ek rakam/SKT bitişik hali etkilenmez."""
    sinirlar = list(baslar) + [n]
    boylar = [min(sinirlar[i + 1], e) - max(sinirlar[i], s) for i in range(len(baslar))
              if sinirlar[i + 1] > s and sinirlar[i] < e]
    return all(4 <= b <= 6 for b in boylar[:-1])


def kart_alani_mi(*adlar) -> bool:
    """AT-SPI/web ögesinin adı, etiketi, açıklaması ya da autocomplete/id/placeholder nitelikleri bir kart bilgisi alanı
    (kart numarası, cvc/cvv, güvenlik kodu, son kullanma) mı?"""
    return any(a and _KART_ALANI.search(katla(a)) for a in adlar)


def _iban_gecerli(harf, rakam):
    """2 harf ülke kodu + rakamlar mod-97 IBAN sınamasını geçiyor mu (TR33 0006 1005 …)? Yalnız rakamlı BBAN'lar."""
    if len(harf) != 2 or not 15 <= len(rakam) + 2 <= 34:
        return False
    sayi = rakam[2:] + "".join(str(ord(c.upper()) - 55) for c in harf) + rakam[:2]
    return int(sayi) % 97 == 1


def kart_numarasi(metin):
    """Metinde 13–19 haneli, kart ailesine uyan, Luhn sınamasını geçen numara var mı (boşluk/nokta/tire/bölü ayırıcılı, ek
    rakama bitişik)? Satır sonu/Tab diziyi bitirir; dizi ≤23 hane; tarih (22.11.2026) ve IBAN (TRxx …) aday değildir; alt
    pencere yalnız grup başında başlar. → son 4 hane | None. Numaranın kendisi hiçbir yere döndürülmez."""
    metin = (metin or "")[:200000]
    metin = _KART_TARIH.sub(lambda m: "\n" * len(m.group(0)), metin)
    for m in _KART_ADAYI.finditer(metin):
        yazi = m.group(0)
        rakam = re.sub(r"\D", "", yazi)
        if len(rakam) < 13 or len(rakam) > KART_AZAMI_HANE:
            continue
        on = metin[max(0, m.start() - 2):m.start()]
        if len(on) == 2 and on.isascii() and on.isalpha():  # "TR33 0006 …": ülke kodu bitişik → geçerli IBAN ise kart değil
            if _iban_gecerli(on, rakam):
                continue
        baslar = [0] + [i for i in range(1, len(rakam)) if _grup_basi(yazi, i)]
        son4 = _luhn_son4(rakam, baslar)
        if son4:
            return son4
    return None


def _grup_basi(yazi, i):
    """yazi (rakam + ayırıcı) içinde i. RAKAM bir grubun ilk rakamı mı (öncesinde ayırıcı var mı)?"""
    sayac = -1
    onceki_rakam = False
    for c in yazi:
        if c.isdigit():
            sayac += 1
            if sayac == i:
                return not onceki_rakam
            onceki_rakam = True
        else:
            onceki_rakam = False
    return False


def kart_tampon_sifirla(k):
    """Pencerenin kart tamponunu boşalt (tıklama: alan/odak değişti; birleştirme sürmez)."""
    _KART_TAMPON.pop(k, None)


def kart_tampon_dolu(k) -> bool:
    """Pencerenin tamponunda (süresi dolmamış) bir rakam dizisi bekliyor mu? (parça yazısının günlüğe gizli gitmesi için)"""
    import time as _t
    kayit = _KART_TAMPON.get(k)
    if kayit and _t.monotonic() - kayit[0] > KART_TAMPON_SN:
        _KART_TAMPON.pop(k, None)
        return False
    return bool(kayit and kayit[1])


def gizli_rakamli_mi(metin) -> bool:
    """Metinde ≥8 rakamlık (ayırıcılı) dizi var mı? Kart kipinde bu tür yazı günlüğe gizli gider (numara parçası olabilir)."""
    return any(len(re.sub(r"\D", "", m.group(0))) >= 8 for m in _KART_ADAYI.finditer(metin or ""))


def gizli_satir(satir):
    """Gizli girdinin günlük satırı: `type …` → `type ***` (parça uzunluğu da yok: kelime uzunlukları sızmasın; toplam
    uzunluk komut etiketinde), `key/keydown/keyup …` → ***."""
    if satir.startswith("type "):
        return "type ***"
    m = re.match(r"(keydown|keyup|key)\s", satir)
    return f"{m.group(1)} ***" if m else satir


def gizli_etiket(etiket):
    """Gizli girdinin günlük etiketi: `tus 4 1 1 1 …` / `bas 4 …` / `dizi: tus …` → tuş dizisi maskelenir."""
    return re.sub(r"^((?:dizi: )?(?:tus|bas)) .*?( --onayli)?$", r"\1 ***\2", etiket or "", flags=re.S)


def kart_tampon_denetle(k, metin):
    """kart_numarasi(metin) + parça parça yazma: aynı pencereye KART_TAMPON_SN sn içinde gönderilen önceki yazının
    SONUNDAKİ rakam dizisiyle birleştirilip Luhn denenir (4111 / 1111 / 1111 / 1111 ayrı çağrılarda da yakalanır).
    Süreç içi (CLI'de her çağrı ayrı süreç: yalnız MCP/Python API tek süreçte yakalar). → son 4 hane | None."""
    import time as _t
    simdi = _t.monotonic()
    zaman, kuyruk = _KART_TAMPON.get(k, (0.0, ""))
    if simdi - zaman > KART_TAMPON_SN:
        kuyruk = ""
        _KART_TAMPON.pop(k, None)  # süresi dolmuş kayıt okunurken silinir
    if kuyruk and metin and metin[0] in "\t\r\n":  # parçalar arasında Tab/Enter: alan değişti, birleştirilmez
        kuyruk = ""
    birlesik = kuyruk + (metin or "")
    son4 = kart_numarasi(birlesik)
    if son4:
        _KART_TAMPON.pop(k, None)
        return son4
    m = _KART_SON_DIZI.search(birlesik[-200:]) if birlesik else None
    if m:
        if len(_KART_TAMPON) > 32:
            _KART_TAMPON.pop(next(iter(_KART_TAMPON)))
        _KART_TAMPON[k] = (simdi, m.group(0)[-48:])
    else:
        _KART_TAMPON.pop(k, None)
    return None


def tus_metni(kombinasyon):
    """tus/bas kombinasyonundaki düz yazı tuşlarının (rakam, kp_rakam, boşluk, tire) yazdığı metin; diğer her akor
    yazıyı keser ("\n"). Tek tuşla kart numarası yazmayı tampona beslemek için."""
    parca = []
    for akor in (kombinasyon or "").split():
        a = akor.lower()
        if len(a) == 1 and a.isdigit():
            parca.append(a)
        elif a.startswith("kp_") and a[3:].isdigit() and len(a) == 4:
            parca.append(a[3:])
        elif a in ("space", "minus", "kp_subtract"):
            parca.append(" " if a == "space" else "-")
        else:
            parca.append("\n")
    return "".join(parca)


# Yazı OLMAYAN tuşlar (parola alanında bir karakter eklemez): gezinme, düzenleme, işlev, kilit tuşları
_YAZI_DISI_TUSLAR = ({"enter", "kpenter", "linefeed", "esc", "tab", "backspace", "delete", "insert", "home", "end", "pageup",
                      "pagedown", "up", "down", "left", "right", "capslock", "numlock", "scrolllock", "sysrq", "pause",
                      "menu", "compose", "super", "ctrl", "alt", "shift", "altgr"}
                     | {f"f{i}" for i in range(1, 25)})


def yazi_tusu_sayisi(kombinasyon):
    """tus/bas kombinasyonunda alana KARAKTER yazan akor sayısı: değiştiricisiz (ya da yalnız shift/altgr) tek karakterli
    tuş (harf, rakam, noktalama, space, kp_rakam…). ctrl/alt/super'li akorlar, Enter/Tab/gezinme/işlev tuşları sayılmaz.
    Tanınmayan x:/k: tuşu yazı sayılır (güvenli taraf)."""
    n = 0
    for kume, bilinmeyen in _akor_kumeleri(kombinasyon):
        if kume & {"ctrl", "alt", "super"}:
            continue
        tuslar = kume - {"shift", "altgr"}
        if bilinmeyen:
            n += 1
        elif tuslar and not (tuslar & _YAZI_DISI_TUSLAR):
            n += 1
    return n


def pano_yazma_engel(metin):
    """Onay kapsamı "kart": panoya YAZILAN metinde Luhn'dan geçen kart numarası varsa onay (ajan numarayı panoya yazıp
    Ctrl+V ile yapıştırmasın; kart_bilgisi_engel yolu: CLI --onayli yok sayılır, gözetimsiz → ret; iletide yalnız son 4
    hane). "hepsi" kipinde dokunmaz. api.pano_yaz ve CLI `pano yaz` ortak kullanır. → onay gerekti mi (onaylandı)."""
    if onay_kapsami() != "kart" or kart_numarasi(metin) is None:
        return False
    eylem_basladi()
    return kart_bilgisi_engel(None, False, metin, False, _("pano yazma"))


def kart_bilgisi_engel(k, onayli, metin, alan_kart=False, ne="yazı", son4=None) -> bool:
    """Onay kapsamı "kart": hedef alan kart alanıysa (alan_kart) ya da yazılacak metinde Luhn'dan geçen kart numarası varsa
    yazma/yapıştırma/değer yazma insan onayı ister (CLI --onayli yok sayılır; gözetimsiz kipte ret). Onay isteğine ve
    iletilere YALNIZ son 4 hane / uzunluk girer; çağıran metni günlükte gizli tutmalı. "hepsi" kipinde dokunmaz.
    → kart bilgisi vardı (onaylandı)."""
    if onay_kapsami() != "kart":
        return False
    son4 = son4 or kart_numarasi(metin)  # son4: çağıranın (parça tamponuyla) bulduğu numara
    if not (alan_kart or son4):
        return False
    if onayli_gecerli_kati(onayli):
        return True
    b = sec().baslik(k) if k and k != EKRAN else ""
    ayrinti = _("Ajan bir kart bilgisi yazmak istiyor ({ne}).").format(ne=ne)
    ayrinti += "\n" + (_("kart numarası: **** {son4}").format(son4=son4) if son4 else
                       _("kart bilgisi alanı, {n} karakter").format(n=len(metin or "")))
    izin, neden = _panelden_onay(_("Kart bilgisi yaz"), b, ayrinti, konu="odeme")
    if not izin:
        raise Dur(10, _("HASSAS: kart bilgisi yazmak ({ne}) kullanıcının onayını ister ({neden}); bu onay yalnız "
                        "panelden verilir").format(ne=ne, neden=neden), tur="hassas")
    return True


def parola_alani_engel(k, onayli, uzunluk, ne, belirsiz=False):
    """Hedef/odaklı öge bir PAROLA alanı (AT-SPI rolü 'password text'): yazı / yapıştırma / değer yazma insan onayı
    ister (--onayli yoksa panelden; red/gözetimsiz → 10). Metin hiçbir iletiye/günlüğe/onay isteğine yazılmaz: yalnız
    uzunluğu. belirsiz=True: alan türü BELİRLENEMEDİ (sayfa belirsiz: çerçeve ↔ pencere kanıtlanamadı; SON-FIX) →
    parola gibi onay; iletide neden "alan türü belirlenemedi", pencere başlığı/adres/belge adı YOK (hangi sayfanın
    okunduğu bilinmiyor; başlık saldırgan sayfanın metni olabilir). → True (onaylandı)."""
    if onaysiz_serbest("parola alanına yazma", ne):  # DEĞERİNİ OKUMA reddi (erisim) bundan bağımsız
        return False
    if onayli_gecerli(onayli):
        return True
    if belirsiz:
        izin, neden = _panelden_onay(_("Türü belirlenemeyen alana yaz"), "", _(
            "Ajan odaklı alana {n} karakter yazmak istiyor ({ne}); alan türü belirlenemedi (parola alanı olabilir: "
            "sayfa belirsiz).").format(n=uzunluk, ne=ne))
        if not izin:
            raise Dur(10, _("HASSAS: alan türü belirlenemedi (parola alanı olabilir); {ne} kullanıcının onayını ister "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                                ne=ne, neden=neden), tur="hassas")
        return True
    b = sec().baslik(k) if k and k != EKRAN else ""
    izin, neden = _panelden_onay(_("Parola alanına yaz"), b, _("Ajan bir parola alanına {n} karakter yazmak istiyor "
                                                              "({ne}).").format(n=uzunluk, ne=ne), konu="parola")
    if not izin:
        raise Dur(10, _("HASSAS: parola alanına {ne} kullanıcının onayını ister ({neden}); kullanıcı sohbette açıkça "
                        "onayladıysa --onayli ile tekrarla").format(ne=ne, neden=neden), tur="hassas")
    return True


# ---------------------------------------------------------------- insan önceliği (girdi nesnesi dışındaki yollar)

def insan_onceligi(ne, azami=8.0):
    """Girdi nesnesi kullanmayan yollar (pencere yönetimi, pencere kapatma, pano yazma, erişilebilirlik eylemi):
    kullanıcı klavye/fare kullanıyorsa (kde) ya da Devral açıksa (sanal) durgunluğu bekle (en çok `azami` sn), sonra
    Dur 12. `ne`: yapılmayan eylemin adı (çevrilmiş)."""
    import sys as _sys
    import time as _t
    from .hata import dur_denetle
    au = sec()
    bitis = _t.monotonic() + azami
    uyarildi = False
    while au.insan_var_mi():
        if not uyarildi:
            print(_("bekleniyor: kullanıcı bilgisayarı kullanıyor…"), file=_sys.stderr)
            uyarildi = True
        if _t.monotonic() >= bitis:
            raise Dur(12, _("kullanıcı {sn} sn boyunca bilgisayarı kullandı (insan önceliği); {ne} yapılmadı").format(
                sn=f"{azami:.0f}", ne=ne))
        dur_denetle()
        _t.sleep(0.3)


# ---------------------------------------------------------------- DUR anahtarı
# DUR is a SET of sources (review INC5 O4/O5/P1): the file dur_dosyasi() holds one "<source> <pid>" line per source;
# DUR is on while the file exists (hata.dur_denetle: one stat). Each source is removed only by its owner:
#   "kullanici"               the user (panel DUR button / tray / shortcut); the user's Devam lifts EVERY source;
#   "panel-kapali-basarisiz"  the panel, closed-fail while its signed DUR record cannot be read; removed only by the
#                             panel (or the user's Devam), never by an agent's dur_kapat("cli");
#   "cli"                     an agent / the command line; an empty (legacy) file counts as "cli".
# Any other (unknown) label is kept and protected like the user's. Writers take a flock (dur-kilit) so adding and
# removing never lose another source; removing the LAST source moves the file away first, then checks what it moved
# and puts back any source added meanwhile (no check-then-remove race, also against writers outside the lock).

DUR_KULLANICI = "kullanici"
DUR_CLI = "cli"
DUR_KAPALI_BASARISIZ = "panel-kapali-basarisiz"
_DUR_BILINMIYOR = "bilinmiyor"  # the file exists but cannot be read: protected
_DUR_ONCELIK = (DUR_KULLANICI, DUR_KAPALI_BASARISIZ, DUR_CLI)
_DUR_YEREL = threading.local()


def dur_acik():
    return os.path.exists(dur_dosyasi())


def _icerik(kaynak):
    return f"{kaynak} {os.getpid()}"


def _gecici_yaz(dizin, icerik):
    """Aynı dizinde geçici dosya (atomik link/replace için). → yol."""
    fd, yol = tempfile.mkstemp(prefix=".dur-", dir=dizin)
    with os.fdopen(fd, "w") as f:
        f.write(icerik)
    return yol


def _kaynak_coz(metin):
    """DUR file content → {source: its line}. One "<source> <pid>" per line; an empty file (legacy / `touch`) is
    {"cli"}. "panel-kapali-basarisiz" and unknown labels stay what they are (never "cli": review INC5 P1)."""
    kaynaklar = {}
    for satir in (metin or "").splitlines():
        p = satir.split()
        if p:
            kaynaklar.setdefault(p[0], satir.strip())
    return kaynaklar or {DUR_CLI: ""}


_DUR_OKU_SINIR = 64 * 1024


def _dur_oku(yol=None):
    """DUR file → {source: line}; {} = no file. A file that exists but cannot be read (I/O error, not a regular file:
    FIFO, directory, symlink, socket) → {"bilinmiyor": ""}. Never blocks: O_NONBLOCK, the type is checked before
    reading, at most 64 KiB (review INC6 D4: a FIFO froze the panel's DUR button)."""
    import stat
    yol = yol or dur_dosyasi()
    try:
        fd = os.open(yol, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return {}
    except OSError:
        return {_DUR_BILINMIYOR: ""} if os.path.lexists(yol) else {}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return {_DUR_BILINMIYOR: ""}
        parcalar, kalan = [], _DUR_OKU_SINIR
        while kalan > 0:
            p = os.read(fd, kalan)
            if not p:
                break
            parcalar.append(p)
            kalan -= len(p)
        return _kaynak_coz(b"".join(parcalar).decode("utf-8", "replace"))
    except OSError:
        return {_DUR_BILINMIYOR: ""}
    finally:
        os.close(fd)


def _duzenli_dosya(yol):
    import stat
    try:
        return stat.S_ISREG(os.lstat(yol).st_mode)
    except OSError:
        return False


def _dur_oku_yazici(yol=None):
    """_dur_oku for a writer (review INC6 D2): a read error is retried once. Still unreadable: a REGULAR file → None
    (DUR is on; its sources are unknown and must not be replaced by a placeholder); not a regular file (FIFO,
    symlink, socket) → {} (nothing readable to keep: it is replaced by a regular file)."""
    yol = yol or dur_dosyasi()
    k = _dur_oku(yol)
    if _DUR_BILINMIYOR in k:
        k = _dur_oku(yol)
    if _DUR_BILINMIYOR not in k:
        return k
    return None if _duzenli_dosya(yol) else {}


class _DurKilidi:
    """Process-wide exclusive flock on RUNTIME_DIR/dur-kilit, re-entrant in the same thread. The lock cannot be taken
    within BEKLE_SN (another process holds it: a same-uid process must not be able to block the user's DUR button)
    or at all (no space, odd directory): go on without it; writes stay atomic (link/replace), only a source written
    at the same moment by someone else could be lost, and the panel puts its own sources back (_dur_koru)."""
    BEKLE_SN = 0.5

    def __enter__(self):
        self.fd = None
        derin = getattr(_DUR_YEREL, "derin", 0)
        _DUR_YEREL.derin = derin + 1
        if derin:
            return self
        import fcntl
        try:
            dizin = os.path.dirname(dur_dosyasi())
            os.makedirs(dizin, mode=0o700, exist_ok=True)
            self.fd = os.open(os.path.join(dizin, "dur-kilit"),
                              os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            import time as _t
            son = _t.monotonic() + self.BEKLE_SN
            while True:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if _t.monotonic() >= son:
                        raise
                    _t.sleep(0.005)
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
            self.fd = None
        return self

    def __exit__(self, *_a):
        _DUR_YEREL.derin -= 1
        if self.fd is not None:
            os.close(self.fd)  # the flock goes with the descriptor
        return False


def _dur_yaz(kaynaklar, birlestir):
    """Write the source set atomically (readers never see an empty / partial file). The file is missing → created
    with os.link (a file created meanwhile is not overwritten: merged when `birlestir`)."""
    yol = dur_dosyasi()
    dizin = os.path.dirname(yol)
    os.makedirs(dizin, mode=0o700, exist_ok=True)

    def metin(k):
        sira = [x for x in _DUR_ONCELIK if x in k] + sorted(x for x in k if x not in _DUR_ONCELIK)
        return "".join((k[x] or x) + "\n" for x in sira)
    gecici = _gecici_yaz(dizin, metin(kaynaklar))
    try:
        try:
            os.link(gecici, yol)
            return
        except FileExistsError:
            pass
        if birlestir:
            simdi = _dur_oku_yazici()
            if simdi is None:  # a regular DUR file that cannot be read: DUR is on, its sources are kept as they are
                return
            if any(k not in kaynaklar for k in simdi):
                os.remove(gecici)
                gecici = _gecici_yaz(dizin, metin({**simdi, **kaynaklar}))
        os.replace(gecici, yol)
        gecici = None
    finally:
        if gecici:
            try:
                os.remove(gecici)
            except OSError:
                pass


def dur_ac(kaynak=DUR_CLI):
    """DUR anahtarını aç: bundan sonra hiçbir deskhand süreci girdi göndermez (13); basılı tuşlar bırakılır.
    kaynak: "kullanici" (arayüz/tepsi/kısayol: insanın kararı), "cli" (ajan/komut satırı) ya da
    "panel-kapali-basarisiz" (panel: imzalı kayıt okunamıyor). Kaynak KÜMEYE eklenir: hiçbir kaynak bir başkasını
    ezmez ya da silmez. Atomik: okuyan hiçbir an yarım/boş dosya görmez."""
    kaynak = str(kaynak).split()[0] if str(kaynak).split() else DUR_CLI
    with _DurKilidi():
        mevcut = _dur_oku_yazici()
        # None: the file exists but cannot be read now: DUR is already on and its unknown sources are NOT overwritten
        # with a placeholder (review INC6 D2); the panel puts its own source back once the file can be read (_dur_koru)
        if mevcut is not None and kaynak not in mevcut:
            _dur_yaz({**mevcut, kaynak: _icerik(kaynak)}, birlestir=True)
    return dur_dosyasi()


def dur_kaynaklari():
    """Açık DUR'un kaynakları (frozenset; boş = kapalı)."""
    return frozenset(_dur_oku())


def dur_kaynagi():
    """Açık DUR'u kim koydu (öncelik: "kullanici" > "panel-kapali-basarisiz" > "cli" > bilinmeyen etiket) | None."""
    k = _dur_oku()
    for x in _DUR_ONCELIK:
        if x in k:
            return x
    return sorted(k)[0] if k else None


DUR_KALDIRMA_MESAJI = N_("DUR yalnız kullanıcı tarafından kaldırılır: Deskhand panelinden ya da DUR kısayoluyla.")


def dur_kaldir_iste(sure=None):
    """CLI/MCP asking to remove the STOP switch (loosening: H3 review, same rule as the panel-authoritative settings).
    Opening DUR is free; removing it needs the user's Yes in the panel dialog (default No). Panel closed, unattended
    mode, no answer → Dur(13). A command-line --approved is NOT an answer here. → True when it was removed."""
    if not dur_acik():
        return False
    from . import onay
    s = onay.iste_sonuc(_("DUR kaldırılsın mı?"), "DUR",
                        _("Bir komut DUR anahtarını kaldırmak istiyor. Siz istemediyseniz Hayır deyin."),
                        **({"sure": sure} if sure else {}), dur_kaldirma=True)
    # the PANEL removes DUR on the user's Yes (onay.yanitla, request type "dur"); the requester never does, whatever
    # answer it got: the switch itself is the proof
    if dur_acik():
        raise Dur(KULLANICI_DUR, _(DUR_KALDIRMA_MESAJI) + " " + _("İstek onaylanmadı ({neden}).").format(
            neden=s.neden))
    return True


def dur_kapat(kaynak=DUR_CLI):
    """DUR kaynağını kaldır. → o kaynak açıktı mı ("kullanici": DUR açık mıydı).
    "kullanici" = kullanıcının kendi kararı (panel Devam'ı, kaldırma isteğine Evet): BÜTÜN kaynaklar kalkar.
    Başka her kaynak YALNIZ kendini kaldırır. "cli" (ajan): DUR başka bir kaynak yüzünden (kullanıcının, panelin
    kapalı-başarısız DUR'u, bilinmeyen etiket) açık kalıyorsa Dur(13): ajan koymadığı bir durdurmayı geri alamaz.
    Yarışsız: son kaynak dosya önce geçici ada TAŞINARAK kaldırılır; taşınan okunur, o arada eklenen kaynak geri konur."""
    yol = dur_dosyasi()
    with _DurKilidi():
        if kaynak == DUR_KULLANICI:
            try:
                os.remove(yol)
                return True
            except FileNotFoundError:
                return False
        mevcut = _dur_oku_yazici()
        if mevcut is None:  # unreadable: nothing is removed, DUR stays on
            mevcut = {_DUR_BILINMIYOR: ""}
        vardi = kaynak in mevcut
        kalan = {k: v for k, v in mevcut.items() if k != kaynak}
        if kalan:
            if vardi:
                _dur_yaz(kalan, birlestir=False)
        elif mevcut:
            tasinan = f"{yol}.kaldir-{os.getpid()}-{threading.get_ident()}"
            try:
                os.rename(yol, tasinan)
            except FileNotFoundError:
                return False
            try:
                tasinan_k = _dur_oku(tasinan)
                if _DUR_BILINMIYOR in tasinan_k:  # cannot check what was moved: put it back as it is (DUR stays on)
                    kalan = {_DUR_BILINMIYOR: ""}
                    try:
                        os.link(tasinan, yol)
                    except FileExistsError:
                        pass  # a new DUR file appeared meanwhile: DUR is on
                else:
                    kalan = {k: v for k, v in tasinan_k.items() if k != kaynak}
                    if kalan:  # a source added between the read and the move (a writer outside the lock): put back
                        _dur_yaz(kalan, birlestir=True)
            finally:
                try:
                    os.remove(tasinan)
                except OSError:
                    pass
    if kalan and kaynak == DUR_CLI:
        if set(kalan) == {DUR_KAPALI_BASARISIZ}:
            raise Dur(KULLANICI_DUR, _("DUR'u panel koydu (imzalı kayıt okunamıyor); yalnız kullanıcı Deskhand "
                                       "panelinden kaldırabilir"))
        if set(kalan) == {_DUR_BILINMIYOR}:
            raise Dur(KULLANICI_DUR, _("DUR dosyası okunamıyor (kaynağı bilinmiyor); yalnız kullanıcı Deskhand "
                                       "panelinden kaldırabilir"))
        raise Dur(KULLANICI_DUR, _("DUR'u kullanıcı koydu; yalnız kullanıcı Deskhand panelinden/tepsiden kaldırabilir"))
    return vardi
