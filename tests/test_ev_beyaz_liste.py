"""Ev dizini BEYAZ LİSTE kanıt testi (arka plan uygulaması ad alanı; arka_ortak.ev_baglari / EV_BEYAZ_LISTE).

Bulgu (docs/olcum/rakip_kiyas.md): eski geçici katman + kara liste (SIR_YOLLARI) düzeninde listede OLMAYAN gizli dosya
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

ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
