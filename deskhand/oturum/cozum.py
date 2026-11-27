"""Uygulama çözümü: ajanın yazdığı ad → başlatılacak GERÇEK uygulamanın kimlikleri (politika ve "açık mı"
tespiti bunlardan hesaplanır, ham addan değil).

Aynı .desktop eşlemesi `uygulama.uygulama_adaylari` ile yapılır (uygulama_bul / api.uygulama_komutu ile birebir);
ad PATH'te bir çalıştırılabilirse o da eklenir (api args verilince onu başlatır). Mutlak/göreli yol verilirse
yolun kendisi çözülür. Hiçbir süreç BAŞLATILMAZ; yalnız dosya okunur (.desktop, betik ilk satırı).

Çıktı (Cozum):
  adlar     politika eşlemesi için aday adlar (ham ad, .desktop kimliği, Exec ikilisi + gerçek yolu, Flatpak kimliği…)
  ikililer  /proc'ta aranacak süreç adları (Exec ikilisi, gerçek yolunun adı, yorumlayıcıyla çalışan betik adı)
  flatpaklar  Exec `flatpak run <kimlik>` ise kimlik(ler)
  belirsiz  "çalışıyor mu" güvenle bilinemiyorsa nedenler (ikili yok, kabuk betiği başlatıcı, AppImage…)
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass, field

# Exec'te asıl programdan önce gelen sarmalayıcılar (seçenekleri atlanır)
_SARMALAYICI = {"env", "nice", "ionice", "nohup", "setsid", "taskset", "prime-run", "gamemoderun", "mangohud",
                "pw-jack", "padsp", "dbus-run-session", "chrt", "firejail", "strace"}
# Betiği argümanla alan yorumlayıcılar: süreç adı yorumlayıcıdır, kimlik betik adıdır
_YORUMLAYICI_ON = ("python", "perl", "ruby", "node", "nodejs", "lua", "luajit", "php", "gjs", "java", "mono",
                   "wish", "tclsh", "pypy")
_KABUK = {"sh", "bash", "dash", "zsh", "ksh", "mksh", "fish", "csh", "tcsh"}
_DESKTOP_ALAN_KODLARI = {"%f", "%F", "%u", "%U", "%i", "%c", "%k", "%d", "%D", "%n", "%N", "%v", "%m"}


@dataclass
class Cozum:
    girdi: str
    adlar: list = field(default_factory=list)
    ikililer: list = field(default_factory=list)
    flatpaklar: list = field(default_factory=list)
    desktoplar: list = field(default_factory=list)   # [{"yol","kimlik","exec"}]
    exec_argv: list = field(default_factory=list)    # tek .desktop eşleşmesinin alan kodsuz Exec'i
    belirsiz: list = field(default_factory=list)

    def ekle_ad(self, *adlar):
        for a in adlar:
            a = (a or "").strip()
            if a and a not in self.adlar:
                self.adlar.append(a)

    def ekle_ikili(self, *adlar):
        for a in adlar:
            a = os.path.basename((a or "").strip())
            if a and a not in self.ikililer:
                self.ikililer.append(a)

    def ekle_belirsiz(self, neden: str):
        if neden not in self.belirsiz:
            self.belirsiz.append(neden)

    def ozet(self) -> dict:
        return {"adlar": list(self.adlar), "ikililer": list(self.ikililer), "flatpak": list(self.flatpaklar),
                "desktop": [d["kimlik"] for d in self.desktoplar], "belirsiz": list(self.belirsiz)}


def exec_argv(exec_satiri: str) -> list[str]:
    """.desktop Exec= → argv (alan kodları %f/%U…, Flatpak @@ işaretleri ve %% atılır). Bozuksa []."""
    try:
        parcalar = shlex.split(exec_satiri or "")
    except ValueError:
        return []
    sonuc = []
    for p in parcalar:
        if p in _DESKTOP_ALAN_KODLARI or p in ("@@", "@@u", "@@f"):
            continue
        sonuc.append(p.replace("%%", "%"))
    return sonuc


def _yorumlayici_mi(ad: str) -> bool:
    ad = os.path.basename(ad).lower()
    return any(ad == y or ad.startswith(y) and ad[len(y):].replace(".", "").isdigit() for y in _YORUMLAYICI_ON)


def _sarmalayicilari_at(argv: list[str]) -> list[str]:
    """env VAR=x / nice -n 5 / … sarmalayıcılarını atla → asıl program ve argümanları."""
    i = 0
    while i < len(argv):
        ad = os.path.basename(argv[i])
        if ad not in _SARMALAYICI:
            break
        i += 1
        while i < len(argv):
            a = argv[i]
            if a in ("-u", "-n", "-c", "-p", "--chdir", "-C") and i + 1 < len(argv):
                i += 2
            elif a.startswith("-") or ("=" in a and not a.startswith("/")) or a.lstrip("-").isdigit():
                i += 1
            else:
                break
    return argv[i:]


# `flatpak run` seçeneklerinden DEĞER alanlar (GOption `--ad değer` yazımını da kabul eder: değer kimlik sayılmaz)
_FLATPAK_RUN_DEGERLI = {
    "--arch", "--branch", "--command", "--cwd", "--runtime", "--runtime-version", "--commit", "--runtime-commit",
    "--share", "--unshare", "--socket", "--nosocket", "--device", "--nodevice", "--allow", "--disallow",
    "--filesystem", "--nofilesystem", "--add-policy", "--remove-policy", "--env", "--unset-env", "--env-fd",
    "--own-name", "--talk-name", "--no-talk-name", "--system-own-name", "--system-talk-name",
    "--system-no-talk-name", "--persist", "--app-path", "--usr-path", "--parent-pid", "--instance-id-fd",
    "--sandbox-expose", "--sandbox-expose-ro", "--sandbox-expose-path", "--sandbox-expose-path-ro",
    "--sandbox-expose-path-try", "--sandbox-expose-path-ro-try", "--sandbox-a11y-own-name", "--installation"}
_FLATPAK_DISA_AKTARIM = re.compile(r"/flatpak/exports/bin/([A-Za-z0-9_.-]+)$")
_FLATPAK_UYGULAMA_YOLU = re.compile(r"/flatpak/app/([A-Za-z0-9_.-]+)/")


def _flatpak_ref_kimligi(ref: str) -> str:
    """`kimlik`, `kimlik/arch/branch` ya da `app/kimlik/arch/branch` → kimlik."""
    p = ref.split("/")
    return p[1] if len(p) > 1 and p[0] in ("app", "runtime") else p[0]


def _flatpak_disa_aktarim(program: str) -> str | None:
    """Flatpak dışa aktarım sarmalayıcısı (…/flatpak/exports/bin/<kimlik>, ör. /var/lib/flatpak/exports/bin/X ya da
    ~/.local/share/flatpak/exports/bin/X; PATH'teki çıplak adı ve sembolik bağın hedefi dahil) → kimlik | None."""
    adaylar = [program]
    if "/" not in program and program.count(".") >= 2:
        adaylar.append(shutil.which(program) or "")
    for y in list(adaylar):
        if y and os.path.islink(y):
            adaylar.append(os.path.realpath(y))
    for y in adaylar:
        m = _FLATPAK_DISA_AKTARIM.search(y or "") or _FLATPAK_UYGULAMA_YOLU.search(y or "")
        if m and "." in m.group(1):
            return m.group(1)
    return None


def _flatpak_kimligi(argv: list[str]) -> tuple[str | None, str | None]:
    """Flatpak uygulama kimliğine normalleştir → (kimlik, --command değeri). Kapsanan yazımlar:
    `flatpak [genel seçenekler] run [seçenekler] <ref> …` (ref `kimlik/arch/branch` ya da `app/…` olabilir; `--ad değer`
    biçimindeki seçenek değeri kimlik sayılmaz) ve dışa aktarım sarmalayıcıları (…/flatpak/exports/bin/<kimlik>)."""
    if not argv:
        return None, None
    if os.path.basename(argv[0]) != "flatpak":
        return _flatpak_disa_aktarim(str(argv[0])), None
    i = 1
    while i < len(argv) and argv[i].startswith("-"):  # genel seçenekler (--verbose, --user, --installation=…)
        i += 1
    if i >= len(argv) or argv[i] != "run":
        return None, None
    i += 1
    komut = None
    while i < len(argv):
        a = argv[i]
        if a == "--":
            i += 1
            return (_flatpak_ref_kimligi(argv[i]), komut) if i < len(argv) else (None, komut)
        if a.startswith("--command="):
            komut = a.split("=", 1)[1]
        elif a in _FLATPAK_RUN_DEGERLI and i + 1 < len(argv):
            if a == "--command":
                komut = argv[i + 1]
            i += 1
        elif not a.startswith("-"):
            return _flatpak_ref_kimligi(a), komut
        i += 1
    return None, komut


def _betik_yorumlayicisi(yol: str) -> str | None:
    """Dosya #! ile başlıyorsa yorumlayıcının adı (env python3 → python3), değilse None."""
    try:
        with open(yol, "rb") as f:
            ilk = f.readline(256)
    except OSError:
        return None
    if not ilk.startswith(b"#!"):
        return None
    parcalar = ilk[2:].decode(errors="replace").split()
    if not parcalar:
        return ""
    ad = os.path.basename(parcalar[0])
    if ad == "env":
        kalan = [p for p in parcalar[1:] if not p.startswith("-")]
        ad = os.path.basename(kalan[0]) if kalan else ""
    return ad


def argv_coz(argv: list[str], c: Cozum) -> None:
    """Bir komut satırını (Exec ya da PATH'teki ikili) çöz → c'ye ad/ikili/flatpak/belirsizlik ekle."""
    argv = _sarmalayicilari_at(list(argv))
    if not argv:
        c.ekle_belirsiz("komut boş")
        return
    fk, fkomut = _flatpak_kimligi(argv)
    if fk:
        c.ekle_ad(fk)
        if fk not in c.flatpaklar:
            c.flatpaklar.append(fk)
        if fkomut:
            c.ekle_ad(os.path.basename(fkomut))
            c.ekle_ikili(fkomut)  # sandbox içindeki süreç bu adla görünür (ana makinenin /proc'unda)
        return
    if os.path.basename(argv[0]) == "flatpak":
        c.ekle_belirsiz("flatpak komutu çözülemedi")
        return
    ilk = argv[0]
    yol = ilk if "/" in ilk else shutil.which(ilk)
    c.ekle_ad(os.path.basename(ilk))
    if not yol or not os.path.isfile(yol):
        c.ekle_belirsiz(f"ikili bulunamadı: {ilk}")
        return
    gercek = os.path.realpath(yol)
    ad = os.path.basename(ilk)
    c.ekle_ad(os.path.basename(gercek))
    if gercek.lower().endswith(".appimage") or ad.lower().endswith(".appimage"):
        c.ekle_belirsiz("AppImage (süreç adı farklı)")
        return
    if ad in _KABUK or os.path.basename(gercek) in _KABUK:
        c.ekle_belirsiz("kabuk komutu")
        return
    if _yorumlayici_mi(ad) or _yorumlayici_mi(gercek):
        betik = next((a for a in argv[1:] if not a.startswith("-")), None)
        if not betik:
            c.ekle_belirsiz("yorumlayıcı betiksiz")
            return
        c.ekle_ad(os.path.basename(betik))
        c.ekle_ikili(betik)
        return
    yorumlayici = _betik_yorumlayicisi(gercek)
    if yorumlayici is not None:
        if yorumlayici in _KABUK or not yorumlayici or not _yorumlayici_mi(yorumlayici):
            # /usr/bin/vivaldi-stable, libreoffice, electron başlatıcıları: başka bir ikiliyi exec eder
            c.ekle_belirsiz(f"başlatıcı betik ({yorumlayici or '?'}): {os.path.basename(gercek)}")
            return
        c.ekle_ikili(ad, os.path.basename(gercek))  # python betiği: argv[1] = betik yolu
        return
    c.ekle_ikili(ad, os.path.basename(gercek))


def coz(uygulama: str, girdiler=None) -> Cozum:
    """Ajanın yazdığı adı çöz. girdiler: .desktop listesi (testler; None = uygulama.masaustu_girdileri())."""
    c = Cozum(girdi=uygulama or "")
    ham = (uygulama or "").strip()
    if not ham:
        c.ekle_belirsiz("ad boş")
        return c
    c.ekle_ad(ham)
    if "/" in ham:  # yol: dosyanın kendisi
        argv_coz([ham], c)
        return c
    try:
        from ..uygulama import uygulama_adaylari
        adaylar = uygulama_adaylari(ham, girdiler)
    except Exception as e:  # noqa: BLE001 - .desktop okunamadı: belirsiz say
        adaylar = []
        c.ekle_belirsiz(f".desktop okunamadı: {e}")
    for g in adaylar:
        c.desktoplar.append({"yol": g.get("yol", ""), "kimlik": g.get("kimlik", ""), "exec": g.get("exec", "")})
        c.ekle_ad(g.get("kimlik", ""), g.get("ad_en", ""), g.get("ad", ""))
        argv = exec_argv(g.get("exec", ""))
        if not argv:
            c.ekle_belirsiz(f"Exec okunamadı: {g.get('kimlik', '')}")
            continue
        argv_coz(argv, c)
        if len(adaylar) == 1:
            c.exec_argv = argv
    if shutil.which(ham):  # api.uygulama_komutu args verilince (ya da .desktop yoksa) bunu başlatır
        argv_coz([ham], c)
    elif not adaylar:
        c.ekle_belirsiz(f"uygulama bulunamadı: {ham}")
    return c
