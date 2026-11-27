"""Ev dizini BEYAZ LİSTE kanıt testi (arka plan uygulaması ad alanı; arka_ortak.ev_baglari / EV_BEYAZ_LISTE).

Bulgu (iç rakip kıyası ölçümü): eski geçici katman + kara liste (SIR_YOLLARI) düzeninde listede OLMAYAN gizli dosya
(`.config/baskauygulama/token`) arka plan uygulamasına okunuyordu. Yeni düzen: ev dizini BOŞ tmpfs; gerçek evden yalnız
görünüm ayarları (beyaz liste) salt okunur, XDG veri klasörleri yazılabilir ve kalıcı, politikanın uygulama başına `ev`
girdileri (varsayılan YOK) salt okunur.

SAHTE ev dizini (arka_ortak._EV_ZORLA, süreç içi) kullanılır; ad alanında kullanıcının GERÇEK ev dizini ayrıca boş tmpfs
ile örtülür (sonda yanlışlıkla gerçek dosya okuyamaz). Ekran/masaüstü gerekmez (bwrap ad alanında kabuk sondası).

Çalıştır:  python3 tests/test_ev_beyaz_liste.py"""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import arka_ortak as ao
from deskhand.oturum import politika

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


if not shutil.which("bwrap"):
    print("atlandı: bwrap yok")
    sys.exit(0)

kok = tempfile.mkdtemp(prefix="deskhand-evbl-", dir=_yalitim.GECICI)
EV = os.path.join(kok, "ev")
RT = os.path.join(kok, "rt")
GERCEK_EV = os.path.realpath(os.path.expanduser("~"))


def yaz(rel, icerik):
    y = os.path.join(EV, rel)
    os.makedirs(os.path.dirname(y), exist_ok=True)
    with open(y, "w") as f:
        f.write(icerik)


r1, r2 = secrets.token_hex(4), secrets.token_hex(4)
SIRLAR = {".config/rastgele_uyg/token": "GIZLI-1", ".netrc": "GIZLI-2", ".git-credentials": "GIZLI-3",
          ".config/gh/hosts.yml": "GIZLI-4", ".docker/config.json": "GIZLI-5", ".local/share/bilinmeyen/anahtar": "GIZLI-6",
          f".config/uyg-{r1}/oturum.json": "GIZLI-7", f".{r2}/kimlik": "GIZLI-8", ".cache/uyg/jeton": "GIZLI-9",
          ".local/bin/betik-jetonlu": "GIZLI-10", "projeler/.env": "GIZLI-11", "notlar.txt": "GIZLI-12",
          ".ssh/id_ed25519": "GIZLI-13", ".local/share/keyrings/login.keyring": "GIZLI-14"}
for r, v in SIRLAR.items():
    yaz(r, v)
BEYAZ = {".config/kdeglobals": "[General]\nColorScheme=BreezeDark\n", ".config/gtk-3.0/settings.ini": "[Settings]\n",
         ".config/kdedefaults/kdeglobals": "[KDE]\n", ".config/fontconfig/fonts.conf": "<fontconfig/>\n",
         ".local/share/fonts/ornek.ttf": "font", ".local/share/icons/tema/index.theme": "[Icon Theme]\n",
         ".config/mimeapps.list": "[Default Applications]\n", ".config/user-dirs.locale": "tr_TR\n",
         ".config/user-dirs.dirs": 'XDG_DOCUMENTS_DIR="$HOME/Belgeler"\nXDG_DOWNLOAD_DIR="$HOME/Indirilenler"\n'}
for r, v in BEYAZ.items():
    yaz(r, v)
os.makedirs(os.path.join(EV, "Belgeler"))
os.makedirs(os.path.join(EV, "Indirilenler"))
yaz(".local/share/user-places.xbel", "<xbel/>")   # uygulamanın KENDİ ayarı: yalnız politika `ev` ile
# beyaz listedeki bir yol sır yoluna giden sembolik bağ: ad alanında içeriği görünmemeli
os.symlink("../.ssh", os.path.join(EV, ".config/gtk-4.0"))
ao._EV_ZORLA = EV


def ad_alani(komut, ev_ek=()):
    argv = ao.korumali_argv(["/usr/bin/sh", "-c", komut], RT, [], ev=EV, ev_ek=ev_ek)
    i = argv.index("--tmpfs") + 2  # ilk --tmpfs /tmp: gerçek ev de boş tmpfs (sonda gerçek dosya göremez)
    argv = argv[:i] + ["--tmpfs", GERCEK_EV] + argv[i:]
    return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                          env={"HOME": EV, "PATH": "/usr/bin"})


# ---------------------------------------------------------------- birim
a_, bilgi = ao.ev_baglari(EV)
kontrol("birim: ev dizini BOŞ tmpfs (0700), katman (overlay) YOK",
        "--overlay-src" not in a_ and "--tmp-overlay" not in a_ and a_[:2] == ["--perms", "0700"] and
        a_[a_.index("--tmpfs") + 1] == os.path.realpath(EV) and bilgi["kip"] == "beyaz", str(a_[:8]))
kontrol("birim: yalnız beyaz liste salt okunur bağlanır (sır/bilinmeyen uygulama yolu bağ listesinde YOK)",
        not any(x.startswith(os.path.join(EV, r)) for r in SIRLAR for x in a_) and
        os.path.join(EV, ".config/kdeglobals") in bilgi["beyaz"], str(bilgi["beyaz"]))
kontrol("birim: sır yoluna giden sembolik bağ (.config/gtk-4.0 → .ssh) beyaz listeden REDDEDİLİR",
        os.path.join(EV, ".config/gtk-4.0") not in bilgi["beyaz"], str(bilgi["beyaz"]))
kontrol("birim: geçersiz `ev` girdileri atılır (mutlak, .., boş)",
        [g for g in ("/etc/passwd", "../x", "", ".", "a/../../b", ".local/share/user-places.xbel")
         if ao.gecerli_ev_girdisi(g)] == [".local/share/user-places.xbel"])

# ---------------------------------------------------------------- canlı ad alanı
sonda = "; ".join(f"cat '{os.path.join(EV, r)}' 2>/dev/null; echo" for r in SIRLAR)
r = ad_alani(sonda)
okunan = [v for v in SIRLAR.values() if v in r.stdout]
kontrol("ad alanı: rastgele adlı/listelenmemiş gizli dosyalar OKUNAMIYOR (.config/rastgele_uyg/token, .netrc, "
        ".git-credentials, gh/hosts.yml, docker, .local/share/bilinmeyen, rastgele gizli dizin, .env, notlar…)",
        r.returncode == 0 and okunan == [], f"okunan {okunan} {r.stderr[-300:]}")
r = ad_alani(f"ls -A '{EV}'; ls -A '{EV}/.config'")
kontrol("ad alanı: ev kökünde ve .config'te yalnız beyaz liste + veri klasörleri görünür (bilinmeyen ad bile yok)",
        r1 not in r.stdout and r2 not in r.stdout and "rastgele_uyg" not in r.stdout and "gh" not in r.stdout.split()
        and "projeler" not in r.stdout and "kdeglobals" in r.stdout and "Belgeler" in r.stdout, r.stdout + r.stderr)
r = ad_alani("; ".join(f"cat '{os.path.join(EV, x)}'" for x in BEYAZ))
kontrol("ad alanı: beyaz listedeki görünüm ayarları OKUNUYOR (kdeglobals, kdedefaults, gtk, fontconfig, yazı tipi, "
        "simge, mimeapps, user-dirs)", all(v in r.stdout for v in BEYAZ.values()), r.stdout + r.stderr)
r = ad_alani(f"echo x > '{EV}/.config/kdeglobals' && echo YAZILDI; ls -A '{EV}/.config/gtk-4.0/' 2>&1")
kontrol("ad alanı: beyaz liste SALT OKUNUR (kdeglobals'a yazılamaz); sır yoluna giden bağ içeriği görünmez",
        "YAZILDI" not in r.stdout and "id_ed25519" not in r.stdout and
        open(os.path.join(EV, ".config/kdeglobals")).read() == BEYAZ[".config/kdeglobals"], r.stdout + r.stderr)
r = ad_alani(f"echo kalici > '{EV}/Belgeler/yeni.txt' && echo gecici > '{EV}/ev-kok.txt' && "
             f"mkdir -p '{EV}/.config/autostart' && echo k > '{EV}/.config/autostart/x.desktop' && "
             f"echo k > '{EV}/.bashrc' && echo TAMAM")
kontrol("ad alanı: XDG veri klasörüne yazılan KALICI (Belgeler/yeni.txt ana makinede)",
        "TAMAM" in r.stdout and open(os.path.join(EV, "Belgeler/yeni.txt")).read() == "kalici\n", r.stdout + r.stderr)
kontrol("ad alanı: ev köküne/.config'e yazılan GEÇİCİ (ana makinede yok: ev-kok.txt, autostart, .bashrc)",
        not os.path.exists(os.path.join(EV, "ev-kok.txt")) and not os.path.exists(os.path.join(EV, ".config/autostart"))
        and not os.path.exists(os.path.join(EV, ".bashrc")))
r = ad_alani(f"ls -A '{EV}'")
kontrol("ad alanı: sonraki başlatma öncekinin ev köküne yazdığını görmez", "ev-kok.txt" not in r.stdout, r.stdout)

# ---------------------------------------------------------------- politika: uygulama başına `ev` (varsayılan YOK)
yap = politika.yukle()
kontrol("politika: varsayılan oturum.toml'da hiçbir uygulamaya `ev` girdisi YOK (varsayılan kapalı)",
        all(not politika.anahtar_politikasi(k, yap).ev for k in yap.get("uygulama", {})))
ozel = {"uygulama": {"_varsayilan": {"kapali_iken": "paylas", "acik_iken": "bekle", "ev": [".config"]},
                     "dolphin": {"kapali_iken": "paylas", "acik_iken": "bekle", "adlar": ["dolphin"],
                                 "ev": [".local/share/user-places.xbel", "/etc/passwd", "../disari", 5]}}}
pd = politika.anahtar_politikasi("dolphin", ozel)
pv = politika.anahtar_politikasi("_varsayilan", ozel, ad="bilinmeyen")
kontrol("politika: uygulama başına `ev` süzülür (geçersizler atılır); `_varsayilan`daki `ev` bilinmeyene VERİLMEZ",
        pd.ev == (".local/share/user-places.xbel",) and pv.ev == (), f"{pd.ev} {pv.ev}")
r = ad_alani(f"cat '{EV}/.local/share/user-places.xbel'; echo; echo x > '{EV}/.local/share/user-places.xbel' && "
             f"echo YAZILDI", ev_ek=pd.ev)
r0 = ad_alani(f"cat '{EV}/.local/share/user-places.xbel' 2>&1")
kontrol("ad alanı: politikanın `ev` girdisi yalnız verildiğinde ve SALT OKUNUR görünür",
        "<xbel/>" in r.stdout and "YAZILDI" not in r.stdout and "<xbel/>" not in r0.stdout, r.stdout + r0.stdout)
r = ad_alani(f"cat '{EV}/.ssh/id_ed25519' '{EV}/.netrc' 2>&1", ev_ek=(".ssh", ".netrc", ".ssh/id_ed25519"))
kontrol("ad alanı: `ev` girdisi SIR_YOLLARI'nı açamaz (.ssh, .netrc yine okunamaz)", "GIZLI" not in r.stdout,
        r.stdout)

# ================================================================ bağımsız inceleme bulguları (ev2)
EV2 = os.path.join(kok, "ev2")
DIS = os.path.join(kok, "dis")   # ev DIŞI, /tmp altı (kok /tmp altında): kaynak olarak reddedilmeli


def yaz2(rel, icerik, taban=EV2):
    y = os.path.join(taban, rel)
    os.makedirs(os.path.dirname(y), exist_ok=True)
    with open(y, "w") as f:
        f.write(icerik)


yaz2(".config/rastgele/token", "GIZLI-A")                # sır listesinde YOK (ör. bilinmeyen uygulama)
yaz2(".config/gh/hosts.yml", "GIZLI-GH")                 # SIR_YOLLARI içinde
yaz2(".config/gtk-3.0/settings.ini", "[Settings]\nA=1\n")
yaz2(".config/gtk-3.0/bookmarks", "GIZLI-YER-IMI")
yaz2(".config/gtk-3.0/servers", "GIZLI-SUNUCU")
yaz2(".local/share/flatpak/overrides/org.x.App", "GIZLI-OVERRIDE")
yaz2(".local/share/flatpak/repo/config", "GIZLI-DEPO")
yaz2(".local/share/flatpak/repo/baska", "DEPO-DIGER")
yaz2(".config/user-dirs.dirs", 'XDG_DOCUMENTS_DIR="$HOME/Belgeler"\n')
yaz2("Belgeler/not.txt", "VERI")
yaz2("dotfiles/Kvantum/k.conf", "DOTFILE")
yaz2(".local/bin/uyg", "#!/bin/sh\n")
os.chmod(os.path.join(EV2, ".local/bin/uyg"), 0o755)
yaz2("Belgeler/gorunur-uyg", "#!/bin/sh\necho CALISTI\n")
os.chmod(os.path.join(EV2, "Belgeler/gorunur-uyg"), 0o755)
os.makedirs(os.path.join(DIS, "tema"))
yaz2("tema/dis.txt", "DIS-TEMA", DIS)
# ORTA-1 (A): beyaz liste dışı bir yere (~/.config kökü) giden sembolik bağ
os.symlink("../.config", os.path.join(EV2, ".config/fontconfig"))
# ORTA-1 (B): bir XDG veri klasörüne giden sembolik bağ (yazılabilir bağlanan yer)
os.symlink("Belgeler", os.path.join(EV2, ".icons"))
# ORTA-1 (2): /tmp altındaki (ev dışı) kaynak
os.symlink(os.path.join(DIS, "tema"), os.path.join(EV2, ".themes"))
# ORTA-1 (3): ev içinde, beyaz listede OLMAYAN bir yere giden bağ (reddedilir) ve beyaz listedeki gerçek girdiye giden bağ (kabul)
os.symlink("../dotfiles/Kvantum", os.path.join(EV2, ".config/Kvantum"))
os.symlink("gtk-3.0", os.path.join(EV2, ".config/gtk-4.0"))
# ev dışı güvenli kaynak (kabul)
os.symlink("/usr/share/icons", os.path.join(EV2, ".local/share/icons"))
ao._EV_ZORLA = EV2


def ad_alani2(komut, ev_ek=(), fd=True, bellek=None, once=None):
    """EV2 için ad alanı (fd=True: O_PATH fd + --ro-bind-fd, üretimdeki yol)."""
    fds: list[int] = []
    try:
        argv = ao.korumali_argv(["/usr/bin/sh", "-c", komut], RT, [], ev=EV2, ev_ek=ev_ek, bellek=bellek,
                                fds=fds if fd else None)
        i = argv.index("--tmpfs", argv.index("--tmpfs") + 1) + 2  # /tmp'ten sonra: gerçek ev boş tmpfs
        argv = argv[:i] + ["--tmpfs", GERCEK_EV] + argv[i:]
        if once:
            once()
        return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                              env={"HOME": EV2, "PATH": "/usr/bin"}, pass_fds=tuple(fds))
    finally:
        for f_ in fds:
            os.close(f_)


kuru = [h for _k, h in ao.ev_beyaz_baglari(EV2)]
kontrol("ORTA-1A birim: beyaz liste girdisi (.config/fontconfig) `.config` köküne (ev içinde, beyaz liste dışı) giden bağ REDDEDİLİR",
        os.path.join(EV2, ".config/fontconfig") not in kuru, str(kuru))
r = ad_alani2(f"cat '{EV2}/.config/fontconfig/rastgele/token' 2>&1; ls -A '{EV2}/.config' 2>&1")
kontrol("ORTA-1A ad alanı: `.config` kökünü gösteren bağ üzerinden sırlar (rastgele/token, gh) OKUNAMIYOR",
        "GIZLI-A" not in r.stdout and "GIZLI-GH" not in r.stdout and "rastgele" not in r.stdout.split(), r.stdout + r.stderr)
# politika `ev` girdisi (kural 3 yok): bağ KABUL, ama KAYNAK→HEDEF eşlemesiyle sır (gh) hedefte de örtülür
kuru_p = [h for _k, h in ao.ev_beyaz_baglari(EV2, (".config/fontconfig",))]
r = ad_alani2(f"cat '{EV2}/.config/fontconfig/rastgele/token' 2>&1; echo; cat '{EV2}/.config/fontconfig/gh/hosts.yml' 2>&1",
              ev_ek=(".config/fontconfig",))
kontrol("ORTA-1(4) ikinci hat eşlemesi: politika `ev` bağı kaynağı `.config` ise sır (gh) hedefte (`fontconfig/gh`) da "
        "örtülür; verilen şey (rastgele/token) görünür",
        os.path.join(EV2, ".config/fontconfig") in kuru_p and "GIZLI-A" in r.stdout and "GIZLI-GH" not in r.stdout,
        r.stdout + r.stderr)
kontrol("ORTA-1B birim: XDG veri klasörüne (Belgeler) giden sembolik bağ (.icons) REDDEDİLİR; ev dışı /tmp kaynağı (.themes) "
        "REDDEDİLİR", os.path.join(EV2, ".icons") not in kuru and os.path.join(EV2, ".themes") not in kuru, str(kuru))
r = ad_alani2(f"ls -A '{EV2}/.icons' '{EV2}/.themes' 2>&1")
kontrol("ORTA-1B/2 ad alanı: veri klasörü ve /tmp kaynaklı bağlar ad alanında görünmez",
        "not.txt" not in r.stdout and "dis.txt" not in r.stdout, r.stdout)
kontrol("ORTA-1(3) birim: ev içinde beyaz liste DIŞINA giden bağ (Kvantum → dotfiles) REDDEDİLİR; beyaz listedeki gerçek "
        "girdiye giden bağ (gtk-4.0 → gtk-3.0) kabul; ev dışı güvenli kaynak (icons → /usr/share/icons) kabul",
        os.path.join(EV2, ".config/Kvantum") not in kuru and os.path.join(EV2, ".config/gtk-4.0") in kuru and
        os.path.join(EV2, ".local/share/icons") in kuru, str(kuru))
r = ad_alani2(f"cat '{EV2}/.config/Kvantum/k.conf' 2>&1; cat '{EV2}/.config/gtk-4.0/settings.ini'")
kontrol("ORTA-1(3) ad alanı: dotfiles bağı görünmez, gtk-4.0 bağı görünür",
        "DOTFILE" not in r.stdout and "A=1" in r.stdout, r.stdout + r.stderr)

# (5) TOCTOU: kaynak fd ile açıldıktan sonra bağ yerine konursa bwrap YİNE ilk açılan nesneyi bağlar
a_fd = ao.ev_baglari(EV2, fds=[])[1]
kontrol("TOCTOU: bwrap `--ro-bind-fd` destekliyor ve beyaz liste fd ile bağlanıyor",
        ao._bwrap_ozellik("--ro-bind-fd") and a_fd["fd"] > 0, str(a_fd))


def degistir():   # denetim + fd açıldıktan SONRA: gtk-3.0 dizinini sır dizinine giden sembolik bağla değiştir
    yol = os.path.join(EV2, ".config/gtk-3.0")
    os.rename(yol, yol + ".eski")
    os.symlink(os.path.join(EV2, ".config/rastgele"), yol)


r = ad_alani2(f"cat '{EV2}/.config/gtk-3.0/settings.ini' 2>&1; cat '{EV2}/.config/gtk-3.0/token' 2>&1", once=degistir)
os.unlink(os.path.join(EV2, ".config/gtk-3.0"))
os.rename(os.path.join(EV2, ".config/gtk-3.0.eski"), os.path.join(EV2, ".config/gtk-3.0"))
kontrol("TOCTOU: fd açıldıktan sonra kaynak sır dizinine bağlanırsa ad alanı ESKİ nesneyi görür (token sızmaz)",
        "A=1" in r.stdout and "GIZLI-A" not in r.stdout, r.stdout + r.stderr)
yol_g = os.path.join(EV2, ".config/gtk-3.0")
kim = (os.stat(yol_g).st_dev, os.stat(yol_g).st_ino)
fd_ok = ao._yol_fd(os.path.realpath(yol_g), kim)
fd_kotu = ao._yol_fd(os.path.realpath(yol_g), (kim[0], kim[1] + 1))
if fd_ok is not None:
    os.close(fd_ok)
kontrol("TOCTOU: _yol_fd (dev,ino) uyuşmazsa ya da yol bağsa None döner",
        fd_ok is not None and fd_kotu is None and ao._yol_fd(os.path.join(EV2, ".themes"), kim) is None)
r = ad_alani2("ls /proc/self/fd | wc -l")
kontrol("TOCTOU: fd'ler uygulamaya SIZMAZ (ad alanında yalnız 0,1,2 + ls'in dizin tanıtıcısı)",
        r.stdout.strip().isdigit() and int(r.stdout.strip()) <= 4, r.stdout + r.stderr)

# KÜÇÜK-2
gecerli = [".config/baska/dosya", "projeler/x", ".local/share/user-places.xbel", "Belgeler/a"]
gecersiz = [".config", ".local", ".local/share", ".local/state", ".cache", ".var", ".config/", "./.config", ".ssh", ".netrc",
            ".bashrc", ".config/*", ".local/share/a*", ".config/[a]b", "*", "/etc", "../x", ""]
kontrol("KÜÇÜK-2: politika `ev` girdisi: glob, derinliği <2 gizli girdi ve merkezlerin kendisi RET; derin yollar KABUL",
        all(ao.gecerli_politika_ev_girdisi(g) for g in gecerli) and
        not any(ao.gecerli_politika_ev_girdisi(g) for g in gecersiz),
        str([g for g in gecersiz if ao.gecerli_politika_ev_girdisi(g)]))
pm = politika.anahtar_politikasi("dolphin", {"uygulama": {"dolphin": {"kapali_iken": "paylas", "acik_iken": "bekle",
                                                                      "adlar": ["dolphin"],
                                                                      "ev": [".config", ".config/dolphin*", ".ssh",
                                                                             ".config/dolphinrc"]}}})
kontrol("KÜÇÜK-2: politika yükleyicisi de aynı süzgeci uygular", pm.ev == (".config/dolphinrc",), str(pm.ev))
r = ad_alani2(f"ls -A '{EV2}/.config' 2>&1", ev_ek=(".config", ".local", ".cache"))
kontrol("KÜÇÜK-2 ad alanı: `ev = [\".config\"]` merkezi açamaz (rastgele/token görünmez)", "rastgele" not in r.stdout.split(),
        r.stdout)

# KÜÇÜK-3
r = ad_alani2(f"cat '{EV2}/.config/gtk-3.0/settings.ini'; cat '{EV2}/.config/gtk-3.0/bookmarks' "
              f"'{EV2}/.config/gtk-3.0/servers' 2>&1; "
              f"ls '{EV2}/.local/share/flatpak/overrides' 2>&1; echo; cat '{EV2}/.local/share/flatpak/repo/baska' '{EV2}/.local/share/flatpak/repo/config'")
kontrol("KÜÇÜK-3: gtk-3.0/bookmarks+servers /dev/null, flatpak overrides boş; komşu dosyalar görünür; flatpak repo/config "
        "BİLEREK örtülmez (örtü `flatpak --user` kurulumunu bozuyor: openat(config) Permission denied, ölçüldü)",
        "A=1" in r.stdout and "DEPO-DIGER" in r.stdout and "GIZLI-DEPO" in r.stdout and "GIZLI-YER-IMI" not in r.stdout and
        "GIZLI-SUNUCU" not in r.stdout and "GIZLI-OVERRIDE" not in r.stdout and
        "org.x.App" not in r.stdout, r.stdout + r.stderr)

# KÜÇÜK-4: paket/sys.prefix bağları veri klasörlerinden SONRA; .git deposunun KÖKÜ reddedilir
_dosya, _prefix = ao.__file__, sys.prefix
try:
    yaz2("proje/.git/HEAD", "ref: x")
    yaz2("proje/deskhand/arka_ortak.py", "#")
    sys.prefix = "/usr"
    ao.__file__ = os.path.join(EV2, "proje/deskhand/arka_ortak.py")
    a4, b4 = ao.ev_baglari(EV2)
    pak = os.path.join(EV2, "proje/deskhand")
    i_pak = next((i for i in range(len(a4) - 2) if a4[i:i + 3] == ["--ro-bind", pak, pak]), -1)
    i_veri = max(i for i in range(len(a4) - 2) if a4[i] == "--bind" and a4[i + 1] == os.path.join(EV2, "Belgeler"))
    ao.__file__ = os.path.join(EV2, "proje/arka_ortak.py")   # dirname = .git deposunun KÖKÜ
    a4k, b4k = ao.ev_baglari(EV2)
    kok_bagli = os.path.join(EV2, "proje") in a4k
finally:
    ao.__file__, sys.prefix = _dosya, _prefix
kontrol("KÜÇÜK-4: paket alt dizini bağlanır ve veri klasörü bağlarından SONRA gelir", i_pak > i_veri > -1, f"{i_pak} {i_veri}")
kontrol("KÜÇÜK-4: yol bir .git deposunun KÖKÜ ise (dirname = proje/) bağlanmaz", not kok_bagli, str(b4k["beyaz"]))

# KÜÇÜK-5
kontrol("KÜÇÜK-5 birim: ev_boyut = min(2 GiB, kafes/4): 4G → 1 GiB; 512M → 128 MiB; 16G → 2 GiB; 25% / bilinmeyen güvenli",
        ao.ev_boyut("4G") == 1 << 30 and ao.ev_boyut("512M") == 128 << 20 and ao.ev_boyut("16G") == 2 << 30 and
        0 < ao.ev_boyut("25%") <= 2 << 30 and ao.ev_boyut("saçma") == 2 << 30)
argv5 = ao.korumali_argv(["/usr/bin/true"], RT, [], ev=EV2, bellek="4G")
i_tmp = argv5.index("/tmp")
i_ev = argv5.index(os.path.realpath(EV2))
kontrol("KÜÇÜK-5 argv: /tmp ve ev tmpfs'i `--size 1073741824` ile",
        argv5[i_tmp - 3:i_tmp] == ["--size", str(1 << 30), "--tmpfs"] and
        argv5[i_ev - 3:i_ev] == ["--size", str(1 << 30), "--tmpfs"], str(argv5[:20]))
r = ad_alani2("df -B1 --output=size /tmp | tail -1; df -B1 --output=size '" + EV2 + "' | tail -1", bellek="4G")
kontrol("KÜÇÜK-5 ad alanı: /tmp ve ev tmpfs'i gerçekten ~1 GiB (bellek 4G)",
        r.stdout.split() == [str(1 << 30)] * 2, r.stdout + r.stderr)

# KÜÇÜK-6: görünmez exec → HEMEN anlaşılır hata (zaman aşımı yok)
import time as _t
from deskhand.hata import Dur
gizli_exec = os.path.join(EV2, ".local/bin/uyg")
masaustu = os.path.join(kok, "uyg.desktop")
with open(masaustu, "w") as f:
    f.write(f"[Desktop Entry]\nType=Application\nName=U\nExec={gizli_exec} %U\n")
t0 = _t.monotonic()
hata = None
try:
    ao.korumali_baslat({}, [gizli_exec], {"PATH": "/usr/bin"}, [])
except Dur as e:
    hata = e
kontrol("KÜÇÜK-6: ev altında ama görünmeyen exec → Dur(9) + yeni ileti + oturum.toml `ev` ipucu, bekleme YOK",
        hata is not None and hata.kod == 9 and "görünmüyor" in hata.mesaj and
        '[uygulama.uyg] ev = [".local/bin/uyg"]' in hata.mesaj and _t.monotonic() - t0 < 5,
        getattr(hata, "mesaj", "hata yok"))
hata = None
try:
    ao.korumali_baslat({}, ["gio", "launch", masaustu], {"PATH": "/usr/bin"}, [])
except Dur as e:
    hata = e
kontrol("KÜÇÜK-6: `gio launch X.desktop` yolunda .desktop Exec'i de aynı denetimden geçer (MCP open_app + CLI ac aynı kapı)",
        hata is not None and hata.kod == 9 and ".local/bin/uyg" in hata.mesaj, getattr(hata, "mesaj", "hata yok"))
ao.exec_gorunur_denetle([gizli_exec], {"PATH": "/usr/bin"}, (".local/bin/uyg",))
ao.exec_gorunur_denetle([os.path.join(EV2, "Belgeler/gorunur-uyg")], {"PATH": "/usr/bin"}, ())
ao.exec_gorunur_denetle(["/usr/bin/sh"], {"PATH": "/usr/bin"}, ())
kontrol("KÜÇÜK-6: politika `ev` ile verilmiş, veri klasöründeki ve sistem exec'i hata VERMEZ", True)

ao._EV_ZORLA = EV

ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
