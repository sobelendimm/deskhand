"""Deskhand (deskhand) MCP sunucusu (stdio): yapay zekâ ajanları masaüstünü 12 araçla kullanır (README: MCP).

Çalıştırma:  python3 -m deskhand.mcp_sunucu        (Claude Code kaydı: README.md (MCP))
Ortam:       DESKHAND_MCP_SADECE_ARKA=1  → yalnız görünmez masaüstü (foreground yasak; `deskhand-bg` kaydı)

İlkeler:
- Mantık yok: tüm işler deskhand.api üzerinden CLI komutlarına gider; güvenlik katmanları (yasak 10, hassas düğme/ödeme
  sayfası, başlık kilidi 4, DUR 13, insan önceliği 12) AYNEN geçerlidir.
- `--onayli` bu yüzeyde YOK. Hassas eylem → onay.iste(...) (Deskhand paneli; YALNIZ insan onaylar). İzin gelirse
  eylem bir kez yapılır; red / panel kapalı / onay modülü yok → ToolError.
- Masaüstü: desktop = foreground | background | auto (auto → mesgul.karar; "sonra" → araç çalışmaz).
- TEK kilit: masaüstüne dokunan araçlar (girdi ve öne getiren okumalar) sıralı. Onay ve karar beklemeleri kilidi
  tutmaz (çekirdek onay eylemin ortasında sorulursa kilit onay süresince bırakılır, sonra yeniden alınıp hedef
  pencere/başlık yeniden doğrulanır).
- Görüntü: uzun kenar varsayılan 1280; koordinatlı tıklama `shot_id` ister, pencere geometrisi değiştiyse reddedilir.
  Yasak pencereler görüntüde siyah kutu, OCR sonucundan çıkarılır.
- Kapanış (SIGINT/SIGTERM/ebeveyn öldü): açık girdiler 400 ms içinde bırakılır, sonra çıkılır.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from . import __version__, api, guvenlik, hata, masaustu
from .arka_uc import EKRAN
from .i18n import N_, _

log = logging.getLogger("deskhand.mcp")

# ---------------------------------------------------------------- isteğe bağlı modüller (paralel geliştirme)


def _modul(ad):
    try:
        return __import__(f"deskhand.{ad}", fromlist=["_"])
    except ImportError as e:  # noqa: F841 - modül yok / içe aktarılamıyor: zarif düşüş
        log.warning("isteğe bağlı modül yok: deskhand.%s (%s)", ad, e)
        return None


def _mesgul():
    m = _modul("mesgul")
    return m if m is not None and hasattr(m, "karar") else None


def _onay():
    m = _modul("onay")
    return m if m is not None and (hasattr(m, "iste") or hasattr(m, "iste_sonuc")) else None


def _oturum():
    m = _modul("oturum")
    return m if m is not None and hasattr(m, "hazirla") else None


def sadece_arka() -> bool:
    return os.environ.get("DESKHAND_MCP_SADECE_ARKA", "").strip().lower() in ("1", "true", "yes", "evet", "on")


# ---------------------------------------------------------------- talimat

TALIMAT = """Deskhand lets you use the user's KDE Plasma desktop safely. "foreground" = the user's real screen, "background" = \
an invisible desktop (used while the user is busy). desktop="auto" (default) decides from whether the user is busy.

Recommended flow:
1. get_status: stop switch, is the user busy, which desktops exist.
2. choose_desktop(task) if the user is busy and you have not asked yet. "later" = do not do the task now; tell the user.
3. read_text(window) (cheaper than screenshot); screenshot when layout matters.
4. click(window, text="Save"): click visible TEXT, not coordinates. Coordinates only with the shot_id of a fresh \
screenshot/read_text.
5. Verify: read the click result (after.changed) or read_text again before the next step.

Safety rules (enforced by the server, you cannot override them):
- Forbidden windows never receive input and are masked (black) in screenshots and OCR. Do not retry.
- Sensitive actions (Buy/Pay/Authorize/Delete account buttons, payment pages) need the USER's approval in the \
Deskhand panel. Deskhand asks them; on "kullanıcı onayı alınamadı" stop and tell the user. Never ask the user for passwords or card numbers.
- [13] the user pressed STOP: send nothing until they resume. [12] the user is using the computer: wait and retry \
later. [4] the window title changed: re-check the window.
- Actions need a window (title pattern or id from get_status/open_app); one input action runs at a time.
- Images: coordinates are pixels of the returned image (max long edge 1280); the server rescales them."""

mcp = MCPServer("deskhand", title="Deskhand", instructions=TALIMAT, version=__version__)

Masaustu = Annotated[Literal["foreground", "background", "auto"],
                     Field(description="foreground = user's screen, background = invisible desktop, auto = decide")]
Pencere = Annotated[str | None, Field(description="Window title pattern (regex) or id; empty = whole screen")]
PencereZorunlu = Annotated[str, Field(description="Target window: title pattern (regex) or id")]

OKUMA = ToolAnnotations(read_only_hint=True, open_world_hint=False)
EYLEM = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
YUMUSAK = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
YONETIM = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
SECIM = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
HEP_YUKLE = {"anthropic/alwaysLoad": True}

# ---------------------------------------------------------------- hata eşleme

KOD_ADI = {  # gösterirken _()
    1: N_("geçersiz istek"), 2: N_("nokta pencerenin/ekranın dışında"),
    3: N_("hedef pencere etkin değil (başka pencere öne geçti)"),
    4: N_("başlık/sınıf kilidi uymadı (pencere değişti)"), 5: N_("birden çok eşleşme (nth ile seç)"),
    6: N_("bulunamadı"), 7: N_("zaman aşımı"), 8: N_("pencere yok ya da taşındı"), 9: N_("araç eksik"),
    10: N_("yasak/hassas: yapılmadı"), 11: N_("akış hata ekranı"), 12: N_("kullanıcı bilgisayarı kullanıyor, sonra dene"),
    13: N_("kullanıcı DUR dedi; kullanıcı devam diyene dek hiçbir girdi gönderme"),
    14: N_("sanal masaüstü kapalı (manage_desktop action=start)"),
    15: N_("kullanıcı oyunda/film izliyor: ekranına dokunma, desktop=background kullan ya da sonra dene"),
    16: N_("uygulama arka planda açılamaz (kullanıcının ekranında açık ya da yalnız ön plan)"),
}


def hata_metni(e: hata.Dur) -> str:
    m = f"[{e.kod}] {_(KOD_ADI.get(e.kod, N_('durduruldu')))}: {e.mesaj}"
    cikti = getattr(e, "cikti", "")
    if cikti:
        m += "\n" + cikti[-1500:]
    return m


# ---------------------------------------------------------------- masaüstü seçimi

_SECIM: dict = {}  # {"secim": "kde"|"sanal"|"sonra", "bitis": monotonic, "neden": str}
_SECIM_KILIT = threading.Lock()
SECIM_SURE = {"kde": 600.0, "sanal": 600.0, "sonra": 60.0}
DIS_AD = {"kde": "foreground", "sanal": "background"}


def _secim_yaz(secim: str, neden: str) -> None:
    with _SECIM_KILIT:
        _SECIM.update(secim=secim, bitis=time.monotonic() + SECIM_SURE[secim], neden=neden)


def _secim_oku() -> dict | None:
    with _SECIM_KILIT:
        if _SECIM and _SECIM["bitis"] > time.monotonic():
            return dict(_SECIM)
    return None


def masaustu_coz(desktop: str, ozet: str) -> tuple[str, str]:
    """→ ("kde"|"sanal", not). auto: oturum seçimi → mesgul.karar; "sonra" → ToolError."""
    if desktop == "foreground":
        if sadece_arka():
            raise ToolError("[10] " + _("bu sunucu yalnız görünmez masaüstünde çalışır (deskhand-bg): "
                                        "desktop='background' ya da 'auto' kullan"))
        return "kde", ""
    if desktop == "background" or sadece_arka():
        return "sanal", ""
    s = _secim_oku()
    if s is None:
        m = _mesgul()
        if m is None:
            return "sanal", _("meşgul modülü yok: güvenli tarafta görünmez masaüstü seçildi")
        try:
            k = m.karar(ozet[:120])
        except Exception as e:  # noqa: BLE001 - karar yolu çökerse güvenli taraf
            log.warning("mesgul.karar hatası: %s", e)
            return "sanal", _("karar alınamadı ({hata}); görünmez masaüstü seçildi").format(hata=e)
        secim = {"on": "kde", "arka": "sanal", "sonra": "sonra"}.get(k, "sanal")
        _secim_yaz(secim, f"mesgul.karar → {k}")
        s = _secim_oku() or {"secim": secim, "neden": ""}
    if s["secim"] == "sonra":
        raise ToolError(_("kullanıcı sonra dedi: bu işi şimdi yapma; kullanıcıya haber ver (choose_desktop ile yeniden "
                          "sorabilirsin)"))
    return s["secim"], s.get("neden", "")


@contextmanager
def baglam(desktop: str, ozet: str):
    """Masaüstünü çöz, bu iş parçacığında o arka ucu sabitle, Dur → ToolError. → bilgi sözlüğü."""
    hedef, not_ = masaustu_coz(desktop, ozet)
    bilgi = {"desktop": DIS_AD[hedef]}
    if not_:
        bilgi["note"] = not_
    try:
        with api.hedef(hedef):
            yield bilgi
    except hata.Dur as e:
        raise ToolError(hata_metni(e)) from None


# ---------------------------------------------------------------- tek kilit

KILIT = threading.Lock()
KILIT_BEKLE = 150.0
_KILIT_YEREL = threading.local()  # bu iş parçacığı KILIT'i tutuyor mu (onay beklerken bırakıp yeniden almak için)


@contextmanager
def kilitli():
    if not KILIT.acquire(timeout=KILIT_BEKLE):
        raise ToolError("[7] " + _("başka bir Deskhand eylemi sürüyor; biraz sonra yeniden dene"))
    _KILIT_YEREL.tutuyor = True
    try:
        yield
    finally:
        if getattr(_KILIT_YEREL, "tutuyor", False):
            _KILIT_YEREL.tutuyor = False
            KILIT.release()


@contextmanager
def kilit_birakilmis():
    """Bu iş parçacığı KILIT'i tutuyorsa blok süresince bırak (insan onayı beklenirken diğer araçlar 120 sn
    beklemesin), sonra yeniden al. Yeniden alınamazsa Dur 7 (kilit tutulmuyor sayılır)."""
    if not getattr(_KILIT_YEREL, "tutuyor", False):
        yield
        return
    _KILIT_YEREL.tutuyor = False
    KILIT.release()
    try:
        yield
    finally:
        if not KILIT.acquire(timeout=KILIT_BEKLE):
            raise hata.Dur(7, _("başka bir Deskhand eylemi sürüyor; biraz sonra yeniden dene"))
        _KILIT_YEREL.tutuyor = True


# ---------------------------------------------------------------- onay (yalnız insan)

def _hassas_mi(e: hata.Dur) -> bool:
    # mesaj çevrilebilir: guvenlik hassas engeli Dur.tur="hassas" ile işaretler (eski yol: Türkçe "HASSAS" öneki)
    return e.kod == 10 and (getattr(e, "tur", None) == "hassas" or e.mesaj.startswith("HASSAS"))


def _onay_iste(eylem: str, hedef_metin: str, ayrinti: str, masaustu_ad: str, goruntu=None) -> tuple[bool, str]:
    o = _onay()
    if o is None:
        return False, _("onay modülü yok (Deskhand paneli kurulu değil)")
    try:
        if hasattr(o, "iste_sonuc"):
            s = o.iste_sonuc(eylem, hedef_metin, ayrinti, masaustu_ad, 120, goruntu)
            return bool(s.izin), s.mesaj
        return bool(o.iste(eylem, hedef_metin, ayrinti, masaustu_ad, 120)), ""
    except Exception as e:  # noqa: BLE001 - onay yolu çökerse red
        log.warning("onay hatası: %s", e)
        return False, _("onay isteği başarısız ({hata})").format(hata=e)


_ONAY_YEREL = threading.local()


def _cekirdek_onay_sarmala() -> bool:
    """guvenlik kendi içinde panelden onay istiyorsa (guvenlik._panelden_onay) onu sar: onay modülü yoksa red,
    izinler bu iş parçacığında sayılır (approved_by_user). → çekirdek onay var mı."""
    asil = getattr(guvenlik, "_panelden_onay", None)
    if asil is None:
        return False
    if getattr(asil, "_mcp_sarili", False):
        return True

    def sarili(*a, **k):
        if _onay() is None:
            return False, _("onay modülü yok (Deskhand paneli kurulu değil)")
        if getattr(guvenlik._EYLEM, "onaylandi", False):  # bu eylemde zaten onaylandı: sormaz, kilit bırakılmaz
            return asil(*a, **k)
        hedef = getattr(_ONAY_YEREL, "hedef", None)  # (pencere, onaydan önceki başlık) — onayla_ve_yap koyar
        with kilit_birakilmis():  # insan beklenirken diğer (okuma) araçları çalışabilsin
            izin, neden = asil(*a, **k)
        if izin and hedef is not None and hedef[0] != EKRAN:
            try:
                b = api.arka().baslik(hedef[0])
            except hata.Dur:
                b = None
            if b != hedef[1]:  # kilit bırakılmışken pencere/sekme değişti: onay bu hedef içindi
                guvenlik._EYLEM.onaylandi = False
                raise hata.Dur(4, _("pencere başlığı onaydan sonra değişti; onay geçersiz, eylem yapılmadı"))
        if izin:
            _ONAY_YEREL.izin = getattr(_ONAY_YEREL, "izin", 0) + 1
        return izin, neden
    sarili._mcp_sarili = True
    guvenlik._panelden_onay = sarili
    return True


def onayla_ve_yap(arac: str, k: str, yap, ayrinti_ek: str = ""):
    """yap(onayli) kilit altında çalışır. → (sonuç, kullanıcı_onayladı_mı).
    Çekirdek onay varsa (guvenlik hassas engelde paneli kendisi sorar): bir eylem = bir onay, burada yeniden
    sorulmaz; red → ToolError. Yoksa: hassas engelde (Dur 10 HASSAS) kilit bırakılır, panelden insan onayı istenir;
    izin gelirse pencere başlığı değişmediyse bir kez onaylı yapılır."""
    au = api.arka()
    if _cekirdek_onay_sarmala():
        _ONAY_YEREL.izin = 0
        with kilitli():
            _ONAY_YEREL.hedef = (k, au.baslik(k) if k != EKRAN else "")
            try:
                sonuc = yap(False)
            except hata.Dur as e:
                if _hassas_mi(e):
                    raise ToolError("[10] " + _("kullanıcı onayı alınamadı: eylem yapılmadı; kullanıcıya bildir, kendi "
                                                "kendine yeniden deneme. ({mesaj})").format(mesaj=e.mesaj)) from None
                raise
            finally:
                _ONAY_YEREL.hedef = None
        return sonuc, getattr(_ONAY_YEREL, "izin", 0) > 0
    with kilitli():
        try:
            return yap(False), False
        except hata.Dur as e:
            if not _hassas_mi(e):
                raise
            engel = e
        baslik0 = au.baslik(k) if k != EKRAN else ""
        goruntu = None
        try:
            im, *_x = api.goruntu_al(k)
            im.thumbnail((640, 480))
            goruntu = im
        except Exception:  # noqa: BLE001 - görüntü isteğe bağlı
            pass
    hedef_metin = baslik0 or _("tüm ekran")
    izin, neden = _onay_iste(arac, hedef_metin, f"{engel.mesaj}{ayrinti_ek}",
                             "arka" if au.ad == "sanal" else "ekran", goruntu)
    if not izin:
        raise ToolError("[10] " + _("kullanıcı onayı alınamadı: {neden}. Eylem yapılmadı; kullanıcıya bildir, kendi "
                                    "kendine yeniden deneme. ({mesaj})").format(neden=neden or _("red"), mesaj=engel.mesaj))
    with kilitli():
        if k != EKRAN and au.baslik(k) != baslik0:
            raise ToolError("[4] " + _("pencere başlığı onaydan sonra değişti; onay geçersiz, eylem yapılmadı"))
        return yap(True), True


# ---------------------------------------------------------------- ekran görüntüleri (shot_id)

_CEKIMLER: OrderedDict[str, dict] = OrderedDict()
_CEKIM_KILIT = threading.Lock()
CEKIM_SAYI = 64
CEKIM_OMUR = 900.0


def cekim_kaydet(k: str, hedef: str, geo, kok, olcek: float, boyut) -> str:
    sid = uuid.uuid4().hex[:12]
    with _CEKIM_KILIT:
        _CEKIMLER[sid] = {"k": k, "hedef": hedef, "geo": tuple(geo), "kok": tuple(kok), "olcek": olcek,
                          "boyut": tuple(boyut), "zaman": time.monotonic()}
        while len(_CEKIMLER) > CEKIM_SAYI:
            _CEKIMLER.popitem(last=False)
    return sid


def cekim_coz(shot_id: str | None, k: str | None) -> dict:
    """shot_id → kayıt; bayatsa (geometri değişti, başka pencere/masaüstü, eski) ToolError."""
    if not shot_id:
        raise ToolError("[1] " + _("koordinat için shot_id gerekli: önce screenshot ya da read_text çağır"))
    with _CEKIM_KILIT:
        c = _CEKIMLER.get(shot_id)
    if c is None:
        raise ToolError("[8] " + _("shot_id bilinmiyor ya da süresi doldu: yeni screenshot al"))
    au = api.arka()
    if c["hedef"] != au.ad:
        raise ToolError("[8] " + _("shot_id başka masaüstüne ait: aynı desktop değeriyle yeni screenshot al"))
    if k is not None and k != c["k"]:
        raise ToolError("[8] " + _("shot_id başka pencereye ait: bu pencerenin screenshot'ını al"))
    if time.monotonic() - c["zaman"] > CEKIM_OMUR:
        raise ToolError("[8] " + _("shot_id çok eski: yeni screenshot al"))
    if tuple(au.geometri(c["k"])) != c["geo"]:
        raise ToolError("[8] " + _("bayat görüntü: pencere görüntüden sonra taşındı/boyutu değişti; tıklanmadı. "
                                   "Yeni screenshot al"))
    return c


def cekim_noktasi(c: dict, x: float, y: float) -> tuple[float, float]:
    """Görüntü pikseli → pencere pikseli."""
    w, h = c["boyut"]
    if not (0 <= x < w and 0 <= y < h):
        raise ToolError("[2] " + _("({x},{y}) görüntünün dışında ({genislik}x{yukseklik})").format(
            x=f"{x:.0f}", y=f"{y:.0f}", genislik=w, yukseklik=h))
    return c["kok"][0] + x / c["olcek"], c["kok"][1] + y / c["olcek"]


def _kimlik_mi(arg: str, k: str) -> bool:
    return arg == k or arg.startswith(("arka:", "0x", "{"))


def baslik_kilidi(arg: str | None, k: str) -> str | None:
    """Girdi için başlık kilidi: desen verildiyse o, kimlik verildiyse pencerenin şu anki başlığı (tam)."""
    import re
    if k == EKRAN:
        return None
    if arg and not _kimlik_mi(arg, k):
        return arg
    return "^" + re.escape(api.arka().baslik(k)) + "$"


def _pencere_zorunlu(window: str | None) -> str:
    k = api.pencere(window)
    if k == EKRAN:
        raise ToolError("[1] " + _("bu eylem için window gerekli (başlık deseni ya da kimlik; get_status windows=true)"))
    return k


def _sonra(k: str, once: str | None, bekle: float = 0.35) -> dict:
    """Eylem sonrası doğrulama: pencere hâlâ var mı, başlık, görüntü değişti mi."""
    time.sleep(bekle)
    au = api.arka()
    try:
        b = au.baslik(k) if k != EKRAN else ""
        au.geometri(k)
    except hata.Dur:
        return {"window_closed": True}
    s = {"title": b}
    if once is not None:
        try:
            im, *_x = api.goruntu_al(k)
            s["changed"] = api.ozet(im) != once
        except hata.Dur:
            pass
    return s


def _once(k: str) -> str | None:
    try:
        im, _, _, _ = api.goruntu_al(k)
        return api.ozet(im)
    except hata.Dur:
        return None


# ================================================================ ARAÇLAR

@mcp.tool(title="Status", annotations=OKUMA, meta=HEP_YUKLE)
def get_status(
    windows: Annotated[bool, Field(description="Also list windows")] = False,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Call FIRST. Stop switch, whether the user is busy (fullscreen video, game, recent input), the session's desktop
    choice, the background desktop state; windows=true lists windows (auto = both desktops)."""
    s: dict[str, Any] = {"version": __version__, "only_background": sadece_arka(),
                         "stop_switch": guvenlik.dur_acik(), "stop_by": guvenlik.dur_kaynagi()}
    m = _mesgul()
    if m is not None and hasattr(m, "durum"):
        try:
            d = m.durum()
            s["user"] = {"busy": bool(d.get("mesgul")), "reasons": list(d.get("nedenler") or [])}
        except Exception as e:  # noqa: BLE001
            s["user"] = None
            s["user_note"] = _("meşgul durumu okunamadı: {hata}").format(hata=e)
    else:
        s["user"] = None
        s["user_note"] = _("meşgul modülü yok")
    try:
        from . import ayarlar
        s["policy"] = ayarlar.al("karar", "mesgulken")
    except Exception:  # noqa: BLE001
        s["policy"] = None
    sec = _secim_oku()
    s["session_choice"] = None if sec is None else ("later" if sec["secim"] == "sonra" else DIS_AD[sec["secim"]])
    d = masaustu.durum()
    s["background"] = {"running": d is not None, "size": list(d["boyut"][:2]) if d else None}
    try:
        if windows and d is not None and desktop in ("background", "auto"):
            with api.hedef("sanal"):
                s["background"]["windows"] = api.pencereler()
        if windows and not sadece_arka() and desktop in ("foreground", "auto"):
            with api.hedef("kde"):
                s["foreground_windows"] = api.pencereler()
    except hata.Dur as e:
        s["windows_note"] = hata_metni(e)
    o = _onay()
    s["approval_channel"] = ("panel" if o is not None and getattr(o, "panel_canli", lambda: False)() else
                             _("panel kapalı (hassas eylemler reddedilir)") if o is not None else _("yok"))
    return s


@mcp.tool(title="Choose desktop", annotations=SECIM)
def choose_desktop(
    task: Annotated[str, Field(description="Short task summary shown to the user (max 120 chars)", max_length=120)],
) -> dict[str, Any]:
    """Ask the USER where to do the task when they are busy (notification: Background / On my screen / Later; waits
    up to ~45 s). Remembered for this session (~10 min). choice "later" = do not do it now, tell the user."""
    if sadece_arka():
        _secim_yaz("sanal", _("deskhand-bg: yalnız görünmez masaüstü"))
        return {"status": "chosen", "choice": "background", "reason": _("bu sunucu yalnız görünmez masaüstünde çalışır")}
    m = _mesgul()
    if m is None:
        _secim_yaz("sanal", _("meşgul modülü yok"))
        return {"status": "chosen", "choice": "background", "reason": _("meşgul modülü yok: güvenli taraf")}
    try:
        if hasattr(m, "karar_ayrintili"):
            r = m.karar_ayrintili(task)
            k, neden = r["karar"], r.get("neden", "")
        else:
            k, neden = m.karar(task), ""
    except Exception as e:  # noqa: BLE001
        raise ToolError("[9] " + _("karar alınamadı: {hata}").format(hata=e)) from None
    secim = {"on": "kde", "arka": "sanal", "sonra": "sonra"}.get(k, "sanal")
    _secim_yaz(secim, neden)
    if secim == "sonra":
        return {"status": "later", "choice": None, "reason": neden}
    return {"status": "chosen", "choice": DIS_AD[secim], "reason": neden}


@mcp.tool(title="Background desktop", annotations=YONETIM)
def manage_desktop(
    action: Literal["start", "stop", "status"],
    size: Annotated[str | None, Field(description="WIDTHxHEIGHT for start, e.g. 1920x1080")] = None,
) -> dict[str, Any]:
    """Start/stop/inspect the invisible background desktop (Xvfb). stop closes every window on it."""
    try:
        if action == "start":
            hata.dur_denetle()
            d = masaustu.masaustu_baslat(size)
            return {"status": "already_running" if d.get("zaten") else "started", "running": True,
                    "size": list(d["boyut"][:2]), "warnings": list(d.get("uyarilar") or [])}
        if action == "stop":
            with kilitli():
                ok, notlar = masaustu.masaustu_durdur()
            with _CEKIM_KILIT:
                for sid in [s for s, c in _CEKIMLER.items() if c["hedef"] == "sanal"]:
                    del _CEKIMLER[sid]
            return {"status": "stopped" if ok else "not_running", "running": False, "warnings": notlar}
        d = masaustu.durum()
        if d is None:
            return {"status": "not_running", "running": False}
        with api.hedef("sanal"):
            pen = api.pencereler()
        return {"status": "running", "running": True, "size": list(d["boyut"][:2]), "windows": pen,
                "health": d.get("saglik") or {}}
    except hata.Dur as e:
        raise ToolError(hata_metni(e)) from None


@mcp.tool(title="Screenshot", annotations=OKUMA, meta=HEP_YUKLE)
def screenshot(
    window: Pencere = None,
    max_edge: Annotated[int, Field(ge=320, le=1568, description="Long edge of the returned image, px")] = 1280,
    region: Annotated[list[int] | None, Field(min_length=4, max_length=4,
                                              description="[x, y, w, h] zoom; in shot_id image pixels if shot_id "
                                                          "given, else window pixels")] = None,
    shot_id: Annotated[str | None, Field(description="Earlier shot the region refers to")] = None,
    format: Literal["png", "jpeg"] = "png",
    desktop: Masaustu = "auto",
) -> CallToolResult:
    """Image of a window (preferred: fewer tokens) or the whole screen. Coordinates are pixels of THIS image; pass its
    shot_id to click/scroll with x,y. Forbidden windows are blacked out."""
    with baglam(desktop, _("ekran görüntüsü: {pencere}").format(pencere=window or _("tüm ekran"))) as bilgi:
        k = api.pencere(window)
        bolge = None
        if region:
            if shot_id:
                c = cekim_coz(shot_id, k)
                x0, y0 = cekim_noktasi(c, region[0], region[1])
                bolge = [round(x0), round(y0), max(1, round(region[2] / c["olcek"])), max(1, round(region[3] / c["olcek"]))]
            else:
                bolge = list(region)
        with kilitli(), api.okuma(k):
            im, geo, kok, maskeler = api.goruntu_al(k, bolge)
        olcek = api.olcek_hesapla(*im.size, max_edge)
        if olcek < 1.0:
            from PIL import Image
            im = im.resize((max(1, round(im.width * olcek)), max(1, round(im.height * olcek))), Image.LANCZOS)
            if maskeler:  # küçültme kenarlara sızıntı (ringing) bırakmasın: maskeyi ölçekli görüntüye yeniden çiz
                from PIL import ImageDraw
                d = ImageDraw.Draw(im)
                for m_ in maskeler:
                    x, y_, g, h = m_["box"]
                    d.rectangle([int(x * olcek), int(y_ * olcek), int((x + g) * olcek + 1), int((y_ + h) * olcek + 1)],
                                fill=(0, 0, 0))
        sid = cekim_kaydet(k, api.arka().ad, geo, kok, olcek, im.size)
        tampon = io.BytesIO()
        if format == "jpeg":
            im.convert("RGB").save(tampon, "JPEG", quality=80)
        else:
            im.save(tampon, "PNG", optimize=True)
        meta = {**bilgi, "shot_id": sid, "width": im.width, "height": im.height, "scale": round(olcek, 4),
                "window": api.pencere_bilgi(k), "region_origin": list(kok),
                "redacted": [{"box": [round(v * olcek) for v in m["box"]]} for m in maskeler]}
        return CallToolResult(content=[
            ImageContent(type="image", data=base64.b64encode(tampon.getvalue()).decode(), mime_type=f"image/{format}"),
            TextContent(type="text", text=json.dumps(meta, ensure_ascii=False)),
        ], structured_content=meta)


@mcp.tool(title="Read text", annotations=OKUMA)
def read_text(
    window: Pencere = None,
    query: Annotated[str | None, Field(description="Only return matches of this text (Turkish-aware, fuzzy)")] = None,
    source: Literal["ocr", "tree"] = "ocr",
    region: Annotated[list[int] | None, Field(min_length=4, max_length=4, description="[x,y,w,h] window px")] = None,
    wait_s: Annotated[float, Field(ge=0, le=60, description="With query: wait until it appears")] = 0,
    deep: Annotated[bool, Field(description="Slower multi-pass OCR (coloured buttons)")] = False,
    max_items: Annotated[int, Field(ge=1, le=300)] = 80,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Read the text in a window by OCR (Turkish+English) or the accessibility tree. Boxes/centers are WINDOW pixels;
    the returned shot_id lets you click those coordinates. Forbidden windows are excluded."""
    with baglam(desktop, _("metin okuma: {pencere}").format(pencere=window or _("tüm ekran"))) as bilgi:
        k = api.pencere(window)
        with kilitli():
            if source == "tree":
                with api.okuma(k):
                    r = api.agac_oku(k, query, en_cok=max_items)
                geo = api.arka().geometri(k)
            else:
                r = api.metin_oku(k, query, region, deep, bekle=wait_s, en_cok=max_items)
                geo = r.pop("geometry")
        sid = cekim_kaydet(k, api.arka().ad, geo, (0, 0), 1.0, (geo[2], geo[3]))
        return {**bilgi, **r, "shot_id": sid, "window": api.pencere_bilgi(k)}


@mcp.tool(title="Find icon/colour", annotations=OKUMA)
def find(
    kind: Literal["icon", "color"],
    window: Pencere = None,
    name: Annotated[str | None, Field(description="Saved icon name (kind=icon)")] = None,
    color: Annotated[str | None, Field(description="yesil|kirmizi|mavi or R,G,B (kind=color)")] = None,
    threshold: Annotated[float, Field(ge=0.5, le=1.0)] = 0.9,
    region: Annotated[list[int] | None, Field(min_length=4, max_length=4)] = None,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Find a saved icon (template match) or coloured areas; does not click. For text use read_text. Centers are
    window pixels (use the returned shot_id to click them)."""
    with baglam(desktop, _("simge/renk arama: {pencere}").format(pencere=window or _("tüm ekran"))) as bilgi:
        k = api.pencere(window)
        with kilitli():
            if kind == "icon":
                if not name:
                    raise ToolError("[1] " + _("kind=icon için name gerekli"))
                r = api.simge_bul(k, name, threshold, region)
            else:
                if not color:
                    raise ToolError("[1] " + _("kind=color için color gerekli"))
                r = api.renk_bul(k, color, bolge=region)
        geo = r.pop("geometry")
        sid = cekim_kaydet(k, api.arka().ad, geo, (0, 0), 1.0, (geo[2], geo[3]))
        return {**bilgi, **r, "shot_id": sid}


@mcp.tool(title="Click", annotations=EYLEM)
def click(
    window: Annotated[str | None, Field(description="Target window (title pattern or id); may be omitted with "
                                                    "shot_id")] = None,
    text: Annotated[str | None, Field(description="Visible text to click (preferred)")] = None,
    icon: Annotated[str | None, Field(description="Saved icon name")] = None,
    element: Annotated[str | None, Field(description="Accessibility element name")] = None,
    x: Annotated[float | None, Field(description="Image x of shot_id")] = None,
    y: Annotated[float | None, Field(description="Image y of shot_id")] = None,
    shot_id: str | None = None,
    nth: Annotated[int | None, Field(ge=1, description="Which match when the text appears several times")] = None,
    button: Literal["left", "right", "middle", "double"] = "left",
    offset: Annotated[list[int] | None, Field(min_length=2, max_length=2,
                                              description="[dx,dy] from the text centre, e.g. field next to a "
                                                          "label")] = None,
    wait_s: Annotated[float, Field(ge=0, le=30, description="Wait for the text to appear")] = 0,
    scroll_search: Annotated[bool, Field(description="Scroll down to find the text")] = False,
    verify: Annotated[bool, Field(description="Report whether the window changed")] = True,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Click visible text (preferred), an icon, an accessibility element, or x,y of a screenshot (needs its shot_id;
    stale shots are refused). Give exactly ONE target. Sensitive buttons (Buy/Pay/Authorize...) or payment pages
    need the user's approval in the Deskhand panel; the server asks them."""
    hedefler = [t for t in (text, icon, element) if t] + (["xy"] if x is not None or y is not None else [])
    if len(hedefler) != 1:
        raise ToolError("[1] " + _("tam olarak BİR hedef ver: text, icon, element ya da x+y (+shot_id)"))
    with baglam(desktop, _("tıklama: {hedef} @ {pencere}").format(hedef=text or icon or element or _("koordinat"),
                                                                 pencere=window or _("görüntü"))) as bilgi:
        hata.dur_denetle()
        if x is not None or y is not None:
            if x is None or y is None:
                raise ToolError("[1] " + _("x ve y birlikte verilmeli"))
            k = api.pencere(window) if window else None
            c = cekim_coz(shot_id, k)
            k = c["k"]
            wx, wy = cekim_noktasi(c, x, y)
        else:
            k = _pencere_zorunlu(window)
        y_ = api.yasak_mi(k)
        if y_:
            raise ToolError("[10] " + _("yasak/hassas: yapılmadı: {neden}").format(neden=y_))
        desen = baslik_kilidi(window, k)
        once = {}

        def yap(onayli):
            once["ozet"] = _once(k) if verify else None
            if text:
                return api.metne_tikla(k, text, button, nth, wait_s, 10 if scroll_search else 0, desen, onayli,
                                       kay=offset)
            if icon:
                return api.simgeye_tikla(k, icon, button, nth, 0.9, desen, onayli)
            if element:
                return api.ogeye_tikla(k, element, button, nth, desen, onayli)
            return api.tikla(k, wx, wy, button, desen, onayli)
        mesaj, onaylandi = onayla_ve_yap("click", k, yap, " | " + _("hedef: {hedef}").format(
            hedef=text or icon or element or f"({x},{y})"))
        s = {**bilgi, "status": "clicked", "message": mesaj, "approved_by_user": onaylandi}
        if verify:
            s["after"] = _sonra(k, once.get("ozet"))
        return s


@mcp.tool(title="Type text", annotations=EYLEM)
def type_text(
    window: PencereZorunlu,
    text: Annotated[str, Field(max_length=2000, description="Text to type (Turkish letters OK; \\n = Enter; on a "
                                                             "payment page Enter/Tab/space need the user's approval)")],
    submit: Annotated[bool, Field(description="Press Enter afterwards")] = False,
    clear_first: Annotated[bool, Field(description="Select all (ctrl+a) first so the text replaces it")] = False,
    secret: Annotated[bool, Field(description="Do not write the text to the log")] = False,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Type into the focused field of the window (click the field first). Stops if the window/title changes or the
    user starts typing. Enter on a payment page needs the user's approval."""
    with baglam(desktop, _("yazı: {pencere}").format(pencere=window)) as bilgi:
        hata.dur_denetle()
        k = _pencere_zorunlu(window)
        desen = baslik_kilidi(window, k)
        metin_ = text + ("\n" if submit else "")  # submit = sondaki Enter: yazıyla TEK eylem, tek onay

        def yap(onayli):
            parcalar = []
            if clear_first:
                parcalar.append(api.tus(k, "ctrl+a", desen))
            parcalar.append(api.yaz(k, metin_, desen, secret, onayli))
            return "\n".join(p for p in parcalar if p)
        # ödeme sayfasında Enter/Tab/boşluklu yazı kullanıcı onayı ister (sunucu sorar)
        mesaj, onaylandi = onayla_ve_yap("type_text", k, yap)
        return {**bilgi, "status": "typed", "message": mesaj, "approved_by_user": onaylandi}


@mcp.tool(title="Press key", annotations=EYLEM)
def press_key(
    window: PencereZorunlu,
    keys: Annotated[str, Field(description="Key or shortcut: enter, esc, ctrl+s, alt+F4, 'ctrl+l ctrl+c' (sequence)")],
    repeat: Annotated[int, Field(ge=1, le=50)] = 1,
    hold_s: Annotated[float, Field(ge=0, le=10, description="Hold the key(s) down this long (games)")] = 0,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Send a key or shortcut to the window. Held keys are always released (cancel, STOP, shutdown). Enter/Space on a
    payment page needs the user's approval."""
    with baglam(desktop, _("tuş {tuslar}: {pencere}").format(tuslar=keys, pencere=window)) as bilgi:
        hata.dur_denetle()
        k = _pencere_zorunlu(window)
        desen = baslik_kilidi(window, k)

        def yap(onayli):
            if hold_s > 0:
                return api.bas(k, keys, hold_s, desen, onayli)
            # tekrar = TEK tuş dizisi (tek eylem): ödeme sayfasında N ayrı onay diyaloğu yerine bir onay
            return api.tus(k, " ".join([keys] * repeat), desen, onayli)
        mesaj, onaylandi = onayla_ve_yap("press_key", k, yap, " | " + _("tuş: {kombinasyon}").format(kombinasyon=keys))
        return {**bilgi, "status": "pressed", "message": mesaj, "approved_by_user": onaylandi}


@mcp.tool(title="Scroll", annotations=YUMUSAK)
def scroll(
    window: PencereZorunlu,
    direction: Literal["up", "down", "left", "right"] = "down",
    amount: Annotated[int, Field(ge=1, le=30)] = 3,
    x: float | None = None,
    y: float | None = None,
    shot_id: Annotated[str | None, Field(description="Needed with x,y (image pixels of that shot)")] = None,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Scroll the window (at its centre, or at x,y of shot_id). Returns whether the view changed."""
    with baglam(desktop, _("kaydırma: {pencere}").format(pencere=window)) as bilgi:
        hata.dur_denetle()
        k = _pencere_zorunlu(window)
        nokta = None
        if x is not None or y is not None:
            if x is None or y is None:
                raise ToolError("[1] " + _("x ve y birlikte verilmeli"))
            nokta = cekim_noktasi(cekim_coz(shot_id, k), x, y)
        desen = baslik_kilidi(window, k)
        with kilitli():
            once = _once(k)
            mesaj = api.kaydir(k, direction, amount, nokta, desen)
            sonra = _sonra(k, once, 0.3)
        return {**bilgi, "status": "scrolled", "message": mesaj, "changed": sonra.get("changed")}


@mcp.tool(title="Open app", annotations=YUMUSAK)
def open_app(
    app: Annotated[str, Field(description="Application name (.desktop entry) or executable")],
    args: Annotated[list[str] | None, Field(description="Arguments (runs app as an executable)")] = None,
    title: Annotated[str | None, Field(description="Wait for a window whose title matches this regex")] = None,
    wait_s: Annotated[float, Field(ge=1, le=120)] = 15,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """Start an application on the chosen desktop and wait for its new window (returns its id). Forbidden apps are
    not started. On the background desktop the user's logged-in sessions are reused when the app's policy allows
    (copy/share); single-instance apps already open on the user's screen may be refused ("wait")."""
    with baglam(desktop, _("uygulama aç: {uygulama}").format(uygulama=app)) as bilgi:
        hata.dur_denetle()
        ot = _oturum() if api.arka().ad == "sanal" else None
        if api.arka().ad == "sanal" and ot is None and not (os.path.isabs(app) and os.path.isfile(app)):
            # Politikasız başlatma kullanıcının GERÇEK uygulama verisini (profil, kasa, ayar) görünmez masaüstünden
            # değiştirebilir: oturum köprüsü yokken yalnız mutlak yollu komutlar (ör. test penceresi) başlatılır.
            raise ToolError("[10] " + _("oturum köprüsü yok: görünmez masaüstünde yalnız mutlak yollu bir komut "
                                        "başlatılabilir (app='/usr/bin/…', args=[...]); '{uygulama}' başlatılmadı. Gerçek "
                                        "uygulamalar için oturum politikası gerekir ya da desktop='foreground' "
                                        "(kullanıcının ekranı).").format(uygulama=app))
        argv, ad, yasak_metin = api.uygulama_komutu(app, args)
        env = None
        notlar = []
        if api.arka().ad == "sanal":
            if masaustu.durum() is None:
                masaustu.masaustu_baslat()
                notlar.append(_("görünmez masaüstü başlatıldı"))
            if ot is None:
                notlar.append(_("oturum köprüsü yok: politikasız başlatıldı (yalnız mutlak yollu komut; giriş "
                                "yapılmış oturum yok)"))
            else:
                # mutlak yol da politikadan geçer (ör. /usr/bin/telegram-desktop → bekle); bilinen bir uygulamaya
                # uymayan ham komut (test penceresi gibi) olduğu gibi başlatılır
                try:
                    h = ot.hazirla(app, ham_komut=os.path.isabs(app))
                except hata.Dur:
                    raise
                except Exception as e:  # noqa: BLE001
                    raise ToolError("[9] " + _("oturum hazırlanamadı: {hata}").format(hata=e)) from None
                karar = getattr(h, "karar", "")
                aciklama = getattr(h, "aciklama", "") or ""
                if karar == "bekle":
                    return {**bilgi, "status": "waiting", "window": None,
                            "message": aciklama or _("{uygulama} kullanıcının ekranında açık; aynı anda iki oturum "
                                                     "çakışır. Kullanıcı kapatınca yeniden dene ya da kullanıcıya sor."
                                                     ).format(uygulama=app)}
                if karar == "on":
                    return {**bilgi, "status": "foreground_only", "window": None,
                            "message": aciklama or _("{uygulama} görünmez masaüstünde açılamaz (şifre deposu ya da kasa "
                                                     "gerektiriyor); kullanıcı meşgul değilse desktop='foreground'."
                                                     ).format(uygulama=app)}
                if karar == "kapali":
                    raise ToolError("[10] " + _("yasak/hassas: yapılmadı: {uygulama} için oturum politikası 'kapali'"
                                                ).format(uygulama=app) + (f" ({aciklama})" if aciklama else ""))
                if karar in ("kopya", "paylas"):
                    if getattr(h, "argv", None):
                        argv = list(h.argv)
                        yasak_metin = [*yasak_metin, " ".join(argv)]
                    env = dict(getattr(h, "env_ek", None) or {}) or None
                    if karar == "kopya" and hasattr(ot, "parmak_kaydet"):
                        ot.parmak_kaydet(getattr(h, "kopya_yolu", None))
                    notlar.append(_("oturum politikası: {karar}").format(karar=karar)
                                  + (f" ({aciklama})" if aciklama else ""))
                elif karar:
                    raise ToolError("[1] " + _("bilinmeyen oturum kararı: {karar}").format(karar=repr(karar)))
        r = api.uygulama_ac(argv, ad, yasak_metin, env, title, wait_s)
        if notlar:
            r["notes"] = notlar
        return {**bilgi, **r}


@mcp.tool(title="Run flow", annotations=EYLEM)
def run_flow(
    action: Literal["list", "run"] = "list",
    name: Annotated[str | None, Field(description="Flow name (from list)")] = None,
    window: Annotated[str | None, Field(description="Target window for run")] = None,
    timeout_s: Annotated[float | None, Field(ge=1, le=600)] = None,
    desktop: Masaustu = "auto",
) -> dict[str, Any]:
    """List or run a saved flow (screen recognition -> steps, until success). Every step passes the same safety
    checks; a sensitive step stops the flow. Flows that contain pre-approved steps need the user's approval."""
    if action == "list":
        return {"status": "ok", "flows": api.akislar()}
    if not name:
        raise ToolError("[1] " + _("run için name gerekli (action=list ile adlar)"))
    with baglam(desktop, _("akış {ad}: {pencere}").format(ad=name, pencere=window)) as bilgi:
        hata.dur_denetle()
        k = _pencere_zorunlu(window)
        y_ = api.yasak_mi(k)
        if y_:
            raise ToolError("[10] " + _("yasak/hassas: yapılmadı: {neden}").format(neden=y_))
        yol = api.akis_yolu(name)
        onayli_adimlar = api.akis_onayli_adimlar(yol)  # ayrıştırılarak (alt dize değil; kısaltmalar geçmez)
        onaylandi = False
        if onayli_adimlar:
            izin, neden = _onay_iste("run_flow", api.arka().baslik(k),
                                     _("akış '{ad}' önceden onaylı (--onayli) adımlar içeriyor").format(ad=name)
                                     + "".join(f"\n• {x}" for x in onayli_adimlar[:8]),
                                     "arka" if api.arka().ad == "sanal" else "ekran")
            if not izin:
                raise ToolError("[10] " + _("kullanıcı onayı alınamadı: {neden}. Akış çalıştırılmadı; kullanıcıya "
                                            "bildir.").format(neden=neden or _("red")))
            onaylandi = True
        with kilitli():
            # onaylanmadıysa çalışırken --onayli adım reddedilir (ön taramadan sonra dosya değişmiş olsa bile)
            mesaj = api.akis_calistir(k, name, timeout_s, baslik_kilidi(window, k), onayli_izin=onaylandi)
        return {**bilgi, "status": "done", "message": mesaj[-3000:], "approved_by_user": onaylandi}


# ================================================================ kapanış

_KAPANIYOR = threading.Event()


def kapan(neden: str = "") -> None:
    """Basılı her şeyi bırak (≤400 ms) ve çık."""
    if _KAPANIYOR.is_set():
        os._exit(0)
    _KAPANIYOR.set()
    try:
        n = api.hepsini_birak(0.4)
        log.info("kapanış (%s): %d girdi bırakıldı", neden, n)
    finally:
        try:
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)


def _sinyal(signum, _frame):
    kapan(signal.Signals(signum).name)


def _ebeveyn_izle(ppid: int) -> None:
    while not _KAPANIYOR.is_set():
        if os.getppid() != ppid:
            kapan("ebeveyn süreç öldü")
        time.sleep(0.5)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--desktop" in argv:  # `deskhand mcp --desktop background` = deskhand-bg
        i = argv.index("--desktop")
        if i + 1 < len(argv) and argv[i + 1] == "background":
            os.environ["DESKHAND_MCP_SADECE_ARKA"] = "1"
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="deskhand-mcp %(levelname)s %(message)s")
    # güvenlik ağı: hedefi açıkça sabitlenmemiş (öngörülmemiş) bir sec() çağrısı görünmez masaüstüne gitsin
    os.environ["DESKHAND_HEDEF"] = "arka"
    from . import yollar
    from .gunluk import temizle
    try:
        yollar.gecis()
        temizle()
    except OSError as e:
        log.warning("hazırlık: %s", e)
    api.yakalayici_kur()
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _sinyal)
    threading.Thread(target=_ebeveyn_izle, args=(os.getppid(),), daemon=True).start()
    try:
        mcp.run()
    finally:
        kapan("sunucu bitti")


if __name__ == "__main__":
    main()
