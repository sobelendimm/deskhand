"""İnsan onayı protokolü (docs/ARCHITECTURE.md §8): hassas eylem YALNIZ panelde bir insan "Bir kez izin ver" derse yapılır.

İsteyen taraf (CLI / MCP / akış):  iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool
  1. Panel canlı değilse (RUNTIME_DIR/panel.pid + /proc doğrulaması) HEMEN red.
  2. RUNTIME_DIR/onay/istek-<uuid>.json yazılır (dizin 0700, dosya 0600; geçici adla yazılıp yerine konur).
  3. yanit-<uuid>.json beklenir. Süre dolarsa, panel kapanırsa ya da DUR açılırsa → red.
  4. Tek kullanımlık: istek, yanıt ve küçük görüntü kullanılınca silinir.
Panel tarafı (deskhand/gui):  bekleyenler(), yanitla(id, karar), temizle(), panel_kaydet()/panel_sil().
Yanıt dosyasını YALNIZ panel yazar; yanıtta panelin PID'i bulunur ve isteyen onu panel.pid ile karşılaştırır.

Tehdit modeli: bu, ajanın yanlışlıkla ya da istem enjeksiyonuyla hassas bir şeye "kendi kendine" izin vermesini
engeller (onay ajanın çağırabileceği hiçbir komutta yok). Aynı kullanıcı kimliğiyle keyfi kabuk çalıştırabilen
kötü niyetli bir sürece karşı bir sandbox DEĞİLDİR.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import NamedTuple

from . import yollar
from .i18n import N_, _

VARSAYILAN_SURE = 120.0
YOKLAMA = 0.1                # isteyen tarafın yanıt yoklama aralığı (sn)
CANLILIK_ARALIK = 1.0        # isteyen, beklerken paneli bu sıklıkta doğrular
ESKI_PAY = 5.0               # süresi geçen isteği panel bu kadar sonra siler (isteyen kendi siler; çökmeye karşı)
AYRINTI_SINIR = 4000

# Onay diyaloğu ve panel pencerelerinin SABİT kimliği: yasak pencere listesine (guvenlik) eklenmeli; hiçbir ajan
# girdisi bunlara gitmez (ajan kendi onay düğmesine basamaz).
PANEL_SINIF = "deskhand"                 # Qt desktopFileName / WM_CLASS (Wayland app_id)
ONAY_BASLIK = "Deskhand — Onay"
PANEL_BASLIK = "Deskhand"
YASAK_DESENLER = (r"^deskhand$", r"^Deskhand — Onay")

# Pencere başlıkları ÇEVRİLMEZ: YASAK_DESENLER (ve guvenlik.YERLESIK_YASAK) bu sabit adlara bakar.
MESAJ_PANEL_YOK = N_("Deskhand paneli kapalı, onay alınamadı")
MESAJLAR = {  # gösterirken _(): OnaySonucu.mesaj
    "izin": N_("kullanıcı bir kez izin verdi"),
    "red": N_("kullanıcı reddetti"),
    "sure": N_("onay süresi doldu (yanıt yok → red)"),
    "panel-yok": MESAJ_PANEL_YOK,
    "panel-kapandi": N_("Deskhand paneli beklerken kapandı → red"),
    "dur": N_("kullanıcı DUR dedi → red"),
    "hata": N_("onay isteği yazılamadı → red"),
}
KARARLAR = ("izin", "red")
_ID = re.compile(r"[0-9a-f]{32}")


class OnaySonucu(NamedTuple):
    izin: bool
    neden: str          # MESAJLAR anahtarı
    istek_id: str = ""

    @property
    def mesaj(self) -> str:
        return _(MESAJLAR[self.neden]) if self.neden in MESAJLAR else self.neden


# ---------------------------------------------------------------- yollar

def dizin() -> str:
    return os.path.join(yollar.runtime_dir(), "onay")


def panel_pid_yolu() -> str:
    return os.path.join(yollar.runtime_dir(), "panel.pid")


def istek_yolu(istek_id: str) -> str:
    return os.path.join(dizin(), f"istek-{istek_id}.json")


def yanit_yolu(istek_id: str) -> str:
    return os.path.join(dizin(), f"yanit-{istek_id}.json")


def goruntu_yolu(istek_id: str) -> str:
    return os.path.join(dizin(), f"istek-{istek_id}.png")


def _dizin_hazirla() -> str:
    os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
    d = dizin()
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _gecerli_id(istek_id) -> bool:
    return isinstance(istek_id, str) and bool(_ID.fullmatch(istek_id))


def _yaz_atomik(yol: str, veri: dict, ozel: bool = False) -> None:
    """Geçici gizli dosyaya yaz → yerine koy (okuyan yarım JSON görmez). ozel: hedef zaten varsa yazma
    (os.link, tek kullanımlık yanıt: ikinci yanıt yazılamaz) → FileExistsError."""
    gecici = os.path.join(os.path.dirname(yol), f".{os.path.basename(yol)}.{os.getpid()}.{uuid.uuid4().hex[:6]}")
    fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(veri, f, ensure_ascii=False)
        if ozel:
            os.link(gecici, yol)
        else:
            os.replace(gecici, yol)
    finally:
        try:
            os.remove(gecici)
        except FileNotFoundError:
            pass


def _sil(*yollar_):
    for y in yollar_:
        try:
            os.remove(y)
        except OSError:
            pass


def _json_oku(yol: str):
    try:
        with open(yol) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- panel canlılığı

def _baslangic(pid: int) -> str | None:
    """/proc/PID/stat'ın 22. alanı (süreç başlangıç zamanı): PID yeniden kullanımına karşı."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            s = f.read()
    except (OSError, ValueError):
        return None
    try:
        return s[s.rindex(")") + 2:].split()[19]
    except (ValueError, IndexError):
        return None


def panel_kaydet(pid: int | None = None) -> str:
    """Panel açılışında: RUNTIME_DIR/panel.pid {pid, baslangic}. → yol."""
    pid = os.getpid() if pid is None else pid
    os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
    _yaz_atomik(panel_pid_yolu(), {"pid": pid, "baslangic": _baslangic(pid), "zaman": time.time()})
    _dizin_hazirla()
    return panel_pid_yolu()


def panel_sil(pid: int | None = None) -> None:
    """Panel kapanırken: pid dosyası yalnız kendisininse silinir."""
    d = _json_oku(panel_pid_yolu()) or {}
    if d.get("pid") == (os.getpid() if pid is None else pid):
        _sil(panel_pid_yolu())


def panel_pid() -> int | None:
    """Canlı panelin PID'i; yoksa / ölmüşse / PID başka sürece geçmişse None."""
    d = _json_oku(panel_pid_yolu())
    if not isinstance(d, dict):
        return None
    pid = d.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    bas = _baslangic(pid)
    if bas is None or (d.get("baslangic") is not None and bas != d.get("baslangic")):
        return None
    return pid


def panel_canli() -> bool:
    return panel_pid() is not None


# ---------------------------------------------------------------- isteyen taraf

def _dur_acik() -> bool:
    from .hata import dur_dosyasi
    return os.path.exists(dur_dosyasi())


def _kaydet_gunluk(sonuc: OnaySonucu, eylem: str, hedef: str, masaustu: str) -> None:
    from .gunluk import gunluk
    yer = "arka sanal " if masaustu == "arka" else ""
    gunluk(f"onay {sonuc.neden} | {yer}[{hedef}] | {eylem}")


def iste_sonuc(eylem: str, hedef: str, ayrinti: str = "", masaustu: str = "ekran", sure: float = VARSAYILAN_SURE,
               goruntu=None, gunluge_yaz: bool = True) -> OnaySonucu:
    """Paneldeki insandan bir kez izin iste ve bekle (en çok `sure` sn). → OnaySonucu.
    masaustu: "ekran" (kullanıcının ekranı) | "arka" (görünmez masaüstü).
    goruntu: hedefin küçük görüntüsü: PIL.Image (onay dizinine kaydedilir, sonra silinir) ya da var olan dosya yolu."""
    masaustu = "arka" if masaustu in ("arka", "sanal", "background") else "ekran"

    def bitir(s: OnaySonucu) -> OnaySonucu:
        if gunluge_yaz:
            _kaydet_gunluk(s, eylem, hedef, masaustu)
        return s

    if _dur_acik():
        return bitir(OnaySonucu(False, "dur"))
    ppid = panel_pid()
    if ppid is None:
        return bitir(OnaySonucu(False, "panel-yok"))
    istek_id = uuid.uuid4().hex
    iy, yy, gy = istek_yolu(istek_id), yanit_yolu(istek_id), goruntu_yolu(istek_id)
    simdi = time.time()
    sure = max(1.0, float(sure))
    try:
        _dizin_hazirla()
        g_yol = None
        if goruntu is not None and hasattr(goruntu, "save"):
            goruntu.save(gy, "PNG")
            os.chmod(gy, 0o600)
            g_yol = gy
        elif isinstance(goruntu, str) and os.path.isfile(goruntu):
            g_yol = os.path.abspath(goruntu)
        istek = {"id": istek_id, "eylem": str(eylem), "hedef": str(hedef),
                 "ayrinti": str(ayrinti or "")[:AYRINTI_SINIR], "masaustu": masaustu, "zaman": simdi,
                 "son_zaman": simdi + sure, "pid": os.getpid(), "goruntu": g_yol}
        _yaz_atomik(iy, istek)
    except OSError:
        _sil(iy, gy)
        return bitir(OnaySonucu(False, "hata", istek_id))
    try:
        son = time.monotonic() + sure
        sonraki_canlilik = time.monotonic() + CANLILIK_ARALIK
        while True:
            y = _json_oku(yy) if os.path.exists(yy) else None
            if isinstance(y, dict):
                if (y.get("id") == istek_id and y.get("kaynak") == "arayuz" and y.get("karar") in KARARLAR
                        and y.get("panel_pid") == ppid):
                    return bitir(OnaySonucu(y["karar"] == "izin", y["karar"], istek_id))
                return bitir(OnaySonucu(False, "red", istek_id))  # biçimsiz/yabancı yanıt = red
            t = time.monotonic()
            if t >= son:
                return bitir(OnaySonucu(False, "sure", istek_id))
            if _dur_acik():
                return bitir(OnaySonucu(False, "dur", istek_id))
            if t >= sonraki_canlilik:
                sonraki_canlilik = t + CANLILIK_ARALIK
                if panel_pid() != ppid:
                    return bitir(OnaySonucu(False, "panel-kapandi", istek_id))
            time.sleep(YOKLAMA)
    finally:
        _sil(iy, yy, gy)


def iste(eylem: str, hedef: str, ayrinti: str = "", masaustu: str = "ekran", sure: float = VARSAYILAN_SURE,
         goruntu=None) -> bool:
    """CONTRACT §8: True yalnız paneldeki insan "Bir kez izin ver" dediyse."""
    return iste_sonuc(eylem, hedef, ayrinti, masaustu, sure, goruntu).izin


# ---------------------------------------------------------------- panel tarafı

def istek_oku(yol: str) -> dict | None:
    """Doğrulanmış istek sözlüğü ya da None (biçimsiz/eksik alan)."""
    d = _json_oku(yol)
    if not isinstance(d, dict) or not _gecerli_id(d.get("id")):
        return None
    if os.path.basename(yol) != f"istek-{d['id']}.json":
        return None
    try:
        d["zaman"] = float(d.get("zaman") or 0)
        d["son_zaman"] = float(d["son_zaman"])
        d["pid"] = int(d.get("pid") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    for alan in ("eylem", "hedef", "ayrinti"):
        d[alan] = str(d.get(alan) or "")
    d["ayrinti"] = d["ayrinti"][:AYRINTI_SINIR]
    d["masaustu"] = "arka" if d.get("masaustu") == "arka" else "ekran"
    g = d.get("goruntu")
    d["goruntu"] = g if isinstance(g, str) and os.path.isfile(g) else None
    return d


def _canli(pid: int) -> bool:
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def bekleyenler(simdi: float | None = None) -> list[dict]:
    """Yanıtlanmamış, süresi dolmamış, isteyeni yaşayan istekler (eskiden yeniye)."""
    simdi = time.time() if simdi is None else simdi
    try:
        adlar = os.listdir(dizin())
    except OSError:
        return []
    sonuc = []
    for ad in adlar:
        if not (ad.startswith("istek-") and ad.endswith(".json")):
            continue
        d = istek_oku(os.path.join(dizin(), ad))
        if d is None or d["son_zaman"] <= simdi or os.path.exists(yanit_yolu(d["id"])):
            continue
        if d["pid"] and not _canli(d["pid"]):
            continue
        sonuc.append(d)
    return sorted(sonuc, key=lambda d: d["zaman"])


def yanitla(istek_id: str, karar: str, simdi: float | None = None) -> bool:
    """Panel: isteği yanıtla (tek kullanımlık). → yazıldı mı. İstek yoksa/süresi geçtiyse/zaten yanıtlandıysa False."""
    if not _gecerli_id(istek_id) or karar not in KARARLAR:
        return False
    simdi = time.time() if simdi is None else simdi
    d = istek_oku(istek_yolu(istek_id))
    if d is None or (karar == "izin" and d["son_zaman"] <= simdi):
        return False  # süresi geçmiş isteğe İZİN yazılmaz (red her zaman yazılabilir)
    try:
        _yaz_atomik(yanit_yolu(istek_id), {"id": istek_id, "karar": karar, "kaynak": "arayuz", "zaman": simdi,
                                           "panel_pid": os.getpid()}, ozel=True)
    except FileExistsError:
        return False
    except OSError:
        return False
    return True


def temizle(simdi: float | None = None) -> list[str]:
    """Panel: süresi çoktan geçmiş / isteyeni ölmüş istekleri ve sahipsiz yanıt/görüntüleri sil. → silinen adlar."""
    simdi = time.time() if simdi is None else simdi
    silinen = []
    try:
        adlar = os.listdir(dizin())
    except OSError:
        return silinen
    for ad in adlar:
        yol = os.path.join(dizin(), ad)
        m = re.fullmatch(r"(istek|yanit)-([0-9a-f]{32})\.(json|png)", ad)
        if not m:
            continue
        tur, istek_id = m.group(1), m.group(2)
        if tur == "istek" and m.group(3) == "json":
            d = istek_oku(yol)
            eski = d is None or d["son_zaman"] + ESKI_PAY < simdi or (d["pid"] and not _canli(d["pid"]))
        else:  # yanıt ya da görüntü: isteği yoksa ve bir dakikadır duruyorsa
            try:
                yas = simdi - os.lstat(yol).st_mtime
            except OSError:
                continue
            eski = not os.path.exists(istek_yolu(istek_id)) and yas > 60
        if eski:
            _sil(yol)
            silinen.append(ad)
    return silinen
