"""İnsan onayı protokolü (docs/ARCHITECTURE.md §8): hassas eylem YALNIZ panelde bir insan "Bir kez izin ver" derse yapılır.

İsteyen taraf (CLI / MCP / akış):  iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool
  0. Gözetimsiz kip (DESKHAND_GOZETIMSIZ=1 / --unattended): hiçbir diyalog açılmaz, beklenmez → HEMEN red.
  1. Panel canlı değilse (RUNTIME_DIR/panel.pid {pid, baslangic, exe} + /proc doğrulaması) HEMEN red.
  2. Panelin onay kanalına bağlanılır: RUNTIME_DIR/onay/kanal.sock (Unix soketi, 0600, dizin 0700). Karşı taraf
     SO_PEERCRED ile doğrulanır: aynı kullanıcı + PID = panel.pid'deki PID + aynı süreç başlangıç zamanı + aynı
     /proc/<pid>/exe + birebir aynı /proc/<pid>/cmdline (exe yorumlayıcı olduğundan panelin modül yolu/giriş
     noktası). Doğrulanamazsa → red ("kanal").
  3. RUNTIME_DIR/onay/istek-<uuid>.json yazılır (diyalog ve bekleyen listesi için; dosya 0600), kanala
     `bekle <uuid>` gönderilir ve karar AYNI bağlantıdan beklenir (`karar izin|red <uuid>`). Süre dolarsa, panel
     kapanırsa (bağlantı kopar) ya da DUR açılırsa → red.
  4. İZİN YALNIZ kanaldan gelir. yanit-<uuid>.json dosyası (eski protokol) yalnız RED sayılır: aynı kullanıcıdaki
     herhangi bir sürecin (ör. yalnız dosya yazabilen bir ajanın) sahte "izin" yazması işe yaramaz.
  5. Tek kullanımlık: istek, yanıt ve küçük görüntü kullanılınca silinir.
Panel tarafı (deskhand/gui):  panel_kaydet() (kanalı da açar) / panel_sil(), bekleyenler(), yanitla(id, karar),
temizle(). Panel kanalda isteyeni de doğrular: bağlanan sürecin PID'i isteğin pid alanıyla aynı olmalı.

Tehdit modeli: bu, ajanın yanlışlıkla ya da istem enjeksiyonuyla hassas bir şeye "kendi kendine" izin vermesini
engeller (onay ajanın çağırabileceği hiçbir komutta yok; yalnız dosya yazabilen bir süreç de izin üretemez). Aynı
kullanıcı kimliğiyle keyfi kabuk çalıştırabilen kötü niyetli bir sürece karşı bir sandbox DEĞİLDİR (paneli
öldürüp yerine geçebilir, ptrace ile bağlanabilir).
"""
from __future__ import annotations

import json
import os
import re
import select
import socket
import stat
import struct
import threading
import time
import uuid
from typing import NamedTuple

from . import yollar
from .hata import gozetimsiz
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
    "gozetimsiz": N_("gözetimsiz çalışmada hassas eylem yapılmaz"),
    "kanal": N_("onay kanalı doğrulanamadı (yanıtın Deskhand panelinden geldiği kanıtlanamadı) → red"),
    "kosul": N_("beklenen koşul gerçekleşti (insan doğrulaması sayfadan kalktı)"),
    "iptal": N_("isteyen vazgeçti (çağrı iptal edildi) → red"),
    "silindi": N_("onay isteği beklerken silindi → red"),
}
TUR_DEVIR = "devir"           # istek türü: insan doğrulaması devri (panelde "Devral / Bitti / Vazgeç"; izin = Bitti)
DEVIR_EN_COK = 3600.0         # insan devri isteğinin en uzun ömrü (request_human timeout_s üst sınırı): bekleme boyunca BAŞKA
                              # süreçlerin girdisi de kapalı kalır (bekleyen_var bu sınıra kadar "sahte" saymaz)
KONTROL_ARALIK = 3.0          # isteyen `kontrol` işlevini en çok bu sıklıkta çağırır (sn)
NABIZ_SINIR = 30.0            # 0.9.1: isteyen beklerken istek dosyasına CANLILIK_ARALIK'ta bir dokunur (nabız); bu kadar sn
                              # dokunulmadıysa bekleme döngüsü yok (süreç donmuş/durdurulmuş, iş parçacığı terk edilmiş):
                              # istek bekleyen SAYILMAZ (panel göstermez, başka süreçlerin girdisi kilitlenmez; temizle siler)
                              # The heartbeat comes from a dedicated thread, and a stale mtime is ignored while the owner
                              # is verifiably running (pid + start time, not stopped): see _calisiyor.
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


def kanal_yolu() -> str:
    """Panelin onay kanalı (Unix soketi; yalnız panel dinler)."""
    return os.path.join(dizin(), "kanal.sock")


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


def _exe(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError):
        return None


def _komut_satiri(pid: int) -> list[str] | None:
    """/proc/<pid>/cmdline → argv (exe = python yorumlayıcısı olduğundan panelin modül yolu/giriş noktası buradan
    ayırt edilir: `python3 -m deskhand panel`, `…/bin/deskhand panel`, `python3 -m deskhand.gui`…)."""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            ham = f.read()
    except (OSError, ValueError):
        return None
    return [p.decode("utf-8", "surrogateescape") for p in ham.split(b"\0") if p] or None


def _cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{int(pid)}/cwd")
    except (OSError, ValueError):
        return None


def paket_yolu() -> str:
    """Bu süreçte yüklü deskhand paketinin dizini (gerçek yol): panel kaydına yazılır, isteyen kendisininkiyle
    karşılaştırır (panel BAŞKA bir kopyadan — ör. ajanın değiştirdiği bir dizinden — çalışıyorsa red)."""
    from . import __file__ as paket_dosyasi
    return os.path.dirname(os.path.realpath(paket_dosyasi))


def panel_kaydet(pid: int | None = None) -> str:
    """Panel açılışında: onay kanalını aç (yalnız kendi PID'i için) + RUNTIME_DIR/panel.pid
    {pid, baslangic, exe, cmdline}. → yol."""
    global _PANEL_ACIK
    pid = os.getpid() if pid is None else pid
    os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
    _dizin_hazirla()
    with _KAYIT_KILIT:  # record + socket lifetime under one lock (refresh thread cannot interleave with shutdown)
        if pid == os.getpid():
            _PANEL_ACIK = True
            kanal_ac()
            _tazeleyici_baslat()  # 0.9.1: kayıt eskirse (ör. Python güncellendi → exe "(deleted)") panel kendisi tazeler
        _yaz_atomik(panel_pid_yolu(), {"pid": pid, "baslangic": _baslangic(pid), "exe": _exe(pid),
                                       "cmdline": _komut_satiri(pid), "cwd": _cwd(pid),
                                       "paket": paket_yolu() if pid == os.getpid() else None, "zaman": time.time()})
    return panel_pid_yolu()


def panel_sil(pid: int | None = None) -> None:
    """Panel kapanırken: pid dosyası yalnız kendisininse silinir; kendi kanalı kapanır (bekleyenlerin bağlantısı
    kopar → isteyenler hemen red)."""
    global _PANEL_ACIK
    pid = os.getpid() if pid is None else pid
    if pid == os.getpid():
        _tazeleyici_durdur()  # waits for the refresh thread: no refresh can run after this point
    with _KAYIT_KILIT:
        if pid == os.getpid():
            _PANEL_ACIK = False
        d = _json_oku(panel_pid_yolu()) or {}
        if d.get("pid") == pid:
            _sil(panel_pid_yolu())
            if pid == os.getpid():
                kanal_kapat()


TAZELE_ARALIK = 60.0          # panel kendi kimlik kaydını bu sıklıkta denetler (gerekirse yeniden yazar)
_TAZELEYICI: tuple[threading.Event, threading.Thread] | None = None
_KAYIT_KILIT = threading.RLock()  # panel.pid + approval socket are created/removed only while holding this lock
_PANEL_ACIK = False               # this process registered as panel (panel_kaydet) and has not shut down (panel_sil)


def _canli_kimlik(pid: int) -> dict:
    """Bir sürecin ŞU ANKİ kimlik alanları (panel kaydında doğrulanan alanlar)."""
    return {"baslangic": _baslangic(pid), "exe": _exe(pid), "cmdline": _komut_satiri(pid), "cwd": _cwd(pid)}


def kayit_farki(kayit: dict | None) -> list[str]:
    """Panel kaydındaki kimlik alanlarından canlı süreçle UYMAYANLAR (isteyenin _kanala_baglan'da birebir karşılaştırdığı
    alanlar). Boş liste = kayıt güncel. Örnek: Python paketi güncellenince çalışan panelin /proc/<pid>/exe'si
    "/usr/bin/python3.X (deleted)" olur → ["exe"] (0.9.1 hatası: hesap oturumu izni sessizce kapalı kalıyordu)."""
    if not isinstance(kayit, dict) or not isinstance(kayit.get("pid"), int):
        return ["pid"]
    canli = _canli_kimlik(kayit["pid"])
    return [k for k, v in canli.items() if v is None or kayit.get(k) != v]


def panel_kaydi_tazele() -> str:
    """Panel sürecinde: kendi kimlik kaydını denetle, eskimişse yeniden yaz. → "ayni" | "tazelendi" | "baskasi" |
    "kapali" (panel_sil already ran: nothing is re-created).
    GÜVENLİK: doğrulama zayıflamaz — kayıt yalnız BU sürecin (panel) kendi canlı /proc değerleriyle yazılır ve isteyen
    yine birebir karşılaştırır (SO_PEERCRED PID + başlangıç + exe + cmdline + cwd + paket). Başka bir CANLI sürecin
    kaydına dokunulmaz ("baskasi"); kayıt yoksa ya da sahibi ölmüşse bu panel yeniden kaydolur (kanal da açılır)."""
    with _KAYIT_KILIT:
        if not _PANEL_ACIK:  # panel shut down (or never registered): never re-create the record/socket
            return "kapali"
        return _panel_kaydi_tazele()


def _panel_kaydi_tazele() -> str:
    benim = os.getpid()
    d = _json_oku(panel_pid_yolu())
    sahip = d.get("pid") if isinstance(d, dict) else None
    if isinstance(sahip, int) and sahip > 0 and sahip != benim:
        bas = _baslangic(sahip)
        if bas is not None and bas == d.get("baslangic"):
            return "baskasi"  # başka canlı panel: onun kaydı
    fark = ["kayit"] if sahip != benim else kayit_farki(d)
    if sahip == benim and d.get("paket") != paket_yolu():
        fark.append("paket")
    if not fark and os.path.exists(kanal_yolu()):
        return "ayni"
    kanal_ac()
    simdi = time.time()
    eski_exe = d.get("exe") if isinstance(d, dict) else None
    _yaz_atomik(panel_pid_yolu(), {"pid": benim, **_canli_kimlik(benim), "paket": paket_yolu(), "zaman": simdi,
                                   "tazelendi": {"zaman": simdi, "neden": ",".join(fark) or "kanal",
                                                 "eski_exe": eski_exe}})
    try:
        from .gunluk import gunluk
        gunluk(f"panel kimlik kaydı tazelendi ({','.join(fark) or 'kanal'})")
    except Exception:  # noqa: BLE001 - günlük isteğe bağlı
        pass
    return "tazelendi"


def _tazeleyici_baslat() -> None:
    """Panel: kimlik kaydını TAZELE_ARALIK'ta bir denetleyen arka iş parçacığı (Qt'siz; panel_sil durdurur)."""
    global _TAZELEYICI
    if _TAZELEYICI is not None:
        return
    dur = threading.Event()

    def dongu():
        while not dur.wait(TAZELE_ARALIK):
            try:
                panel_kaydi_tazele()
            except Exception:  # noqa: BLE001 - bir tur başarısız: sonraki turda yeniden
                pass
    t = threading.Thread(target=dongu, name="panel-kayit-tazele", daemon=True)
    _TAZELEYICI = (dur, t)
    t.start()


def _tazeleyici_durdur() -> None:
    global _TAZELEYICI
    t, _TAZELEYICI = _TAZELEYICI, None
    if t is not None:
        t[0].set()
        if t[1] is not threading.current_thread():
            t[1].join(10)  # a refresh already in progress finishes before the record is removed


def panel_kanal_tanisi() -> str | None:
    """SALT OKUNUR tanı (doktor): canlı panelin kaydı süreçle uyuşuyor mu? → None (uyuşuyor / panel yok) | neden."""
    d = _panel_kaydi()
    if d is None:
        return None
    fark = kayit_farki(d)
    if d.get("paket") != paket_yolu():
        fark.append("paket")
    if not fark:
        return None
    exe = _exe(d["pid"]) or ""
    if "exe" in fark and exe.endswith(" (deleted)"):
        return _("panel kaydı eski: panel çalışırken Python/kurulum güncellenmiş (exe: {exe}); panel kaydını en çok "
                 "{sn} sn içinde kendiliğinden tazeler, düzelmezse paneli yeniden başlatın").format(
                     exe=exe, sn=int(TAZELE_ARALIK))
    return _("panel kaydı eski ({alanlar} uymuyor): panel en çok {sn} sn içinde kendiliğinden tazeler, düzelmezse "
             "paneli yeniden başlatın").format(alanlar=", ".join(fark), sn=int(TAZELE_ARALIK))


def kayit_tazelendi_bilgisi() -> dict | None:
    """Canlı panelin kaydı kendiliğinden tazelendiyse {zaman, neden, eski_exe}; yoksa None (doktor bilgisi)."""
    d = _panel_kaydi()
    t = d.get("tazelendi") if isinstance(d, dict) else None
    return t if isinstance(t, dict) else None


def _panel_kaydi() -> dict | None:
    """Canlı panelin kaydı {pid, baslangic, exe}; yoksa / ölmüşse / PID başka sürece geçmişse None."""
    d = _json_oku(panel_pid_yolu())
    if not isinstance(d, dict):
        return None
    pid = d.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    bas = _baslangic(pid)
    if bas is None or (d.get("baslangic") is not None and bas != d.get("baslangic")):
        return None
    return d


def panel_pid() -> int | None:
    """Canlı panelin PID'i; yoksa / ölmüşse / PID başka sürece geçmişse None."""
    d = _panel_kaydi()
    return None if d is None else d["pid"]


# ---------------------------------------------------------------- onay kanalı (Unix soketi + SO_PEERCRED)

_PEERCRED = struct.Struct("3i")  # struct ucred {pid, uid, gid}
KANAL_ZAMAN_ASIMI = 2.0          # bağlanma / ilk satır en çok bu kadar sn


def _karsi_taraf(s: socket.socket) -> tuple[int, int]:
    """SO_PEERCRED → (pid, uid). Sunucu tarafında: bağlanan istemci; istemci tarafında: listen() eden sunucu."""
    pid, uid, _gid = _PEERCRED.unpack(s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size))
    return pid, uid


def _satir_oku(s: socket.socket, sinir: int = 256) -> str | None:
    tampon = b""
    while b"\n" not in tampon and len(tampon) < sinir:
        parca = s.recv(sinir - len(tampon))
        if not parca:
            return None
        tampon += parca
    return tampon.split(b"\n", 1)[0].decode("ascii", "replace") if b"\n" in tampon else None


class _Kanal:
    """Panel sürecindeki onay kanalı sunucusu (Qt'siz; iş parçacıklı). Bağlantı başına tek istek: istemci
    `bekle <id>\\n` yazar; isteğin pid alanı SO_PEERCRED PID'iyle aynı değilse bağlantı kapatılır. Karar
    (`gonder`) o bağlantıya `karar <izin|red> <id>\\n` olarak yazılır; istemci henüz bağlanmadıysa saklanır."""

    def __init__(self):
        self.yol = kanal_yolu()
        self._kilit = threading.Lock()
        self._bekleyen: dict[str, socket.socket] = {}
        self._kararlar: dict[str, tuple[str, float]] = {}
        self._yanitlanan: dict[str, float] = {}
        self._durdu = threading.Event()
        _dizin_hazirla()
        try:
            if stat.S_ISSOCK(os.lstat(self.yol).st_mode):
                os.unlink(self.yol)  # ölü panelden kalan
        except FileNotFoundError:
            pass
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        eski = os.umask(0o177)
        try:
            s.bind(self.yol)
        finally:
            os.umask(eski)
        os.chmod(self.yol, 0o600)
        s.listen(16)
        self._s = s
        threading.Thread(target=self._kabul, name="onay-kanal", daemon=True).start()

    def _kabul(self):
        while not self._durdu.is_set():
            try:
                c, _a = self._s.accept()
            except OSError:
                return
            threading.Thread(target=self._baglanti, args=(c,), name="onay-kanal-b", daemon=True).start()

    def _baglanti(self, c: socket.socket):
        istek_id = None
        try:
            pid, uid = _karsi_taraf(c)
            if uid != os.getuid():
                return
            c.settimeout(KANAL_ZAMAN_ASIMI)
            satir = _satir_oku(c)
            parca = (satir or "").split()
            if len(parca) == 2 and parca[0] == "liste" and parca[1] in ("yasak", "seviye", "onaylar", "kimlik", "kalici"):
                # panelin bellekteki yetkili kopyası (liste_koruma; onaylar=kapsam, kimlik=hesap oturumu izni); SALT OKUMA
                c.sendall(_liste_yaniti(parca[1]))
                return
            if len(parca) != 2 or parca[0] != "bekle" or not _gecerli_id(parca[1]):
                return
            d = istek_oku(istek_yolu(parca[1]))
            if d is None or d["pid"] != pid:  # yalnız isteğin sahibi kararı alır
                return
            istek_id = parca[1]
            with self._kilit:
                karar = self._kararlar.pop(istek_id, None)
                if karar is None:
                    if istek_id in self._bekleyen:
                        istek_id = None  # aynı isteğe ikinci bağlantı: ilkini ezmesin
                        return
                    self._bekleyen[istek_id] = c
            if karar is not None:
                c.sendall(f"karar {karar[0]} {istek_id}\n".encode())
                return
            c.settimeout(None)
            while c.recv(64):  # isteyen vazgeçene / karar yazılıp kapatana dek
                pass
        except OSError:
            pass
        finally:
            if istek_id is not None:
                with self._kilit:
                    if self._bekleyen.get(istek_id) is c:
                        del self._bekleyen[istek_id]
            try:
                c.close()
            except OSError:
                pass

    def yanitlandi(self, istek_id: str) -> bool:
        with self._kilit:
            return istek_id in self._yanitlanan

    def gonder(self, istek_id: str, karar: str) -> bool:
        """Kararı isteyene ilet (tek kullanımlık). → kabul edildi mi (bu istek daha önce yanıtlandıysa False)."""
        simdi = time.monotonic()
        with self._kilit:
            if istek_id in self._yanitlanan:
                return False
            self._yanitlanan[istek_id] = simdi
            for k in [k for k, t in self._yanitlanan.items() if simdi - t > 3600]:
                del self._yanitlanan[k]
            for k in [k for k, (_kr, t) in self._kararlar.items() if simdi - t > DEVIR_EN_COK + ESKI_PAY]:
                del self._kararlar[k]
            c = self._bekleyen.pop(istek_id, None)
            if c is None:
                self._kararlar[istek_id] = (karar, simdi)
                return True
        try:
            c.sendall(f"karar {karar} {istek_id}\n".encode())
        except OSError:
            return karar == "red"  # isteyen gitmiş: izin kimseye ulaşmadı
        return True

    def kapat(self):
        self._durdu.set()
        try:
            self._s.close()
        except OSError:
            pass
        try:
            if stat.S_ISSOCK(os.lstat(self.yol).st_mode):
                os.unlink(self.yol)
        except OSError:
            pass
        with self._kilit:
            bekleyen, self._bekleyen = list(self._bekleyen.values()), {}
        for c in bekleyen:
            try:
                c.shutdown(socket.SHUT_RDWR)  # isteyen EOF görür → panel kapandı → red
            except OSError:
                pass


liste_saglayici = None  # panel: liste_koruma.Koruyucu.metin (tur → metin | None)
LISTE_SINIRI = 1024 * 1024


def _liste_yaniti(tur: str) -> bytes:
    f = liste_saglayici
    if f is None:
        return b"saglayici-yok\n"
    try:
        metin = f(tur)
    except Exception:  # noqa: BLE001
        return b"saglayici-yok\n"
    if metin is None:
        return b"yok\n"
    veri = metin.encode("utf-8", "surrogateescape")[:LISTE_SINIRI]
    return f"icerik {len(veri)}\n".encode() + veri


class _ListeYok(Exception):
    pass


def liste_iste(tur: str) -> str | None:
    """İstemci (CLI/MCP): panelin bellekteki yasak/seviye listesi, doğrulanmış onay kanalından. → metin | None (dosya
    yok = kısıt yok). Panel yok / kanal doğrulanamadı / panel liste sunmuyor → _ListeYok (çağıran dosyaya düşer)."""
    kayit = _panel_kaydi()
    if kayit is None:
        raise _ListeYok("panel yok")
    try:
        s = _kanala_baglan(kayit)
    except _KanalHatasi as e:
        raise _ListeYok(str(e)) from None
    try:
        s.settimeout(KANAL_ZAMAN_ASIMI)
        s.sendall(f"liste {tur}\n".encode())
        tampon = b""
        while b"\n" not in tampon and len(tampon) < 64:
            parca = s.recv(64 - len(tampon))
            if not parca:
                break
            tampon += parca
        baslik, _a, veri = tampon.partition(b"\n")
        k = baslik.decode("ascii", "replace").split()
        if k == ["yok"]:
            return None
        if len(k) != 2 or k[0] != "icerik" or not k[1].isdigit() or int(k[1]) > LISTE_SINIRI:
            raise _ListeYok(baslik.decode("ascii", "replace")[:40])
        n = int(k[1])
        while len(veri) < n:
            parca = s.recv(min(65536, n - len(veri)))
            if not parca:
                raise _ListeYok("eksik yanıt")
            veri += parca
        return veri[:n].decode("utf-8", "surrogateescape")
    except OSError as e:
        raise _ListeYok(str(e)) from None
    finally:
        s.close()


_KANAL: _Kanal | None = None
_KANAL_KILIT = threading.Lock()


def kanal_ac() -> None:
    """Panel: onay kanalını aç (açıksa ve yolu aynıysa dokunma)."""
    global _KANAL
    with _KANAL_KILIT:
        if _KANAL is not None and _KANAL.yol == kanal_yolu() and os.path.exists(_KANAL.yol):
            return
        if _KANAL is not None:
            _KANAL.kapat()
        _KANAL = _Kanal()


def kanal_kapat() -> None:
    global _KANAL
    with _KANAL_KILIT:
        k, _KANAL = _KANAL, None
    if k is not None:
        k.kapat()


class _KanalHatasi(Exception):
    pass


def _kanala_baglan(kayit: dict) -> socket.socket:
    """İsteyen: panelin onay kanalına bağlan ve karşı tarafın panel olduğunu doğrula → bağlı soket.
    Doğrulanamazsa _KanalHatasi (çağıran red döner)."""
    d = dizin()
    try:
        sd = os.lstat(d)
        sk = os.lstat(kanal_yolu())
    except OSError as e:
        raise _KanalHatasi(f"kanal yok: {e}") from None
    uid = os.getuid()
    if not stat.S_ISDIR(sd.st_mode) or sd.st_uid != uid or stat.S_IMODE(sd.st_mode) & 0o077:
        raise _KanalHatasi("onay dizini başkasının ya da izni geniş")
    if not stat.S_ISSOCK(sk.st_mode) or sk.st_uid != uid or stat.S_IMODE(sk.st_mode) & 0o077:
        raise _KanalHatasi("kanal soketi değil ya da izni geniş")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
    try:
        s.settimeout(KANAL_ZAMAN_ASIMI)
        s.connect(kanal_yolu())
        pid, puid = _karsi_taraf(s)
        if puid != uid:
            raise _KanalHatasi("kanalın sahibi başka kullanıcı")
        if pid != kayit.get("pid"):
            raise _KanalHatasi(f"kanalı dinleyen süreç ({pid}) panel değil ({kayit.get('pid')})")
        if _baslangic(pid) != kayit.get("baslangic") or not kayit.get("exe") or _exe(pid) != kayit.get("exe"):
            raise _KanalHatasi("panel sürecinin kimliği (başlangıç zamanı / exe) uymuyor")
        if not kayit.get("cmdline") or _komut_satiri(pid) != kayit.get("cmdline"):
            raise _KanalHatasi("panel sürecinin komut satırı (modül yolu / giriş noktası) kayıttakiyle aynı değil")
        if not kayit.get("cwd") or _cwd(pid) != kayit.get("cwd"):
            raise _KanalHatasi("panel sürecinin çalışma dizini kayıttakiyle aynı değil")
        if kayit.get("paket") != paket_yolu():
            raise _KanalHatasi(f"panelin deskhand paketi ({kayit.get('paket')}) bu kurulumunki değil ({paket_yolu()})")
        s.settimeout(None)
        return s
    except (OSError, _KanalHatasi) as e:
        s.close()
        if isinstance(e, _KanalHatasi):
            raise
        raise _KanalHatasi(f"kanala bağlanılamadı: {e}") from None


def bekleyen_var(masaustu: str, haric_pid: int | None = None, simdi: float | None = None,
                 masa: str | None = None) -> bool:
    """Bu masaüstü ("ekran" | "arka") için canlı bir süreçten bekleyen onay isteği var mı? (MCP girdi kapısı.)
    haric_pid: bu sürecin kendi istekleri sayılmaz (süreç içi kayıt ayrıca tutulur). Ömrü olağandışı uzun
    (sahte/bozuk) istek sayılmaz: girdiyi süresiz kilitleyemez. Arka uç adı da kabul edilir ("sanal" → "arka",
    "kde" → "ekran"; iste_sonuc ile aynı eşleme): eylem.girdi_al arka uç adıyla çağırır. masa: görünmez masaüstünün
    adı (None: bu sürecinki, masalar.secili()); başka görünmez masaüstündeki bekleyen onay bunu kilitlemez."""
    from . import masalar
    masaustu = "arka" if masaustu in ("arka", "sanal", "background") else "ekran"
    if masaustu == "arka":
        masa = masalar.secili() if masa is None else masa
    for d in bekleyenler(simdi):
        if d["masaustu"] != masaustu or d["pid"] <= 0 or d["pid"] == haric_pid:
            continue
        if masaustu == "arka" and d.get("masa", "") != masa:
            continue
        sinir = (DEVIR_EN_COK if d.get("tur") == TUR_DEVIR else VARSAYILAN_SURE) + ESKI_PAY
        if d["son_zaman"] - d["zaman"] > sinir:
            continue
        return True
    return False


def panel_canli() -> bool:
    return panel_pid() is not None


# ---------------------------------------------------------------- isteyen taraf

def _dur_acik() -> bool:
    from .hata import dur_dosyasi
    return os.path.exists(dur_dosyasi())


DEVIR_ETIKET = {"izin": "devir-tamam", "kosul": "devir-kosul"}  # insan devri: "onay izin" DEĞİL (izin verilmedi, iş devredildi)


def _kaydet_gunluk(sonuc: OnaySonucu, eylem: str, hedef: str, masaustu: str, tur: str = "") -> None:
    from .gunluk import gunluk
    yer = "arka sanal " if masaustu == "arka" else ""
    neden = DEVIR_ETIKET.get(sonuc.neden, f"devir-{sonuc.neden}") if tur == TUR_DEVIR else sonuc.neden
    gunluk(f"onay {neden} | {yer}[{hedef}] | {eylem}")


def iste_sonuc(eylem: str, hedef: str, ayrinti: str = "", masaustu: str = "ekran", sure: float = VARSAYILAN_SURE,
               goruntu=None, gunluge_yaz: bool = True, tur: str = "", kontrol=None, iptal=None) -> OnaySonucu:
    """Paneldeki insandan bir kez izin iste ve bekle (en çok `sure` sn). → OnaySonucu.
    masaustu: "ekran" (kullanıcının ekranı) | "arka" (görünmez masaüstü).
    tur: "" (hassas eylem onayı) | "devir" (insan doğrulaması devri: panel "Devral/Bitti/Vazgeç" gösterir; izin = Bitti).
    kontrol: isteğe bağlı koşul işlevi (beklerken ~KONTROL_ARALIK sn'de bir çağrılır); True dönerse bekleme biter,
    OnaySonucu(izin=False, neden="kosul"): izin DEĞİL, yalnız "beklenen şey kendiliğinden oldu" (isteği kapatma yetkisi
    ajanda değil: koşul sayfanın gerçek durumudur ve bekleme boyunca ajanın girdisi o masaüstüne kapalıdır).
    goruntu: hedefin küçük görüntüsü: PIL.Image (onay dizinine kaydedilir, sonra silinir) ya da var olan dosya yolu.
    iptal: isteğe bağlı işlev; True dönerse (ör. MCP çağrısı istemcide iptal edildi) bekleme HEMEN biter, istek silinir,
    OnaySonucu(False, "iptal") — red; yalnız isteyenin kendi beklemesini bitirir (izin üretemez)."""
    masaustu = "arka" if masaustu in ("arka", "sanal", "background") else "ekran"
    # Gerçek ekran kilidi (DESKHAND_GERCEK_EKRAN=kapali) gerçek oturuma GİRDİYİ keser. Görünmez masaüstündeki bir eylemin
    # onayını panelde göstermek gerçek ekrana girdi değildir: yalnız hedef kullanıcının ekranıysa reddedilir (yoksa
    # görünmez masaüstündeki ödeme sayfası onaysız kalıp tümüyle kilitlenirdi).
    if masaustu == "ekran" and not os.environ.get("DESKHAND_RUNTIME_DIR"):  # kullanıcının GERÇEK paneli
        from .hata import gercek_ekran_denetle
        gercek_ekran_denetle(_("onay iletişim kutusu"))

    def bitir(s: OnaySonucu) -> OnaySonucu:
        if gunluge_yaz:
            _kaydet_gunluk(s, eylem, hedef, masaustu, tur)
        return s

    if gozetimsiz():  # başında insan yok: panel diyaloğu açılmaz, beklenmez (tek nokta: CLI, MCP, akış hep buradan)
        return bitir(OnaySonucu(False, "gozetimsiz"))
    if _dur_acik():
        return bitir(OnaySonucu(False, "dur"))
    kayit = _panel_kaydi()
    if kayit is None:
        return bitir(OnaySonucu(False, "panel-yok"))
    ppid = kayit["pid"]
    try:
        _dizin_hazirla()
        kanal = _kanala_baglan(kayit)  # yanıt YALNIZ bu doğrulanmış bağlantıdan kabul edilir
    except (OSError, _KanalHatasi) as e:
        from .gunluk import gunluk
        gunluk(f"onay kanalı reddedildi: {e}")
        return bitir(OnaySonucu(False, "kanal"))
    istek_id = uuid.uuid4().hex
    iy, yy, gy = istek_yolu(istek_id), yanit_yolu(istek_id), goruntu_yolu(istek_id)
    simdi = time.time()
    sure = max(1.0, float(sure))
    try:
        g_yol = None
        if goruntu is not None and hasattr(goruntu, "save"):
            goruntu.save(gy, "PNG")
            os.chmod(gy, 0o600)
            g_yol = gy
        elif isinstance(goruntu, str) and os.path.isfile(goruntu):
            g_yol = os.path.abspath(goruntu)
        from . import masalar
        istek = {"id": istek_id, "eylem": str(eylem), "hedef": str(hedef),
                 "ayrinti": str(ayrinti or "")[:AYRINTI_SINIR], "masaustu": masaustu, "zaman": simdi,
                 "son_zaman": simdi + sure, "pid": os.getpid(), "pid_bas": _baslangic(os.getpid()), "goruntu": g_yol,
                 "masa": masalar.secili() if masaustu == "arka" else ""}
        if tur == TUR_DEVIR:
            istek["tur"] = TUR_DEVIR
        _yaz_atomik(iy, istek)
        kanal.sendall(f"bekle {istek_id}\n".encode())
    except Exception:  # noqa: BLE001 - görüntü/istek yazılamadı: red (soket açık kalmasın)
        kanal.close()
        _sil(iy, gy)
        return bitir(OnaySonucu(False, "hata", istek_id))
    nabiz_dur = threading.Event()

    def nabiz():
        # Heartbeat from its own thread: a slow `kontrol` (e.g. waiting for the in-process tool lock) must not make
        # a live request look abandoned to other processes.
        while not nabiz_dur.wait(CANLILIK_ARALIK):
            try:
                os.utime(iy)
            except OSError:
                return

    def iptal_mi() -> bool:
        if iptal is None:
            return False
        try:
            return bool(iptal())
        except Exception:  # noqa: BLE001 - iptal okunamadı: beklemeye devam
            return False

    threading.Thread(target=nabiz, name="onay-nabiz", daemon=True).start()
    try:
        son = time.monotonic() + sure
        sonraki_canlilik = time.monotonic() + CANLILIK_ARALIK
        sonraki_kontrol = time.monotonic() + KONTROL_ARALIK
        tampon = b""
        while True:
            try:
                hazir = select.select([kanal], [], [], YOKLAMA)[0]
                parca = kanal.recv(256) if hazir else None
            except OSError:
                parca = b""
            if parca == b"":  # panel bağlantıyı kapattı (kapandı / isteği reddetti) → red
                return bitir(OnaySonucu(False, "panel-kapandi", istek_id))
            if parca:
                tampon += parca
                if b"\n" in tampon or len(tampon) > 256:
                    satir = tampon.split(b"\n", 1)[0].decode("ascii", "replace").split()
                    if len(satir) == 3 and satir[0] == "karar" and satir[1] in KARARLAR and satir[2] == istek_id:
                        if iptal_mi():  # cancellation wins over a decision that arrived in the same poll
                            return bitir(OnaySonucu(False, "iptal", istek_id))
                        return bitir(OnaySonucu(satir[1] == "izin", satir[1], istek_id))
                    return bitir(OnaySonucu(False, "red", istek_id))  # biçimsiz yanıt = red
            if os.path.exists(yy):  # dosya yanıtı (eski protokol / panel kapanırken): YALNIZ red sayılır
                return bitir(OnaySonucu(False, "red", istek_id))
            if not os.path.exists(iy):  # request file removed (cleanup / another process): the panel can no longer
                return bitir(OnaySonucu(False, "silindi", istek_id))  # show it, so stop waiting (never an approval)
            t = time.monotonic()
            if t >= son:
                return bitir(OnaySonucu(False, "sure", istek_id))
            if _dur_acik():
                return bitir(OnaySonucu(False, "dur", istek_id))
            if iptal_mi():
                return bitir(OnaySonucu(False, "iptal", istek_id))
            if t >= sonraki_canlilik:
                sonraki_canlilik = t + CANLILIK_ARALIK
                if panel_pid() != ppid:
                    return bitir(OnaySonucu(False, "panel-kapandi", istek_id))
            if kontrol is not None and t >= sonraki_kontrol:
                try:
                    if kontrol():
                        if iptal_mi():  # kontrol may take long: re-check cancellation at the decision point
                            return bitir(OnaySonucu(False, "iptal", istek_id))
                        return bitir(OnaySonucu(False, "kosul", istek_id))
                except Exception:  # noqa: BLE001 - koşul okunamadı: beklemeye devam (insan kararı/zaman aşımı geçerli)
                    pass
                sonraki_kontrol = time.monotonic() + KONTROL_ARALIK
    finally:
        nabiz_dur.set()
        try:
            kanal.close()
        except OSError:
            pass
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
    from . import masalar
    m = d.get("masa")
    d["masa"] = m if d["masaustu"] == "arka" and isinstance(m, str) and masalar.AD_DESENI.fullmatch(m) else ""
    d["tur"] = TUR_DEVIR if d.get("tur") == TUR_DEVIR else ""
    g = d.get("goruntu")
    d["goruntu"] = g if isinstance(g, str) and os.path.isfile(g) else None
    return d


def _canli(pid: int) -> bool:
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def _sahibi_canli(d: dict) -> bool:
    """İsteyen süreç yaşıyor mu: PID var ve (kayıtta varsa) başlangıç zamanı aynı (PID yeniden kullanımına karşı)."""
    if not _canli(d["pid"]):
        return False
    bas = d.get("pid_bas")
    return not isinstance(bas, str) or _baslangic(d["pid"]) == bas


def _calisiyor(d: dict) -> bool:
    """Owner verifiably alive AND running: pid + recorded start time match and the process is not stopped/zombie.
    Such a request is never treated as abandoned on file mtime alone (another process could age the mtime)."""
    bas = d.get("pid_bas")
    if not isinstance(bas, str) or not _canli(d["pid"]) or _baslangic(d["pid"]) != bas:
        return False
    try:
        with open(f"/proc/{int(d['pid'])}/stat") as f:
            st = f.read()
        return st[st.rindex(")") + 2] not in "TtZX"
    except (OSError, ValueError, IndexError):
        return False


def _nabiz_var(yol: str) -> bool:
    """İstek dosyasına son NABIZ_SINIR sn içinde dokunulmuş mu (isteyenin bekleme döngüsü yaşıyor)."""
    try:
        return time.time() - os.stat(yol).st_mtime <= NABIZ_SINIR
    except OSError:
        return False


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
        if _KANAL is not None and _KANAL.yanitlandi(d["id"]):  # izin kanaldan gitti (dosya yok): yeniden sorma
            continue
        if d["pid"] and not _sahibi_canli(d):
            continue
        if not _nabiz_var(os.path.join(dizin(), ad)) and not _calisiyor(d):  # stale heartbeat counts only when the
            continue  # owner is not verifiably running (stopped / no start time recorded)
        sonuc.append(d)
    return sorted(sonuc, key=lambda d: d["zaman"])


def yanitla(istek_id: str, karar: str, simdi: float | None = None) -> bool:
    """Panel: isteği yanıtla (tek kullanımlık). → iletildi mi. İstek yoksa/süresi geçtiyse/zaten yanıtlandıysa False.
    İZİN yalnız bu süreçteki onay kanalından isteyene gider (kanal yoksa False). RED ayrıca yanıt dosyasına yazılır
    (isteyen dosyayı yalnız red sayar; kanal kopuksa da red kesin ulaşır)."""
    if not _gecerli_id(istek_id) or karar not in KARARLAR:
        return False
    simdi = time.time() if simdi is None else simdi
    d = istek_oku(istek_yolu(istek_id))
    if d is None or (karar == "izin" and d["son_zaman"] <= simdi):
        return False  # süresi geçmiş isteğe İZİN verilmez (red her zaman verilebilir)
    k = _KANAL
    if (k is not None and k.yanitlandi(istek_id)) or os.path.exists(yanit_yolu(istek_id)):
        return False  # tek kullanımlık: ilk karar kesin
    if karar == "izin":
        return k is not None and k.gonder(istek_id, "izin")
    try:
        _yaz_atomik(yanit_yolu(istek_id), {"id": istek_id, "karar": "red", "kaynak": "arayuz", "zaman": simdi,
                                           "panel_pid": os.getpid()}, ozel=True)
    except OSError:  # FileExistsError dahil: zaten yanıtlanmış
        return False
    if k is not None:
        k.gonder(istek_id, "red")
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
            eski = (d is None or d["son_zaman"] + ESKI_PAY < simdi or (d["pid"] and not _sahibi_canli(d))
                    or (not _nabiz_var(yol) and not _calisiyor(d)))
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
