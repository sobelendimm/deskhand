"""Uçbirim ENTER KAPISI (docs/ARCHITECTURE.md §4): yıkıcı komut parça parça yazılıp (ör. "sud" + "o reboot") ayrı bir
Enter ile çalıştırılamasın.

Uçbirim sınıflı bir pencereye satırı çalıştıran bir tuş (enter, kpenter, ctrl+j, ctrl+m, ctrl+o; yazının içindeki \\n)
gitmeden HEMEN ÖNCE o anki giriş satırı okunur — önce AT-SPI (uçbirim ögesinin imleç satırı; erişilebilirlik zaten
açıksa), yoksa pencerenin OCR'ı (alttaki satırlar) — ve guvenlik.riskli_komut'tan geçer; yıkıcıysa insan onayı
(yoksa 10). Yedek: Deskhand'in bu pencereye yazdıklarının TAMPONU (RUNTIME_DIR/ucbirim/<sha1(arka uç:pencere:pid)>.json,
dosya 0600, dizin 0700, flock): yazdırılabilir tuşlar ve `type` eklenir, BackSpace siler; Enter / ctrl+c / ctrl+u / Esc
temizler; ok tuşları, ctrl+a/e/r/w, Tab, tıklama, orta tık, yapıştırma "kirli" yapar (satırın içeriği artık bilinmez).
Yeni pencere, başka bir uçbirim penceresine geçiş ve TAMPON_SN hareketsizlik de "kirli" yapar (bu arada kullanıcı
satırı değiştirmiş olabilir; temiz saymak parçalı yazmaya kapı açardı). Kirliyken satır okunamıyorsa Enter onay ister.

Ön plandaki süreç kabuk değilse (pencere PID → uçbirimin çocuğu → /proc/<kabuk>/stat tpgid; vim/less/REPL) yazı
sıradan yazıdır (kapı uygulanmaz); ssh / tmux / kapsayıcı kabuğu ise denetim sürer. PID bilinmiyorsa kapı uygulanır."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time

from . import guvenlik, yollar
from .arka_uc import EKRAN, sec
from .hata import Dur
from .i18n import _

TAMPON_SN = 120.0
# ön planda bunlardan biri varsa satır bir KABUĞA gider (Enter kapısı uygulanır)
KABUK_BENZERI = {"bash", "zsh", "fish", "sh", "dash", "ksh", "mksh", "tcsh", "csh", "nu", "xonsh", "elvish", "yash",
                 "ion", "busybox", "login", "ssh", "mosh-client", "mosh", "et", "telnet", "rlogin", "rsh", "tmux",
                 "tmux: client", "screen", "zellij", "dtach", "abduco", "sudo", "su", "doas", "run0", "machinectl",
                 "toolbox", "distrobox", "podman", "docker", "kubectl", "lxc", "incus", "script", "nsenter", "chroot",
                 "systemd-nspawn", "flatpak", "sshpass", "autossh", "xonsh", "pwsh", "osh", "oil"}
# dotool tuş adı → yazdığı karakter (yazdırılabilir tuşların tamponu için)
_TUS_KARAKTER = {"space": " ", "minus": "-", "equal": "=", "slash": "/", "dot": ".", "comma": ",", "semicolon": ";",
                 "apostrophe": "'", "grave": "`", "backslash": "\\", "leftbrace": "[", "rightbrace": "]",
                 "kpminus": "-", "kpplus": "+", "kpasterisk": "*", "kpslash": "/", "kpdot": "."}
_ISTEM = re.compile(r"[$#>%❯»➜λ\]:]\s*")


def ucbirim_hedefi(au, k):
    """Pencere uçbirim mi ya da uçbirim barındırıyor mu (sınıf, süreç ağacında tty'li kabuk, AT-SPI terminal rolü)?"""
    return bool(k) and k != EKRAN and guvenlik.ucbirim_penceresi_mi(k)


# satırda geçmiş açılımı (!!, !n, !-n, !dizge, ^a^b) ya da geçmişi değiştiren/çalıştıran komut: çalışacak komut görünmez
_GECMIS_ACILIMI = re.compile(r"(?:^|[\s;&|(`])(?:!(?:!|-?\d+|[A-Za-z_./][^\s=]*)|\^[^^\s]+\^)|"
                             r"(?:^|[\s;&|(])(?:fc|r)(?:\s|$)|\b(?:history|print)\s+(?:-\w*\s+)*-s\b")


# ---------------------------------------------------------------- ön plan süreci

def on_plan_kabuk_mu(au, k):
    """Uçbirimin ön planında kabuk (ya da ssh/çoklayıcı/kapsayıcı kabuğu) var mı? Bilinmiyorsa True (güvenli taraf)."""
    from . import kendi
    pid = guvenlik._pencere_pid(au, k)
    if not pid:
        return True
    adlar = kendi.on_plan_surecleri(pid)
    if not adlar:
        return True
    return any(a in KABUK_BENZERI or a.startswith(("tmux", "ssh", "mosh")) for a in adlar)


# ---------------------------------------------------------------- tampon

def _anahtar(au, k):
    pid = guvenlik._pencere_pid(au, k)
    return hashlib.sha1(f"{au.ad}:{k}:{pid or ''}".encode()).hexdigest()


def _dizin():
    d = os.path.join(yollar.runtime_dir(), "ucbirim")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


@contextlib.contextmanager
def _tampon(au, k):
    """Kilitli tampon kaydı {metin, kirli, zaman} (değiştirilirse geri yazılır)."""
    d = _dizin()
    anahtar = _anahtar(au, k)
    yol = os.path.join(d, anahtar + ".json")
    fd = os.open(yol, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            t = json.loads(f.read() or "{}")
        except ValueError:
            t = {}
        simdi = time.time()
        if not t:
            t = {"metin": "", "kirli": True, "zaman": simdi}  # yeni pencere: satırda ne olduğu bilinmiyor
        elif simdi - float(t.get("zaman") or 0) > TAMPON_SN:
            t.update(metin="", kirli=True)
        son_yol = os.path.join(d, "son")
        try:
            with open(son_yol) as s:
                son = s.read().strip()
        except OSError:
            son = ""
        if son and son != anahtar:
            t.update(metin="", kirli=True)  # başka uçbirim penceresine geçilmişti
        yield t
        t["zaman"] = time.time()
        f.seek(0)
        f.truncate()
        f.write(json.dumps(t))
        try:
            with open(son_yol + ".tmp", "w") as s:
                s.write(anahtar)
            os.chmod(son_yol + ".tmp", 0o600)
            os.replace(son_yol + ".tmp", son_yol)
        except OSError:
            pass


def _temizle(t):
    t.update(metin="", kirli=False, onayli=None)


def _kirlet(t):
    t.update(metin="", kirli=True, onayli=None)


def _tus_isle(t, kombinasyon):
    for akor in kombinasyon.split():
        kume = {guvenlik._tus_kanonik(x) for x in akor.split("+") if x}
        if guvenlik.enter_tusu_mu(akor) or ("ctrl" in kume and kume & {"c", "u"}) or kume == {"esc"}:
            _temizle(t)
            continue
        if kume == {"backspace"}:
            t["metin"] = t["metin"][:-1]
            continue
        degistirici = kume & {"ctrl", "alt", "super"}
        tuslar = [x for x in akor.split("+") if x and guvenlik._tus_kanonik(x) not in ("shift", "ctrl", "alt", "super")]
        if not degistirici and len(tuslar) == 1:
            ad = tuslar[0][2:] if tuslar[0].startswith("x:") else tuslar[0]
            c = _TUS_KARAKTER.get(ad.lower(), ad if len(ad) == 1 else None)
            if c is not None and (c.isalnum() or c in _TUS_KARAKTER.values()):
                if "shift" in kume:
                    if not c.isalpha():
                        _kirlet(t)
                        continue
                    c = c.upper()
                t["metin"] += c
                continue
        _kirlet(t)  # ok tuşları, ctrl+a/e/r/w/k/y, Tab, Home/End, yapıştırma…: satır artık bilinmez


def tampon_isle(au, k, *, yazi=None, tus=None, kirli=False, temiz=False, onayli=False):
    """Uçbirim penceresine giden girdiyi tampona işle (uçbirim değilse hiçbir şey yapmaz). Hata yutulur (tampon
    yalnız kapının yedeğidir; yazılamazsa kapı satırı okuyamadığında güvenli tarafta onay ister)."""
    try:
        if not ucbirim_hedefi(au, k):
            return
        with _tampon(au, k) as t:
            if kirli:
                _kirlet(t)
            if temiz:
                _temizle(t)
            if tus:
                _tus_isle(t, tus)
            for c in yazi or "":
                if c == "\n":
                    _temizle(t)
                elif c == "\t" or c == "\b" or ord(c) < 0x20:
                    _kirlet(t)
                else:
                    t["metin"] += c
            if onayli and not t.get("kirli"):  # bu satır (yazılırken) kullanıcıca onaylandı: Enter'da yeniden sorulmaz
                t["onayli"] = t["metin"]
    except (OSError, Dur):
        pass


def tampon_oku(au, k):
    try:
        with _tampon(au, k) as t:
            return dict(t)
    except OSError:
        return {"metin": "", "kirli": True}


# ---------------------------------------------------------------- giriş satırını okuma

def _atspi_satirlar(k):
    """Erişilebilirlik zaten açıksa (kendiliğinden AÇILMAZ: kalıcı masaüstü ayarı) uçbirim ögesinin imleç satırı ve
    önceki iki satır → [satır] | None."""
    try:
        from . import erisim
        if not erisim.erisim_acik():
            return None
        return erisim.imlec_satirlari(k)
    except Dur:
        return None
    except Exception:  # noqa: BLE001 - okuma isteğe bağlı: OCR'a düşülür
        return None


def _ocr_satirlar(k):
    """Pencerenin OCR'ı → en alttaki (en çok 3) yazılı satır | None."""
    try:
        from .gorsel import pencere_goruntusu
        from .ocr import oku, satirla
        im, _geo, _kok = pencere_goruntusu(k)
        satirlar = [s for s in satirla(oku(im)) if (s.get("t") or "").strip()]
    except Dur:
        return None
    except Exception:  # noqa: BLE001
        return None
    if not satirlar:
        return None
    satirlar.sort(key=lambda s: (s.get("y", 0), s.get("x", 0)))
    return [s["t"] for s in satirlar[-4:]]  # gömülü uçbirimin altında durum çubuğu olabilir: bir satır fazla


def satir_oku(k):
    """O anki giriş satırı adayları (önce AT-SPI, yoksa OCR) → [satır] | None (okunamadı)."""
    return _atspi_satirlar(k) or _ocr_satirlar(k)


def adaylar(satirlar):
    """Okunan satırlar → denetlenecek komut adayları: istem (prompt) işaretinden sonrası, kaydırılmış (sarılmış) uzun
    komut için birleşik satırlar. Yanlış negatife karşı birden çok aday (biri yıkıcıysa onay)."""
    satirlar = [s.rstrip() for s in satirlar if s and s.strip()]
    if not satirlar:
        return []
    p = max((i for i, s in enumerate(satirlar) if _ISTEM.search(s)), default=None)
    tabanlar = ["".join(satirlar[p:])] if p is not None else ["".join(satirlar[-n:]) for n in (1, 2, 3)
                                                             if n <= len(satirlar)]
    tabanlar += satirlar[-4:]  # tek tek satırlar (istem işareti yanlış satırda bulunduysa)
    sonuc = []
    for t in tabanlar:
        sonuc.append(t)
        sonuc += [t[m.end():] for m in _ISTEM.finditer(t)]
        ilk = t.split(None, 1)
        if len(ilk) == 2 and len(ilk[0]) <= 2:  # OCR istemi yanlış okuduysa ("S sudo …")
            sonuc.append(ilk[1])
    return list(dict.fromkeys(x for x in sonuc if x.strip()))


# ---------------------------------------------------------------- kapı

def enter_kapisi(k, onayli, ek="", gizli=False, goruntu_al=True):
    """Uçbirime satırı çalıştıran tuş gitmeden HEMEN ÖNCE: giriş satırı (okunan + Deskhand'in tamponu; `ek` = aynı
    eylemde Enter'dan önce yazılacak metin) yıkıcı komutsa ya da satır okunamıyor VE bilinmiyorsa insan onayı (--onayli
    yoksa panelden; red/gözetimsiz → Dur 10). → onay gerekti mi (onaylandı)."""
    au = sec()
    if not ucbirim_hedefi(au, k) or not on_plan_kabuk_mu(au, k):
        return False
    okunan = satir_oku(k)
    tampon = tampon_oku(au, k)
    aday = [a + ek for a in adaylar(okunan or [])]
    if not tampon.get("kirli"):
        aday.append(tampon.get("metin", "") + ek)
    elif ek:
        aday.append(ek)
    onaylanan = (tampon.get("onayli") or "") if not tampon.get("kirli") and not ek else ""

    def onayli_mi(a):  # yazılırken onaylanmış satırın kendisi (istem öneki zararsız)
        a = a.rstrip()
        return bool(onaylanan.strip()) and a.endswith(onaylanan.strip()) and \
            guvenlik.riskli_komut(a[:len(a) - len(onaylanan.strip())]) is None
    neden = next((r for r in (guvenlik.riskli_komut(a) for a in aday if not onayli_mi(a)) if r), None)
    if neden is None and any(_GECMIS_ACILIMI.search(a) for a in aday if not onayli_mi(a)):
        neden = _("satırda geçmiş açılımı/geçmiş komutu var (!!, !n, ^a^b, fc, r, history -s): çalışacak komut bilinmiyor")
    if neden is None and okunan is None and tampon.get("kirli"):
        neden = _("giriş satırı okunamadı ve içeriği bilinmiyor (geçmişten çağrılmış ya da düzenlenmiş olabilir)")
    if neden is None:
        return False
    if guvenlik.onayli_gecerli(onayli):
        return True
    b = au.baslik(k)
    satir = next((a for a in aday if guvenlik.riskli_komut(a)), aday[-1] if aday else "")
    goster = guvenlik._yazilacak(satir, gizli) if satir else _("(okunamadı)")
    ayrinti = neden + "\n" + _("uçbirim: {sinif}").format(sinif=au.sinif(k)) + "\n" + \
        _("çalışacak satır: {satir}").format(satir=goster)
    goruntu = None if getattr(guvenlik._EYLEM, "onaylandi", False) or not goruntu_al else guvenlik.hedef_goruntusu(k)
    izin, onay_neden = guvenlik._panelden_onay(_("Uçbirimde Enter: {satir}").format(satir=goster), b, ayrinti, goruntu)
    if not izin:
        raise Dur(10, _("UÇBİRİM ENTER KAPISI ({neden} ← {baslik}): satırı çalıştırmak kullanıcının onayını ister "
                        "({onay_neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
            neden=neden, baslik=repr(b), onay_neden=onay_neden), tur="hassas")
    return True


def tus_dizisi_kapisi(k, onayli, kombinasyon):
    """tus/bas: dizideki her Enter eşdeğerinden önce. İlk Enter'da satır = okunan/tampon + önceki yazdırılabilir tuşlar;
    sonraki Enter'larda yalnız aradaki tuşlar. → onay gerekti mi."""
    if not guvenlik.enter_tusu_mu(kombinasyon):
        return False
    au = sec()
    if not ucbirim_hedefi(au, k):
        return False
    gecici = {"metin": "", "kirli": False}
    ilk, onay = True, False
    for akor in kombinasyon.split():
        if guvenlik.enter_tusu_mu(akor):
            if ilk:
                onay = enter_kapisi(k, onayli or onay, ek="" if gecici["kirli"] else gecici["metin"])
                ilk = False
            else:
                r = guvenlik.riskli_komut(gecici["metin"]) if not gecici["kirli"] else None
                if r and not onay:
                    onay = enter_kapisi(k, onayli, ek=gecici["metin"])
            gecici = {"metin": "", "kirli": False}
            continue
        _tus_isle(gecici, akor)
    return onay
