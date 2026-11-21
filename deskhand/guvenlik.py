"""Güvenlik katmanı (iki arka uçta da AYNEN, docs/ARCHITECTURE.md §4):

- Yasak pencereler (CONFIG_DIR/yasak-pencereler.txt): hiçbir girdi gönderilmez, uygulama başlatılmaz (10).
- Hassas düğme (ödeme/yetki/hesap silme) ve ödeme sayfası başlığı: --onayli olmadan tıklanmaz (10).
  --onayli YALNIZ kullanıcı o adımı sohbette açıkça onayladıysa verilir.
- Başlık (-b) ve sınıf (-s) kilidi: her girdiden hemen önce (4).
- DUR anahtarı (RUNTIME_DIR/dur): her girdi satırından önce (13); `dur` oluşturur, `devam` siler. Yazma/kaldırma
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
HASSAS = re.compile(
    r"\b(satin al\w*|simdi al|hemen al|ode|odeme yap\w*|odemeyi (tamamla|onayla)\w*|siparis ver\w*|"
    r"siparisi (tamamla|onayla)\w*|alisverisi tamamla\w*|buy( now)?|purchase|pay( now)?|place order|"
    r"complete (order|purchase|payment)|confirm (order|payment|purchase)|authori[sz]e|yetkilendir\w*|"
    r"izin ver\w*|allow|grant( access)?|hesab\w* sil\w*|delete (my )?account|kalici olarak sil\w*|"
    r"permanently delete)\b")
# başlığı ödeme/sipariş onayı olan sayfada HER tıklama ve Enter/boşluk onay ister: OCR'ın okuyamadığı
# ödeme düğmesine (ör. orta ton zeminde beyaz yazı) koordinatla basılmasın. Form doldurmak (yaz) serbest; ama
# yazı Enter/Tab/boşluk içeriyorsa (\n = gönder, Tab+boşluk = odaktaki düğmeye bas) o da onay ister.
HASSAS_SAYFA = re.compile(r"\b(odeme|checkout|payment|siparisi (onayla|tamamla)\w*|siparis ozeti|"
                          r"order (review|summary)|kasa|billing)\b")

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
_EVDEV_AD = {29: "ctrl", 97: "ctrl", 56: "alt", 100: "alt", 125: "super", 126: "super", 111: "delete", 14: "backspace",
             99: "sysrq", 38: "l", **{59 + i: f"f{i + 1}" for i in range(10)}, 87: "f11", 88: "f12"}
_KEYSYM_AD = {0xffe3: "ctrl", 0xffe4: "ctrl", 0xffe9: "alt", 0xffea: "alt", 0xfe03: "alt", 0xffe7: "super",
              0xffe8: "super", 0xffeb: "super", 0xffec: "super", 0xffff: "delete", 0xff08: "backspace",
              0xff15: "sysrq", 0x6c: "l", 0x4c: "l", **{0xffbe + i: f"f{i + 1}" for i in range(12)}}
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


def riskli_tus(kombinasyon, birlikte=False):
    """Oturumu/sistemi sonlandıran ya da ekrandan çıkaran tuş kombinasyonu mu? → neden metni | None.
    Yasak DEĞİL: çağıran insan onayı ister (riskli_tus_engel). kombinasyon: eylem.tus_coz çıktısı ya da ham metin
    ('ctrl+alt+delete', 'x:Delete', 'k:111', boşlukla ayrılmış akorlar).
    Dar kapsam: ctrl+alt+delete, ctrl+alt+backspace, ctrl+alt+f1…f12 (sanal uçbirim), meta+l ve ctrl+alt+l (ekran
    kilidi), alt+sysrq+tuş. birlikte=True (bas: boşlukla ayrılmış tuşlar AYNI ANDA basılı kalır): tek küme sayılır."""
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
    __slots__ = ("kelimeler", "ic", "yon")

    def __init__(self):
        self.kelimeler, self.ic, self.yon = [], [], []  # sözcükler, komut ikamesi içleri, (işleç, hedef) yönlendirmeler


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


def _komut_riski(kom, degiskenler, derinlik):
    """Tek basit komut → (neden listesi, asıl komut adı)."""
    t = []
    for w in kom.kelimeler:
        t += _kume_ac(_degisken_coz(w, degiskenler))
    nedenler = []
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
            i += 1
            continue
        if not w or w.startswith("$") or _ISARET in w:  # bilinmeyen değer komut konumunda: sonrakine bak
            i += 1
            continue
        ad = _yol_adi(w)
        if ad in ("busybox", "toybox"):  # busybox rm -rf ~ → rm
            i += 1
            continue
        if ad in _SARMALAYICI:
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
        return nedenler, ""
    komut, arg = _yol_adi(t[i]), t[i + 1:]
    if komut in _ATAMA_KOMUT:
        for a in arg:
            m = _ATAMA.fullmatch(a)
            if m and _ISARET not in m.group(3):
                degiskenler[m.group(1)] = m.group(3)
        return nedenler, komut
    if komut in _YETKI:
        nedenler.append(_("{komut} ile yetki yükseltme").format(komut=komut))
    if komut in _GUC or (komut in ("init", "telinit") and any(a in ("0", "6") for a in arg)):
        nedenler.append(_("sistemi kapatma/yeniden başlatma ({komut})").format(komut=komut))
    if komut in ("systemctl", "loginctl") and (any(a in _SISTEMD_GUC for a in arg) or (
            komut == "loginctl" and any(a.startswith(("terminate-", "kill-")) for a in arg))):
        nedenler.append(_("{komut} ile kapatma/yeniden başlatma/askıya alma/oturum sonlandırma").format(komut=komut))
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
        nedenler.append(_("{komut} -R kök/ev/sistem dizininde: tüm dosyaların izin/sahipliğini değiştirir").format(komut=komut))
    if derinlik < 3:
        if komut in _KABUK | {"eval"}:  # sh -c "sudo …" / bash -lc … / eval "rm -rf /": gömülü komut da denetlenir
            for j, a in enumerate(arg):
                if komut == "eval" or re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a):
                    nedenler += _metin_riskleri(" ".join(arg[j + (0 if komut == "eval" else 1):]), derinlik + 1)
                    break
            if any("curl" in x or "wget" in x for x in kom.ic):  # bash <(curl …), sh -c "$(curl …)"
                nedenler.append(_("indirilen betiği doğrudan kabuğa verme (curl/wget … | sh)"))
        if _YORUMLAYICI.fullmatch(komut):  # python3 -c KOD, perl -e KOD …
            for j, a in enumerate(arg):
                if re.fullmatch(r"-[a-zA-Z]*[ceEpr]", a) and j + 1 < len(arg) and _YORUMLAYICI_KOD.search(arg[j + 1]):
                    nedenler.append(_("{komut} ile satır içi kod: dosya silme / komut çalıştırma / dinamik kod").format(
                        komut=komut))
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
    return nedenler


def riskli_komut(metin):
    """Metin yıkıcı bir kabuk komutu kalıbına uyuyor mu? → neden metni | None. Yalnız METNE bakar; hedef pencerenin
    uçbirim olup olmadığı (ucbirim_mi) çağıranda denetlenir. Metin kabuk kurallarıyla sözcüklere ayrılır (tırnak/ters
    bölü kaldırılır, $'…' açılır, komut ikamesinin içi ayrıca denetlenir); kabuk anahtar sözcükleri ({ } ! if then do…),
    değişken atamaları ve bilinmeyen $DEĞİŞKEN komut adı atlanır, aynı metindeki atama çözülür (S=sudo; $S reboot);
    busybox X → X; sh/bash -c, eval, env -S içi ve python -c / perl -e kodu yeniden denetlenir.
    Dar, gerekçeli kalıplar: geri alınamaz silme (rm -r, find -delete, find -exec rm), yetki yükseltme
    (sudo/doas/pkexec/run0), indirileni kabuğa verme, disk biçimlendirme/üzerine yazma, çatal bombası, kökte toplu
    izin/sahiplik değişikliği, kapatma/yeniden başlatma/askıya alma, zorla git push, :w !sudo."""
    if not metin or not metin.strip():
        return None
    nedenler = list(dict.fromkeys(_metin_riskleri(metin)))
    return "; ".join(nedenler[:3]) if nedenler else None


# ---------------------------------------------------------------- yasak pencereler

# Kullanıcı dosyasından BAĞIMSIZ, silinemeyen yasaklar: Deskhand paneli ve onay diyaloğu. Ajan bunlara girdi
# gönderebilseydi kendi isteğini onaylayabilir ya da kullanıcının DUR'unu kaldırabilirdi.
YERLESIK_YASAK = (r"^deskhand$", r"^Deskhand — Onay")


def yasak_desenler():
    return list(YERLESIK_YASAK) + _kullanici_yasaklari()


def _kullanici_yasaklari():
    yol = yollar.yasak_dosya()
    if not os.path.exists(yol):
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, "w") as f:
            f.write(_(VARSAYILAN_YASAK))
    with open(yol) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def yasak_denetle(k):
    if k == EKRAN or not k:
        return  # masaüstü kipinde: klavye → etkin pencere (denetle), fare → imlecin altındaki pencere denetlenir
    au = sec()
    b, sinif = au.baslik(k), au.sinif(k)
    for d in yasak_desenler():
        if re.search(d, b, re.I) or re.search(d, sinif, re.I):
            raise Dur(10, _("YASAK pencere: {baslik} (sınıf {sinif}) /{desen}/ ile eşleşti; hiçbir girdi gönderilmez "
                            "({dosya})").format(baslik=repr(b), sinif=repr(sinif), desen=d, dosya=yollar.yasak_dosya()))


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
    """Dosyadaki [(desen, seviye)] (dosya yoksa/boşsa []). Dosya OKUNURKEN oluşturulmaz. Her çağrıda taze okunur
    (küçük dosya, ~20 µs; önbellek zaman damgası kaba kaldığında eski kuralı gösterebilirdi): panelden yapılan
    değişiklik hemen geçerli olur."""
    try:
        with open(yollar.seviye_dosya()) as f:
            return [k for k in (seviye_satiri_coz(l) for l in f) if k]
    except OSError:
        return []


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
                        "({dosya})").format(baslik=repr(b), sinif=repr(sinif), seviye=_SEVIYE_KOK[s],
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
    satırların türüne göre uygulama erişim seviyesi. Ayar satırları (typedelay/typehold) denetlenmez."""
    tur = girdi_turu(satirlar)
    if tur:
        seviye_denetle(k, tur)


# ---------------------------------------------------------------- pencere / başlık / sınıf kilidi

def sinif_denetle(k):
    if SINIF_DESEN:
        sinif = sec().sinif(k)
        if not re.search(SINIF_DESEN, sinif, re.I):
            raise Dur(4, _("pencere sınıfı uymadı: {sinif} (beklenen /{desen}/); girdi gönderilmedi").format(
                sinif=repr(sinif), desen=SINIF_DESEN))


def denetle(k, desen):
    """Girdi göndermeden HEMEN önce: pencere hâlâ aktif mi, yasak değil mi, başlık (sekme) doğru mu."""
    au = sec()
    if k == EKRAN:  # masaüstü kipi: etkin pencere yasak olmasın; -b verildiyse etkin pencerenin başlığı uysun
        a = au.aktif()
        if not a:  # boşsa yasak denetimi atlanırdı (yasak pencere öndeyken bile) → doğrulanamadı = dur
            raise Dur(3, _("etkin pencere belirlenemedi; girdi gönderilmedi"))
        yasak_denetle(a)
        if desen and not re.search(desen, au.baslik(a), re.I):
            raise Dur(4, _("etkin pencere başlığı uymadı: {baslik} (beklenen /{desen}/)").format(
                baslik=repr(au.baslik(a)), desen=desen))
        sinif_denetle(a)
        return
    a = au.aktif()  # boşsa doğrulanamadı → a != k → durur (güvenli taraf)
    if a != k:
        raise Dur(3, _("aktif pencere değişti → {baslik}; girdi gönderilmedi").format(baslik=repr(au.baslik(a))))
    pencere_denetle(k, desen)


def pencere_denetle(k, desen):
    """denetle'nin pencere kilitleri, ETKİN pencere şartı OLMADAN: yasak pencere (10), başlık (4) ve sınıf (4) kilidi.
    Odağı almayan yollar (erişilebilirlik eylemi: erisim.py) için; fare/klavye yolunun denetle()'siyle aynı sonuç."""
    au = sec()
    yasak_denetle(k)
    if desen:
        b = au.baslik(k)
        if not re.search(desen, b, re.I):
            raise Dur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/); girdi gönderilmedi").format(
                baslik=repr(b), desen=desen))
    sinif_denetle(k)


def imlec_alti_denetle(k, px=None, py=None):
    """mouseto'dan sonra, tıklamadan ÖNCE (tek sorgu): (1) imleç gerçekten hedef noktada mı — kullanıcı
    arada fareyi oynattıysa tıklama başka yere düşerdi → 12; (2) altındaki pencere hedef mi? Yasak → 10; başka
    uygulamanın penceresi (bildirim, üstte duran pencere) → 3. Aynı uygulamanın açılır menüsü serbest."""
    au = sec()
    fx, fy, w = au.fare()
    if px is not None and fx is not None and (abs(fx - px) > 2 or abs(fy - py) > 2):
        raise Dur(12, _("imleç hedefte değil ({fx},{fy} ≠ {px},{py}): kullanıcı fareyi oynattı (insan önceliği); "
                        "tıklanmadı").format(fx=fx, fy=fy, px=px, py=py))
    if not w:  # imlecin altı bilinemedi: neyin üstüne tıklanacağı doğrulanamaz → dur (güvenli taraf)
        raise Dur(3, _("imlecin altındaki pencere doğrulanamadı; tıklanmadı"))
    if w == k:
        return
    yasak_denetle(w)
    seviye_denetle(w, "fare")  # imlecin altındaki başka pencere 'goruntule' seviyesinde olabilir
    if k == EKRAN:
        return
    if au.sinif(w) != au.sinif(k):
        raise Dur(3, _("imlecin altında başka pencere var: {baslik}; tıklanmadı").format(baslik=repr(au.baslik(w))))


# ---------------------------------------------------------------- hassas düğme / ödeme sayfası

_EYLEM = threading.local()  # iş parçacığı başına: bu eylem için insan onayı alındı mı


def eylem_basladi():
    """Her eylemin başında (eylem.girdi_al) çağrılır: önceki eylemin onayı yeni eyleme TAŞINMAZ."""
    _EYLEM.onaylandi = False


def _panelden_onay(eylem, hedef, ayrinti, goruntu=None):
    """Paneldeki insandan bir kez izin (CONTRACT §8). → (izin, neden). Panel/onay modülü yoksa (False, neden).
    Aynı eylemde ikinci hassas denetim (sayfa + düğme) yeniden sormaz: bir eylem = bir onay.
    goruntu: hedefin küçük görüntüsü (PIL) — kullanıcı NEYİ onayladığını görür."""
    if getattr(_EYLEM, "onaylandi", False):
        return True, _("bu eylem için zaten onaylandı")
    try:
        from . import onay
    except Exception as e:  # noqa: BLE001
        return False, _("onay modülü yüklenemedi: {hata}").format(hata=e)
    s = onay.iste_sonuc(eylem, hedef, ayrinti, masaustu=sec().ad, goruntu=goruntu)
    if s.izin:
        _EYLEM.onaylandi = True
    return s.izin, s.mesaj


ONAY_GORUNTU = (480, 200)  # onay isteğindeki küçük görüntü: tıklama noktasının çevresi (pencere pikseli)


def hedef_goruntusu(k, nokta=None):
    """Onay isteği için hedefin küçük görüntüsü: nokta verildiyse çevresi (nokta kırmızı çerçeveyle işaretli),
    yoksa pencerenin küçültülmüşü. Alınamazsa None (onay yine sorulur, yalnız görüntüsüz)."""
    try:
        from PIL import ImageDraw

        from .gorsel import pencere_goruntusu
        if nokta is None:
            im, _geo, _kok = pencere_goruntusu(k)
            im = im.copy()
            im.thumbnail((640, 400))
            return im
        x, y = round(nokta[0]), round(nokta[1])
        gw, gh = ONAY_GORUNTU
        im, _geo, (bx, by) = pencere_goruntusu(k, (x - gw // 2, y - gh // 2, gw, gh))
        im = im.convert("RGB")
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


def hassas_sayfa_engel(k, onayli, ne, yakin=(), nokta=None, ek="", goruntu_al=True):
    """Başlığı ödeme/onay sayfası olan pencerede eylem (tıklama, Enter/boşluk, Enter/boşluklu yazı) onay ister.
    yakin: tıklanacak noktadaki yazılar, nokta: (x, y) pencere pikseli, ek: ayrıntıya eklenecek satır (tuş, yazı),
    goruntu_al: onay isteğine hedefin küçük görüntüsü eklensin mi (pencereyi öne getirir).
    Onay isteği noktadaki yazıyı, hassas düğme metnini ve hedefin küçük görüntüsünü taşır (kullanıcı NEYİ
    onayladığını görür); aynı eylemdeki hassas düğme denetimi yeniden sormaz. → sayfa hassas mı."""
    b = sec().baslik(k)
    m = HASSAS_SAYFA.search(katla(b))
    onayli = onayli_gecerli(onayli)
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
        izin, neden = _panelden_onay(_("Hassas sayfada {eylem}").format(eylem=ne), b, ayrinti, goruntu)
        if not izin:
            raise Dur(10, _("HASSAS sayfa ({eslesen} ← {baslik}): bu sayfada {eylem} kullanıcının onayını ister "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=repr(m.group(0)), baslik=repr(b), eylem=ne, neden=neden), tur="hassas")
    return bool(m)


def hassas_mi(*metinler):
    for t in metinler:
        m = HASSAS.search(katla(t or ""))
        if m:
            return m.group(0)
    return None


def hassas_engel(onayli, *metinler, hedef="", k=None, nokta=None):
    """Hassas düğme (Satın al / Öde / Yetkilendir / Hesabı sil…) onay ister. k + nokta verildiyse onay isteği
    noktadaki yazıyı ve çevresinin küçük görüntüsünü taşır."""
    eslesen = hassas_mi(*metinler)
    onayli = onayli_gecerli(onayli)
    if eslesen and not onayli:
        yakin = [m for m in metinler if m]
        asil = next((m for m in yakin if HASSAS.search(katla(m))), eslesen)  # kullanıcıya ekrandaki yazı gösterilir
        ayrinti = _("Ödeme/yetki/hesap silme gibi hassas bir düğme") + _nokta_ayrintisi(nokta, yakin)
        goruntu = None if k is None or getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k, nokta)
        izin, neden = _panelden_onay(_("Düğmeye tıkla: “{dugme}”").format(dugme=asil), hedef or " / ".join(yakin[:2]),
                                     ayrinti, goruntu)
        if not izin:
            raise Dur(10, _("HASSAS düğme ('{eslesen}' ← {yakin}): ödeme/yetki/hesap silme kullanıcının kararı "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=eslesen, yakin=yakin, neden=neden), tur="hassas")
    return eslesen


def _yazilacak(metin, gizli):
    """Onay ayrıntısında gösterilecek (kısaltılmış) yazı; --gizli ise yalnız uzunluk."""
    return f"***({len(metin)})" if gizli else repr(metin if len(metin) <= 120 else metin[:117] + "…")


def riskli_tus_engel(k, onayli, kombinasyon, birlikte=False):
    """Oturumu/sistemi sonlandıran ya da ekrandan çıkaran tuş kombinasyonu (riskli_tus) onay ister: --onayli yoksa
    panelden insan onayı, panel kapalıysa/red/gözetimsiz kipte Dur(10). → kombinasyon riskli mi (onaylandı)."""
    neden = riskli_tus(kombinasyon, birlikte)
    if not neden:
        return False
    if not onayli_gecerli(onayli):
        b = sec().baslik(k) if k and k != EKRAN else ""
        goruntu = None if getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k)
        izin, onay_neden = _panelden_onay(_("Riskli tuş: {kombinasyon}").format(kombinasyon=kombinasyon), b,
                                          neden + "\n" + _("tuş: {kombinasyon}").format(kombinasyon=kombinasyon), goruntu)
        if not izin:
            raise Dur(10, _("RİSKLİ TUŞ ({kombinasyon}): {neden}; kullanıcının onayını ister ({onay_neden}); kullanıcı "
                            "sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                kombinasyon=kombinasyon, neden=neden, onay_neden=onay_neden), tur="hassas")
    return True


def ucbirim_komut_engel(k, onayli, metin, gizli=False, goruntu_al=True):
    """Hedef pencere bir uçbirimse (ucbirim_mi) ve yazılacak metin yıkıcı komut kalıbına uyuyorsa (riskli_komut)
    onay ister (riskli_tus_engel ile aynı yol). Komut, yazılmadan ÖNCE yakalanır: Enter ayrı gönderilse bile.
    Onay isteği komutu (kısaltılmış) taşır. → uçbirimde riskli komut mu (onaylandı)."""
    neden = riskli_komut(metin)  # ucuz ön eleme: sınıf sorgusu (kde: kdotool) yalnız eşleşince
    if not neden:
        return False
    au = sec()
    pen = k if k and k != EKRAN else au.aktif()
    sinif = au.sinif(pen) if pen else ""
    if not ucbirim_mi(sinif):
        return False
    if not onayli_gecerli(onayli):
        b = au.baslik(pen)
        ayrinti = neden + "\n" + _("uçbirim: {sinif}").format(sinif=sinif) + "\n" + \
            _("yazılacak: {metin}").format(metin=_yazilacak(metin, gizli))
        goruntu = None if getattr(_EYLEM, "onaylandi", False) or not goruntu_al else hedef_goruntusu(pen)
        izin, onay_neden = _panelden_onay(_("Uçbirime komut yaz: {komut}").format(komut=_yazilacak(metin, gizli)), b,
                                          ayrinti, goruntu)
        if not izin:
            raise Dur(10, _("UÇBİRİM KOMUTU ({neden} ← {baslik}): yıkıcı olabilecek komutu uçbirime yazmak kullanıcının "
                            "onayını ister ({onay_neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile "
                            "tekrarla").format(neden=neden, baslik=repr(b), onay_neden=onay_neden), tur="hassas")
    return True


def baslatma_komut_engel(komut_metni, onayli=False):
    """Ham komut satırıyla uygulama başlatma (CLI `ac --komut`, MCP open_app args): komut yıkıcı bir kabuk kalıbına
    uyuyorsa (riskli_komut: rm -r, sudo, curl | sh…) insan onayı ister (uçbirime yazmayla aynı kalıp ve aynı onay yolu;
    gözetimsiz kipte --onayli geçmez). Red → Dur(10), HİÇBİR şey başlatılmaz. → riskli miydi (onaylandı)."""
    neden = riskli_komut(komut_metni)
    if not neden:
        return False
    eylem_basladi()  # başlatma kendi eylemi: önceki eylemin onayı taşınmaz
    if not onayli_gecerli(onayli):
        izin, onay_neden = _panelden_onay(_("Komut başlat: {komut}").format(komut=_yazilacak(komut_metni, False)),
                                          _("uygulama başlatma"), neden + "\n" + _("komut: {komut}").format(
                                              komut=_yazilacak(komut_metni, False)))
        if not izin:
            raise Dur(10, _("RİSKLİ KOMUT BAŞLATMA ({neden}): yıkıcı olabilecek komutu başlatmak kullanıcının onayını "
                            "ister ({onay_neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile "
                            "tekrarla").format(neden=neden, onay_neden=onay_neden), tur="hassas")
    return True


def onayli_gecerli(onayli):
    """--onayli (kullanıcı sohbette açıkça onayladı) geçerli mi? Gözetimsiz kipte sohbet/insan yoktur: --onayli
    sayılmaz, onay gerektiren her eylem reddedilir (onay.iste_sonuc 'gozetimsiz')."""
    return bool(onayli) and not gozetimsiz()


# ---------------------------------------------------------------- DUR anahtarı

def dur_acik():
    return os.path.exists(dur_dosyasi())


def _icerik(kaynak):
    return f"{kaynak} {os.getpid()}\n"


def _gecici_yaz(dizin, icerik):
    """Aynı dizinde geçici dosya (atomik link/replace için). → yol."""
    fd, yol = tempfile.mkstemp(prefix=".dur-", dir=dizin)
    with os.fdopen(fd, "w") as f:
        f.write(icerik)
    return yol


def dur_ac(kaynak="cli"):
    """DUR anahtarını aç: bundan sonra hiçbir deskhand süreci girdi göndermez (13); basılı tuşlar bırakılır.
    kaynak: "kullanici" (arayüz/tepsi/kısayol: insanın kararı) ya da "cli" (ajan/komut satırı).
    Atomik: okuyan hiçbir an yarım/boş dosya görmez. Ajan (cli) var olan DUR'a dokunmaz (os.link: yalnız yoksa
    oluşturur), böylece kullanıcının DUR'u hiçbir yarışta ajanınkiyle ezilmez; kullanıcınınki her zaman yazılır."""
    yol = dur_dosyasi()
    dizin = os.path.dirname(yol)
    os.makedirs(dizin, mode=0o700, exist_ok=True)
    gecici = _gecici_yaz(dizin, _icerik(kaynak))
    try:
        if kaynak == "kullanici":
            os.replace(gecici, yol)
            gecici = None
        else:
            try:
                os.link(gecici, yol)  # yoksa oluştur; varsa (kimin olursa olsun) olduğu gibi kalsın
            except FileExistsError:
                pass
    finally:
        if gecici:
            try:
                os.remove(gecici)
            except OSError:
                pass
    return yol


def _kaynak_coz(metin):
    ilk = metin.split()
    return "kullanici" if ilk and ilk[0] == "kullanici" else "cli"


def dur_kaynagi():
    """Açık DUR'u kim koydu: "kullanici" | "cli" | None (kapalı)."""
    try:
        with open(dur_dosyasi()) as f:
            return _kaynak_coz(f.read())
    except OSError:
        return None


def dur_kapat(kaynak="cli"):
    """DUR anahtarını kapat. → önceden açık mıydı. Kullanıcının (arayüzden) koyduğu DUR'u yalnız kullanıcı
    kaldırır: ajan 'devam' diyerek insanın durdurma kararını geri alamaz → Dur(13).
    Yarışsız: ajan dosyayı önce geçici ada TAŞIR (atomik), sonra taşıdığı dosyanın içeriğine bakar; o arada
    kullanıcı DUR koyduysa (içerik 'kullanici') dosyayı geri koyar ve 13 verir."""
    yol = dur_dosyasi()
    if kaynak == "kullanici":
        try:
            os.remove(yol)
            return True
        except FileNotFoundError:
            return False
    if dur_kaynagi() == "kullanici":  # sıradan durum: hiç dokunmadan reddet
        raise Dur(KULLANICI_DUR, _("DUR'u kullanıcı koydu; yalnız kullanıcı Deskhand panelinden/tepsiden kaldırabilir"))
    tasinan = f"{yol}.kaldir-{os.getpid()}-{threading.get_ident()}"
    try:
        os.rename(yol, tasinan)
    except FileNotFoundError:
        return False
    try:
        with open(tasinan) as f:
            sahip = _kaynak_coz(f.read())
    except OSError:
        sahip = "kullanici"  # okunamadı: güvenli taraf (geri koy)
    if sahip == "kullanici":
        try:
            os.link(tasinan, yol)  # yerinde yeni bir DUR yoksa geri koy
        except FileExistsError:
            os.replace(tasinan, yol)  # yeni DUR (ajanınki ya da kullanıcınınki) varsa: kullanıcınınki kazanır
            tasinan = None
        finally:
            if tasinan:
                os.remove(tasinan)
        raise Dur(KULLANICI_DUR, _("DUR'u kullanıcı koydu; yalnız kullanıcı Deskhand panelinden/tepsiden kaldırabilir"))
    os.remove(tasinan)
    return True
