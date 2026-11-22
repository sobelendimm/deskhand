"""Uygulama başlatma: .desktop girdileri, ad ile bulma, başlat → YENİ penceresini bekle. Komut: ac."""
from __future__ import annotations

import inspect
import os
import re
import shutil
import stat
import sys
import time
import uuid

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
                              "gizli": alan.get("NoDisplay") == "true",
                              "ucbirimde": alan.get("Terminal", "").strip().lower() == "true",
                              "kategoriler": [k for k in alan.get("Categories", "").split(";") if k]})
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


# ---------------------------------------------------------------- MCP: yalnız masaüstü girdisi + belge argümanı
# Kabuğu OLMAYAN bir MCP ajanı open_app ile kod çalıştıramamalı (docs/ARCHITECTURE.md §4 "MCP uygulama başlatma"):
# uygulama yalnız kurulu bir .desktop girdisidir, argümanlar yalnız URL ya da var olan belge yoludur. Yorumlayıcı,
# kabuk, sarmalayıcı, yetki yükseltici, başlatıcı ve uçbirim öykünücüsü hiçbir biçimde (doğrudan, .desktop Exec'inde,
# Flatpak --command'ında) başlatılmaz. CLI `ac --komut` bu yoldan GEÇMEZ (kabuğu olan kullanıcı/ajan içindir).

# Tam ad eşleşmesi (küçük harf, yol atılmış); sürüm ekli adlar (python3.12, perl5.38, lua5.4) _yorumlayici_adi ile.
YASAK_PROGRAMLAR = frozenset({
    # kabuklar
    "sh", "bash", "rbash", "zsh", "fish", "dash", "ksh", "mksh", "pdksh", "oksh", "yash", "csh", "tcsh", "nu", "elvish",
    "xonsh", "busybox", "toybox",
    # sarmalayıcılar / süreç başlatıcılar (asıl komutu argümanda taşır)
    "env", "nohup", "setsid", "systemd-run", "run0", "flatpak-spawn", "xargs", "exec", "command", "time", "timeout",
    "stdbuf", "unbuffer", "script", "expect", "watch", "parallel", "at", "batch", "dbus-run-session", "dbus-launch",
    "dbus-send", "gdbus", "busctl", "qdbus", "qdbus6", "qdbus-qt5", "qdbus-qt6", "strace", "ltrace", "gdb", "lldb",
    "valgrind", "bwrap", "unshare", "nsenter", "chroot", "proot", "systemd-nspawn", "toolbox", "distrobox",
    "distrobox-enter", "podman", "docker", "make", "cmake", "ninja",
    # yetki yükseltme
    "sudo", "sudoedit", "doas", "pkexec", "su", "sg", "newgrp", "kdesu", "kdesudo", "gksu", "gksudo",
    # ağ kabukları / tüneller
    "socat", "nc", "ncat", "netcat", "telnet", "ssh", "mosh", "rsh",
    # başlatıcılar (dosyayı/girdiyi kendi seçtiği programla açar ya da çalıştırır)
    "xdg-open", "gio", "gtk-launch", "kde-open", "kde-open5", "kde-open6", "kioclient", "kioclient5", "kioclient6",
    "exo-open", "kstart", "kstart5", "kstart6", "krunner", "dex", "open", "mimeopen", "run-mailcap", "see",
    # yorumlayıcılar / sanal makineler
    "python", "python2", "python3", "pypy", "pypy3", "ipython", "ipython3", "jupyter", "perl", "ruby", "irb", "node",
    "nodejs", "deno", "bun", "lua", "luajit", "php", "tclsh", "wish", "gjs", "seed", "osascript", "java", "jshell",
    "javaw", "mono", "dotnet", "pwsh", "powershell", "r", "rscript", "julia", "guile", "racket", "sbcl", "clisp",
    "ocaml", "ghci", "runghc", "erl", "elixir", "iex", "scala", "kotlin", "groovy", "swipl", "awk", "gawk", "mawk",
    "nawk", "sed", "find", "wine", "wine64", "wineconsole", "wine-preloader", "wine64-preloader", "winedbg", "proton",
    "umu-run", "qemu", "vim", "nvim", "vi", "ex", "emacs", "emacsclient",
    # Deskhand'in kendisi (CLI --approved ile kendi kendini onaylama)
    "deskhand", "ekran", "deskhand-bg", "deskhand-mcp",
    # alt komut/seçenekle başka program çalıştıranlar (git -c alias.x=!…, flock -c, tmux new '…', setpriv KOMUT…)
    "git", "flock", "tmux", "screen", "byobu", "dtach", "abduco", "setpriv", "capsh", "runuser", "chpst", "daemonize",
    "start-stop-daemon", "ssh-agent", "xvfb-run", "xinit", "startx", "torsocks", "proxychains", "proxychains4",
    "systemd-cat", "systemd-inhibit", "systemctl", "loginctl", "uwsm", "rlwrap", "perf", "catchsegv", "eatmydata",
    "fakeroot", "fakechroot", "kioexec", "kde-inhibit", "kdeinit5", "kdeinit6", "klauncher", "nsjail", "minijail0",
    "ld.so", *"xdotool ydotool dotool dotoold wtype".split(),  # girdi enjeksiyon araçları (tek dizede: ham çağrı değil)
    "kwriteconfig5", "kwriteconfig6", "dconf",
    "gsettings", "crontab", "dbus-update-activation-environment", "ldd",
})
_YORUMLAYICI_KOK = ("python", "pypy", "perl", "ruby", "lua", "luajit", "php", "node", "tclsh", "wish", "guile", "java",
                    "wine", "pwsh", "julia")
# Uçbirim öykünücüleri (guvenlik.UCBIRIM_SINIFLARI'na ek; ikili adı ve Flatpak kimliği): uçbirim açmak = kabuk
UCBIRIM_PROGRAMLARI = frozenset({
    "st", "xfce4-terminal", "lxterminal", "terminology", "deepin-terminal", "cosmic-term", "warp-terminal", "blackbox",
    "termite", "kmscon", "x-terminal-emulator", "kitten", "org.gnome.console", "com.raggesilver.blackbox",
    "app.devsuite.ptyxis", "org.wezfurlong.wezterm", "io.elementary.terminal", "com.gexperts.tilix",
})
# Asıl programı sarıp başlatan ama kendisi komut yorumlamayan araçlar: arkasındaki program aynen denetlenir
_GECIRGEN = frozenset({"nice", "ionice", "chrt", "taskset", "prime-run", "primusrun", "optirun", "vglrun",
                       "gamemoderun", "mangohud", "pw-jack", "padsp", "firejail", "obs-gamecapture", "strangle",
                       "gamescope", "steam-runtime"})
ARGUMAN_SINIRI = 16
ARGUMAN_UZUNLUK = 4096
URL_SEMALARI = ("http", "https")


def _ad(yol: str) -> str:
    return os.path.basename(yol or "").strip().lower()


def _yorumlayici_adi(ad: str) -> bool:
    """python3.12, perl5.38, lua5.4, php8.3, java17… → True (kök + yalnız rakam/nokta/tire)."""
    return any(ad.startswith(k) and re.fullmatch(r"[0-9.\-]*", ad[len(k):]) for k in _YORUMLAYICI_KOK)


def program_yasak_mi(yol: str) -> str | None:
    """Program (ikili yolu ya da adı) MCP'den başlatılamayacak türden mi? → neden | None."""
    from .guvenlik import ucbirim_mi
    ad = _ad(yol)
    if not ad:
        return None
    if ad in YASAK_PROGRAMLAR or _yorumlayici_adi(ad) or ad.startswith("ld-linux"):
        return _("'{ad}' bir yorumlayıcı/kabuk/sarmalayıcı/başlatıcı (keyfi kod çalıştırır)").format(ad=ad)
    if ad in UCBIRIM_PROGRAMLARI or ucbirim_mi(ad):
        return _("'{ad}' bir uçbirim öykünücüsü (uçbirim = kabuk)").format(ad=ad)
    return None


def _guclu_yasak(parca: str) -> str | None:
    """Exec'in herhangi bir öğesi için (program konumunda olmasa da): yol olarak yazılmış yasak program
    (/usr/bin/python3, /bin/sh) ya da yalın kabuk/yorumlayıcı/yetki/Deskhand adı → neden."""
    ad = _ad(parca)
    if not ad or parca.startswith("-"):
        return None
    if "/" in parca or ad in _KABUKLAR or ad in _YETKI or ad in ("deskhand", "ekran", "env") or _yorumlayici_adi(ad):
        neden = program_yasak_mi(parca)
        if neden:
            return neden
    return None


_KABUK_METAKARAKTER = re.compile(r"[;|&`$<>]|\$\(")
_KABUKLAR = frozenset({"sh", "bash", "rbash", "zsh", "fish", "dash", "ksh", "mksh", "csh", "tcsh", "busybox"})
_YETKI = frozenset({"sudo", "doas", "pkexec", "su", "run0", "kdesu"})


def _exec_denetle(argv: list[str]) -> str | None:
    """.desktop Exec argv'si (alan kodları atılmış) → neden | None. Program konumundaki öğe (geçirgen sarmalayıcılar
    nice/prime-run/gamemoderun… atlanarak) tam listeyle; diğer her öğe (ve `--secenek=DEGER` değeri) yol ya da yalın
    kabuk/yorumlayıcı adıysa yine yasak. Flatpak: yalnız `flatpak run KIMLIK`; kimlik ve --command denetlenir."""
    if not argv:
        return _("Exec satırı boş ya da çözümlenemedi")
    for j, parca in enumerate(argv):
        # Exec = program + sabit seçenekler + alan kodları: kabuk metakarakteri / gömülü komut taşıyan öğe yok
        if _KABUK_METAKARAKTER.search(parca) or parca.startswith("!") or "=!" in parca:
            return _("Exec öğesi gömülü komut taşıyor: {parca}").format(parca=repr(parca)[:120])
        if any(c.isspace() for c in parca) and not os.path.exists(parca):
            return _("Exec öğesi boşluklu bir komut metni: {parca}").format(parca=repr(parca)[:120])
        if parca == "--" and j + 1 < len(argv) and _ad(argv[0]) not in _GECIRGEN:
            sonraki = argv[j + 1]
            if os.path.isabs(sonraki) or shutil.which(sonraki):
                return _("Exec'te '--' sonrasında başka bir program: {p}").format(p=repr(sonraki)[:120])
        for aday in (parca, parca.split("=", 1)[1] if parca.startswith("-") and "=" in parca else ""):
            neden = _guclu_yasak(aday) if aday else None
            if neden:
                return neden
    i = 0
    while i < len(argv):
        neden = program_yasak_mi(argv[i])
        if neden:
            return neden
        if _ad(argv[i]) not in _GECIRGEN:
            break
        i += 1  # geçirgen sarmalayıcının seçenekleri: arkasındaki asıl program da program konumunda denetlenir
        while i < len(argv) and (argv[i].startswith("-") or argv[i].isdigit() or argv[i] == "--"):
            i += 1
    asil = argv[i:]
    if asil and _ad(asil[0]) == "flatpak":
        alt = next((a for a in asil[1:] if not a.startswith("-")), "")
        if alt != "run":
            return _("flatpak yalnız 'run' ile başlatılabilir ('{alt}')").format(alt=alt)
        from .oturum.cozum import _flatpak_kimligi
        kimlik, komut = _flatpak_kimligi(asil)
        for aday in (kimlik or "", komut or ""):
            neden = program_yasak_mi(aday) if aday else None
            if neden:
                return neden
    return None


def girdi_denetle(g: dict) -> str | None:
    """Masaüstü girdisi MCP'den başlatılabilir mi? → neden (başlatılamaz) | None."""
    from .guvenlik import ucbirim_mi
    if g.get("ucbirimde"):
        return _("girdi bir uçbirimde çalışır (Terminal=true)")
    if any(k.lower() == "terminalemulator" for k in g.get("kategoriler") or ()):
        return _("girdi bir uçbirim öykünücüsü (Categories=TerminalEmulator)")
    kimlik = (g.get("kimlik") or "").lower()
    if kimlik in UCBIRIM_PROGRAMLARI or ucbirim_mi(kimlik):
        return _("girdi bir uçbirim öykünücüsü ({kimlik})").format(kimlik=g.get("kimlik"))
    from .oturum.cozum import exec_argv
    return _exec_denetle(exec_argv(g.get("exec", "")))


def _belge_yolu_denetle(yol: str) -> str | None:
    if not os.path.isabs(yol):
        return _("yol mutlak olmalı")
    if not os.path.exists(yol):
        return _("dosya/klasör yok")
    gercek = os.path.realpath(yol)
    if os.path.isfile(gercek) and os.access(gercek, os.X_OK):
        return _("çalıştırılabilir dosya belge olarak verilemez")
    if gercek.lower().endswith((".desktop", ".service", ".lnk")):
        return _("başlatıcı dosyası belge olarak verilemez")
    return None


def belge_argumanlari(args) -> list[str]:
    """MCP open_app argümanları: yalnız http(s)/file URL'si ya da var olan bir dosya/klasörün MUTLAK yolu (o
    uygulamada açılacak belge). `-` ile başlayan (seçenek), `=` içeren (URL dışında), denetim karakterli, başka şemalı
    (javascript:, data:, steam:…), çalıştırılabilir dosya ya da .desktop gösteren argüman → Dur(10)."""
    from urllib.parse import unquote, urlsplit
    args = list(args or [])
    if len(args) > ARGUMAN_SINIRI:
        raise Dur(10, _("en çok {n} argüman verilebilir").format(n=ARGUMAN_SINIRI))
    sonuc = []
    for a in args:
        neden = None
        if not isinstance(a, str) or not a.strip():
            neden = _("boş argüman")
        elif len(a) > ARGUMAN_UZUNLUK or any(ord(c) < 32 or ord(c) == 127 for c in a):
            neden = _("çok uzun ya da denetim karakteri içeriyor")
        elif a.lstrip().startswith("-"):
            neden = _("seçenek (- ile başlıyor) verilemez")
        else:
            u = urlsplit(a)
            sema = u.scheme.lower()
            if sema in URL_SEMALARI:
                if not u.netloc or any(c.isspace() for c in a):
                    neden = _("geçersiz URL")
            elif sema == "file":
                neden = (_("yalnız yerel file:// URL'si") if u.netloc not in ("", "localhost")
                         else _belge_yolu_denetle(unquote(u.path)))
            elif sema:
                neden = _("yalnız http, https ya da file URL'si ('{sema}:' değil)").format(sema=sema)
            elif "=" in a:
                neden = _("'=' içeren argüman verilemez (ortam değişkeni/seçenek)")
            else:
                neden = _belge_yolu_denetle(a)
        if neden:
            raise Dur(10, _("argüman reddedildi {arg}: {neden}. open_app argümanları yalnız açılacak belge olabilir "
                            "(http/https/file URL'si ya da var olan dosyanın mutlak yolu)").format(
                arg=repr(a)[:200], neden=neden))
        sonuc.append(a)
    return sonuc


# İzin listesi: ROOT sahipli, kullanıcının yazamadığı sistem dizinleri. Buradaki girdi + root sahipli ikili program =
# onaysız. Kullanıcının yazabildiği dizinlerdeki (~/.local/share/applications, kullanıcı Flatpak'ı) girdiler ya da
# programı kullanıcıya ait / betik olan girdiler insan onayı ister (bir eylem = bir onay; gözetimsiz kipte ret).
SISTEM_UYGULAMA_DIZINLERI = ("/usr/share/applications", "/usr/local/share/applications",
                             "/var/lib/flatpak/exports/share/applications")


def _root_yazilamaz(yol: str) -> bool:
    """Yol (sembolik bağlar çözülerek) ve TÜM üst dizinleri root sahipli ve grup/diğerleri yazamıyor mu?"""
    try:
        for p in {os.path.realpath(yol), os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(yol))),
                                                       os.path.basename(yol))}:
            while True:
                st = os.stat(p)
                if st.st_uid != 0 or st.st_mode & 0o022:
                    return False
                if p == "/":
                    break
                p = os.path.dirname(p)
    except OSError:
        return False
    return True


def program_guvenilir(program: str) -> str | None:
    """Exec'in programı onaysız başlatılabilir mi? → None | neden. Yol çözülür (PATH'te kullanıcının önce gelen bir
    dizinindeki aynı adlı dosya bulunursa o denetlenir); root sahipli, yazılamaz, çalıştırılabilir bir İKİLİ (ELF)
    olmalı: çalıştırılabilir metin dosyası (#! betik) kabul edilmez."""
    yol = program if os.path.isabs(program) else shutil.which(program)
    if not yol:
        return _("program bulunamadı: {p}").format(p=program)
    gercek = os.path.realpath(yol)
    if not _root_yazilamaz(yol):
        return _("program root sahipli/yazılamaz değil: {p}").format(p=gercek)
    try:
        st = os.stat(gercek)
        with open(gercek, "rb") as f:
            imza = f.read(4)
    except OSError:
        return _("program okunamadı: {p}").format(p=gercek)
    if not stat.S_ISREG(st.st_mode) or not os.access(gercek, os.X_OK):
        return _("program çalıştırılabilir bir dosya değil: {p}").format(p=gercek)
    if imza == b"\x7fELF":
        return None
    if imza[:2] == b"#!":  # sistemin kurduğu, kullanıcının değiştiremediği sarmalayıcı betik (libreoffice, steam…)
        return _betik_yorumlayici_guvenilir(gercek)
    return _("program ikili ya da betik değil: {p}").format(p=gercek)


def _elf_root(yol: str) -> bool:
    try:
        with open(os.path.realpath(yol), "rb") as f:
            return _root_yazilamaz(yol) and f.read(4) == b"\x7fELF" and os.access(yol, os.X_OK)
    except OSError:
        return False


def _betik_yorumlayici_guvenilir(betik: str) -> str | None:
    """Root sahipli, yazılamaz #! betiğin yorumlayıcısı da root sahipli, yazılamaz bir ELF mi? `#!/usr/bin/env PROG`
    ise env ve PROG (PATH ile çözülür) aynı koşulu sağlamalı; env'e seçenek (-S…) ya da ortam ataması verilemez."""
    try:
        with open(betik, "rb") as f:
            satir = f.readline(512).decode("utf-8", "replace")
    except OSError:
        return _("betik okunamadı: {p}").format(p=betik)
    parcalar = satir[2:].strip().split()
    if not parcalar or not os.path.isabs(parcalar[0]):
        return _("betiğin yorumlayıcısı mutlak yol değil: {p}").format(p=betik)
    yorumlayici = parcalar[0]
    if not _elf_root(yorumlayici):
        return _("betiğin yorumlayıcısı root sahipli/yazılamaz bir ikili değil: {y}").format(y=yorumlayici)
    if _ad(yorumlayici) == "env":
        if len(parcalar) < 2 or parcalar[1].startswith("-") or "=" in parcalar[1]:
            return _("betiğin env satırı yalın bir program adı değil: {s}").format(s=satir.strip()[:120])
        hedef = parcalar[1] if os.path.isabs(parcalar[1]) else shutil.which(parcalar[1])
        if not hedef or not _elf_root(hedef):
            return _("betiğin env hedefi root sahipli/yazılamaz bir ikili değil: {h}").format(h=parcalar[1])
    return None


def _exec_programlari(argv: list[str]) -> list[str]:
    """Exec'te çalışacak programlar: geçirgen sarmalayıcılar + asıl program (Flatpak'ta flatpak'ın kendisi)."""
    sonuc, i = [], 0
    while i < len(argv):
        sonuc.append(argv[i])
        if _ad(argv[i]) not in _GECIRGEN:
            break
        i += 1
        while i < len(argv) and (argv[i].startswith("-") or argv[i].isdigit() or argv[i] == "--"):
            i += 1
    return sonuc


def girdi_guvenilir(g: dict) -> str | None:
    """Masaüstü girdisi ONAYSIZ başlatılabilir mi (izin listesi)? → None | neden (insan onayı gerekir).
    Girdi dosyası SISTEM_UYGULAMA_DIZINLERI'nde, root sahipli ve yazılamaz (üst dizinleriyle); Exec'teki her program
    root sahipli, yazılamaz bir ikili."""
    yol = os.path.abspath(g.get("yol") or "")
    if not any(yol.startswith(d.rstrip("/") + "/") for d in SISTEM_UYGULAMA_DIZINLERI):
        return _("girdi kullanıcının yazabildiği bir dizinde: {yol}").format(yol=yol)
    if not _root_yazilamaz(yol):
        return _("girdi dosyası root sahipli/yazılamaz değil: {yol}").format(yol=yol)
    from .oturum.cozum import exec_argv
    programlar = _exec_programlari(exec_argv(g.get("exec", "")))
    if not programlar:
        return _("Exec satırı çözümlenemedi")
    for p in programlar:
        neden = program_guvenilir(p)
        if neden:
            return neden
    return None


def _ozel_kopya(g: dict) -> dict:
    """Onaylı (kullanıcı dizinindeki) girdi: içerik BİR KEZ okunur, onaylanan Exec ile aynı olduğu doğrulanır ve
    RUNTIME_DIR/uygulama/ altına 0600 kopyası yazılır; başlatma kopyadan yapılır (onaydan sonra dosyayı değiştirmek
    işe yaramaz). → kopyayı gösteren girdi."""
    from .oturum.cozum import exec_argv
    try:
        with open(g["yol"], "rb") as f:
            ham = f.read(256 * 1024)
    except OSError as e:
        raise Dur(10, _("girdi okunamadı: {hata}").format(hata=e)) from None
    exec_ = None
    bolum = None
    for satir in ham.decode("utf-8", "replace").splitlines():
        satir = satir.strip()
        if satir.startswith("["):
            bolum = satir
        elif bolum == "[Desktop Entry]" and satir.startswith("Exec=") and exec_ is None:
            exec_ = satir[5:].strip()
    if exec_ is None or exec_argv(exec_) != exec_argv(g.get("exec", "")):
        raise Dur(10, _("girdi onay sırasında değişti; başlatılmadı"))
    d = os.path.join(yollar.runtime_dir(), "uygulama")
    os.makedirs(d, mode=0o700, exist_ok=True)
    simdi = time.time()
    for ad in os.listdir(d):  # eski kopyalar
        try:
            if simdi - os.lstat(os.path.join(d, ad)).st_mtime > 3600:
                os.remove(os.path.join(d, ad))
        except OSError:
            pass
    kopya = os.path.join(d, f"{re.sub(r'[^A-Za-z0-9._-]', '_', g['kimlik'])[:80]}-{uuid.uuid4().hex[:8]}.desktop")
    fd = os.open(kopya, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(ham)
    return dict(g, yol=kopya, kaynak_yol=g["yol"])


def mcp_uygulama(ad: str, args=None) -> tuple[dict, list[str]]:
    """MCP open_app'in TEK giriş noktası: `ad` kurulu bir masaüstü girdisine çözülür (ham yol/komut YOK), girdi ve
    argümanlar denetlenir (kara liste → 10). İzin listesi dışındaki girdi (kullanıcı dizini, kullanıcıya ait ya da
    betik program) insan onayı ister: red/panel yok/gözetimsiz → 10 (tur "hassas"); izinde girdinin özel kopyası
    döner. → (girdi, doğrulanmış argümanlar). Uymazsa Dur (1/5/6 çözüm, 10 güvenlik)."""
    ad = (ad or "").strip()
    if "/" in ad:
        raise Dur(10, _("open_app yalnız kurulu bir uygulamanın adını alır (.desktop girdisi); yol ya da komut "
                        "verilemez: {ad}").format(ad=repr(ad)[:200]))
    belgeler = belge_argumanlari(args)  # girdi aranmadan önce: ret ucuz ve ayrıntısız
    g = uygulama_bul(ad)
    neden = girdi_denetle(g)
    if neden:
        raise Dur(10, _("'{ad}' MCP'den başlatılamaz: {neden}").format(ad=g.get("kimlik") or ad, neden=neden))
    guvensiz = girdi_guvenilir(g)
    if guvensiz:
        from . import guvenlik
        guvenlik.eylem_basladi()  # bu başlatma kendi eylemi: önceki eylemin onayı taşınmaz
        ayrinti = (_("Doğrulanmamış uygulama girdisi ({neden})").format(neden=guvensiz) + "\n"
                   + _("girdi: {yol}").format(yol=g["yol"]) + "\n" + _("Exec: {exec_}").format(exec_=g.get("exec", ""))
                   + ("\n" + _("belgeler: {b}").format(b=" ".join(belgeler))[:600] if belgeler else ""))
        izin, onay_neden = guvenlik._panelden_onay(
            _("Uygulama başlat: {ad}").format(ad=g.get("ad") or g.get("kimlik")), g.get("kimlik") or ad, ayrinti)
        if not izin:
            raise Dur(10, _("'{ad}' doğrulanmamış bir girdi ({neden}); başlatmak kullanıcının onayını ister ({onay}). "
                            "Başlatılmadı; kullanıcıya bildir.").format(ad=g.get("kimlik") or ad, neden=guvensiz,
                                                                       onay=onay_neden), tur="hassas")
        g = _ozel_kopya(g)
    return g, belgeler


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
    if len(argv) >= 3 and os.path.basename(argv[0]) == "gio" and argv[1] == "launch" and argv[2].endswith(".desktop"):
        komut = _desktop_exec(argv[2])  # ardından gelenler (MCP open_app belge argümanları) aynen sona eklenir
        return [*komut, ERISIM_BAYRAGI, *argv[3:]] if komut and chromium_ailesi_mi(komut) else argv
    return [*argv, ERISIM_BAYRAGI] if chromium_ailesi_mi(argv) else argv


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
        baslatma_komut_engel(a.komut_satiri, getattr(a, "onayli", False))  # rm -r / sudo / curl | sh…: insan onayı
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
    if au.ad == "sanal":  # Chromium/Electron ağaca yalnız bu bayrakla girer (agac / ogeye-tikla arka planda çalışsın)
        komut = erisim_bayragi_ekle(komut)
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
