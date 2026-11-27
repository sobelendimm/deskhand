"""Oturum kopyası bekçisi + ortak canlılık/silme yardımcıları (YALNIZ standart kitaplık).

Sorun (22 Kas 2026): kapanan arka plan Firefox'larının kopyaları (225-514 MB) masaüstü kapanana dek RUNTIME_DIR'da
(tmpfs) kalıyordu → /run/user/<uid> %100 doldu, her durum dosyası yazımı OSError 28 verdi.

Çözüm: kopya dizinine SAHİP kaydı (.deskhand-sahip.json: tarayıcı sürecinin pid'i + /proc/<pid>/stat alan 22 başlangıç
zamanı; pid yeniden kullanımına karşı) yazılır ve tarayıcı başlatılınca bu betik ayrı süreç olarak açılır: sahip süreç
bitince (pidfd ile beklenir) ve kopyayı hiçbir canlı süreç kullanmıyorsa (/proc/*/cmdline, cwd, fd) kopya HEMEN silinir.
Ayrıca kopya.supur() (yeni kopya açılırken, masaüstü/uygulama başlatırken, doctor'da) aynı ölçütle ölüleri süpürür.

Silme güvenliği: yalnız kopya kökünün (adı "oturum", RUNTIME_DIR altında) DOĞRUDAN alt dizini, beklenen ad kalıbı
(<uygulama>-YYYYmmdd-HHMMSS-<pid>-<6 hex>), sembolik bağ değil; shutil.rmtree (Linux'ta fd tabanlı, bağ izlemez).

Betik olarak: python3 -I kopya_bekcisi.py --kok KOK --kopya YOL --pid PID --bas BAŞLANGIÇ
"""
from __future__ import annotations

import json
import os
import re
import select
import shutil
import sys
import time

SAHIP_DOSYA = ".deskhand-sahip.json"
KOPYA_DESENI = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}-\d{8}-\d{6}-\d+-[0-9a-f]{6}")
HAZIRLIK_AZAMI = 900.0   # sahibi henüz yazılmamış kopyayı hazırlayan süreç canlıysa bu kadar sn korunur
ESKI_PAY = 300.0         # sahip kaydı OLMAYAN (eski sürüm) kopya bu kadar sn yeniyse korunur (hazırlanıyor olabilir)
BEKCI_ARALIK = 2.0       # sahip öldükten sonra kopyayı kullanan süreç kaldıysa yoklama aralığı
BEKCI_AZAMI = 7 * 86400  # bekçi en çok bu kadar yaşar (sonra süpürme yapar)
SON_PAY = 5.0            # sahip bittikten sonra silmeden önce: masaüstü kapanıyorsa oturum.kapanis önce davransın
KORU_DOSYA = ".deskhand-koru.json"  # koruma işareti (bellek bekçisi): varken bekçi/süpürme kopyayı SİLMEZ
KORU_AZAMI = 86400.0     # işaret en çok bu kadar sn geçerli (sonra süpürülebilir; masaüstü kapanışı yine siler)


def surec_durumu(pid: int) -> tuple[str, str] | None:
    """/proc/<pid>/stat → (durum harfi, başlangıç zamanı alan 22); süreç yoksa None."""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            ham = f.read().decode(errors="replace")
    except (OSError, ValueError):
        return None
    alanlar = ham[ham.rfind(")") + 2:].split()
    if len(alanlar) < 20:
        return None
    return alanlar[0], alanlar[19]


def canli(pid, bas=None) -> bool:
    """pid yaşıyor (zombi değil) ve başlangıç zamanı bas ise (verildiyse) aynı süreç mi?"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    d = surec_durumu(pid)
    if d is None or d[0] in ("Z", "X", "x"):
        return False
    return bas is None or str(bas) == d[1]


def baslangic(pid: int) -> str | None:
    d = surec_durumu(pid)
    return d[1] if d else None


def sahip_oku(yol: str) -> dict:
    try:
        with open(os.path.join(yol, SAHIP_DOSYA), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sahip_yaz(yol: str, kayit: dict) -> None:
    """Atomik (0600). Alan doluysa sessizce geçer (kopya yine süpürülür: sahipsiz + eski sayılır)."""
    gecici = os.path.join(yol, f"{SAHIP_DOSYA}.{os.getpid()}.tmp")
    try:
        fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(kayit, f)
        os.replace(gecici, os.path.join(yol, SAHIP_DOSYA))
    except OSError:
        try:
            os.unlink(gecici)
        except OSError:
            pass


def koru_isaretle(yol: str, neden: str) -> None:
    """Kopyayı silinmeye karşı işaretle (ör. bellek bekçisinin bekleyen ya da başarısız Firefox yeniden başlatması: oturum
    yedeği kopyanın içinde). İşaret KORU_AZAMI sn geçerlidir; sonra kopya yine süpürülebilir (tmpfs dolmasın)."""
    gecici = os.path.join(yol, f"{KORU_DOSYA}.{os.getpid()}.tmp")
    try:
        fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"neden": str(neden), "zaman": time.time(), "pid": os.getpid()}, f)
        os.replace(gecici, os.path.join(yol, KORU_DOSYA))
    except OSError:
        try:
            os.unlink(gecici)
        except OSError:
            pass


def koru_kaldir(yol: str) -> None:
    try:
        os.unlink(os.path.join(yol, KORU_DOSYA))
    except OSError:
        pass


def korunuyor(yol: str) -> bool:
    """Kopyada geçerli (KORU_AZAMI sn'den yeni) koruma işareti var mı? Okunamayan işaret dosyanın yaşıyla değerlendirilir."""
    isaret = os.path.join(yol, KORU_DOSYA)
    try:
        st = os.lstat(isaret)
    except OSError:
        return False
    try:
        with open(isaret, encoding="utf-8") as f:
            zaman = float(json.load(f).get("zaman"))
    except (OSError, ValueError, TypeError, AttributeError):
        zaman = st.st_mtime
    return time.time() - zaman < KORU_AZAMI


def kullanilanlar(yollar) -> set[str]:
    """Verilen kopya yollarından hangilerini bir CANLI süreç kullanıyor (komut satırında geçiyor, çalışma dizini ya da
    açık dosyası altında)? Yalnız okunabilen (kendi kullanıcımızın) süreçlere bakılır. Bekçinin kendisi sayılmaz."""
    hedefler = {os.path.realpath(y): y for y in yollar}
    if not hedefler:
        return set()
    ikili = {g: g.encode() for g in hedefler}
    bulunan: set[str] = set()
    ben = os.getpid()
    try:
        pidler = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return set(hedefler.values())  # bilinemiyor: güvenli taraf (hepsi kullanımda)
    for pid in pidler:
        if pid == ben or len(bulunan) == len(hedefler):
            continue
        d = surec_durumu(pid)
        if d is None or d[0] in ("Z", "X", "x"):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read()
        except OSError:
            continue  # başka kullanıcının ya da bitmiş süreç
        if b"kopya_bekcisi" in cmd:
            continue  # bekçiler kopya yolunu argüman olarak taşır: kullanıcı sayılmaz
        for g, b in ikili.items():
            if g not in bulunan and b in cmd:
                bulunan.add(g)
        bakilacak = [f"/proc/{pid}/cwd"]
        try:
            bakilacak += [f"/proc/{pid}/fd/{x}" for x in os.listdir(f"/proc/{pid}/fd")]
        except OSError:
            pass
        for bag in bakilacak:
            try:
                hedef = os.readlink(bag)
            except OSError:
                continue
            for g in hedefler:
                if g not in bulunan and (hedef == g or hedef.startswith(g + os.sep)):
                    bulunan.add(g)
    return {hedefler[g] for g in bulunan}


def kok_gecerli(kok: str) -> bool:
    """Kopya kökü: adı 'oturum', sembolik bağ değil, dizin."""
    return os.path.basename(os.path.normpath(kok)) == "oturum" and os.path.isdir(kok) and not os.path.islink(kok)


def silinebilir_yol(yol: str, kok: str) -> bool:
    if not kok_gecerli(kok):
        return False
    if os.path.islink(yol) or not os.path.isdir(yol):
        return False
    if not KOPYA_DESENI.fullmatch(os.path.basename(yol)):
        return False
    if korunuyor(yol):
        return False  # bekleyen/başarısız Firefox yeniden başlatması: oturum yedeği burada
    return os.path.dirname(os.path.realpath(yol)) == os.path.realpath(kok)


def guvenli_sil(yol: str, kok: str) -> bool:
    if not silinebilir_yol(yol, kok):
        return False
    shutil.rmtree(yol, ignore_errors=True)
    return not os.path.exists(yol)


def cerez_uyarisi(yol: str) -> None:
    """Silmeden önce: kopyada önceden var olan uzun ömürlü çerezler değiştiyse (jeton döndürme) günlüğe uyarı — masaüstü
    kapanışındaki (oturum.kapanis) uyarının aynısı. Paket içe aktarılamazsa sessizce geçer."""
    try:
        kok = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if kok not in sys.path:
            sys.path.insert(0, kok)
        from deskhand.gunluk import gunluk
        from deskhand.oturum import PARMAK_DOSYA, cerez_parmak, degisim_bildir
        with open(os.path.join(yol, PARMAK_DOSYA)) as f:
            once = json.load(f)
        degisen = degisim_bildir(once, cerez_parmak(yol))
        if degisen:
            gunluk(f"oturum: {os.path.basename(yol)} kopyasında şu sitelerin oturum çerezleri yenilendi; asıl tarayıcıda "
                   f"yeniden giriş gerekebilir: {', '.join(degisen[:10])}")
    except Exception:  # noqa: BLE001 - bilgi amaçlı
        pass


def kalici_kaydet(yol: str) -> None:
    """Before deleting: save the sessions of the sites listed in `[oturum] kalici` (oturum/kalici.py). The package is
    imported only here (this script stays standard-library at import time); any failure is ignored."""
    try:
        kok = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if kok not in sys.path:
            sys.path.insert(0, kok)
        from deskhand.oturum import kalici
        kalici.kapanirken(yol)
    except Exception:  # noqa: BLE001 - the copy is deleted anyway
        pass


def bekle_ve_sil(kok: str, yol: str, pid: int, bas: str | None, aralik: float = BEKCI_ARALIK,
                 azami: float = BEKCI_AZAMI, son_pay: float = SON_PAY) -> bool:
    """Sahip süreç bitene dek bekle (pidfd; yoksa yoklama), son_pay sn daha bekle (masaüstü kapanırken oturum.kapanis
    çerez karşılaştırmasını kendisi yapsın), sonra kopyayı kullanan süreç kalmayınca (çerez uyarısı + ) sil. Kopya
    başkası tarafından silinirse (masaüstü kapanışı) çıkar. → silindi mi."""
    bitis = time.monotonic() + azami
    fd = None
    if canli(pid, bas):
        try:
            fd = os.pidfd_open(pid)
        except (OSError, AttributeError):
            fd = None
        if fd is not None and not canli(pid, bas):  # pidfd açılırken pid değişmiş olabilir
            os.close(fd)
            fd = None
    try:
        while time.monotonic() < bitis and os.path.isdir(yol) and canli(pid, bas):
            if fd is not None:
                select.select([fd], [], [], 5.0)
            else:
                time.sleep(aralik)
    finally:
        if fd is not None:
            os.close(fd)
    son = time.monotonic() + son_pay
    while os.path.isdir(yol) and time.monotonic() < son:
        time.sleep(0.1)
    while time.monotonic() < bitis and os.path.isdir(yol):
        if not kullanilanlar([yol]):
            if not silinebilir_yol(yol, kok):
                return False
            cerez_uyarisi(yol)
            kalici_kaydet(yol)
            return guvenli_sil(yol, kok)
        time.sleep(aralik)
    return False


def main(argv: list[str]) -> int:
    a = {}
    i = 0
    while i + 1 < len(argv):
        a[argv[i].lstrip("-")] = argv[i + 1]
        i += 2
    try:
        kok, yol, pid = a["kok"], a["kopya"], int(a["pid"])
    except (KeyError, ValueError):
        print("kullanım: kopya_bekcisi.py --kok KOK --kopya YOL --pid PID [--bas BAŞLANGIÇ]", file=sys.stderr)
        return 2
    if not silinebilir_yol(yol, kok):
        return 3
    try:
        son_pay = float(a.get("son-pay", SON_PAY))
    except ValueError:
        son_pay = SON_PAY
    bekle_ve_sil(kok, yol, pid, a.get("bas") or None, son_pay=son_pay)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
