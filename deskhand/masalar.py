"""Çoklu görünmez masaüstü: ad, bağlam, yollar, sahiplik (Aşama 0 + 1 çekirdeği).

İLKE: bir süreç (MCP oturumu ya da CLI çağrısı) TEK görünmez masaüstüne bağlıdır. Bağlam `secili()`:
iş parçacığı yereli (`masa_sabit(ad)`) > ortam `DESKHAND_MASAUSTU` > "" (varsayılan).

Ad biçimi `[a-z0-9][a-z0-9-]{0,15}`; "" = varsayılan masaüstü ve yolları ESKİSİYLE AYNI (geriye uyum, geçiş yok):
  RUNTIME_DIR/sanal.json, sanal.lock, devral, sanal-girdi.lock, oturum/, sanal-sahip
Adlı masaüstü: RUNTIME_DIR/masa/<ad>/{sanal.json, sanal.lock, devral, girdi.lock, sahip, oturum/}.
`gorev` adı görev kipine ayrılmıştır (Aşama 2).

Sahiplik (`sahip` dosyası): "mcp <pid> <başlangıç> <ebeveyn_pid> <ebeveyn_başlangıç> <oto> <pid ad alanı>". Kapı
(erisim_kapisi): varsayılan masaüstü göreve ayrılmışsa görev işareti önce (görev kipi geçer, diğerleri Dur 14);
sahibi ölü/bozuk → serbest; sahip başka PID ad alanında → Dur 14; çağıran sahip → izin; çağıranın ata zincirinde
sahibin ebeveyni var (aynı Claude oturumunun Bash'i) → izin; ata zincirinde hiç `claude` yok (insan) → izin; panel
(gorev_kipi.GOZLEMCI) → izin; diğer → Dur(14) (okuma dahil). Bu bir KOORDİNASYON kuralıdır, aynı kullanıcının kabuk
koduna karşı güvenlik sınırı değildir.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import threading

from . import yollar
from .hata import Dur
from .i18n import _

AD_DESENI = re.compile(r"[a-z0-9][a-z0-9-]{0,15}")
AYRILMIS = frozenset({"gorev"})
ORTAM = "DESKHAND_MASAUSTU"
OTO_ONEK = "oturum-"
VARSAYILAN_AZAMI = 3
AZAMI_SINIR = (1, 6)

_YEREL = threading.local()


# ---------------------------------------------------------------- ad + bağlam

def dogrula(ad: str | None, ayrilmis_serbest: bool = False) -> str:
    """Adı doğrula → ad ("" = varsayılan). Geçersizse Dur(1)."""
    ad = "" if ad is None else str(ad).strip()
    if ad == "":
        return ""
    if not AD_DESENI.fullmatch(ad):
        raise Dur(1, _("geçersiz masaüstü adı: {ad} (küçük harf/rakam/tire, en çok 16)").format(ad=repr(ad)))
    if ad in AYRILMIS and not ayrilmis_serbest:
        raise Dur(1, _("masaüstü adı ayrılmış: {ad}").format(ad=ad))
    return ad


def secili() -> str:
    """Bu iş parçacığının/sürecin masaüstü adı: masa_sabit > DESKHAND_MASAUSTU > ""."""
    ad = getattr(_YEREL, "ad", None)
    if ad is not None:
        return ad
    ortam = os.environ.get(ORTAM, "")
    if not ortam:
        return ""
    try:
        return dogrula(ortam, ayrilmis_serbest=True)
    except Dur:
        return ""  # bozuk ortam değeri: varsayılan (doğrulanmamış ad hiçbir yola girmez)


@contextlib.contextmanager
def masa_sabit(ad: str | None):
    """Bu iş parçacığını geçici olarak `ad` masaüstüne bağla (None: değişiklik yok)."""
    if ad is None:
        yield
        return
    ad = dogrula(ad, ayrilmis_serbest=True)
    onceki = getattr(_YEREL, "ad", None)
    _YEREL.ad = ad
    try:
        yield
    finally:
        _YEREL.ad = onceki


def _ad(ad: str | None) -> str:
    return secili() if ad is None else dogrula(ad, ayrilmis_serbest=True)


# ---------------------------------------------------------------- yollar

def masa_koku() -> str:
    return os.path.join(yollar.runtime_dir(), "masa")


def kok(ad: str | None = None) -> str:
    """Masaüstünün dosya kökü: "" → RUNTIME_DIR; adlı → RUNTIME_DIR/masa/<ad>."""
    ad = _ad(ad)
    return yollar.runtime_dir() if ad == "" else os.path.join(masa_koku(), ad)


def kok_hazirla(ad: str | None = None) -> str:
    k = kok(ad)
    os.makedirs(k, mode=0o700, exist_ok=True)
    return k


def durum_yolu(ad: str | None = None) -> str:
    return os.path.join(kok(ad), "sanal.json")


def kilit_yolu(ad: str | None = None) -> str:
    return os.path.join(kok(ad), "sanal.lock")


def devral_yolu(ad: str | None = None) -> str:
    return os.path.join(kok(ad), "devral")


def girdi_kilidi_yolu(ad: str | None = None) -> str:
    ad = _ad(ad)
    return os.path.join(kok(ad), "sanal-girdi.lock" if ad == "" else "girdi.lock")


def sahip_yolu(ad: str | None = None) -> str:
    ad = _ad(ad)
    return os.path.join(kok(ad), "sanal-sahip" if ad == "" else "sahip")


def oturum_koku(ad: str | None = None) -> str:
    return os.path.join(kok(ad), "oturum")


def adlar() -> list[str]:
    """Kaydı (sanal.json) ya da sahibi olan masaüstü adları: "" önce."""
    s = []
    if os.path.exists(durum_yolu("")) or os.path.exists(sahip_yolu("")):
        s.append("")
    try:
        icerik = sorted(os.listdir(masa_koku()))
    except OSError:
        icerik = []
    for ad in icerik:
        if not AD_DESENI.fullmatch(ad):
            continue
        yol = os.path.join(masa_koku(), ad)
        if os.path.islink(yol) or not os.path.isdir(yol):
            continue
        if os.path.exists(durum_yolu(ad)) or os.path.exists(sahip_yolu(ad)):
            s.append(ad)
    return s


def kok_sil(ad: str) -> None:
    """Adlı masaüstünün dizinini sil (kayıt yok, sahip yok iken). Varsayılan için hiçbir şey yapmaz."""
    ad = dogrula(ad, ayrilmis_serbest=True)
    if ad == "":
        return
    yol = os.path.join(masa_koku(), ad)
    if os.path.isdir(yol) and not os.path.islink(yol):
        shutil.rmtree(yol, ignore_errors=True)


# ---------------------------------------------------------------- sahiplik

def _baslangic(pid) -> str | None:
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            s = f.read()
        return s[s.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def _ebeveyn(pid) -> int | None:
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError, TypeError):
        return None


def _atalar(pid: int | None = None) -> list[tuple[int, str | None]]:
    """(pid, başlangıç) zinciri: pid (varsayılan bu süreç) dahil, 1'e dek."""
    pid = os.getpid() if pid is None else int(pid)
    s = []
    for _i in range(64):
        if pid is None or pid <= 1:
            break
        s.append((pid, _baslangic(pid)))
        pid = _ebeveyn(pid)
    return s


# Yapay zekâ ajanı süreçlerinin adları (comm ya da argv[0..1] dosya adı). Ata zincirinde bunlardan biri OLMAYAN çağrı
# insanındır (kullanıcının kendi terminali / KDE kısayolu) ve panel gibi izinlidir.
AJAN_ADLARI = frozenset({"claude"})


def _ajan_mi(pid: int) -> bool:
    try:
        with open(f"/proc/{int(pid)}/comm") as f:
            if f.read().strip() in AJAN_ADLARI:
                return True
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            argv = f.read(4096).split(b"\0")[:2]
    except (OSError, ValueError):
        return False
    for a in argv:
        ad = os.path.basename(a.decode(errors="replace"))
        if ad in AJAN_ADLARI or "claude-code" in a.decode(errors="replace"):
            return True
    return False


def ajan_atasi_var(pid: int | None = None) -> bool:
    """Çağıranın ata zincirinde bir yapay zekâ ajanı (claude) süreci var mı."""
    return any(_ajan_mi(p) for p, _b in _atalar(pid))


def pid_ad_alani() -> str:
    """Bu sürecin PID ad alanı kimliği (/proc/self/ns/pid düğümü): sahip PID'leri yalnız aynı ad alanında anlamlıdır."""
    try:
        return str(os.stat("/proc/self/ns/pid").st_ino)
    except OSError:
        return "-"


def sahip_icerik(pid: int | None = None, oto: bool = False, ebeveyn: int | None = None) -> str:
    """"mcp <pid> <başlangıç> <ebeveyn_pid> <ebeveyn_başlangıç> <oto> <pid ad alanı>". ebeveyn: MCP sunucusunun İLK
    ebeveyni (main'de saklanır; sonradan systemd'ye geçmiş olsa da Claude oturumu o)."""
    pid = os.getpid() if pid is None else int(pid)
    eb = (_ebeveyn(pid) or 0) if ebeveyn is None else int(ebeveyn)
    return f"mcp {pid} {_baslangic(pid) or '-'} {eb} {_baslangic(eb) or '-'} {1 if oto else 0} {pid_ad_alani()}\n"


def _sahip_alanlari(ad: str | None) -> list[str] | None:
    try:
        with open(sahip_yolu(ad)) as f:
            p = f.read(300).split()
    except OSError:
        return None
    if len(p) not in (6, 7) or p[0] != "mcp":
        return None
    return p


def sahip_oku(ad: str | None = None) -> dict | None:
    """CANLI sahip kaydı → {pid, bas, ebeveyn, ebeveyn_bas, oto, yabanci_ns}; dosya yok / bozuk / sahip ölmüş / PID
    başka sürece geçmiş → None. Sahip BAŞKA bir PID ad alanındaysa (yabanci_ns) PID'i burada denetlenemez: serbest
    SAYILMAZ (canlı yabancı sahip gibi)."""
    p = _sahip_alanlari(ad)
    if p is None:
        return None
    try:
        pid, eb = int(p[1]), int(p[3])
    except ValueError:
        return None
    if pid <= 1 or p[2] == "-":
        return None
    yabanci = len(p) == 7 and p[6] != "-" and p[6] != pid_ad_alani()
    if not yabanci and _baslangic(pid) != p[2]:
        return None
    return {"pid": pid, "bas": p[2], "ebeveyn": eb, "ebeveyn_bas": p[4], "oto": p[5] == "1", "yabanci_ns": yabanci}


def sahiplen(ad: str | None = None, oto: bool = False, pid: int | None = None, ebeveyn: int | None = None) -> bool:
    """Masaüstünü bu sürece (pid) yaz. Canlı başka sahip varsa False (değiştirmez)."""
    ad = _ad(ad)
    pid = os.getpid() if pid is None else int(pid)
    s = sahip_oku(ad)
    if s is not None and (s["pid"] != pid or s["yabanci_ns"]):
        return False
    kok_hazirla(ad)
    yol = sahip_yolu(ad)
    gecici = f"{yol}.{os.getpid()}"
    fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(sahip_icerik(pid, oto, ebeveyn))
    os.replace(gecici, yol)
    return True


def birak(ad: str | None = None, pid: int | None = None) -> bool:
    """Sahipliği bırak (yalnız sahip bu süreçse ya da sahip ölmüşse). → silindi mi."""
    pid = os.getpid() if pid is None else int(pid)
    yol = sahip_yolu(ad)
    if not os.path.exists(yol):
        return False
    s = sahip_oku(ad)
    if s is not None and (s["pid"] != pid or s["yabanci_ns"]):
        return False
    try:
        os.remove(yol)
        return True
    except FileNotFoundError:
        return False


def oto_mu(ad: str | None = None) -> bool:
    """Sahip dosyasında oto bayrağı (sahip ölü olsa da okunur)."""
    p = _sahip_alanlari(ad)
    return p is not None and p[5] == "1"


def izinli_mi(ad: str | None = None, pid: int | None = None) -> bool:
    """Kapı kuralı (Dur vermeden): sahipsiz → True; sahip pid ya da sahibin ebeveyni pid'in ata zincirinde → True;
    ata zincirinde HİÇ yapay zekâ ajanı (claude) yoksa (insan: kendi terminali, KDE kısayolu) → True. Sahip başka PID
    ad alanında → False. KOORDİNASYON kuralıdır (ajan oturumları birbirinin işini bozmasın), aynı kullanıcının kabuk
    koduna karşı güvenlik sınırı DEĞİLDİR."""
    s = sahip_oku(ad)
    if s is None:
        return True
    if s["yabanci_ns"]:
        return False
    zincir = _atalar(pid)
    if any(p == s["pid"] for p, _b in zincir):
        return True
    if s["ebeveyn"] > 1 and s["ebeveyn_bas"] != "-" and any(
            p == s["ebeveyn"] and b == s["ebeveyn_bas"] for p, b in zincir):
        return True
    return not any(_ajan_mi(p) for p, _b in zincir)


def erisim_kapisi(ad: str | None = None) -> None:
    """Başka oturumun masaüstüne erişimi (okuma dahil) durdurur: Dur(14). Panel (GOZLEMCI) serbest. Varsayılan
    masaüstü bir göreve ayrılmışsa (gorev_kipi işareti canlı) yetki SAHİPLİKTEN ÖNCE görev işaretindedir: görev
    kipindeki süreç geçer (görevin masaüstü), diğerleri görev masaüstü kuralıyla Dur(14)."""
    from . import gorev_kipi
    if gorev_kipi.GOZLEMCI:
        return
    ad = _ad(ad)
    if ad == "" and gorev_kipi.masaustu_ayrildi():
        if gorev_kipi.etkin():
            return
        raise Dur(14, _("görünmez masaüstü şu an panelin görev ajanına ayrılmış; görev bitince yeniden deneyin "
                        "(ya da panelden görevi durdurun)"))
    if not izinli_mi(ad):
        raise Dur(14, _("görünmez masaüstü {ad} başka bir oturumun masaüstü; ona erişilmez "
                        "(kendi masaüstünüzü kullanın: --desktop-name)").format(ad=repr(ad or "varsayılan")))


# ---------------------------------------------------------------- sınır

def azami() -> int:
    """[masaustu] azami (1..6, varsayılan 3)."""
    try:
        from . import ayarlar
        v = int(ayarlar.al("masaustu", "azami"))
    except Exception:  # noqa: BLE001 - ayar okunamadı: varsayılan
        v = VARSAYILAN_AZAMI
    return max(AZAMI_SINIR[0], min(AZAMI_SINIR[1], v))


def oto_ad(dolu) -> str:
    """En küçük boş `oturum-N` (N>=1)."""
    dolu = set(dolu)
    n = 1
    while f"{OTO_ONEK}{n}" in dolu:
        n += 1
    return f"{OTO_ONEK}{n}"
