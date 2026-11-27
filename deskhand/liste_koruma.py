"""Yasak listesi ve uygulama erişim seviyeleri: PANEL YETKİLİ KAYNAKTIR (docs/ARCHITECTURE.md §4 "Ayar dosyaları").

Tehdit: ajan kendi araçlarıyla (uçbirimde rm, dosya yöneticisinde silme, düzenleyicide boşaltma) yasak-pencereler.txt
ya da uygulama-seviyeleri.txt dosyasını silip/değiştirip kısıtları kaldırabilirdi (dosya yoksa = kısıt yok).

- Panel açılışta dosyaları okur ve BELLEKTE tutar (`Koruyucu`). Dosyayı yalnız panelin kendi Kaydet'i yazar
  (`kaydet`). Dosya dışarıdan değişir ya da silinirse panel kendi içeriğini KORUR, dosyayı geri yazar ve uyarır
  (`denetle`; panelde QFileSystemWatcher + yoklama).
- CLI ve MCP içeriği panelden onay kanalıyla alır (`liste yasak|seviye|onaylar|kimlik|kalici|kalici_sure`; onay.py).

AUTHENTICATED PANEL MARK (H3 second security review, Y1 class + Y5). Every panel-authoritative value — yasak, seviye,
onaylar (KAPSAM), hesap_oturumlari (KIMLIK), [oturum] kalici (KALICI), [oturum] kalici_sure_gun (SURE) — has a mark
STATE_DIR/liste-<tur>.isaret {surum, sha256, icerik, var, zaman, hmac}. hmac = HMAC-SHA256(key, ["deskhand-panel-
isaret", 2, tur, icerik]); the 256-bit key is its own Secret Service item (application=deskhand, purpose=panel-isaret,
label "Deskhand panel mark key"), created and used for signing ONLY by the panel (`_isaret_yaz`). A plain sha256 mark
(the old format) or any mark that does not verify is NOT the panel's word.

Rule, per value read from disk while the panel was closed (panel start) or from the file (panel closed, yasak/seviye):
  a) TIGHTENING relative to the panel's verified value is accepted without a mark (removing is never asked);
  b) LOOSENING — or a change whose direction cannot be decided — is applied only with a valid HMAC mark; otherwise it
     is NOT applied (closed-fail): the panel keeps/restores its last verified value and asks the user once
     (`sor(tur, aciklama)` / `onayla(siteler)`, a Qt dialog in gui/panel.py, default No); panel closed → Dur 10;
  c) no key / locked wallet / no Secret Service: nothing verifies, so (b) applies to every loosening; there is NO
     fallback to sha256 or to an unsigned mark;
  d) migration: values under an old sha256 mark are asked once at the first start; Yes → signed;
  e) one question per (setting, file content) per panel session; a file that cannot be written is reported once
     (no dialog loop, review C6).
With no verified value (no mark, or one that does not verify) the reference is the strictest default (TABAN):
onaylar=hepsi, hesap_oturumlari=∅, kalici=∅, kalici_sure_gun=30. yasak/seviye have no such floor: the very first start
(no mark AND no key in the wallet) takes the file; later an unverifiable mark → the stricter of file and mark content,
and the user is asked.

Direction per type (siki_mi):
  yasak       tighter = every pattern line of the reference is still there (adding lines tightens)
  seviye      tighter = every rule of the reference is still there with the same or a lower level (extra rules tighten)
  onaylar     tighter = 'hepsi' (or unchanged); 'kart' is loosening
  kimlik      tighter = a subset of the reference providers
  kalici      tighter = a subset of the reference sites
  kalici_sure tighter = fewer or equal days

Threat model (honest): a process that only writes files (the agent's shell, an editor, a prompt-injected agent) cannot
loosen these settings without the user's Yes in the panel. Code running as the same user that DELIBERATELY reads the
key from the Secret Service (secret-tool / secretstorage: KDE Wallet has no per-application ACL) can forge a mark: that
is out of scope here (it needs the S1 isolation of the agent shell from the session bus). Deleting every mark while the
wallet is locked looks like a first start for yasak/seviye (the file is taken, visibly).

Qt'siz (CLI/MCP hafif kalsın); panel tarafının Qt izleyicisi deskhand/gui/panel.py'de.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time

from . import yollar
from .hata import Dur
from .i18n import N_, _

TURLER = ("yasak", "seviye")
KAPSAM = "onaylar"  # kanal türü + işaret adı (liste-onaylar.isaret); dosya: ayarlar.toml [guvenlik] onaylar
KAPSAMLAR = ("hepsi", "kart")
KIMLIK = "kimlik"  # kanal türü + işaret adı (liste-kimlik.isaret); dosya: ayarlar.toml [guvenlik] hesap_oturumlari
KIMLIK_SAGLAYICILARI = ("microsoft", "google", "edevlet")  # sıra = kanonik yazım sırası (ayarlar.KUME ile aynı)
KALICI = "kalici"  # kanal türü + işaret adı (liste-kalici.isaret); dosya: ayarlar.toml [oturum] kalici (site listesi)
SURE = "kalici_sure"  # kanal türü + işaret adı; dosya: ayarlar.toml [oturum] kalici_sure_gun (review Y5)
SURE_VARSAYILAN = 30
TUM = TURLER + (KAPSAM, KIMLIK, KALICI, SURE)
TABAN = {KAPSAM: "hepsi", KIMLIK: "", KALICI: "", SURE: str(SURE_VARSAYILAN)}  # strictest default (no verified value)
ISARET_SURUM = 2
ONBELLEK_SN = 0.3  # istemci: panelden alınan listeyi bu kadar süre yeniden sormaz (pencere listesinde her pencere
#                   için denetim); panelin Kaydet'i en geç bu kadar sonra geçerli. Dosya yolu önbelleksiz.
MESAJ_KAYIP = N_("Deskhand ayar dosyası ({dosya}) kayıp ya da panel dışında değişti; güvenli tarafta hiçbir girdi "
                 "gönderilmez; Deskhand paneli açın (panel kendi kaydını geri yükler).")
MESAJ_DOGRULANAMADI = N_("Deskhand ayar dosyasının ({dosya}) panel imzası doğrulanamadı (cüzdan kilitli/yok ya da "
                         "imza geçersiz); güvenli tarafta hiçbir girdi gönderilmez; Deskhand paneli açın.")
_AYAR_ADI = {"yasak": N_("yasak pencereler"), "seviye": N_("uygulama erişim seviyeleri"), KAPSAM: N_("onay kapsamı"),
             KIMLIK: N_("hesap oturumu izni"), KALICI: N_("kalıcı oturum siteleri"),
             SURE: N_("kalıcı oturum süresi (gün)")}


def dosya(tur: str) -> str:
    return yollar.yasak_dosya() if tur == "yasak" else yollar.seviye_dosya()


def isaret_yolu(tur: str) -> str:
    return os.path.join(yollar.state_dir(), f"liste-{tur}.isaret")


def _ozet(metin: str | None) -> str:
    return "yok" if metin is None else hashlib.sha256(metin.encode("utf-8", "surrogateescape")).hexdigest()


def _oku(yol: str) -> str | None:
    try:
        with open(yol, encoding="utf-8", errors="surrogateescape") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def isaret_oku(tur: str) -> dict | None:
    try:
        with open(isaret_yolu(tur)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("sha256"), str):
        return None
    return d


def _yaz_atomik(yol: str, metin: str) -> None:
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = f"{yol}.{os.getpid()}.{threading.get_ident()}"
    with open(gecici, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(metin)
    os.replace(gecici, yol)


# ---------------------------------------------------------------- the mark key (Secret Service, its own item)

_ANAHTARLIK = None
_ANAHTAR: bytes | None = None
_ANAHTAR_DENEME = 0.0       # monotonic time of the last failed read (client: not asked again for 2 s)
_ANAHTAR_YOK_KESIN = False  # the key ring answered: there is no key (the panel never signed anything)
_ANAHTAR_KILIT = threading.Lock()


def _anahtarlik():
    global _ANAHTARLIK
    if _ANAHTARLIK is None:
        from .oturum.kalici import GizliServis

        class _IsaretAnahtari(GizliServis):
            ETIKET = "Deskhand panel mark key"
            OZNITELIK = {"application": "deskhand", "purpose": "panel-isaret"}
        _ANAHTARLIK = _IsaretAnahtari()
    return _ANAHTARLIK


def isaret_anahtarlik_ayarla(nesne) -> None:
    """Replace the mark key ring (tests inject a fake: anahtar(olustur: bool) -> bytes, raises kalici.AnahtarYok)."""
    global _ANAHTARLIK
    _ANAHTARLIK = nesne
    _anahtar_unut()


def _anahtar_unut() -> None:
    global _ANAHTAR, _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN
    with _ANAHTAR_KILIT:
        _ANAHTAR, _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN = None, 0.0, False


def _isaret_anahtari(olustur: bool = False) -> bytes | None:
    """The mark key (cached in memory for the process), or None (no key / locked wallet / no Secret Service)."""
    global _ANAHTAR, _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN
    with _ANAHTAR_KILIT:
        if _ANAHTAR is not None:
            return _ANAHTAR
        if not olustur and time.monotonic() - _ANAHTAR_DENEME < 2.0 and _ANAHTAR_DENEME:
            return None
        from .oturum.kalici import AnahtarYok
        try:
            k = _anahtarlik().anahtar(olustur)
        except AnahtarYok as e:
            _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN = time.monotonic(), bool(e.yok)
            return None
        except Exception:  # noqa: BLE001 - any key ring error: nothing verifies (closed-fail)
            _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN = time.monotonic(), False
            return None
        if not isinstance(k, (bytes, bytearray)) or len(k) != 32:
            _ANAHTAR_DENEME, _ANAHTAR_YOK_KESIN = time.monotonic(), False
            return None
        _ANAHTAR, _ANAHTAR_YOK_KESIN = bytes(k), False
        return _ANAHTAR


def _ilk_kurulum() -> bool:
    """No mark key exists at all (the key ring answered so): the panel never ran with this wallet. A locked or missing
    wallet answers nothing: treated as a first start for yasak/seviye only (documented limit)."""
    return _isaret_anahtari(False) is None


def _imza(k: bytes, tur: str, metin: str | None) -> str:
    veri = json.dumps(["deskhand-panel-isaret", ISARET_SURUM, tur, metin], ensure_ascii=False)
    return hmac.new(k, veri.encode("utf-8", "surrogateescape"), hashlib.sha256).hexdigest()


def _isaret_yaz(tur: str, metin: str | None) -> None:
    """Panel only: the mark of `tur`, signed when the key is available (created on first use)."""
    d = {"surum": ISARET_SURUM, "sha256": _ozet(metin), "icerik": metin, "var": metin is not None,
         "zaman": time.time()}
    k = _isaret_anahtari(True)
    if k is not None:
        d["hmac"] = _imza(k, tur, metin)
    _yaz_atomik(isaret_yolu(tur), json.dumps(d, ensure_ascii=False))
    try:
        os.chmod(isaret_yolu(tur), 0o600)
    except OSError:
        pass


def isaret_dogrula(tur: str) -> tuple[str, str | None]:
    """("yok", None) no mark · ("gecerli", content) the panel's verified value · ("dogrulanamadi", content|None) a
    mark that is not the panel's word (old sha256 format, forged, or no key to check it)."""
    m = isaret_oku(tur)
    if m is None:
        return "yok", None
    icerik = m.get("icerik") if m.get("var", True) else None
    if icerik is not None and not isinstance(icerik, str):
        return "dogrulanamadi", None
    h = m.get("hmac")
    if not isinstance(h, str) or m["sha256"] != _ozet(icerik):
        return "dogrulanamadi", icerik
    k = _isaret_anahtari(False)
    if k is None or not hmac.compare_digest(h, _imza(k, tur, icerik)):
        return "dogrulanamadi", icerik
    return "gecerli", icerik


# ---------------------------------------------------------------- direction (tighter / looser)

def _yasak_desenleri(metin: str | None) -> set[str]:
    return {s.strip() for s in (metin or "").splitlines() if s.strip() and not s.lstrip().startswith("#")}


def _seviye_haritasi(metin: str | None) -> dict[str, int]:
    from .guvenlik import seviye_satiri_coz
    h: dict[str, int] = {}
    for satir in (metin or "").splitlines():
        k = seviye_satiri_coz(satir)
        if k:
            h[k[0]] = min(h.get(k[0], 2), k[1])
    return h


def _sure_sayi(v) -> int:
    try:
        return max(1, min(365, int(v)))
    except (TypeError, ValueError, OverflowError):
        return SURE_VARSAYILAN


def siki_mi(tur: str, yeni: str | None, eski: str | None) -> bool:
    """Is `yeni` as strict as `eski` or stricter? (False when the direction cannot be decided = loosening.)"""
    if tur == "yasak":
        return _yasak_desenleri(eski) <= _yasak_desenleri(yeni)
    if tur == "seviye":
        y = _seviye_haritasi(yeni)
        return all(d in y and y[d] <= s for d, s in _seviye_haritasi(eski).items())
    if tur == KAPSAM:
        return yeni == "hepsi" or yeni == eski
    if tur == KIMLIK:
        return kimlik_ayristir(yeni) <= kimlik_ayristir(eski)
    if tur == KALICI:
        return kalici_ayristir(yeni) <= kalici_ayristir(eski)
    if tur == SURE:
        return _sure_sayi(yeni) <= _sure_sayi(eski)
    return False


def en_siki(tur: str, a: str | None, b: str | None) -> str | None:
    """A value at least as strict as both (used when the panel's own value is unknown)."""
    if siki_mi(tur, a, b):
        return a
    if siki_mi(tur, b, a):
        return b
    if tur in TURLER:  # union of the lines: every pattern / the lowest level of every rule
        return (a or "").rstrip("\n") + "\n" + (b or "")
    if tur == KAPSAM:
        return "hepsi"
    if tur == KIMLIK:
        return kimlik_metni(kimlik_ayristir(a) & kimlik_ayristir(b))
    if tur == KALICI:
        return kalici_metni(kalici_ayristir(a) & kalici_ayristir(b))
    return str(min(_sure_sayi(a), _sure_sayi(b)))


def _dosyadaki(tur: str) -> str | None:
    """The value written on disk, normalised like the panel keeps it."""
    if tur in TURLER:
        return _oku(dosya(tur))
    if tur == KAPSAM:
        return _kapsam_dosyadan()
    if tur == KIMLIK:
        return kimlik_metni(kimlik_ayristir(_kimlik_dosyadan()))
    if tur == KALICI:
        return kalici_metni(kalici_ayristir(_kalici_dosyadan()))
    return str(_sure_dosyadan())


def _kisa(metin: str | None) -> str:
    if metin is None:
        return _("(yok)")
    s = "; ".join(x.strip() for x in metin.splitlines() if x.strip()) or _("(boş)")
    return s if len(s) <= 200 else s[:200] + "…"


# ---------------------------------------------------------------- panel tarafı

class Koruyucu:
    """Panelin yetkili kopyası. uyari(metin) her geri yüklemede çağrılır (panel: günlük + bildirim).
    onayla(siteler) -> bool: kalıcı oturum sitesi sorusu; sor(tur, aciklama) -> bool: diğer ayarların gevşetme
    sorusu (Qt diyaloğu, varsayılan Hayır). None (arayüz yok) = hiçbir zaman onaylanmaz."""

    def __init__(self, uyari=None, onayla=None, sor=None):
        self.uyari = uyari or (lambda m: None)
        self.onayla = onayla
        self.sor = sor
        self._soruyor = False
        self._cevaplar: dict[tuple[str, str | None], bool] = {}  # C6: one question per (setting, file content)
        self._yazilamadi: set[tuple[str, str | None]] = set()
        self._kilit = threading.Lock()
        self.bellek: dict[str, str | None] = {}
        for tur in TUM:
            self._acilis(tur)

    # ---- the question
    def _sor(self, tur: str, yeni: str | None, ref: str | None) -> bool:
        anahtar = (tur, yeni)
        if anahtar in self._cevaplar:
            return self._cevaplar[anahtar]
        if self._soruyor:  # the dialog runs a nested event loop: the poll timer must not ask again meanwhile
            return False
        self._soruyor = True
        try:
            if tur == KALICI and self.onayla is not None:
                siteler = sorted(kalici_ayristir(yeni) - kalici_ayristir(ref)) or sorted(kalici_ayristir(yeni))
                cevap = bool(self.onayla(siteler))
            elif self.sor is not None:
                cevap = bool(self.sor(tur, _("{ayar}: panelin kaydı «{eski}», dosyada «{yeni}»").format(
                    ayar=_(_AYAR_ADI[tur]), eski=_kisa(ref), yeni=_kisa(yeni))))
            else:
                cevap = False
        except Exception:  # noqa: BLE001 - the dialog failed: not approved
            cevap = False
        finally:
            self._soruyor = False
        self._cevaplar[anahtar] = cevap
        return cevap

    # ---- file writes
    def _dosyaya_yaz(self, tur: str, deger: str | None) -> bool:
        """Write the panel's value back to its file (+ signed mark). A failure is reported once per content (C6)."""
        try:
            if tur in TURLER:
                if deger is None:
                    try:
                        os.remove(dosya(tur))
                    except FileNotFoundError:
                        pass
                else:
                    _yaz_atomik(dosya(tur), deger)
            else:
                from . import ayarlar
                bolum, anahtar = {KAPSAM: ("guvenlik", "onaylar"), KIMLIK: ("guvenlik", "hesap_oturumlari"),
                                  KALICI: ("oturum", "kalici"), SURE: ("oturum", "kalici_sure_gun")}[tur]
                ayarlar.ayarla(bolum, anahtar, _sure_sayi(deger) if tur == SURE else deger)
            tamam = True
        except Exception as e:  # noqa: BLE001 - not writable: the authoritative value stays in memory
            tamam = False
            dosyada = _dosyadaki(tur)
            if (tur, dosyada) not in self._yazilamadi:
                self._yazilamadi.add((tur, dosyada))
                self.uyari(_("Ayar dosyası yazılamadı ({hata}); panelin değeri ({ayar}) bellekte geçerli, aynı "
                             "değişiklik bu oturumda yeniden sorulmaz.").format(hata=type(e).__name__,
                                                                               ayar=_(_AYAR_ADI[tur])))
        try:
            _isaret_yaz(tur, deger)
        except OSError:
            pass
        return tamam

    # ---- panel start
    def _acilis(self, tur: str) -> None:
        d = _dosyadaki(tur)
        durum, m = isaret_dogrula(tur)
        if tur in TURLER and d is None and tur == "yasak" and durum == "yok" and _ilk_kurulum():
            from .guvenlik import VARSAYILAN_YASAK
            d = _(VARSAYILAN_YASAK)
            _yaz_atomik(dosya(tur), d)
        if durum == "gecerli":
            if siki_mi(tur, d, m):
                self._kabul(tur, d)
                return
            ref = m
        elif tur in TURLER:
            if durum == "yok" and _ilk_kurulum():
                self._kabul(tur, d)
                return
            ref = en_siki(tur, d, m)
        else:
            if siki_mi(tur, d, TABAN[tur]):
                self._kabul(tur, d)
                return
            ref = en_siki(tur, d, TABAN[tur])
        if self._sor(tur, d, ref):
            self._kabul(tur, d)
            return
        self.bellek[tur] = ref
        if ref != d:
            self._dosyaya_yaz(tur, ref)
        else:
            _isaret_yaz(tur, ref)
        self.uyari(self._ret_iletisi(tur, d, ref))

    def _kabul(self, tur: str, d: str | None) -> None:
        self.bellek[tur] = d
        _isaret_yaz(tur, d)
        if tur == KIMLIK and kimlik_ayristir(d):  # visible on every start
            from .oturum.politika import KIMLIK_ADLARI
            self.uyari(_("Hesap oturumu izni açık: {saglayici}. Görünmez masaüstündeki tarayıcı bu hesaplara girişli "
                         "açılır. Kapatmak için panelde Ayarlar → Hesap oturumları.").format(
                             saglayici=", ".join(KIMLIK_ADLARI.get(x, x) for x in sorted(kimlik_ayristir(d)))))

    @staticmethod
    def _ret_iletisi(tur: str, d: str | None, ref: str | None) -> str:
        if tur in TURLER:
            return _("{dosya} panel kapalıyken silinmiş ya da değiştirilmiş; panelin son kaydı geri yüklendi "
                     "(değişiklikleri Ayarlar'dan yapın).").format(dosya=dosya(tur))
        if tur == KAPSAM:
            return _("Onay kapsamı 'kart' (Yalnız kartla ödeme) panel dışında yazılmış; geçerli sayılmadı, tüm "
                     "onaylar açık kaldı ('hepsi'). Değiştirmek için panelde Ayarlar → Onay soruları.")
        if tur == KIMLIK:
            return _("Hesap oturumu izni ({saglayici}) panel dışında açılmış; geçerli sayılmadı, kimlik çerezleri "
                     "süzülmeye devam ediyor. Açmak için panelde Ayarlar → Hesap oturumları.").format(
                         saglayici=", ".join(sorted(kimlik_ayristir(d) - kimlik_ayristir(ref))))
        if tur == KALICI:
            return _("Kalıcı oturum sitesi ({siteler}) panel dışında eklenmiş ve onaylanmadı; kullanılmıyor.").format(
                siteler=", ".join(sorted(kalici_ayristir(d) - kalici_ayristir(ref))))
        return _("Kalıcı oturum süresi ({yeni} gün) panel dışında yazılmış ve onaylanmadı; {eski} gün "
                 "kullanılıyor.").format(yeni=d, eski=ref)

    # ---- panel Ayarlar (the single authoritative writer)
    def kapsam_kaydet(self, deger: str) -> None:
        """Panelin Ayarlar'ı: onay kapsamı (tek yetkili yazar)."""
        if deger not in KAPSAMLAR:
            raise ValueError(deger)
        with self._kilit:
            self.bellek[KAPSAM] = deger
            self._dosyaya_yaz(KAPSAM, deger)

    def kimlik_kaydet(self, deger: str) -> None:
        """Panelin Ayarlar'ı: hesap oturumu izni (tek yetkili yazar; açarken onay diyaloğu gui'de)."""
        k = kimlik_ayristir(deger, kati=True)
        with self._kilit:
            self.bellek[KIMLIK] = kimlik_metni(k)
            self._dosyaya_yaz(KIMLIK, self.bellek[KIMLIK])

    def kalici_kaydet(self, deger: str) -> None:
        """Panel (user-approved): the persistent-session site list (single authoritative writer)."""
        k = kalici_ayristir(deger, kati=True)
        with self._kilit:
            self.bellek[KALICI] = kalici_metni(k)
            self._dosyaya_yaz(KALICI, self.bellek[KALICI])

    def sure_kaydet(self, gun: int) -> None:
        """Panel (user-approved): [oturum] kalici_sure_gun."""
        with self._kilit:
            self.bellek[SURE] = str(_sure_sayi(gun))
            self._dosyaya_yaz(SURE, self.bellek[SURE])

    def _tek_yonlu_denetle(self, tur: str) -> list[str]:
        """File vs memory for a one-way setting (kalici, kalici_sure): tightening is accepted; loosening is asked
        (outside the lock: the dialog must not block the channel that serves the lists)."""
        if self._soruyor:
            return []
        dosyada = _dosyadaki(tur)
        with self._kilit:
            bellekte = self.bellek.get(tur)
        if dosyada == bellekte:
            return []
        if siki_mi(tur, dosyada, bellekte):
            with self._kilit:
                self.bellek[tur] = dosyada
                _isaret_yaz(tur, dosyada)
            return [_("Kalıcı oturum listesinden ayar dosyasında site çıkarıldı; kabul edildi.") if tur == KALICI else
                    _("Kalıcı oturum süresi ayar dosyasında kısaltıldı; kabul edildi.")]
        tekrar = (tur, dosyada) in self._cevaplar
        if self._sor(tur, dosyada, bellekte):
            with self._kilit:
                self.bellek[tur] = dosyada
                self._dosyaya_yaz(tur, dosyada)
            return []
        with self._kilit:
            self._dosyaya_yaz(tur, bellekte)
        if tekrar:
            return []  # C6: already refused and reported in this session
        if tur == KALICI:
            return [_("Kalıcı oturum listesine panel dışında site eklenmek istendi ({siteler}); onaylanmadı, panelin "
                      "listesi korundu ve dosya geri yazıldı.").format(
                          siteler=", ".join(sorted(kalici_ayristir(dosyada) - kalici_ayristir(bellekte))))]
        return [self._ret_iletisi(tur, dosyada, bellekte)]

    def _dosyaya(self, tur: str) -> None:
        self._dosyaya_yaz(tur, self.bellek.get(tur))

    def metin(self, tur: str) -> str | None:
        with self._kilit:
            return self.bellek.get(tur)

    def kaydet(self, tur: str, metin: str) -> None:
        """Panelin Kaydet'i: bellek + dosya + işaret (tek yetkili yazar)."""
        with self._kilit:
            self.bellek[tur] = metin
            self._dosyaya(tur)

    def denetle(self) -> list[str]:
        """Dosyalar bellekle aynı mı? Değilse (silindi/değişti) bellekteki içerik geri yazılır. → uyarı metinleri."""
        uyarilar = []
        with self._kilit:
            for tur in TURLER:
                if _oku(dosya(tur)) != self.bellek.get(tur):
                    self._dosyaya(tur)
                    uyarilar.append(_("{dosya} panel dışında silindi ya da değiştirildi; panelin kaydı korundu ve dosya "
                                      "geri yazıldı (değişiklikleri Ayarlar'dan yapın).").format(dosya=dosya(tur)))
            dosyada = _kapsam_dosyadan()
            if dosyada == "hepsi" and self.bellek.get(KAPSAM) != "hepsi":
                # dosyada hepsi / dosya ya da anahtar silindi: daha SIKI taraf, kabul (gevşetme değil)
                self.bellek[KAPSAM] = "hepsi"
                _isaret_yaz(KAPSAM, "hepsi")
                uyarilar.append(_("Onay kapsamı ayar dosyasında panel dışında 'hepsi' yapıldı ya da silindi; tüm "
                                  "onaylar yeniden açık."))
            elif dosyada != self.bellek.get(KAPSAM):
                self._dosyaya(KAPSAM)
                uyarilar.append(_("Onay kapsamı ayar dosyasında panel dışında değiştirildi; panelin değeri ('{deger}') "
                                  "korundu ve dosya geri yazıldı (değişiklikleri Ayarlar'dan yapın).").format(
                                      deger=self.bellek.get(KAPSAM)))
            dosyada_k = kimlik_ayristir(_kimlik_dosyadan())
            bellekte_k = kimlik_ayristir(self.bellek.get(KIMLIK))
            if dosyada_k != bellekte_k:
                if dosyada_k < bellekte_k:  # dosyadan kapatıldı / dosya silindi: SIKI taraf, kabul
                    self.bellek[KIMLIK] = kimlik_metni(dosyada_k)
                    _isaret_yaz(KIMLIK, self.bellek[KIMLIK])
                    uyarilar.append(_("Hesap oturumu izni ayar dosyasında panel dışında kapatıldı ya da silindi; "
                                      "kimlik çerezleri yeniden süzülüyor."))
                else:
                    self._dosyaya(KIMLIK)
                    uyarilar.append(_("Hesap oturumu izni ayar dosyasında panel dışında açılmaya çalışıldı; geçerli "
                                      "sayılmadı, panelin değeri korundu ve dosya geri yazıldı (açmak için panelde "
                                      "Ayarlar → Hesap oturumları)."))
        uyarilar += self._tek_yonlu_denetle(KALICI)
        uyarilar += self._tek_yonlu_denetle(SURE)
        for u in uyarilar:
            self.uyari(u)
        return uyarilar


AKTIF: Koruyucu | None = None  # panel sürecinde etkin koruyucu (onay kanalı `liste` isteğini buradan yanıtlar)


def panel_baslat(uyari=None, onayla=None, sor=None) -> Koruyucu:
    global AKTIF
    AKTIF = Koruyucu(uyari, onayla, sor)
    from . import onay
    onay.liste_saglayici = AKTIF.metin
    return AKTIF


def panel_durdur() -> None:
    global AKTIF
    AKTIF = None
    from . import onay
    onay.liste_saglayici = None


def panel_kaydet(tur: str, metin: str) -> None:
    """gui/ayar.py Kaydet: panel koruyucusu varsa onun üzerinden (yoksa dosya + işaret)."""
    if AKTIF is not None:
        AKTIF.kaydet(tur, metin)
    else:
        _yaz_atomik(dosya(tur), metin)
        _isaret_yaz(tur, metin)


def panel_kapsam_kaydet(deger: str) -> None:
    """gui/ayar.py onay kapsamı seçimi: panel koruyucusu varsa onun üzerinden (yoksa dosya + işaret)."""
    if AKTIF is not None:
        AKTIF.kapsam_kaydet(deger)
        return
    if deger not in KAPSAMLAR:
        raise ValueError(deger)
    from . import ayarlar
    ayarlar.ayarla("guvenlik", "onaylar", deger)
    _isaret_yaz(KAPSAM, deger)


def panel_kimlik_kaydet(deger: str) -> None:
    """gui/ayar.py Hesap oturumları: panel koruyucusu varsa onun üzerinden (yoksa dosya + işaret)."""
    if AKTIF is not None:
        AKTIF.kimlik_kaydet(deger)
        return
    metin_ = kimlik_metni(kimlik_ayristir(deger, kati=True))
    from . import ayarlar
    ayarlar.ayarla("guvenlik", "hesap_oturumlari", metin_)
    _isaret_yaz(KIMLIK, metin_)


def kimlik_ayristir(deger, kati: bool = False) -> frozenset:
    """"microsoft,google" → {"microsoft", "google"}. Bilinmeyen ad atılır (kati=True: ValueError)."""
    if not isinstance(deger, str):
        if kati:
            raise ValueError(repr(deger))
        return frozenset()
    parcalar = {p.strip().lower() for p in deger.replace(" ", ",").split(",") if p.strip()}
    if kati and parcalar - set(KIMLIK_SAGLAYICILARI):
        raise ValueError(deger)
    return frozenset(p for p in parcalar if p in KIMLIK_SAGLAYICILARI)


def kimlik_metni(saglayicilar) -> str:
    return ",".join(k for k in KIMLIK_SAGLAYICILARI if k in set(saglayicilar))


def _kimlik_dosyadan() -> str:
    from . import ayarlar
    try:
        d = ayarlar.al("guvenlik", "hesap_oturumlari")
    except Exception:  # noqa: BLE001 - okunamadı: güvenli taraf (izin yok)
        return ""
    return d if isinstance(d, str) else ""


def kimlik_dosyada() -> frozenset:
    """Ayar dosyasında YAZAN (doğrulanmamış) sağlayıcılar: yalnız bilgi (doctor); karar için kimlik_izinleri()."""
    return kimlik_ayristir(_kimlik_dosyadan())


def kimlik_izinleri() -> frozenset:
    """Kullanıcının panelden açtığı hesap oturumu izinleri ({"microsoft", "google"} alt kümesi). Panel sürecinde
    bellekteki yetkili değer; başka süreçte YALNIZ panelin doğrulanmış kanalından (`liste kimlik`). Panel kapalı /
    doğrulanamadı / eski panel / tanınmayan yanıt → boş küme (izin yok). Dosyaya bakılmaz: dosya yazabilen bir süreç
    (ajan) izni açamaz. Görev kipinde izin hiç uygulanmaz (çağıran: oturum/firefox.hazirla)."""
    if AKTIF is not None:
        return kimlik_ayristir(AKTIF.metin(KIMLIK))
    d = _panelden(KIMLIK)
    return kimlik_ayristir(d) if isinstance(d, str) else frozenset()


def panel_kalici_kaydet(deger: str) -> None:
    """Panel (after the user approved): the persistent-session site list (koruyucu if any, else file + mark)."""
    if AKTIF is not None:
        AKTIF.kalici_kaydet(deger)
        return
    metin_ = kalici_metni(kalici_ayristir(deger, kati=True))
    from . import ayarlar
    ayarlar.ayarla("oturum", "kalici", metin_)
    _isaret_yaz(KALICI, metin_)


def kalici_ayristir(deger, kati: bool = False) -> frozenset:
    """"shopier.com, https://x.test/a" → {"shopier.com", "x.test"} (gorev_kipi.site_ayristir rules). Invalid entries
    are dropped (kati=True: ValueError)."""
    if not isinstance(deger, str):
        if kati:
            raise ValueError(repr(deger))
        return frozenset()
    from .gorev_kipi import site_ayristir_ayrintili
    siteler, ret = site_ayristir_ayrintili(deger)
    if kati and ret:
        raise ValueError("; ".join(ret))
    return frozenset(siteler)


def kalici_metni(siteler) -> str:
    return ",".join(sorted(set(siteler)))


def _kalici_dosyadan() -> str:
    """The raw file value (the lenient reader keeps the valid entries; ayarlar.oku)."""
    from . import ayarlar
    try:
        d = ayarlar.al("oturum", "kalici")
    except Exception:  # noqa: BLE001 - unreadable: nothing persistent
        return ""
    return d if isinstance(d, str) else ""


def kalici_dosyada() -> frozenset:
    """Sites WRITTEN in the settings file (not verified): information only (doctor); decisions use kalici_siteleri()."""
    return kalici_ayristir(_kalici_dosyadan())


def kalici_siteleri() -> frozenset:
    """The persistent-background-session sites the user approved in the panel. Panel process: its memory; any other
    process ONLY through the panel's verified channel (`liste kalici`). Panel closed / channel not verified / old panel
    → empty (nothing persistent). The file is not read: a process that can write it (an agent) cannot add a site."""
    if AKTIF is not None:
        return kalici_ayristir(AKTIF.metin(KALICI))
    d = _panelden(KALICI)
    return kalici_ayristir(d) if isinstance(d, str) else frozenset()


def _sure_dosyadan() -> int:
    from . import ayarlar
    try:
        return _sure_sayi(ayarlar.al("oturum", "kalici_sure_gun"))
    except Exception:  # noqa: BLE001 - unreadable: the default
        return SURE_VARSAYILAN


def kalici_sure_gun() -> int:
    """[oturum] kalici_sure_gun as the panel approved it (review Y5): the panel's value (memory / `liste
    kalici_sure`); a shorter value in the file counts at once (tightening); panel closed / not verified → at most the
    default 30 (and the panel-closed store saves nothing anyway)."""
    dosyada = _sure_dosyadan()
    if AKTIF is not None:
        panelde = AKTIF.metin(SURE)
    else:
        panelde = _panelden(SURE)
    p = _sure_sayi(panelde) if isinstance(panelde, str) and panelde.strip().isdigit() else SURE_VARSAYILAN
    return min(dosyada, p)


def _kapsam_dosyadan() -> str:
    from . import ayarlar
    try:
        d = ayarlar.al("guvenlik", "onaylar")
    except Exception:  # noqa: BLE001 - okunamadı: güvenli taraf
        return "hepsi"
    return d if d in KAPSAMLAR else "hepsi"


def kapsam() -> str:
    """Geçerli onay kapsamı. Panel sürecinde bellekteki yetkili değer; başka süreçte YALNIZ panelin doğrulanmış
    kanalından (`liste onaylar`). Panel kapalı / doğrulanamadı / eski panel / tanınmayan yanıt → "hepsi".
    Dosyaya bakılmaz: dosya yazabilen bir süreç kapsamı gevşetemez. (Önbellek çağıranda: guvenlik.onay_kapsami.)"""
    if AKTIF is not None:
        d = AKTIF.metin(KAPSAM)
        return d if d in KAPSAMLAR else "hepsi"
    d = _panelden(KAPSAM)
    return d if isinstance(d, str) and d in KAPSAMLAR else "hepsi"


# ---------------------------------------------------------------- istemci tarafı (guvenlik)

_ONBELLEK: dict[str, tuple[float, str | None]] = {}
_ONBELLEK_KILIT = threading.Lock()


def metin(tur: str, olustur: bool = True) -> str | None:
    """Geçerli liste metni: panel açıksa panelden (bellekteki yetkili kopya), kapalıysa dosyadan + işaret denetimi.
    → metin | None (seviye dosyası yok = kısıt yok). Kayıp/değişmiş işaretli dosyada Dur 10. olustur=False: ilk
    kurulumda (işaret yok, dosya yok) varsayılan yasak listesi DÖNER ama dosya yazılmaz (salt okuyan durum yolları)."""
    if AKTIF is not None:
        return AKTIF.metin(tur)
    simdi = time.monotonic()
    with _ONBELLEK_KILIT:
        o = _ONBELLEK.get(tur)
        if o is not None and simdi - o[0] < ONBELLEK_SN:
            return o[1]
    sonuc = _panelden(tur)
    if sonuc is _YOK:
        return _dosyadan(tur, olustur)  # dosya yolu önbelleksiz: elle/panelden yazılan değişiklik hemen geçerli
    with _ONBELLEK_KILIT:
        _ONBELLEK[tur] = (time.monotonic(), sonuc)
    return sonuc


def onbellek_sil() -> None:
    with _ONBELLEK_KILIT:
        _ONBELLEK.clear()


_YOK = object()


def _panelden(tur: str):
    """Panel açık ve kanalı doğrulanıyorsa panelin içeriği; değilse _YOK."""
    from . import onay
    try:
        return onay.liste_iste(tur)
    except Exception:  # noqa: BLE001 - panel yok / doğrulanamadı / eski panel: dosya yolu (işaret denetimli)
        return _YOK


def _dosyadan(tur: str, olustur: bool = True) -> str | None:
    """Panel closed: the file, only as strict as the panel's VERIFIED last value (HMAC mark) or stricter. A mark that
    does not verify (old sha256 / forged / locked wallet) or a missing mark once the panel has a key → Dur 10."""
    yol = dosya(tur)
    mevcut = _oku(yol)
    durum, m = isaret_dogrula(tur)
    if durum == "gecerli":
        if not siki_mi(tur, mevcut, m):
            raise Dur(10, _(MESAJ_KAYIP).format(dosya=yol))
        return mevcut
    if durum == "dogrulanamadi":
        raise Dur(10, _(MESAJ_KAYIP if (isaret_oku(tur) or {}).get("sha256") != _ozet(mevcut) else
                        MESAJ_DOGRULANAMADI).format(dosya=yol))
    if not _ilk_kurulum():
        raise Dur(10, _(MESAJ_KAYIP).format(dosya=yol))  # the panel signed before: a missing mark was deleted
    if mevcut is None and tur == "yasak":  # ilk kurulum: eski davranış
        from .guvenlik import VARSAYILAN_YASAK
        mevcut = _(VARSAYILAN_YASAK)
        if olustur:
            try:
                _yaz_atomik(yol, mevcut)
            except OSError:
                pass
    return mevcut
