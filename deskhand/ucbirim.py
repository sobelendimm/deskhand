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

# ---------------------------------------------------------------- "uçbirim olabilir" ve klavye menüsü işaretleri

ACIK_OLABILIR_SN = 30.0  # gömülü uçbirim açabilen tuştan sonra pencere bu kadar süre "uçbirim olabilir"
MENU_SN = 3.0            # klavye menüsü tuşundan sonra p/y bu süre içinde yapıştırma sayılır


def _akor_kumesi(akor):
    return frozenset(guvenlik._tus_kanonik(x) for x in akor.split("+") if x)


# Dolphin F4 / shift+F4, Kate F4, VS Code ctrl+` / ctrl+shift+`, Konsole parçası ctrl+alt+t / ctrl+shift+t, alt+F12
ACMA_AKORLARI = {frozenset({"f4"}), frozenset({"shift", "f4"}), frozenset({"ctrl", "grave"}),
                 frozenset({"ctrl", "shift", "grave"}), frozenset({"ctrl", "alt", "t"}), frozenset({"ctrl", "shift", "t"}),
                 frozenset({"alt", "f12"}), frozenset({"ctrl", "apostrophe"}), frozenset({"ctrl", "shift", "apostrophe"})}


def acma_tusu_mu(akor):
    """Uçbirim (paneli) açabilen kısayol mu?"""
    k = _akor_kumesi(akor)
    return k in ACMA_AKORLARI or ({"grave", "ctrl"} <= k)


def gomulebilir(au, k):
    """Pencere sınıfı uçbirim gömebilen bir uygulama mı (Dolphin, Kate, IDE…)?"""
    return bool(k) and k != EKRAN and bool(guvenlik._GOMULU.search(au.sinif(k) or ""))


def _isaret_yolu(au, k, tur):
    return os.path.join(_dizin(), f"{tur}-{_anahtar(au, k)}")


def isaret_koy(au, k, tur):
    """Pencere için zaman işareti (RUNTIME_DIR/ucbirim/<tur>-<sha1>, 0600): süreçler arası (CLI her komutta yeni süreç)."""
    try:
        yol = _isaret_yolu(au, k, tur)
        fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(str(time.time()))
    except (OSError, Dur):
        pass


def isaret_taze(au, k, tur, sn):
    try:
        with open(_isaret_yolu(au, k, tur)) as f:
            return time.time() - float(f.read().strip() or 0) <= sn
    except (OSError, ValueError, Dur):
        return False


def ucbirim_hedefi(au, k):
    """Pencere uçbirim mi / uçbirim barındırıyor mu (sınıf, süreç ağacında tty'li kabuk, AT-SPI terminal rolü) ya da son
    ACIK_OLABILIR_SN içinde ona uçbirim açabilen bir tuş gönderildi mi? "Uçbirim değil" sonucu önbelleğe alınmaz: her
    çağrıda yeniden hesaplanır (F4'ten sonra kabuk doğduğu an)."""
    if not k or k == EKRAN:
        return False
    return guvenlik.ucbirim_penceresi_mi(k) or isaret_taze(au, k, "ucbirim", ACIK_OLABILIR_SN)


def tus_sonrasi(au, k, kombinasyon):
    """tus/bas gönderildikten sonra: gömebilen pencereye uçbirim açma tuşu gittiyse 30 sn "uçbirim olabilir";
    klavye menüsü tuşu gittiyse 3 sn "menü açık" (ardından gelen p/y yapıştırma sayılır)."""
    if not k or k == EKRAN:
        return
    akorlar = kombinasyon.split()
    if gomulebilir(au, k) and any(acma_tusu_mu(a) for a in akorlar):
        isaret_koy(au, k, "ucbirim")
    if akorlar and guvenlik.menu_tusu_mu(akorlar[-1]):
        isaret_koy(au, k, "menu")


def menu_acik_mi(au, k):
    return isaret_taze(au, k, "menu", MENU_SN)


# ---------------------------------------------------------------- kapı: uçbirimde HER Enter insan onayı ister

def _on_plan_notu(au, k):
    from . import kendi
    pid = guvenlik._pencere_pid(au, k)
    adlar = kendi.on_plan_surecleri(pid) if pid else None
    if adlar and not any(a in KABUK_BENZERI or a.startswith(("tmux", "ssh", "mosh")) for a in adlar):
        return _("ön planda kabuk değil: {adlar} (vim/REPL olabilir; yine de satır çalıştırılır)").format(
            adlar=", ".join(sorted(set(adlar))))
    return ""


def enter_kapisi(k, onayli, ek="", gizli=False, goruntu_al=True, olabilir=False, yalniz_ek=False):
    """Uçbirim (ya da gömülü uçbirim) barındıran pencereye satırı çalıştıran tuş (enter, kpenter, ctrl+j/m/o, yazıdaki
    \\n) gitmeden HEMEN ÖNCE: satır içeriğinden BAĞIMSIZ insan onayı — bir Enter = bir onay (önceki onay taşınmaz).
    Onay isteği o anki satırı (okunabiliyorsa; `ek` = aynı eylemde Enter'dan önce yazılacak metin), "uçbirimde komut
    çalıştırılacak" bilgisini ve riskli_komut uyarısını ("YIKICI OLABİLİR: …") taşır. --onayli (CLI, kullanıcı sohbette
    onayladı) geçer; gözetimsiz kipte ret. olabilir=True: aynı çağrıda uçbirim açma tuşu önce geldi.
    yalniz_ek=True: satır yalnız `ek` (aynı yazının önceki Enter'ından sonraki satır; ekrandaki satır henüz o değil).
    → onay alındı mı (False = pencere uçbirim değil, kapı yok)."""
    au = sec()
    if not (olabilir or ucbirim_hedefi(au, k)):
        return False
    if guvenlik.onay_kapsami() == "kart":  # Enter kapısı onay istemez; satır uyarısı yalnız günlüğe (ucuz: OCR yok)
        t = {"metin": "", "kirli": False} if yalniz_ek else tampon_oku(au, k)
        uyari = next((r for r in (guvenlik.riskli_komut(a, gizli=gizli) for a in (t.get("metin", "") + ek, ek)) if r),
                     None)  # gizli: neden yalnız kalıp adı (günlüğe metin parçası gitmez)
        guvenlik.onaysiz_serbest("uçbirim Enter", f"YIKICI OLABİLİR: {uyari}" if uyari else "")
        return False
    if guvenlik.onayli_gecerli(onayli):
        return True
    okunan = None if yalniz_ek else satir_oku(k)
    tampon = {"metin": "", "kirli": False} if yalniz_ek else tampon_oku(au, k)
    aday = [a + ek for a in adaylar(okunan or [])]
    if not tampon.get("kirli"):
        aday.append(tampon.get("metin", "") + ek)
    elif ek:
        aday.append(ek)
    uyari = next((r for r in (guvenlik.riskli_komut(a, gizli=gizli) for a in aday) if r), None)  # gizli: kalıp adı
    genel_uyari = False  # uyarı metni okunan satırdan sözcük taşımıyor (ajana olduğu gibi gidebilir)
    if uyari is None and any(_GECMIS_ACILIMI.search(a) for a in aday):
        genel_uyari = True
        uyari = _("satırda geçmiş açılımı/geçmiş komutu var (!!, !n, ^a^b, fc, r, history -s): çalışacak komut görünmez")
    satir = next((a for a in aday if guvenlik.riskli_komut(a)), None) or \
        (aday[0] if okunan else (aday[-1] if aday else ""))
    goster = guvenlik._yazilacak(satir, gizli) if satir else _("(satır okunamadı)")
    b = au.baslik(k)
    ayrinti = [_("Uçbirimde komut çalıştırılacak (Enter)."), _("satır: {satir}").format(satir=goster)]
    if uyari:
        ayrinti.append(_("YIKICI OLABİLİR: {neden}").format(neden=uyari))
    not_ = _on_plan_notu(au, k)
    if not_:
        ayrinti.append(not_)
    ayrinti.append(_("uçbirim: {sinif}").format(sinif=au.sinif(k)) +
                   ("" if guvenlik.ucbirim_mi(au.sinif(k)) else " " + _("(gömülü uçbirim)")))
    guvenlik._EYLEM.onaylandi = False  # bir Enter = bir onay: bu eylemdeki önceki onay bu Enter'ı kapsamaz
    goruntu = guvenlik.hedef_goruntusu(k) if goruntu_al else None
    izin, onay_neden = guvenlik._panelden_onay(_("Uçbirimde komut çalıştır: {satir}").format(satir=goster), b,
                                               "\n".join(ayrinti), goruntu,
                                               ajan_eylem=_("Uçbirimde komut çalıştır (Enter)"))
    if not izin:
        # Ajana dönen iletiye EKRANDAN OKUNAN (OCR) satırdan türeyen neden konmaz: ham uçbirim kırpımına binen yasak
        # pencerenin sözcükleri (dosya/komut adı) taşınabilir (SINIF-MASKE). Ayrıntı yalnız insan panelinde. Ajanın
        # kendi bildiği metinden (yazdığı tampon + ek) çıkan neden olduğu gibi kalır.
        bilinen = ([tampon.get("metin", "") + ek] if not tampon.get("kirli") else []) + ([ek] if ek else [])
        uyari_ajan = next((r for r in (guvenlik.riskli_komut(a, gizli=gizli) for a in bilinen) if r), None)
        if uyari and not uyari_ajan:
            uyari_ajan = uyari if genel_uyari else _("ekrandan okunan satır (ayrıntı yalnız onay panelinde)")
        with guvenlik.baslik_gizle(gizli):  # gizli yazı: başlık (önizleme) iletiye girmez (CLI yolu dahil)
            bg = guvenlik.baslik_goster(b)
        raise Dur(10, _("UÇBİRİM ENTER KAPISI ({baslik}): uçbirimde komut çalıştırmak (Enter) her zaman kullanıcının "
                        "onayını ister ({onay_neden}){uyari}; kullanıcı sohbette açıkça onayladıysa --onayli ile "
                        "tekrarla").format(baslik=bg, onay_neden=onay_neden,
                                           uyari=("; " + _("YIKICI OLABİLİR: {neden}").format(neden=uyari_ajan))
                                           if uyari_ajan else ""), tur="hassas")
    return True


def tus_dizisi_kapisi(k, onayli, kombinasyon):
    """tus/bas: dizideki HER Enter eşdeğeri için ayrı onay (sırayla, gönderimden önce). Satır = okunan/tampon + önceki
    yazdırılabilir tuşlar (ilk Enter), sonrakilerde aradaki tuşlar. Aynı çağrıda uçbirim gömebilen pencereye uçbirim
    açma tuşu (F4, ctrl+`…) Enter'dan önce geliyorsa o Enter da onay ister. → Enter başına onay listesi
    ([True, False…]; hiçbiri onaylanmadıysa False)."""
    if not guvenlik.enter_tusu_mu(kombinasyon):
        return False
    au = sec()
    olabilir = False
    gecici = {"metin": "", "kirli": False}
    ilk, onaylar = True, []
    for akor in kombinasyon.split():
        if not olabilir and acma_tusu_mu(akor) and gomulebilir(au, k):
            olabilir = True
        if guvenlik.enter_tusu_mu(akor):
            ek = "" if gecici["kirli"] else gecici["metin"]
            onaylar.append(enter_kapisi(k, onayli, ek=ek if ilk else gecici["metin"], olabilir=olabilir))
            ilk = False
            gecici = {"metin": "", "kirli": False}
            continue
        _tus_isle(gecici, akor)
    return onaylar if any(onaylar) else False
