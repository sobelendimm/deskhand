"""Yasak listesi ve uygulama erişim seviyeleri: PANEL YETKİLİ KAYNAKTIR (docs/ARCHITECTURE.md §4 "Ayar dosyaları").

Tehdit: ajan kendi araçlarıyla (uçbirimde rm, dosya yöneticisinde silme, düzenleyicide boşaltma) yasak-pencereler.txt
ya da uygulama-seviyeleri.txt dosyasını silip/değiştirip kısıtları kaldırabilirdi (dosya yoksa = kısıt yok).

- Panel açılışta dosyaları okur ve BELLEKTE tutar (`Koruyucu`). Dosyayı yalnız panelin kendi Kaydet'i yazar
  (`kaydet`). Dosya dışarıdan değişir ya da silinirse panel kendi içeriğini KORUR, dosyayı geri yazar ve uyarır
  (`denetle`; panelde QFileSystemWatcher + yoklama).
- CLI ve MCP içeriği panelden onay kanalıyla alır (`liste yasak|seviye|onaylar|kimlik|kalici|kalici_sure`; onay.py).

WALLET-ANCHORED PANEL STATE (H3 second security review, Y1 class + Y5, and the follow-up scan). Every panel-
authoritative value — yasak, seviye, onaylar (KAPSAM), hesap_oturumlari (KIMLIK), [oturum] kalici (KALICI),
[oturum] kalici_sure_gun (SURE) — has its last APPROVED value in ONE Secret Service item (application=deskhand,
purpose=panel-isaret, label "Deskhand panel settings": {anahtar, sayac{tur}, son{tur}}), written ONLY by the panel
(`_isaret_yaz`; the counter of a setting grows when its value changes). The mark file STATE_DIR/liste-<tur>.isaret
carries HMAC-SHA256(anahtar, ["deskhand-panel-isaret", 3, tur, sayac, icerik]); it is valid only when the HMAC is right
AND its counter equals the item's (an older signed mark put back = replay → not valid). Decisions take the reference
from the item (`onayli_deger`), never from a file: a forged file + mark cannot replace the approved value.

Rule, per value read from disk while the panel was closed (panel start) or from the file (panel closed, yasak/seviye):
  a) TIGHTENING relative to the approved value is accepted without a question (removing is never asked);
  b) LOOSENING — or a change whose direction cannot be decided — is NOT applied (closed-fail): the panel keeps/restores
     the approved value and asks the user once (`sor(tur, aciklama)` / `onayla(siteler)`, a Qt dialog in gui/panel.py,
     default No); panel closed → Dur 10 (yasak/seviye);
  c) no signed state (first start, locked wallet, no Secret Service, any error): only the defaults (TABAN: onaylar=hepsi,
     hesap_oturumlari=∅, kalici=∅, kalici_sure_gun=30) and tightenings apply; every loosening is asked; one visible
     warning per panel start; no fallback to sha256 or to an unsigned mark, no Dur 10 loop.
     yasak/seviye (their default is "no rule", so "tighter than the default" proves nothing): a file is used without a
     question ONLY on a first start (the key ring answered "no item" AND no mark). Otherwise (locked wallet, no Secret
     Service, marks deleted or forged) ONE combined question shows the file contents (default No; review INC3 B1).
     Yes → applied, signed as soon as the wallet can be read. No / no dialog → the lists are "not verified": the
     channel answers `dogrulanamadi` and clients stop with Dur 10 (visible reason); when the wallet can be read again
     the panel restores the signed value and checks again (`denetle`);
  d) migration: values under an old sha256 mark have no approved value yet → (c): loosenings are asked once, Yes → signed;
  e) only a No is remembered, per (setting, file content, approved value) and panel session: no dialog loop (review
     C6). A Yes is never replayed: the reference is the approved state (the user's Yes and Settings edits update it),
     so content the user removed and an agent writes back is asked again (review INC3 B2). A file that cannot be
     written is reported once.

Direction per type (siki_mi):
  yasak       tighter = every pattern line of the reference is still there (adding lines tightens)
  seviye      tighter = every rule of the reference is still there with the same or a lower level (extra rules tighten)
  onaylar     tighter = 'hepsi' (or unchanged); 'kart' is loosening
  kimlik      tighter = a subset of the reference providers
  kalici      tighter = a subset of the reference sites
  kalici_sure tighter = fewer or equal days

Threat model (honest): a process that only writes files (the agent's shell, an editor, a prompt-injected agent) cannot
loosen these settings without the user's Yes in the panel. Code running as the same user that DELIBERATELY reads or
changes the Secret Service item (secret-tool / secretstorage: KDE Wallet has no per-application ACL) is out of scope (it
needs the S1 isolation of the agent shell from the session bus); deleting the item while the wallet is unlocked looks
like a first start (c).

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
ISARET_SURUM = 3
ONBELLEK_SN = 0.3  # istemci: panelden alınan listeyi bu kadar süre yeniden sormaz (pencere listesinde her pencere
#                   için denetim); panelin Kaydet'i en geç bu kadar sonra geçerli. Dosya yolu önbelleksiz.
MESAJ_DOGRULANAMADI = N_("Deskhand ayar dosyasının ({dosya}) önceki onaylı değeri doğrulanamadı (cüzdan kilitli/yok); "
                         "güvenli tarafta hiçbir girdi gönderilmez; Deskhand paneli açın.")
MESAJ_PANEL_DOGRULANAMADI = N_("Deskhand paneli {tur} listesini doğrulayamadı (cüzdan okunamıyor; listeler "
                               "doğrulanamadı); güvenli tarafta hiçbir girdi gönderilmez. Cüzdanı açın ya da listeyi "
                               "panelin Ayarlar'ından kaydedin.")
MESAJ_KAYIP = N_("Deskhand ayar dosyası ({dosya}) kayıp ya da panel dışında değişti; güvenli tarafta hiçbir girdi "
                 "gönderilmez; Deskhand paneli açın (panel kendi kaydını geri yükler).")
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


# ---------------------------------------------------------------- the panel's signed state (Secret Service item)

_KASA = None                     # oku() -> bytes | None (None = no item yet), yaz(bytes); errors: kalici.AnahtarYok
_DURUM: dict | None = None       # cached {"anahtar": bytes, "sayac": {tur: int}, "son": {tur: str | None}}
_DURUM_ZAMAN = 0.0
_DURUM_NEDEN: str | None = None  # why there is no signed state (None = it worked, or no item was ever written)
_DURUM_YOK_KESIN = False         # the key ring answered "no item" (only then can it be a first start)
_DURUM_KILIT = threading.RLock()
_DURUM_ONBELLEK_SN = 1.0


def _test_kumu() -> bool:
    """The settings AND the marks live in a /tmp sandbox (tests/_yalitim: mkdtemp). A real profile never does. Only
    then does DESKHAND_ANAHTARLIK=kapali mean "no item"; anywhere else it is a missing wallet: closed-fail (security
    scan 2/3). Code that can point these variables elsewhere reads its own settings anyway (docs: threat model)."""
    def tmp_altinda(yol: str) -> bool:
        y = os.path.realpath(yol)
        return y.startswith("/tmp/") and y != "/tmp/"
    return tmp_altinda(yollar.config_dir()) and tmp_altinda(yollar.state_dir())


def _kasa_nesnesi():
    global _KASA
    if _KASA is None:
        from .oturum.kalici import AnahtarYok, GizliServis

        class _PanelKasasi(GizliServis):
            """ONE Secret Service item: the mark key, a counter per setting and the panel's last approved value."""
            ETIKET = "Deskhand panel settings"
            OZNITELIK = {"application": "deskhand", "purpose": "panel-isaret"}

            def _bul(self, koleksiyon):
                for oge in koleksiyon.search_items(self.OZNITELIK):
                    if oge.is_locked():
                        raise AnahtarYok(_("cüzdan kilitli"))
                    s = bytes(oge.get_secret())
                    if s:
                        return s
                return None

            def oku(self):
                if os.environ.get("DESKHAND_ANAHTARLIK") == "kapali" and _test_kumu():
                    return None  # test sandbox (tests/_yalitim): "no item" (a first start), never the real wallet
                try:
                    return self.anahtar(False)
                except AnahtarYok as e:
                    if e.yok:
                        return None
                    raise

            def yaz(self, veri: bytes) -> None:
                if os.environ.get("DESKHAND_ANAHTARLIK") == "kapali":
                    raise AnahtarYok(_("anahtarlık kapalı (DESKHAND_ANAHTARLIK=kapali)"))
                import secretstorage
                baglanti = secretstorage.dbus_init()
                try:
                    koleksiyon = secretstorage.Collection(baglanti)
                    if koleksiyon.is_locked():
                        raise AnahtarYok(_("cüzdan kilitli"))
                    koleksiyon.create_item(self.ETIKET, self.OZNITELIK, veri, replace=True,
                                           content_type="application/json")
                finally:
                    baglanti.close()
        _KASA = _PanelKasasi()
    return _KASA


def isaret_anahtarlik_ayarla(nesne) -> None:
    """Replace the panel's Secret Service item (tests: an object with oku() -> bytes | None and yaz(bytes))."""
    global _KASA
    _KASA = nesne
    _anahtar_unut()


def _anahtar_unut() -> None:
    global _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN
    with _DURUM_KILIT:
        _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN = None, 0.0, None
        global _DURUM_YOK_KESIN
        _DURUM_YOK_KESIN = False


def _durum_coz(ham) -> dict | None:
    try:
        d = json.loads(bytes(ham).decode("utf-8"))
        k = bytes.fromhex(d["anahtar"])
        sayac = {t: int(v) for t, v in d.get("sayac", {}).items() if t in TUM and int(v) >= 0}
        son = {t: v for t, v in d.get("son", {}).items() if t in TUM and (v is None or isinstance(v, str))}
        dur = d.get("dur") is True
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
    return {"anahtar": k, "sayac": sayac, "son": son, "dur": dur} if len(k) == 32 else None


def _neden(e: Exception) -> str:
    return getattr(e, "neden", None) or _("Secret Service hatası")


def _durum(olustur: bool = False) -> dict | None:
    """The panel's signed state, or None: no item yet (first start), locked wallet, no Secret Service, any error.
    olustur=True (panel only): a missing (or unreadable-content) item is created with a fresh key."""
    global _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN
    with _DURUM_KILIT:
        if _DURUM is not None and time.monotonic() - _DURUM_ZAMAN < _DURUM_ONBELLEK_SN:
            return _DURUM
        global _DURUM_YOK_KESIN
        try:
            ham = _kasa_nesnesi().oku()
        except Exception as e:  # noqa: BLE001 - locked / no service / error / DESKHAND_ANAHTARLIK=kapali: no signed
            _DURUM, _DURUM_NEDEN, _DURUM_YOK_KESIN = None, _neden(e), False  # state, NEVER a first start
            return None
        _DURUM_YOK_KESIN = not ham  # the key ring answered: there is no item at all
        d = _durum_coz(ham) if ham else None
        if d is None and ham:
            _DURUM_NEDEN = _("panelin imzalı kaydı okunamadı (bozuk)")
        if d is None:
            if not olustur:
                _DURUM = None
                if not ham:
                    _DURUM_NEDEN = None
                return None
            d = {"anahtar": os.urandom(32), "sayac": {}, "son": {}}
            if not _durum_kaydet(d):
                return None
        _DURUM, _DURUM_ZAMAN = d, time.monotonic()
        if ham:
            _DURUM_NEDEN = None
        return d


def _durum_kaydet(d: dict) -> bool:
    global _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN
    veri = json.dumps({"surum": 1, "anahtar": d["anahtar"].hex(), "sayac": d["sayac"], "son": d["son"],
                       "dur": bool(d.get("dur"))}, ensure_ascii=False).encode("utf-8", "surrogateescape")
    with _DURUM_KILIT:
        try:
            _kasa_nesnesi().yaz(veri)
        except Exception as e:  # noqa: BLE001 - not written: nothing is signed
            _DURUM, _DURUM_NEDEN = None, _neden(e)
            return False
        _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN = d, time.monotonic(), None
        return True


def isaret_gecmisi() -> bool:
    """Some panel mark exists: the panel has run (and signed) here before."""
    return any(os.path.lexists(isaret_yolu(t)) for t in TUM)


def ilk_kurulum() -> bool:
    """A first start ONLY when the key ring definitely answered "no item" AND no mark exists."""
    _durum(False)
    return _DURUM_YOK_KESIN and not isaret_gecmisi()


def kasa_nedeni() -> str | None:
    """Why the panel's signed state could not be used in this process (None = it worked / never written)."""
    return _DURUM_NEDEN


def onayli_deger(tur: str) -> tuple[bool, str | None]:
    """(True, value): the panel's last APPROVED value of `tur`, from the Secret Service item (a file or a mark cannot
    change it). (False, None): no signed state for it (first start, locked wallet, no Secret Service, error)."""
    d = _durum(False)
    if d is None or tur not in d["son"]:
        return False, None
    return True, d["son"][tur]


def _imza(k: bytes, tur: str, sayac: int, metin: str | None) -> str:
    veri = json.dumps(["deskhand-panel-isaret", ISARET_SURUM, tur, sayac, metin], ensure_ascii=False)
    return hmac.new(k, veri.encode("utf-8", "surrogateescape"), hashlib.sha256).hexdigest()


def _isaret_yaz(tur: str, metin: str | None) -> bool:
    """Panel only: `metin` becomes the panel's approved value: the Secret Service item (son[tur], sayac[tur] + 1 when
    the value changed) and the file mark HMAC(key, [tur, sayac, metin]). No usable item → an unsigned mark.
    → signed (False: the wallet could not be read/written; the caller may sign it later)."""
    d = _durum(True)
    sayac = None
    if d is not None:
        if tur in d["son"] and d["son"][tur] == metin:
            sayac = d["sayac"].get(tur, 0)
        else:
            yeni = {**d, "sayac": {**d["sayac"], tur: d["sayac"].get(tur, 0) + 1}, "son": {**d["son"], tur: metin}}
            d = yeni if _durum_kaydet(yeni) else None
            sayac = yeni["sayac"][tur] if d is not None else None
    m = {"surum": ISARET_SURUM, "sha256": _ozet(metin), "icerik": metin, "var": metin is not None,
         "zaman": time.time()}
    if d is not None and sayac is not None:
        m["sayac"] = sayac
        m["hmac"] = _imza(d["anahtar"], tur, sayac, metin)
    _yaz_atomik(isaret_yolu(tur), json.dumps(m, ensure_ascii=False))
    try:
        os.chmod(isaret_yolu(tur), 0o600)
    except OSError:
        pass
    return d is not None and sayac is not None


def panel_dur_sakla(acik: bool) -> bool:
    """Panel only (review INC3 B4): keep "the user's DUR is on" in the panel's signed state, so that killing the panel,
    deleting the DUR file and starting a new panel does not lift it. → stored (False: the wallet cannot be used)."""
    d = _durum(True)
    if d is None:
        return False
    if bool(d.get("dur")) == bool(acik):
        return True
    return _durum_kaydet({**d, "dur": bool(acik)})


def panel_dur_kayitli() -> bool:
    """The panel's signed state says the user's DUR is on (False: no / cannot be read)."""
    d = _durum(False)
    return bool(d is not None and d.get("dur"))


def isaret_dogrula(tur: str) -> tuple[str, str | None]:
    """The file mark: ("yok", None) · ("gecerli", content): HMAC right AND its counter == the item's (an older signed
    mark put back = replay → not valid) · ("dogrulanamadi", content|None) otherwise. Decisions use onayli_deger."""
    m = isaret_oku(tur)
    if m is None:
        return "yok", None
    icerik = m.get("icerik") if m.get("var", True) else None
    if icerik is not None and not isinstance(icerik, str):
        return "dogrulanamadi", None
    d = _durum(False)
    h, s = m.get("hmac"), m.get("sayac")
    if d is None or not isinstance(h, str) or not isinstance(s, int) or isinstance(s, bool) or \
            s != d["sayac"].get(tur) or not hmac.compare_digest(h, _imza(d["anahtar"], tur, s, icerik)):
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
        self._redler: set[tuple[str, str, str]] = set()  # C6/B2: (setting, sha256 file, sha256 approved) refused
        self._yazilamadi: set[tuple[str, str | None]] = set()
        self._kilit = threading.Lock()
        self.bellek: dict[str, str | None] = {}
        self._dogrulanamayan: set[str] = set()  # yasak/seviye not verified (wallet unreadable, user said No): Dur 10
        self._imzasiz: set[str] = set()  # approved by the user while the wallet could not be written: sign later
        self._dogrulanacak: list[tuple[str, str | None]] = []
        self._kasa_deneme = time.monotonic()
        self._gecmis = isaret_gecmisi()  # before this start writes any mark
        self._ilk = ilk_kurulum()  # the key ring answered "no item" AND no mark: a first start
        for tur in TUM:
            self._acilis(tur)
        self._dogrulanamayanlari_sor()
        if kasa_nedeni():  # once per start, visible: why loosening values are being asked / not applied
            self.uyari(_("Panelin imzalı kaydı kullanılamıyor ({neden}); yalnız varsayılanlar ve daraltmalar "
                         "uygulanıyor, gevşetmeler panelde sorulur.").format(neden=kasa_nedeni()))

    KASA_YENIDEN_SN = 5.0  # unverified / unsigned values: how often denetle tries the wallet again

    # ---- the question
    def _soru(self, tur: str, aciklama: str, siteler: list[str] | None = None) -> bool:
        """Ask once (default No). Nothing is cached here: see _sor (only a No is remembered)."""
        if self._soruyor:  # the dialog runs a nested event loop: the poll timer must not ask again meanwhile
            return False
        self._soruyor = True
        try:
            if siteler is not None and self.onayla is not None:
                return bool(self.onayla(siteler))
            if self.sor is not None:
                return bool(self.sor(tur, aciklama))
            return False
        except Exception:  # noqa: BLE001 - the dialog failed: not approved
            return False
        finally:
            self._soruyor = False

    @staticmethod
    def _red_anahtari(tur: str, yeni: str | None, ref: str | None) -> tuple[str, str, str]:
        return (tur, _ozet(yeni), _ozet(ref))

    def _sor(self, tur: str, yeni: str | None, ref: str | None) -> bool:
        """A loosening of `ref` (the approved value) to `yeni`. Only a No is remembered (review INC3 B2: a cached Yes
        let content the user later removed come back without a question)."""
        anahtar = self._red_anahtari(tur, yeni, ref)
        if anahtar in self._redler:
            return False
        if self._soruyor:
            return False
        siteler = None
        if tur == KALICI and self.onayla is not None:
            siteler = sorted(kalici_ayristir(yeni) - kalici_ayristir(ref)) or sorted(kalici_ayristir(yeni))
        cevap = self._soru(tur, _("{ayar}: panelin kaydı «{eski}», dosyada «{yeni}»").format(
            ayar=_(_AYAR_ADI[tur]), eski=_kisa(ref), yeni=_kisa(yeni)), siteler)
        if not cevap:
            self._redler.add(anahtar)
        return cevap

    def _imza_izle(self, tur: str, imzali: bool) -> None:
        """A value the user approved (Yes / Settings): not signed now (wallet unreadable) → signed in denetle."""
        if imzali:
            self._imzasiz.discard(tur)
        else:
            self._imzasiz.add(tur)

    def _dogrulanamayanlari_sor(self) -> None:
        """Panel start, yasak/seviye with no signed value and not a first start (locked wallet, no Secret Service,
        marks deleted or forged): ONE question with the file contents, default No (review INC3 B1)."""
        liste, self._dogrulanacak = self._dogrulanacak, []
        if not liste:
            return
        neden = kasa_nedeni() or _("panelin imzalı kaydı yok")
        satirlar = "\n".join(_("{ayar}: dosyada «{yeni}»").format(ayar=_(_AYAR_ADI[t]), yeni=_kisa(d))
                             for t, d in liste)
        aciklama = _("Panelin imzalı kaydı okunamıyor ({neden}); şu listeler doğrulanamadı:\n{satirlar}").format(
            neden=neden, satirlar=satirlar)
        if self._soru(",".join(t for t, _d in liste), aciklama):
            for tur, d in liste:
                if d is None and tur == "yasak":
                    from .guvenlik import VARSAYILAN_YASAK
                    d = _(VARSAYILAN_YASAK)
                    try:
                        _yaz_atomik(dosya(tur), d)
                    except OSError:
                        pass
                self._kabul(tur, d, onay=True)
            return
        with self._kilit:
            for tur, d in liste:
                self.bellek[tur] = d  # kept as found (the settings page shows it); NOT served: Dur 10
                self._dogrulanamayan.add(tur)
        self.uyari(_("Cüzdan okunamıyor; listeler doğrulanamadı ({ayarlar}). Bu listeler doğrulanana kadar Deskhand "
                     "girdi göndermez (Dur 10). Cüzdan açılınca panel imzalı kaydı geri yükler; ya da listeleri "
                     "Ayarlar'dan kaydedin.").format(ayarlar=", ".join(_(_AYAR_ADI[t]) for t, _d in liste)))

    def _kasa_yeniden(self) -> list[str]:
        """denetle: the wallet can be read again → sign the values approved meanwhile, restore + re-check the
        unverified lists from the signed state."""
        if not (self._dogrulanamayan or self._imzasiz) or self._soruyor:
            return []
        simdi = time.monotonic()
        if simdi - self._kasa_deneme < self.KASA_YENIDEN_SN:
            return []
        self._kasa_deneme = simdi
        if _durum(False) is None:
            return []
        for tur in sorted(self._imzasiz):
            with self._kilit:
                deger = self.bellek.get(tur)
                if tur not in self._dogrulanamayan and _isaret_yaz(tur, deger):
                    self._imzasiz.discard(tur)
        uyarilar = []
        for tur in sorted(self._dogrulanamayan):
            var, ref = onayli_deger(tur)
            if not var:
                continue  # still no signed value: stays unverified (the user can save the list in Ayarlar)
            with self._kilit:
                reddedilen = self.bellek.get(tur)
            # the user already said No to this file content at start: restored without a second question
            self._redler.add(self._red_anahtari(tur, reddedilen, ref))
            self._acilis(tur)  # signed value now known: tighter file → kept, looser → restored (or asked)
            with self._kilit:
                self._dogrulanamayan.discard(tur)
            uyarilar.append(_("Cüzdan okunabildi; {ayar} panelin imzalı kaydıyla doğrulandı.").format(
                ayar=_(_AYAR_ADI[tur])))
        return uyarilar

    def yanit(self, tur: str) -> str | None:
        """The value served on the approval channel (`liste <tur>`): an unverified list is not served (B1)."""
        with self._kilit:
            if tur in self._dogrulanamayan:
                from .onay import ListeDogrulanamadi
                raise ListeDogrulanamadi(tur)
            return self.bellek.get(tur)

    # ---- file writes
    def _dosyaya_yaz(self, tur: str, deger: str | None, onay: bool = False) -> bool:
        """Write the panel's value back to its file (+ signed mark). A failure is reported once per content (C6).
        onay=True: the user approved `deger` (Yes / Settings): if it cannot be signed now, it is signed later."""
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
            imzali = _isaret_yaz(tur, deger)
        except OSError:
            imzali = False
        if onay:
            self._dogrulanamayan.discard(tur)  # the user's own value: verified by the user
            self._imza_izle(tur, imzali)
        return tamam

    # ---- panel start
    def _acilis(self, tur: str) -> None:
        d = _dosyadaki(tur)
        var, ref = onayli_deger(tur)  # the panel's last approved value: from the Secret Service item, never a file
        if var:
            if siki_mi(tur, d, ref):
                self._kabul(tur, d)
                return
        elif tur in TURLER:
            if self._ilk:
                # first start (the key ring answered "no item" AND no mark): the default is the built-in list only
                # (yasak) and no rule (seviye); any file is that or stricter
                if d is None and tur == "yasak":
                    from .guvenlik import VARSAYILAN_YASAK
                    d = _(VARSAYILAN_YASAK)
                    try:
                        _yaz_atomik(dosya(tur), d)
                    except OSError:
                        pass
                self._kabul(tur, d)
                return
            # not a first start and no signed value (locked wallet, no Secret Service, DESKHAND_ANAHTARLIK=kapali,
            # marks deleted or forged): "tighter than the default" proves nothing for these lists and an unsigned
            # mark is no evidence (review INC3 B1). Asked together after the loop (_dogrulanamayanlari_sor)
            self._dogrulanacak.append((tur, d))
            return
        else:
            if siki_mi(tur, d, TABAN[tur]):
                self._kabul(tur, d)
                return
            ref = en_siki(tur, d, TABAN[tur])
        if self._sor(tur, d, ref):
            self._kabul(tur, d, onay=True)
            return
        self.bellek[tur] = ref
        if ref != d:
            self._dosyaya_yaz(tur, ref)
        else:
            _isaret_yaz(tur, ref)
        self.uyari(self._ret_iletisi(tur, d, ref))

    def _kabul(self, tur: str, d: str | None, onay: bool = False) -> None:
        self.bellek[tur] = d
        imzali = _isaret_yaz(tur, d)
        if onay:
            self._imza_izle(tur, imzali)
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
            self._dosyaya_yaz(KAPSAM, deger, onay=True)

    def kimlik_kaydet(self, deger: str) -> None:
        """Panelin Ayarlar'ı: hesap oturumu izni (tek yetkili yazar; açarken onay diyaloğu gui'de)."""
        k = kimlik_ayristir(deger, kati=True)
        with self._kilit:
            self.bellek[KIMLIK] = kimlik_metni(k)
            self._dosyaya_yaz(KIMLIK, self.bellek[KIMLIK], onay=True)

    def kalici_kaydet(self, deger: str) -> None:
        """Panel (user-approved): the persistent-session site list (single authoritative writer)."""
        k = kalici_ayristir(deger, kati=True)
        with self._kilit:
            self.bellek[KALICI] = kalici_metni(k)
            self._dosyaya_yaz(KALICI, self.bellek[KALICI], onay=True)

    def sure_kaydet(self, gun: int) -> None:
        """Panel (user-approved): [oturum] kalici_sure_gun."""
        with self._kilit:
            self.bellek[SURE] = str(_sure_sayi(gun))
            self._dosyaya_yaz(SURE, self.bellek[SURE], onay=True)

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
        tekrar = self._red_anahtari(tur, dosyada, bellekte) in self._redler
        if self._sor(tur, dosyada, bellekte):
            with self._kilit:
                self.bellek[tur] = dosyada
                self._dosyaya_yaz(tur, dosyada, onay=True)
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

    def _dosyaya(self, tur: str, onay: bool = False) -> None:
        self._dosyaya_yaz(tur, self.bellek.get(tur), onay)

    def metin(self, tur: str) -> str | None:
        with self._kilit:
            return self.bellek.get(tur)

    def kaydet(self, tur: str, metin: str) -> None:
        """Panelin Kaydet'i: bellek + dosya + işaret (tek yetkili yazar). The user's own value: an unverified list
        becomes verified (B1), and it is signed now or as soon as the wallet can be written."""
        with self._kilit:
            self.bellek[tur] = metin
            self._dosyaya(tur, onay=True)

    def denetle(self) -> list[str]:
        """Dosyalar bellekle aynı mı? Değilse (silindi/değişti) bellekteki içerik geri yazılır. → uyarı metinleri.
        Unverified / unsigned values: the wallet is tried again (KASA_YENIDEN_SN) and the lists re-checked (B1)."""
        uyarilar = self._kasa_yeniden()
        with self._kilit:
            for tur in TURLER:
                if tur in self._dogrulanamayan:
                    continue  # not served (Dur 10) and not signed: nothing to restore until it is verified (B1)
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
    onay.liste_saglayici = AKTIF.yanit
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
        try:
            return AKTIF.yanit(tur)
        except Exception as e:  # noqa: BLE001 - onay.ListeDogrulanamadi: not verified (B1)
            raise Dur(10, _(MESAJ_PANEL_DOGRULANAMADI).format(tur=_(_AYAR_ADI.get(tur, tur)))) from e
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
    except onay.ListeDogrulanamadi:  # the panel answered: this list is not verified (wallet unreadable): Dur 10
        raise Dur(10, _(MESAJ_PANEL_DOGRULANAMADI).format(tur=_(_AYAR_ADI.get(tur, tur)))) from None
    except Exception:  # noqa: BLE001 - panel yok / doğrulanamadı / eski panel: dosya yolu (işaret denetimli)
        return _YOK


def _dosyadan(tur: str, olustur: bool = True) -> str | None:
    """Panel closed: the file is used only when it is the panel's last APPROVED value (Secret Service item) or
    stricter; looser / deleted → Dur 10. No signed state (first start, locked wallet): the file (any file is the
    default or stricter for yasak/seviye), no Dur 10 loop."""
    yol = dosya(tur)
    mevcut = _oku(yol)
    var, ref = onayli_deger(tur)
    if var:
        if not siki_mi(tur, mevcut, ref):
            raise Dur(10, _(MESAJ_KAYIP).format(dosya=yol))
        return mevcut
    if not ilk_kurulum():  # no signed record and not a first start (marks exist, or the key ring cannot answer:
        # locked wallet, no Secret Service, DESKHAND_ANAHTARLIK=kapali): closed-fail (security scan 2/3); the panel
        # reads its own wallet and restores the approved value
        raise Dur(10, _(MESAJ_DOGRULANAMADI).format(dosya=yol))
    if mevcut is None and tur == "yasak":  # no signed state and no mark ever: the default list
        from .guvenlik import VARSAYILAN_YASAK
        mevcut = _(VARSAYILAN_YASAK)
        if olustur:
            try:
                _yaz_atomik(yol, mevcut)
            except OSError:
                pass
    return mevcut
