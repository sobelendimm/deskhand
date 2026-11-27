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
     the panel restores the signed value and checks again (`denetle`, one snapshot of the signed state: review INC4
     Y1); a readable wallet with no approved value for the list asks again when the file changed or the No was given
     while the wallet was locked (INC4 Y3). Every question shows the applied ENTRIES (`gosterim`, INC4 O3);
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
import unicodedata

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
                               "doğrulanamadı); güvenli tarafta hiçbir girdi gönderilmez. Cüzdan okununca panel imzalı "
                               "kaydı geri yükler; imzalı kayıt yoksa listeyi panelde yeniden sorar.")
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
_SERVIS_YOK_KESIN = False        # there is no Secret Service at all (not locked: absent; review INC5 Y10)
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

            def servis_yok_kesin(self) -> bool:
                """True ONLY when there is definitely no Secret Service: python-secretstorage is not installed, or
                the session bus answers that org.freedesktop.secrets is neither running nor activatable. A locked
                wallet, no session bus, D-Bus errors and DESKHAND_ANAHTARLIK=kapali outside the test sandbox are
                NOT "absent" (closed-fail)."""
                if os.environ.get("DESKHAND_ANAHTARLIK") == "kapali":
                    return False
                try:
                    import secretstorage
                except ImportError:
                    return True
                try:
                    baglanti = secretstorage.dbus_init()
                except Exception:  # noqa: BLE001 - no session bus: unknown, not absent
                    return False
                try:
                    return not secretstorage.check_service_availability(baglanti)
                except Exception:  # noqa: BLE001 - unknown
                    return False
                finally:
                    baglanti.close()

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
        global _DURUM_YOK_KESIN, _SERVIS_YOK_KESIN
        _DURUM_YOK_KESIN = _SERVIS_YOK_KESIN = False


def _durum_coz(ham) -> dict | None:
    try:
        d = json.loads(bytes(ham).decode("utf-8"))
        k = bytes.fromhex(d["anahtar"])
        sayac = {t: int(v) for t, v in d.get("sayac", {}).items() if t in TUM and int(v) >= 0}
        son = {t: v for t, v in d.get("son", {}).items() if t in TUM and (v is None or isinstance(v, str))}
        dur = d.get("dur")
        if not isinstance(dur, bool):
            dur = None  # missing / wrong field: the user's DUR is unknown → closed-fail (review INC5 N1)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
    return {"anahtar": k, "sayac": sayac, "son": son, "dur": dur} if len(k) == 32 else None


def _neden(e: Exception) -> str:
    return getattr(e, "neden", None) or _("Secret Service hatası")


def _durum(olustur: bool = False, bozugu_yenile: bool = False) -> dict | None:
    """The panel's signed state, or None: no item yet (first start), locked wallet, no Secret Service, any error.
    olustur=True (panel only): a MISSING item is created with a fresh key. An item that exists but cannot be read
    (corrupt content) is re-created ONLY with bozugu_yenile=True: the user's own DUR action (panel_dur_sakla). Any
    automatic path leaves it as it is, so the user's DUR stays closed-fail ON (review INC5 N1)."""
    global _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN
    with _DURUM_KILIT:
        if _DURUM is not None and time.monotonic() - _DURUM_ZAMAN < _DURUM_ONBELLEK_SN:
            return _DURUM
        global _DURUM_YOK_KESIN, _SERVIS_YOK_KESIN
        try:
            ham = _kasa_nesnesi().oku()
        except Exception as e:  # noqa: BLE001 - locked / no service / error / DESKHAND_ANAHTARLIK=kapali: no signed
            _DURUM, _DURUM_NEDEN, _DURUM_YOK_KESIN = None, _neden(e), False  # state, NEVER a first start
            try:
                _SERVIS_YOK_KESIN = bool(getattr(_kasa_nesnesi(), "servis_yok_kesin", lambda: False)())
            except Exception:  # noqa: BLE001 - unknown: closed-fail
                _SERVIS_YOK_KESIN = False
            return None
        _SERVIS_YOK_KESIN = False
        _DURUM_YOK_KESIN = not ham  # the key ring answered: there is no item at all
        d = _durum_coz(ham) if ham else None
        if d is None and ham:
            _DURUM_NEDEN = _("panelin imzalı kaydı okunamadı (bozuk)")
        if d is None:
            if not olustur or (ham and not bozugu_yenile):
                _DURUM = None
                if not ham:
                    _DURUM_NEDEN = None
                return None
            # a missing item: a first start (no DUR record = off); a corrupt one re-made by the user's DUR action
            # (panel_dur_sakla writes the user's value right after)
            d = {"anahtar": os.urandom(32), "sayac": {}, "son": {}, "dur": False if not ham else None}
            if not _durum_kaydet(d):
                return None
        _DURUM, _DURUM_ZAMAN = d, time.monotonic()
        if ham:
            _DURUM_NEDEN = None
        return d


def _durum_kaydet(d: dict) -> bool:
    global _DURUM, _DURUM_ZAMAN, _DURUM_NEDEN
    dur = d.get("dur")
    veri = json.dumps({"surum": 1, "anahtar": d["anahtar"].hex(), "sayac": d["sayac"], "son": d["son"],
                       "dur": dur if isinstance(dur, bool) else None}, ensure_ascii=False).encode("utf-8", "surrogateescape")
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
    deleting the DUR file and starting a new panel does not lift it. → stored (False: the wallet cannot be used).
    The user's DUR action is the only one that re-makes a corrupt item (review INC5 N1)."""
    d = _durum(True, bozugu_yenile=True)
    if d is None:
        return False
    if d.get("dur") is bool(acik):
        return True
    return _durum_kaydet({**d, "dur": bool(acik)})


def panel_dur_kayitli() -> bool:
    """The panel's signed state says the user's DUR is on (False: no / cannot be read)."""
    d = _durum(False)
    return bool(d is not None and d.get("dur") is True)


def panel_dur_durumu() -> bool | None:
    """The user's DUR as the panel's signed state records it: True / False, or None when it cannot be read (locked
    wallet, unreadable / corrupt item, item without a DUR field: the caller fails closed; review INC4 B4, INC5 N1).
    The key ring answering "no item", or no Secret Service at all (absent, not locked: review INC5 Y10), is False:
    a first start. An item deleted while the wallet is open is outside the threat model (a process that can edit the
    user's wallet)."""
    d = _durum(False)
    if d is not None:
        dur = d.get("dur")
        return dur if isinstance(dur, bool) else None
    return False if (_DURUM_YOK_KESIN or _SERVIS_YOK_KESIN) else None


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


# ---------------------------------------------------------------- the approval display (review INC4: O3, Y5)
# What the user approves is the list of ENTRIES the application applies, taken with the application's own parser
# (guvenlik._kullanici_yasaklari / seviye_kurallari: str.splitlines, strip, '#' comments), never the raw text:
#  - every entry on its own numbered line; blank and comment lines are folded into one marked line (they apply nothing);
#  - every character that is not printable ASCII or a Turkish letter (çğıİöşüÇĞÖŞÜ) → visible \u{XXXX} AND a ⚠ note
#    on an unnumbered line below it: control / bidi / zero-width / combining marks, look-alike letters (Cyrillic е),
#    and look-alikes that are not letters (Roman numerals Ⅹ Ⅽ, mathematical digits 𝟐, U+2800, U+3002, fullwidth
#    forms; review INC5 Y7/Y8); a run of spaces → \u{0020}×N; a very long entry is marked the same way (a content
#    line always carries its number);
#  - a run of blank and/or comment lines folds into ONE marked line (review INC5 Y9); a question longer than
#    GOSTERIM_UST_SINIR entries or GOSTERIM_SATIR_SINIR shown lines cannot be answered Yes (read it in Settings);
#  - with an approved value: per-entry difference (removed first); counts in a FIXED label outside the content;
#  - without one: a fixed label says the comparison is impossible and that the list is ALL the entries (N);
#  - the Yes is bound to the hash of the canonical entry lists (`Gosterim.iz`), handed to the dialog as a token and
#    never read back from a widget (Qt normalises CR / NBSP / U+2029: review INC4 Y5).
GOSTERIM_SURUM = 1
GOSTERIM_UST_SINIR = 2000  # entries per question; above it the Yes is disabled (padding: unreadable question)
GOSTERIM_SATIR_SINIR = 3 * GOSTERIM_UST_SINIR  # shown lines per question (entries + folded runs + ⚠ notes)
UZUN_GIRIS = 160
_GUVENLI_HARF = frozenset("çğıİöşüÇĞÖŞÜ")  # shown as they are: legitimate Turkish text is not marked
_ISARET = {"+": "+", "-": "−", "~": "~", " ": " "}
SORU_DEGISIKLIK = N_("Deskhand ayarı panel kapalıyken değişti ya da panelin imzası doğrulanamadı. Bu değişiklik "
                     "uygulansın mı? Siz yapmadıysanız Hayır deyin.")
SORU_DOGRULANAMADI = N_("Panelin imzalı kaydı okunamıyor ({neden}); şu listeler doğrulanamadı. Dosyadaki girişler "
                        "uygulansın mı? Siz yazmadıysanız Hayır deyin.")
SORU_KALICI = N_("Görünmez masaüstündeki tarayıcının şu sitelerdeki oturumu kalıcı saklansın mı (şifreli, KDE "
                 "Cüzdanı anahtarıyla; banka/ödeme siteleri hiçbir zaman)? Bu isteği siz yapmadıysanız Hayır deyin.")
ETIKET_TAMAMI = N_("Onaylı kayıt okunamadı — karşılaştırma yapılamıyor; aşağıdaki liste dosyadaki girişlerin "
                   "TAMAMIDIR ({n} giriş); eksik kural görüyorsanız Hayır deyin.")
ETIKET_FARK = N_("Onaylı kayda göre: {k} kaldırılan, {e} eklenen, {d} değişen giriş; {s} giriş aynı. Kaldırılanlar "
                 "önce listelenir.")
ETIKET_FARK_VARSAYILAN = N_("Onaylı kayıt yok; varsayılan değere göre: {k} kaldırılan, {e} eklenen, {d} değişen "
                            "giriş; {s} giriş aynı.")
ETIKET_ISARETLI = N_("Dikkat: {n} girişte görünmez, ASCII dışı ya da çok uzun içerik var (⚠ satırları).")
ETIKET_SINIR = N_("Liste çok uzun (üst sınır {sinir} giriş, {satir} satır); bu soruya Evet verilemez. Listeyi "
                  "Ayarlar'dan inceleyin.")


def _kacis(metin: str) -> tuple[str, list[str]]:
    """→ (visible text, notes): every character that is neither printable ASCII nor a Turkish letter as \\u{XXXX},
    each named in a note (review INC5 Y7/Y8: no look-alike or invisible character is shown raw or unmarked); runs of
    spaces counted."""
    cikti: list[str] = []
    notlar: list[str] = []
    i = 0
    while i < len(metin):
        ch = metin[i]
        if ch == " ":
            j = i
            while j < len(metin) and metin[j] == " ":
                j += 1
            cikti.append(" " if j - i == 1 else f"\\u{{0020}}×{j - i}")
            i = j
            continue
        o = ord(ch)
        if 0x20 < o < 0x7F or ch in _GUVENLI_HARF:
            cikti.append(ch)
        else:
            cikti.append(f"\\u{{{o:04X}}}")
            n = f"U+{o:04X} {unicodedata.name(ch, '?')}"
            if n not in notlar:
                notlar.append(n)
        i += 1
    if not notlar:
        return "".join(cikti), []
    ek = "" if len(notlar) <= 6 else f" (+{len(notlar) - 6})"
    return "".join(cikti), [_("görünmez ya da ASCII dışı karakter: {harfler}").format(
        harfler=", ".join(notlar[:6]) + ek)]


def _yasak_girisleri(metin: str | None) -> list[tuple[int, str | None]]:
    """(line number, pattern | None for a blank/comment line): guvenlik._kullanici_yasaklari's own rule."""
    return [(no, s.strip() if s.strip() and not s.lstrip().startswith("#") else None)
            for no, s in enumerate((metin or "").splitlines(), 1)]


def _seviye_girisleri(metin: str | None) -> list[tuple[int, tuple[str, int] | None]]:
    from .guvenlik import seviye_satiri_coz
    return [(no, seviye_satiri_coz(s)) for no, s in enumerate((metin or "").splitlines(), 1)]


def kanonik(tur: str, metin: str | None) -> list:
    """The entries the application applies for `metin` (the hash input of an approval)."""
    if tur == "yasak":
        return [g for _n, g in _yasak_girisleri(metin) if g is not None]
    if tur == "seviye":
        return [list(g) for _n, g in _seviye_girisleri(metin) if g is not None]
    if tur == KIMLIK:
        return [k for k in KIMLIK_SAGLAYICILARI if k in kimlik_ayristir(metin)]
    if tur == KALICI:
        return sorted(kalici_ayristir(metin))
    if tur == SURE:
        return [str(_sure_sayi(metin))]
    return [] if metin is None else [metin]


def _numarali(tur: str, metin: str | None) -> list[tuple[int, str, object]]:
    """[(number, shown key, compared value)] in order; yasak/seviye numbers are the application's line numbers."""
    if tur == "yasak":
        return [(no, g, None) for no, g in _yasak_girisleri(metin) if g is not None]
    if tur == "seviye":
        return [(no, g[0], g[1]) for no, g in _seviye_girisleri(metin) if g is not None]
    return [(i, g, None) for i, g in enumerate(kanonik(tur, metin), 1)]


_SEVIYE_ADI = {0: "goruntule", 1: "tikla", 2: "tam"}


class Bolum:
    """One setting of a question: fixed name + fixed label (numbers only) + content lines."""

    def __init__(self, tur: str, etiket: str, satirlar: list[str], isaretli: int, giris: int):
        self.tur, self.ayar, self.etiket, self.satirlar = tur, _(_AYAR_ADI.get(tur, tur)), etiket, satirlar
        self.isaretli, self.giris = isaretli, giris


class Gosterim(str):
    """An approval question as shown (str value = the plain-text form, for logs and non-GUI callers). The dialog
    renders soru / bolumler; `iz` = sha256 of the canonical entry lists: the token the dialog gives back with a Yes."""
    soru: str
    bolumler: list
    iz: str
    evet_kapali: bool


def _satir(isaret: str, no: int, anahtar: str, ek: str = "") -> tuple[list[str], bool]:
    gorunur, notlar = _kacis(anahtar)
    if len(anahtar) > UZUN_GIRIS:
        notlar.append(_("çok uzun giriş: {n} karakter").format(n=len(anahtar)))
    s = [f"{_ISARET[isaret]} {no:>5} │ {gorunur}{ek}"] + [f"{'':>9}⚠ {n}" for n in notlar]
    return s, bool(notlar)


def _katla(tur: str, metin: str | None) -> list[tuple[int, int, str]]:
    """Runs of blank / comment lines of yasak/seviye: [(first, last, kind)]."""
    if tur not in TURLER:
        return []
    girisler = _yasak_girisleri(metin) if tur == "yasak" else _seviye_girisleri(metin)
    satirlar = (metin or "").splitlines()
    sonuc: list[tuple[int, int, str]] = []
    for no, g in girisler:
        if g is not None:
            continue
        tur_ = "bos" if not satirlar[no - 1].strip() else "yorum"
        if sonuc and sonuc[-1][1] == no - 1:  # blank and comment lines mixed: still ONE line (review INC5 Y9)
            sonuc[-1] = (sonuc[-1][0], no, tur_ if sonuc[-1][2] == tur_ else "karisik")
        else:
            sonuc.append((no, no, tur_))
    return sonuc


def _katlanan_satir(ilk: int, son: int, tur_: str) -> str:
    n = son - ilk + 1
    aralik = str(ilk) if n == 1 else f"{ilk}–{son}"
    if tur_ == "bos":
        return f"{'':>9}⋯ " + _("{n} boş satır ({aralik}) katlandı").format(n=n, aralik=aralik)
    if tur_ == "yorum":
        return f"{'':>9}⋯ " + _("{n} yorum satırı ({aralik}) uygulanmaz").format(n=n, aralik=aralik)
    return f"{'':>9}⋯ " + _("⟨boş/yorum ×{n}⟩ ({aralik}) uygulanmaz").format(n=n, aralik=aralik)


def _deger_eki(tur: str, deger) -> str:
    return f" = {_SEVIYE_ADI.get(deger, deger)}" if tur == "seviye" else ""


def _bolum(tur: str, yeni: str | None, ref: str | None, ref_tur: str | None) -> Bolum:
    girisler = _numarali(tur, yeni)
    satirlar: list[str] = []
    isaretli = 0
    if ref_tur is None:  # no approved value: ALL the entries, in file order, blank/comment runs folded
        katlar = {k[0]: k for k in _katla(tur, yeni)}
        girdi_no = {no: (a, v) for no, a, v in girisler}
        for no in sorted(set(katlar) | set(girdi_no)):
            if no in katlar:
                ilk, son, cins = katlar[no]
                satirlar.append(_katlanan_satir(ilk, son, cins))
                continue
            a, v = girdi_no[no]
            s, im = _satir(" ", no, a, _deger_eki(tur, v))
            satirlar += s
            isaretli += im
        etiket = _(ETIKET_TAMAMI).format(n=len(girisler))
    else:  # per-entry difference to the reference: removed first, then added, then changed (seviye)
        eski = _numarali(tur, ref)
        ye: dict = {}
        es: dict = {}
        for hedef, kaynak in ((ye, girisler), (es, eski)):
            for _n, a, v in kaynak:  # seviye: a repeated pattern resolves to its lowest level (_seviye_haritasi)
                hedef[a] = v if a not in hedef or v is None else min(hedef[a], v)
        ilk_no_y = {}
        for no, a, _v in girisler:
            ilk_no_y.setdefault(a, no)
        ilk_no_e = {}
        for no, a, _v in eski:
            ilk_no_e.setdefault(a, no)
        kaldirilan = [a for a in es if a not in ye]
        eklenen = [a for a in ye if a not in es]
        degisen = [a for a in ye if a in es and ye[a] != es[a]]
        for isaret, liste, nolar, degerler in (("-", kaldirilan, ilk_no_e, es), ("+", eklenen, ilk_no_y, ye)):
            for a in liste:
                s, im = _satir(isaret, nolar[a], a, _deger_eki(tur, degerler[a]))
                satirlar += s
                isaretli += im
        for a in degisen:
            s, im = _satir("~", ilk_no_y[a], a, f": {_SEVIYE_ADI.get(es[a], es[a])} → {_SEVIYE_ADI.get(ye[a], ye[a])}")
            satirlar += s
            isaretli += im
        ayni = len([a for a in ye if a in es and ye[a] == es[a]])
        etiket = _(ETIKET_FARK if ref_tur == "onayli" else ETIKET_FARK_VARSAYILAN).format(
            k=len(kaldirilan), e=len(eklenen), d=len(degisen), s=ayni)
    if isaretli:
        etiket += " " + _(ETIKET_ISARETLI).format(n=isaretli)
    return Bolum(tur, etiket, satirlar, isaretli, len(girisler))


def gosterim(soru: str, parcalar: list[tuple[str, str | None, str | None, str | None]]) -> Gosterim:
    """parcalar: [(tur, new value, reference value, reference kind: "onayli" | "varsayilan" | None = no reference)]."""
    bolumler = [_bolum(t, y, r, rt) for t, y, r, rt in parcalar]
    kanon = [[t, rt, kanonik(t, y), None if rt is None else kanonik(t, r)] for t, y, r, rt in parcalar]
    iz = hashlib.sha256(json.dumps(["deskhand-onay-gosterim", GOSTERIM_SURUM, kanon], ensure_ascii=False)
                        .encode("utf-8", "surrogateescape")).hexdigest()
    kapali = (sum(b.giris for b in bolumler) > GOSTERIM_UST_SINIR or
              sum(len(b.satirlar) for b in bolumler) > GOSTERIM_SATIR_SINIR)
    if kapali:
        for b in bolumler:
            b.etiket += " " + _(ETIKET_SINIR).format(sinir=GOSTERIM_UST_SINIR, satir=GOSTERIM_SATIR_SINIR)
    duz = soru + "".join(f"\n\n[{b.ayar}]\n{b.etiket}\n" + "\n".join(b.satirlar) for b in bolumler)
    g = Gosterim(duz)
    g.soru, g.bolumler, g.iz, g.evet_kapali = soru, bolumler, iz, kapali
    return g


def dogrulanmamis_gosterim(tur: str, metin: str | None) -> Gosterim:
    """Settings, read-only view of an unverified list: the same display as the question (all the entries)."""
    return gosterim("", [(tur, metin, None, None)])


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
        self._dogrulama_redleri: dict[str, tuple[str, bool]] = {}  # unverified No: (sha256 content, wallet locked)
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
    def _soru(self, tur: str, g: Gosterim, siteler: list[str] | None = None) -> bool:
        """Ask once (default No). Nothing is cached here: see _sor (only a No is remembered). `g` is the display
        (gosterim()); a dialog answering (Yes?, token) counts only when token == g.iz (the canonical entry lists)."""
        if self._soruyor:  # the dialog runs a nested event loop: the poll timer must not ask again meanwhile
            return False
        self._soruyor = True
        try:
            if siteler is not None and self.onayla is not None:
                import inspect
                try:
                    iki = len(inspect.signature(self.onayla).parameters) >= 2
                except (TypeError, ValueError):
                    iki = False
                cevap = self.onayla(siteler, g) if iki else self.onayla(siteler)
            elif self.sor is not None:
                cevap = self.sor(tur, g)
            else:
                return False
            if isinstance(cevap, tuple):  # the panel dialog: (Yes?, the token of the display it SHOWED)
                evet, iz = (cevap + (None,))[:2]
                if evet and iz != g.iz:
                    self.uyari(_("Onay penceresinde gösterilen girişler uygulanacak değerle aynı değil; Evet "
                                 "uygulanmadı."))
                    return False
                cevap = evet
            return bool(cevap) and not g.evet_kapali
        except Exception:  # noqa: BLE001 - the dialog failed: not approved
            return False
        finally:
            self._soruyor = False

    @staticmethod
    def _red_anahtari(tur: str, yeni: str | None, ref: str | None) -> tuple[str, str, str]:
        return (tur, _ozet(yeni), _ozet(ref))

    def _sor(self, tur: str, yeni: str | None, ref: str | None, ref_tur: str = "onayli") -> bool:
        """A loosening of `ref` (the approved value; ref_tur "varsayilan": the strict default) to `yeni`. Only a No is
        remembered (review INC3 B2: a cached Yes let content the user later removed come back without a question)."""
        anahtar = self._red_anahtari(tur, yeni, ref)
        if anahtar in self._redler:
            return False
        if self._soruyor:
            return False
        siteler = None
        if tur == KALICI and self.onayla is not None:
            siteler = sorted(kalici_ayristir(yeni) - kalici_ayristir(ref)) or sorted(kalici_ayristir(yeni))
        soru = _(SORU_KALICI) if tur == KALICI else _(SORU_DEGISIKLIK)
        cevap = self._soru(tur, gosterim(soru, [(tur, yeni, ref, ref_tur)]), siteler)
        if not cevap:
            self._redler.add(anahtar)
        return cevap

    def _imza_izle(self, tur: str, imzali: bool) -> None:
        """A value the user approved (Yes / Settings): not signed now (wallet unreadable) → signed in denetle."""
        if imzali:
            self._imzasiz.discard(tur)
        else:
            self._imzasiz.add(tur)

    def _dogrulanamayanlari_sor(self, liste: list[tuple[str, str | None]] | None = None) -> None:
        """yasak/seviye with no signed value and not a first start (locked wallet, no Secret Service, marks deleted or
        forged; at panel start, or later when the wallet is read but holds no approved value): ONE question showing ALL
        the entries of each file, default No (review INC3 B1, INC4 O3)."""
        if liste is None:
            liste, self._dogrulanacak = self._dogrulanacak, []
        if not liste:
            return
        kilitli = kasa_nedeni() is not None
        neden = kasa_nedeni() or _("panelin imzalı kaydında bu listelerin onaylı değeri yok")
        g = gosterim(_(SORU_DOGRULANAMADI).format(neden=neden), [(t, d, None, None) for t, d in liste])
        if self._soru(",".join(t for t, _d in liste), g):
            for tur, d in liste:
                if d is None and tur == "yasak":
                    from .guvenlik import VARSAYILAN_YASAK
                    d = _(VARSAYILAN_YASAK)
                    try:
                        _yaz_atomik(dosya(tur), d)
                    except OSError:
                        pass
                self._kabul(tur, d, onay=True)
                with self._kilit:
                    self._dogrulanamayan.discard(tur)
                self._dogrulama_redleri.pop(tur, None)
            return
        with self._kilit:
            for tur, d in liste:
                self.bellek[tur] = d  # kept as found (the settings page shows it); NOT served: Dur 10
                self._dogrulanamayan.add(tur)
                # what the No was given to (and whether the wallet was locked then): asked again only when the file
                # changes or the wallet, locked then, can be read now but holds no approved value (review INC4 Y3)
                self._dogrulama_redleri[tur] = (_ozet(d), kilitli)
        self.uyari(_("Cüzdandaki imzalı kayıtla listeler doğrulanamadı ({ayarlar}; {neden}). Deskhand "
                     "durdu (Dur 10). Cüzdan okununca panel imzalı kaydı geri yükler; imzalı kayıt yoksa dosya "
                     "değişince ya da panel yeniden başlayınca yeniden sorulur.").format(
                         neden=neden, ayarlar=", ".join(_(_AYAR_ADI[t]) for t, _d in liste)))

    def _kasa_yeniden(self) -> list[str]:
        """denetle: the wallet can be read again → sign the values approved meanwhile, restore + re-check the
        unverified lists. ONE read of the signed state is used for every decision (review INC4 Y1: a second read
        after a lock left a type unchecked but no longer "unverified")."""
        if not (self._dogrulanamayan or self._imzasiz) or self._soruyor:
            return []
        simdi = time.monotonic()
        if simdi - self._kasa_deneme < self.KASA_YENIDEN_SN:
            return []
        self._kasa_deneme = simdi
        d = _durum(True)  # the panel: a readable wallet without the item gets a fresh one (review INC4 Y3)
        if d is None:
            return []
        anlik = {t: d["son"][t] for t in TUM if t in d["son"]}  # the snapshot
        for tur in sorted(self._imzasiz):
            with self._kilit:
                deger = self.bellek.get(tur)
                if tur not in self._dogrulanamayan and _isaret_yaz(tur, deger):
                    self._imzasiz.discard(tur)
        uyarilar = []
        yeniden: list[tuple[str, str | None]] = []
        for tur in sorted(self._dogrulanamayan):
            if tur not in anlik:
                # the wallet is readable but holds no approved value for this list (the item was deleted and made
                # again): asked again when the file changed or the No was given while the wallet was locked
                dosyada = _dosyadaki(tur)
                sha, kilitliydi = self._dogrulama_redleri.get(tur, (None, True))
                if kilitliydi or _ozet(dosyada) != sha:
                    yeniden.append((tur, dosyada))
                continue
            ref = anlik[tur]
            with self._kilit:
                reddedilen = self.bellek.get(tur)
            # the user already said No to this file content at start: restored without a second question
            self._redler.add(self._red_anahtari(tur, reddedilen, ref))
            self._dogrulanacak = [x for x in self._dogrulanacak if x[0] != tur]
            self._acilis(tur, onayli=(True, ref))  # the snapshot: tighter file → kept, looser → restored (or asked)
            if any(x[0] == tur for x in self._dogrulanacak):  # defensive: never "verified" without a decision
                self._dogrulanacak = [x for x in self._dogrulanacak if x[0] != tur]
                continue
            with self._kilit:
                self._dogrulanamayan.discard(tur)
            self._dogrulama_redleri.pop(tur, None)
            uyarilar.append(_("Cüzdan okunabildi; {ayar} panelin imzalı kaydıyla doğrulandı.").format(
                ayar=_(_AYAR_ADI[tur])))
        if yeniden:
            self._dogrulanamayanlari_sor(yeniden)
        return uyarilar

    def dogrulanmamis(self, tur: str) -> bool:
        """yasak/seviye is not verified (wallet unreadable, No): Settings shows it read-only (EK-2)."""
        with self._kilit:
            return tur in self._dogrulanamayan

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
            self._imza_izle(tur, imzali)
        return tamam

    # ---- panel start
    def _acilis(self, tur: str, onayli: tuple[bool, str | None] | None = None) -> None:
        """onayli: the approved value the caller already read (one snapshot; review INC4 Y1)."""
        d = _dosyadaki(tur)
        # the panel's last approved value: from the Secret Service item, never a file
        var, ref = onayli if onayli is not None else onayli_deger(tur)
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
        if self._sor(tur, d, ref, "onayli" if var else "varsayilan"):
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
        """Panelin Kaydet'i: bellek + dosya + işaret (tek yetkili yazar). Signed now or as soon as the wallet can be
        written. An UNVERIFIED list cannot be saved (review EK-2: the page shows the unapproved file content; saving
        it would sign the attacker's value): PermissionError until the wallet is read or the full-content Yes."""
        with self._kilit:
            if tur in self._dogrulanamayan:
                raise PermissionError(_("{ayar} doğrulanmadı (Dur 10); cüzdan okununca panel imzalı kaydı geri "
                                        "yükler ya da dosyadaki girişleri yeniden sorar.").format(
                    ayar=_(_AYAR_ADI.get(tur, tur))))
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


def dogrulanmamis(tur: str) -> bool:
    """Panel process: this list is not verified (Settings: read-only, Save disabled; EK-2)."""
    return AKTIF is not None and AKTIF.dogrulanmamis(tur)


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
