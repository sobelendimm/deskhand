"""GİRDİ MERKEZİ: panelin içinde HAZIR bekleyen tek dotool ve ona bağlanan istemciler (docs/ARCHITECTURE.md §2, §4).

Neden: her komutta dotool'un uinput aygıtını kurması ~0,66 sn sürüyordu. Panel açıkken tek bir dotool hazır bekler;
kde Girdi satırlarını RUNTIME_DIR/girdi.sock üzerinden ona gönderir (ilk satıra kadar ~ms). Panel kapalıyken ya da
merkez el sıkışmayı başaramazsa Girdi kendi dotool'unu açar (iç geri düşme). Qt kullanılmaz: panel bunu bir iş
parçacığında çalıştırır; panel süreci ölürse dotool'un girişi kapanır, dotool çıkar, aygıt yok olur (tuşlar bırakılır).

Güvenlik (istemcideki denetimlere EK, onların yerine DEĞİL):
- soket 0600, dizin 0700; SO_PEERCRED ile yalnız aynı kullanıcı (istemci de sunucunun kullanıcısını denetler).
- her partiden hemen önce DUR anahtarı (hata.dur_dosyasi): açıksa basma satırları reddedilir (13), bırakma serbest.
- bağlantı başına BASILI durum (keydown/buttondown): bağlantı kopunca (istemci öldü, SIGKILL) hepsi bırakılır. Kopan
  bağlantının kuyrukta işlenmekte olan girdisi varsa dotool yeniden başlatılır: denetimsiz girdi sürmez.
- DUR açılınca tüm bağlantıların basılıları bırakılır; dotool kuyrukta girdi işliyorsa yeniden başlatılır (kuyruk düşer).
- bir partinin satırları ATOMİK: tek kilit altında tek yazım. Başka bağlantının girdisi kuyrukta sürerken 'mesgul'
  döner; istemci tüm denetimlerini YENİDEN yapıp tekrar dener (denetim girdiden hemen önce kalır, CHANGE 2).
- yalnız dotool satır dilinin bilinen fiilleri geçer; bağlantı başına gecikme ayarları (typedelay…) korunur.

Protokol (UTF-8 satırlar):
  istemci → merkez: "merhaba 1 <düzen> <varyant|->" ; "parti <n>" + n satır ; "bekle"
  merkez → istemci: "tamam …" | "mesgul <sn>" | "hata <kod> <mesaj>" ; bekle → "tamam <n>" + n uyarı satırı
"""
from __future__ import annotations

import os
import re
import socket
import stat
import struct
import threading
import time

from . import hata
from .gunluk import gunluk
from .i18n import _

SURUM = 1
BIRAKMA = frozenset({"keyup", "buttonup"})
AYARLAR = ("keydelay", "keyhold", "typedelay", "typehold")
FIILLER = frozenset({"key", "keydown", "keyup", "type", "click", "buttondown", "buttonup", "wheel", "hwheel",
                     "scroll", "mouseto", "mousemove", *AYARLAR})
VARSAYILAN_AYAR = {"keydelay": 2, "keyhold": 8, "typedelay": 2, "typehold": 8}  # man dotool
DUR_ARALIK = 0.02        # DUR anahtarı yoklama aralığı (sn; os.path.exists ~2 µs)
MESGUL_PAY = 0.005       # başka bağlantının kuyruğu bundan uzun sürecekse 'mesgul'
KOPMA_PAY = 0.05         # kopan bağlantının kuyruğu bundan uzun sürecekse dotool yeniden başlar
AZAMI_SATIR = 4096       # bir partide en çok satır
AZAMI_UZUNLUK = 1 << 16  # bir satırın en çok bayt uzunluğu
AZAMI_BAGLANTI = 32
COKME_SINIRI = (3, 30.0)  # 30 sn'de 3 kez kendiliğinden ölürse yeniden başlatma durur (istemciler kendi yoluna düşer)
ISTEMCI_ZAMAN = 5.0       # istemci: parti yanıtı için en çok bekleme
_DUZEN_RE = re.compile(r"[A-Za-z0-9_()+.:-]{1,64}")
_PEERCRED = struct.Struct("3i")


def soket_yolu() -> str:
    return os.path.join(hata.calisma_dizini(), "girdi.sock")


def es_kimligi(s: socket.socket) -> tuple[int, int, int]:
    """SO_PEERCRED → (pid, uid, gid): bağlantının öbür ucundaki süreç (çekirdek doğrular, taklit edilemez)."""
    return _PEERCRED.unpack(s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size))


def _ayir(satir: str) -> tuple[str, str]:
    fiil, _bos, arg = satir.partition(" ")
    return fiil, arg


def satir_gecerli(satir: str) -> bool:
    """dotool satır dilinin bilinen bir fiili mi (kontrol karakteri yok; ayarlar 0..10000 tam sayı)?"""
    if not satir or len(satir.encode()) > AZAMI_UZUNLUK or any(c in satir for c in "\r\n\x00"):
        return False
    fiil, arg = _ayir(satir)
    if fiil not in FIILLER:
        return False
    if fiil in AYARLAR:
        return arg.isdigit() and int(arg) <= 10000
    return True


def basma_mi(satir: str) -> bool:
    """Ekrana etki eden satır mı? (bırakma ve gecikme ayarı değil). DUR açıkken yalnız bunlar reddedilir."""
    fiil = _ayir(satir)[0]
    return fiil not in BIRAKMA and fiil not in AYARLAR


def _tuslar(arg: str) -> set[str]:
    """'ctrl+s leftshift' → {'ctrl', 's', 'leftshift'} (keydown/keyup akorları)."""
    return {t for akor in arg.split() for t in akor.split("+") if t}


def girdi_suresi(satirlar, ayar) -> float:
    """Bu satırların dotool'da işlenme süresi (sn), gecikme ayarlarıyla (man dotool). Kuyruk bitiş tahmini için."""
    ms = 0.0
    for s in satirlar:
        fiil, arg = _ayir(s)
        if fiil == "type":
            ms += len(arg) * (ayar["typehold"] + ayar["typedelay"])
        elif fiil == "key":
            ms += max(1, len(arg.split())) * (ayar["keyhold"] + ayar["keydelay"])
        elif fiil == "click":
            ms += ayar["keyhold"] + ayar["keydelay"]
        elif fiil in ("keydown", "keyup", "buttondown", "buttonup"):
            ms += max(1, len(arg.split())) * ayar["keydelay"]
        ms += 0.3  # olay yazımı + zamanlayıcı payı
    return ms / 1000 * 1.1


class _Baglanti:
    def __init__(self, sock: socket.socket, pid: int):
        self.sock, self.pid = sock, pid
        self.tuslar: set[str] = set()
        self.dugmeler: set[str] = set()
        self.ayar = dict(VARSAYILAN_AYAR)
        self.nesil = None  # el sıkışmadaki dotool nesli; dotool yeniden başlarsa eski bağlantı reddedilir
        self.uyarilar: list[str] = []


class GirdiMerkezi:
    """Tek dotool sahibi + Unix soket sunucusu. baslat() → arka plan iş parçacıkları; durdur() → hepsi kapanır,
    dotool sonlanır (aygıt yok olur: basılı her şey bırakılır)."""

    def __init__(self, yol: str | None = None, duzen: tuple[str, str] | None = None):
        self.yol = yol or soket_yolu()
        self.izinli_uid = os.getuid()
        self._kilit = threading.RLock()
        self._baglantilar: set[_Baglanti] = set()
        self._p = None
        self._nesil = 0
        self._hazir = threading.Event()
        self._hata = None          # dotool kalıcı olarak açılamıyor
        self._cokmeler: list[float] = []
        self._duzen = duzen
        self._dotool_ayar = dict(VARSAYILAN_AYAR)
        self._mesgul_son = 0.0     # dotool kuyruğunun tahmini bitişi (monotonic)
        self._sahip = None         # kuyruktaki son basma partisinin bağlantısı
        self._dur = None           # izlenen DUR dosyasının imzası
        self._durdu = threading.Event()
        self._dinleyici = None
        self._dugum = None
        self._isler: list[threading.Thread] = []

    # ---------------------------------------------------------------- yaşam döngüsü
    def baslat(self) -> "GirdiMerkezi":
        d = os.path.dirname(self.yol)
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise OSError(_("girdi merkezi: çalışma dizini bu kullanıcının değil: {yol}").format(yol=d))
        if stat.S_IMODE(st.st_mode) & 0o077:
            os.chmod(d, 0o700)
        if os.path.lexists(self.yol):
            if _canli(self.yol):
                raise OSError(_("girdi merkezi zaten çalışıyor: {yol}").format(yol=self.yol))
            os.unlink(self.yol)  # ölü panelden kalmış
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        eski = os.umask(0o177)  # soket baştan 0600 doğsun (bind ile chmod arasında açık pencere olmasın)
        try:
            s.bind(self.yol)
        finally:
            os.umask(eski)
        os.chmod(self.yol, 0o600)
        st = os.lstat(self.yol)
        self._dugum = (st.st_dev, st.st_ino)
        s.listen(16)
        s.settimeout(0.25)
        self._dinleyici = s
        if self._duzen is None:
            from .arka_uc import kde
            self._duzen = kde.klavye_duzeni()
        for hedef in (self._kabul, self._dur_izle, self._bekci):
            t = threading.Thread(target=hedef, daemon=True, name=f"girdi-merkezi{hedef.__name__}")
            t.start()
            self._isler.append(t)
        gunluk(f"girdi merkezi başladı | {self.yol}")
        return self

    def durdur(self) -> None:
        if self._durdu.is_set():
            return
        self._durdu.set()
        if self._dinleyici is not None:
            try:
                self._dinleyici.close()
            except OSError:
                pass
        try:
            st = os.lstat(self.yol)
            if (st.st_dev, st.st_ino) == self._dugum:  # yalnız kendi soketimizi sil
                os.unlink(self.yol)
        except OSError:
            pass
        with self._kilit:
            for b in list(self._baglantilar):
                try:
                    b.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            self._dotool_birak(nazik=True)
        for t in self._isler:
            if t is not threading.current_thread():
                t.join(timeout=2)
        gunluk("girdi merkezi durdu")

    def calisiyor(self) -> bool:
        return self._dinleyici is not None and not self._durdu.is_set()

    def dotool_pid(self):
        p = self._p
        return p.pid if p is not None else None

    # ---------------------------------------------------------------- dotool
    def _dotool_ac(self):
        """Yeni dotool süreci aç ve aygıtı hazır olana dek bekle (kde.Girdi ile aynı ölçüt). Kilit DIŞINDA çağrılır."""
        from .arka_uc import kde
        duzen, varyant = self._duzen
        env = dict(os.environ, DOTOOL_XKB_LAYOUT=duzen)
        env.pop("DOTOOL_XKB_VARIANT", None)
        if varyant:
            env["DOTOOL_XKB_VARIANT"] = varyant
        taban = kde._goreli_imlec_sayisi()
        t0 = time.monotonic()
        p = kde.dotool_ac(env)
        hazir_an = None
        while time.monotonic() - t0 < kde.DOTOOL_AZAMI and p.poll() is None and not self._durdu.is_set():
            if kde._goreli_imlec_sayisi() > taban:
                hazir_an = time.monotonic() + kde.DOTOOL_SON_UYKU
                break
            time.sleep(0.01)
        kalan = (hazir_an or t0 + 1.0) - time.monotonic()
        if kalan > 0 and not self._durdu.is_set():
            time.sleep(kalan)
        return p

    def _bekci(self):
        """Tek dotool sürecini açık ve hazır tutar; ölürse yeniden açar (sınırlı)."""
        while not self._durdu.is_set():
            with self._kilit:
                p = self._p
                if p is not None and p.poll() is not None:
                    simdi = time.monotonic()
                    self._cokmeler = [t for t in self._cokmeler if simdi - t < COKME_SINIRI[1]] + [simdi]
                    gunluk(f"girdi merkezi | dotool kapandı (çıkış {p.returncode})")
                    self._dotool_birak()
                    if len(self._cokmeler) >= COKME_SINIRI[0]:
                        self._hata = _("dotool tekrar tekrar kapandı (uinput yüklü mü?)")
                p = self._p
                gerek = p is None and self._hata is None
            if gerek:
                try:
                    yeni = self._dotool_ac()
                except OSError as e:
                    with self._kilit:
                        self._hata = _("dotool başlatılamadı: {hata}").format(hata=e)
                    continue
                with self._kilit:
                    if self._durdu.is_set():
                        _sonlandir(yeni)
                        return
                    if yeni.poll() is not None:  # kurulumda öldü: sonraki turda çökme sayılır
                        self._p = yeni
                        continue
                    self._p = yeni
                    self._nesil += 1
                    self._dotool_ayar = dict(VARSAYILAN_AYAR)
                    self._mesgul_son, self._sahip = 0.0, None
                    threading.Thread(target=self._stderr_oku, args=(yeni,), daemon=True).start()
                    self._hazir.set()
                continue
            self._durdu.wait(0.05)

    def _stderr_oku(self, p):
        """dotool uyarıları → kuyruktaki son girdinin bağlantısına (yaklaşık eşleme) + günlük."""
        try:
            for satir in p.stderr:
                satir = satir.strip()
                if not satir:
                    continue
                with self._kilit:
                    if self._sahip is not None and len(self._sahip.uyarilar) < 50:
                        self._sahip.uyarilar.append(satir)
                gunluk(f"girdi merkezi | dotool: {satir}")
        except (OSError, ValueError):
            pass

    def _dotool_birak(self, nazik=False):
        """(kilit altında) dotool'u sonlandır: aygıt yok olur → çekirdek basılı her şeyi bırakır, kuyruk düşer.
        Bekçi yenisini açar. Eski nesildeki bağlantılar bundan sonra reddedilir."""
        p, self._p = self._p, None
        self._hazir.clear()
        for b in self._baglantilar:
            b.tuslar.clear()
            b.dugmeler.clear()
        self._mesgul_son, self._sahip = 0.0, None
        if p is not None:
            _sonlandir(p, nazik)

    def _yaz(self, satirlar) -> bool:
        """(kilit altında) satırları TEK yazımla dotool'a ver."""
        if not satirlar:
            return True
        try:
            self._p.stdin.write("".join(s + "\n" for s in satirlar))
            self._p.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            self._dotool_birak()
            return False

    def _birakma_satirlari(self, tuslar, dugmeler):
        return [f"buttonup {d}" for d in sorted(dugmeler)] + [f"keyup {t}" for t in sorted(tuslar)]

    def _baglanti_birak(self, b: _Baglanti):
        """(kilit altında) b'nin basılılarını bırak (başka bağlantının da basılı tuttukları hariç)."""
        digerleri = [x for x in self._baglantilar if x is not b]
        tuslar = b.tuslar - set().union(*(x.tuslar for x in digerleri))
        dugmeler = b.dugmeler - set().union(*(x.dugmeler for x in digerleri))
        b.tuslar.clear()
        b.dugmeler.clear()
        if (tuslar or dugmeler) and self._p is not None and b.nesil == self._nesil:
            satirlar = self._birakma_satirlari(tuslar, dugmeler)
            self._yaz(satirlar)
            gunluk(f"girdi merkezi | bırak (pid {b.pid}) | {' ; '.join(satirlar)}")

    # ---------------------------------------------------------------- DUR
    def _dur_izle(self):
        """DUR dosyasının KİMLİĞİNİ (inode + mtime) izler: kapatılıp hemen yeniden açılan DUR da kaçmaz."""
        while not self._durdu.is_set():
            try:
                st = os.stat(hata.dur_dosyasi())
                imza = (st.st_dev, st.st_ino, st.st_mtime_ns)
            except OSError:
                imza = None
            if imza is not None and imza != self._dur:
                with self._kilit:
                    self._dur_acildi()
            self._dur = imza
            self._durdu.wait(DUR_ARALIK)

    def _dur_acildi(self):
        """(kilit altında) DUR açıldı: kuyruk sürüyorsa dotool yeniden başlar (kuyruk düşer, her şey bırakılır);
        değilse tüm bağlantıların basılıları bırakılır."""
        if self._p is None:
            return
        if self._mesgul_son - time.monotonic() > 0.01:
            gunluk("girdi merkezi | DUR: kuyruktaki girdi düşürüldü, dotool yeniden başlıyor")
            self._dotool_birak()
            return
        tuslar = set().union(*(b.tuslar for b in self._baglantilar))
        dugmeler = set().union(*(b.dugmeler for b in self._baglantilar))
        for b in self._baglantilar:
            b.tuslar.clear()
            b.dugmeler.clear()
        if tuslar or dugmeler:
            satirlar = self._birakma_satirlari(tuslar, dugmeler)
            self._yaz(satirlar)
            gunluk(f"girdi merkezi | DUR: bırakıldı | {' ; '.join(satirlar)}")

    # ---------------------------------------------------------------- bağlantılar
    def _kabul(self):
        while not self._durdu.is_set():
            try:
                s, _adres = self._dinleyici.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                pid, uid, _gid = es_kimligi(s)
            except OSError:
                s.close()
                continue
            if uid != self.izinli_uid:
                gunluk(f"girdi merkezi | REDDEDİLDİ: başka kullanıcı (uid {uid}, pid {pid})")
                s.close()
                continue
            with self._kilit:
                if len(self._baglantilar) >= AZAMI_BAGLANTI:
                    s.close()
                    continue
                b = _Baglanti(s, pid)
                self._baglantilar.add(b)
            s.settimeout(None)
            threading.Thread(target=self._hizmet, args=(b,), daemon=True).start()

    def _hizmet(self, b: _Baglanti):
        f = b.sock.makefile("rb")
        try:
            if self._el_sik(b, f):
                while not self._durdu.is_set():
                    satir = f.readline(AZAMI_UZUNLUK + 2)
                    if not satir:
                        break
                    t = satir.decode("utf-8", "replace").rstrip("\n").split(" ")
                    if t[0] == "parti" and len(t) == 2 and t[1].isdigit() and 0 < int(t[1]) <= AZAMI_SATIR:
                        govde = []
                        for _i in range(int(t[1])):
                            x = f.readline(AZAMI_UZUNLUK + 2)
                            if not x.endswith(b"\n"):
                                raise ConnectionError
                            govde.append(x[:-1].decode("utf-8", "replace"))
                        self._yanit(b, self._parti(b, govde))
                    elif t == ["bekle"]:
                        self._yanit(b, self._bekle(b))
                    else:
                        self._yanit(b, f"hata 1 {_('bilinmeyen istek')}")
                        break
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            with self._kilit:
                if (b is self._sahip and b.nesil == self._nesil
                        and self._mesgul_son - time.monotonic() > KOPMA_PAY):
                    # istemci girdisi bitmeden koptu (öldü): kalan girdi denetimsiz sürmesin
                    gunluk(f"girdi merkezi | bağlantı koptu (pid {b.pid}), kuyruk düşürüldü")
                    self._dotool_birak()
                else:
                    self._baglanti_birak(b)
                self._baglantilar.discard(b)
            try:
                f.close()
                b.sock.close()
            except OSError:
                pass

    @staticmethod
    def _yanit(b, metin):
        b.sock.sendall((metin + "\n").encode())

    def _el_sik(self, b, f) -> bool:
        t = f.readline(512).decode("utf-8", "replace").split()
        if len(t) != 4 or t[0] != "merhaba" or t[1] != str(SURUM) or not _DUZEN_RE.fullmatch(t[2]) \
                or not (t[3] == "-" or _DUZEN_RE.fullmatch(t[3])):
            self._yanit(b, f"hata 1 {_('el sıkışma geçersiz')}")
            return False
        duzen = (t[2], "" if t[3] == "-" else t[3])
        for _deneme in range(2):
            if not self._hazir_bekle():
                self._yanit(b, f"hata 9 {self._hata or _('dotool hazır değil')}")
                return False
            with self._kilit:
                if self._p is None:
                    continue
                if duzen != self._duzen:
                    diger = any(x is not b and x.nesil is not None for x in self._baglantilar)
                    if diger or self._mesgul_son > time.monotonic():
                        self._yanit(b, f"hata 9 {_('klavye düzeni farklı ve merkez kullanımda')}")
                        return False
                    gunluk(f"girdi merkezi | klavye düzeni {self._duzen} → {duzen}: dotool yeniden başlıyor")
                    self._duzen = duzen
                    self._dotool_birak()
                    continue
                b.nesil = self._nesil
                self._yanit(b, f"tamam {SURUM} {self._p.pid}")
                return True
        self._yanit(b, f"hata 9 {_('dotool hazır değil')}")
        return False

    def _hazir_bekle(self) -> bool:
        from .arka_uc import kde
        bitis = time.monotonic() + kde.DOTOOL_AZAMI + 1.5
        while time.monotonic() < bitis and not self._durdu.is_set():
            if self._hata is not None:
                return False
            if self._hazir.wait(0.02):
                return True
        return self._hazir.is_set()

    def _parti(self, b: _Baglanti, satirlar: list[str]) -> str:
        if not all(satir_gecerli(s) for s in satirlar):
            yanlis = next(s for s in satirlar if not satir_gecerli(s))
            return f"hata 1 {_('geçersiz girdi satırı')}: {yanlis[:60]!r}"
        basma = any(basma_mi(s) for s in satirlar)
        with self._kilit:
            if self._p is None or b.nesil != self._nesil or not self._hazir.is_set():
                return f"hata 9 {_('dotool yeniden başladı; girdi gönderilmedi')}"
            if basma and os.path.exists(hata.dur_dosyasi()):  # hata.dur_denetle() ile aynı ölçüt, yazımdan HEMEN önce
                return "hata 13 DUR"
            simdi = time.monotonic()
            if basma and self._sahip is not b and self._mesgul_son - simdi > MESGUL_PAY:
                return f"mesgul {self._mesgul_son - simdi:.3f}"
            onek = [f"{k} {b.ayar[k]}" for k in AYARLAR if b.ayar[k] != self._dotool_ayar[k]]
            if not self._yaz(onek + satirlar):
                return f"hata 9 {_('dotool beklenmedik şekilde kapandı')}"
            for k in AYARLAR:
                self._dotool_ayar[k] = b.ayar[k]
            for s in satirlar:
                fiil, arg = _ayir(s)
                if fiil in AYARLAR:
                    b.ayar[fiil] = self._dotool_ayar[fiil] = int(arg)
                elif fiil == "keydown":
                    b.tuslar |= _tuslar(arg)
                elif fiil == "keyup":
                    b.tuslar -= _tuslar(arg)
                elif fiil == "buttondown":
                    b.dugmeler.add(arg.strip())
                elif fiil == "buttonup":
                    b.dugmeler.discard(arg.strip())
            sure = girdi_suresi(onek + satirlar, b.ayar)
            self._mesgul_son = max(self._mesgul_son, simdi) + sure
            if basma:
                self._sahip = b
            return "tamam"

    def _bekle(self, b: _Baglanti) -> str:
        """Bu bağlantının kuyruktaki girdisi bitene dek bekle (istemci kapanmadan önce: komut girdi bitince döner)."""
        with self._kilit:
            son = self._mesgul_son if self._sahip is b else 0.0
        kalan = son - time.monotonic()
        if kalan > 0:
            self._durdu.wait(min(kalan, 120.0))
        time.sleep(0.01)  # son satırın uyarısı okunsun
        with self._kilit:
            u, b.uyarilar = b.uyarilar, []
        return "\n".join([f"tamam {len(u)}", *u])


def _sonlandir(p, nazik=False):
    try:
        p.stdin.close()
    except (OSError, ValueError):
        pass
    if p.poll() is None:
        if nazik:
            try:
                p.wait(timeout=0.3)
            except Exception:  # noqa: BLE001 - subprocess.TimeoutExpired
                pass
        if p.poll() is None:
            p.kill()
    try:
        p.wait(timeout=2)
    except Exception:  # noqa: BLE001
        pass


def _canli(yol: str) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(yol)
        return True
    except OSError:
        return False
    finally:
        s.close()


# ---------------------------------------------------------------- istemci (kde.Girdi kullanır)

class MerkezHatasi(Exception):
    def __init__(self, kod: int, mesaj: str):
        super().__init__(mesaj)
        self.kod, self.mesaj = kod, mesaj


class Mesgul(Exception):
    """Başka bir bağlantının girdisi kuyrukta: denetimleri yeniden yapıp tekrar dene."""

    def __init__(self, sn: float):
        super().__init__(sn)
        self.sn = sn


class Istemci:
    def __init__(self, sock: socket.socket, pid: int):
        self.sock, self.sunucu_pid = sock, pid
        self.f = sock.makefile("rb")
        self.dotool_pid = None

    @classmethod
    def baglan(cls, duzen: tuple[str, str], yol: str | None = None) -> "Istemci | None":
        """Merkez varsa bağlan ve el sıkışmayı GÖNDER (yanıt hazir_bekle'de okunur: kurulumla örtüşsün). Soket bu
        kullanıcının ve 0600 değilse ya da öbür uç başka kullanıcıysa None (çağıran kendi dotool'una düşer)."""
        yol = yol or soket_yolu()
        try:
            st = os.lstat(yol)
        except OSError:
            return None
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            return None
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(yol)
            pid, uid, _gid = es_kimligi(s)
            if uid != os.getuid():
                s.close()
                return None
            s.sendall(f"merhaba {SURUM} {duzen[0]} {duzen[1] or '-'}\n".encode())
        except OSError:
            s.close()
            return None
        return cls(s, pid)

    def _oku(self, sure: float) -> str:
        try:
            self.sock.settimeout(sure)
            satir = self.f.readline(AZAMI_UZUNLUK + 2)
        except (OSError, ValueError):
            raise MerkezHatasi(9, _("girdi merkezi yanıt vermedi")) from None
        if not satir:
            raise MerkezHatasi(9, _("girdi merkezi bağlantısı koptu"))
        return satir.decode("utf-8", "replace").rstrip("\n")

    @staticmethod
    def _hata(yanit: str):
        t = yanit.split(" ", 2)
        if t[0] == "hata" and len(t) >= 2 and t[1].isdigit():
            return MerkezHatasi(int(t[1]), t[2] if len(t) > 2 else "")
        return MerkezHatasi(9, _("girdi merkezi anlaşılmayan yanıt verdi: {yanit}").format(yanit=yanit[:80]))

    def hazir_bekle(self, sure: float) -> None:
        y = self._oku(sure)
        t = y.split()
        if len(t) < 3 or t[0] != "tamam" or t[1] != str(SURUM):
            raise self._hata(y)
        self.dotool_pid = int(t[2]) if t[2].isdigit() else None

    def gonder(self, satirlar) -> None:
        satirlar = [x for s in satirlar for x in s.split("\n")]  # kendi dotool yolundaki gibi: \n satır böler
        veri = f"parti {len(satirlar)}\n" + "".join(s + "\n" for s in satirlar)
        try:
            self.sock.sendall(veri.encode())
        except OSError:
            raise MerkezHatasi(9, _("girdi merkezi bağlantısı koptu")) from None
        y = self._oku(ISTEMCI_ZAMAN)
        if y == "tamam":
            return
        if y.startswith("mesgul "):
            try:
                raise Mesgul(float(y.split()[1]))
            except ValueError:
                raise Mesgul(0.01) from None
        raise self._hata(y)

    def bekle(self, sure: float = 15.0) -> list[str]:
        """Gönderilen girdi bitene dek bekle; dotool uyarılarını döndür."""
        try:
            self.sock.sendall(b"bekle\n")
            t = self._oku(sure).split()
            n = int(t[1]) if len(t) == 2 and t[0] == "tamam" and t[1].isdigit() else 0
            return [self._oku(1.0) for _i in range(n)]
        except (MerkezHatasi, OSError):
            return []

    def kapat(self) -> None:
        try:
            self.f.close()
            self.sock.close()
        except OSError:
            pass

