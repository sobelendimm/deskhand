"""Günlük satırı → insan diliyle tek cümle (Etkinlik "Ne oldu", başlık şeridi, tepsi ipucu, "Ajan şu an"). Qt'siz.

Girdi: gunluk_okur.ayristir'ın sözlüğü. Çıktı etkin dilde (TR/EN) tek cümle; bilinmeyen satır için genel ama anlaşılır
bir cümle (asla boş, asla istisna). Ham satır KAYBOLMAZ: ``ayrinti()`` onu (yalnız yasak pencere başlığı ve URL
sorgusu/parçası maskeli) Ayrıntı sütununa/ipucuna verir.

Gizlilik (F2): gizli yazı/tuş satırında içerik, uzunluk ve "***" insan metnine çıkmaz; cümle sabit
``guvenlik.gizli_yer()`` kalıbını taşır. Yasak pencere başlığı (guvenlik.yasak_desenler + onay.YASAK_DESENLER) hiçbir
sütunda gösterilmez. Pencere kimliği ({d7bf}, arka:0x…) ve URL sorgusu/parçası (belirteç) kullanıcıya çıkmaz.
"""
from __future__ import annotations

import re
import time

from ..i18n import N_, _
from . import metinler as T

BILINMEYEN = N_("Deskhand bir işlem kaydetti (ayrıntı sütununda)")
PENCEREDE = N_("{uygulama} penceresinde {eylem}")  # EN: "{eylem} in {uygulama}"
YASAK_PENCERE = N_("(yasak pencere: gizlendi)")

# ---- çoğul: Türkçe sayıdan sonra tekil; İngilizce tekil/çoğul ayrı msgid (ngettext yerine; katalog düz sözlük)
TUS_TEKIL, TUS_COGUL = N_("1 tuş"), N_("{n} tuş")
KARAKTER_TEKIL, KARAKTER_COGUL = N_("1 karakter"), N_("{n} karakter")
ONAY_TEKIL, ONAY_COGUL = N_("1 onay isteği bekliyor"), N_("{n} onay isteği bekliyor")

# ---- eylem parçaları (küçük harfle başlar; cümle başı büyütülür)
TIK = {"sol": N_("tıklandı"), "sag": N_("sağ tıklandı"), "cift": N_("çift tıklandı"), "orta": N_("orta tuşla tıklandı"),
       "uclu": N_("üç kez tıklandı")}
OGE_TIK = {"sol": N_("'{hedef}' öğesine tıklandı"), "sag": N_("'{hedef}' öğesine sağ tıklandı"),
           "cift": N_("'{hedef}' öğesine çift tıklandı")}
METNE_TIK = N_("'{hedef}' yazısına tıklandı")
SIMGEYE_TIK = N_("'{hedef}' simgesine tıklandı")
RENGE_TIK = N_("renkli bir alana tıklandı")
OGE_ISLEM = N_("'{hedef}' öğesi kullanıldı")
YAZI = N_("{sayi} yazıldı")                  # sayi = KARAKTER_* ("12 karakter yazıldı")
OGEYE_YAZI = N_("'{hedef}' alanına {sayi} yazıldı")
GIZLI_YAZI = N_("yazı girildi {gizli}")       # gizli = guvenlik.gizli_yer()
GIZLI_TUS = N_("tuşlara basıldı {gizli}")
TUSA = N_("{tus} tuşuna basıldı")
KISAYOL = N_("{tus} kısayoluna basıldı")
TUSLARA = N_("{sayi}a basıldı")               # sayi = TUS_* ("3 tuşa basıldı")
BASILI = N_("{tus} tuşu basılı tutuldu")
BIRAKILDI = N_("{tus} tuşu bırakıldı")
BIRAKILDI_GENEL = N_("basılı tuşlar bırakıldı")
FARE = N_("fare imleci taşındı")
KAYDIR = {"asagi": N_("aşağı kaydırıldı"), "yukari": N_("yukarı kaydırıldı"), "sol": N_("sola kaydırıldı"),
          "sag": N_("sağa kaydırıldı")}
KAYDIR_GENEL = N_("sayfa kaydırıldı")
SURUKLE = N_("fareyle sürüklendi")
ACILDI = N_("{uygulama} açıldı")
ACILDI_GENEL = N_("bir uygulama açıldı")
KAPATILDI = N_("{uygulama} penceresi kapatıldı")
KAPATILDI_GENEL = N_("bir pencere kapatıldı")
OKUNDU = N_("{uygulama} penceresindeki yazı okundu")
OKUNDU_GENEL = N_("ekrandaki yazı okundu")
GORUNTU = N_("ekran görüntüsü alındı")
PENCERE_ISLEM = {"tasi": N_("pencere taşındı"), "boyut": N_("pencere boyutu değişti"),
                 "kucult": N_("pencere küçültüldü"), "buyut": N_("pencere büyütüldü"),
                 "geri": N_("pencere eski boyutuna döndü")}
PENCERE_GENEL = N_("pencere düzenlendi")
PANO_OKU = N_("pano okundu")
PANO_YAZ = N_("panoya yazı kondu")
DOSYA_SEC = N_("dosya seçildi")
AKIS = N_("kayıtlı akış çalıştırıldı")
ERISIM = N_("erişilebilirlik arayüzü kullanıldı")
GIRDI_GENEL = N_("bir girdi gönderildi")
# DUR satırı: hangi işlem durduruldu (ad) — iletinin kendisi (başlık, beklenen desen) gösterilmez
DURDURULDU = N_("{islem} güvenlik denetiminde durduruldu (kod {kod})")
DURDURULDU_GENEL = N_("bir işlem güvenlik denetiminde durduruldu")
ISLEM_ADI = {"tikla": N_("tıklama işlemi"), "yaz": N_("yazma"), "tus": N_("tuş basma"), "bas": N_("tuş basılı tutma"),
             "kaydir": N_("kaydırma"), "fare": N_("fare taşıma"), "surukle": N_("sürükleme işlemi"), "ac": N_("uygulamayı açma"),
             "kapat": N_("pencereyi kapatma"), "metne-tikla": N_("tıklama işlemi"), "ogeye-tikla": N_("tıklama işlemi"),
             "simgeye-tikla": N_("tıklama işlemi"), "renge-tikla": N_("tıklama işlemi"), "ogeye-yaz": N_("yazma"),
             "pano": N_("pano kullanımı"), "git": N_("adrese gitme"), "dizi": N_("adım dizisi"), "akis": N_("akış")}
ISLEM_GENEL = N_("bir işlem")
ONAY = N_("onay sorusu: {karar} ('{hedef}')")
ONAY_HEDEFSIZ = N_("onay sorusu: {karar}")
UYARI = N_("uyarı kaydedildi (ayrıntı sütununda)")
MASAUSTU_KAYDI = N_("arka plan masaüstü bildirimi (ayrıntı sütununda)")
BELLEK_KAYDI = N_("bellek bakımı yapıldı (ayrıntı sütununda)")
GIRDI_MERKEZI = N_("girdi hizmeti bildirimi (ayrıntı sütununda)")
PANEL_KAYDI = N_("panel bildirimi (ayrıntı sütununda)")

_TUS_AD = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Super", "meta": "Meta",
           "return": "Enter", "enter": "Enter", "kp_enter": "Enter", "escape": "Esc", "esc": "Esc", "tab": "Tab",
           "space": "Space", "backspace": "Backspace", "delete": "Delete"}
_KIMLIK = re.compile(r"^(?:\{[^}]*\}|arka:\S*|0x[0-9a-fA-F]+|\S*:\d+)(?:\s.*)?$")
_URL_SORGU = re.compile(r"((?:https?|file)://[^\s?#'\"\]]*)[?#][^\s'\"\]]*")
_TIRNAK = re.compile(r"'([^']*)'")


# ---------------------------------------------------------------- yardımcılar
def cogul(n: int, tekil: str, cok: str) -> str:
    """n'e göre tekil/çoğul msgid (TR'de ikisi de "N tuş"; EN "1 key" / "3 keys")."""
    return _(tekil) if n == 1 else _(cok).format(n=n)


def onay_bekliyor(n: int) -> str:
    return cogul(int(n), ONAY_TEKIL, ONAY_COGUL)


def _gizli_kaliplar() -> tuple[str, ...]:
    from .. import guvenlik
    return tuple({"(gizli yazı: gizlendi)", guvenlik.gizli_yer()})


def _gizli_yer() -> str:
    from .. import guvenlik
    return guvenlik.gizli_yer()


_YASAK: dict = {"t": 0.0, "desenler": None, "sabit": None}


def _yasak_onbellek_sifirla(desenler: list[str] | None) -> None:
    """Testler: yasak desenleri sabitle (None: gerçek kaynağa dön)."""
    _YASAK.update(t=0.0, desenler=None, sabit=[re.compile(d, re.I) for d in desenler] if desenler else None)


def _yasak_desenler() -> list:
    if _YASAK["sabit"] is not None:
        return _YASAK["sabit"]
    simdi = time.monotonic()
    if _YASAK["desenler"] is None or simdi - _YASAK["t"] > 5:
        from .. import guvenlik, onay
        try:
            ham = list(guvenlik.yasak_desenler())
        except Exception:  # noqa: BLE001 - liste okunamadı (Dur 10): en az yerleşikler
            ham = list(guvenlik.YERLESIK_YASAK)
        derli = []
        for d in ham + list(onay.YASAK_DESENLER):
            try:
                derli.append(re.compile(d, re.I))
            except re.error:
                continue
        _YASAK.update(t=simdi, desenler=derli)
    return _YASAK["desenler"]


def _yasak_mi(metin: str) -> bool:
    return bool(metin) and any(d.search(metin) for d in _yasak_desenler())


def _url_temizle(metin: str) -> str:
    return _URL_SORGU.sub(r"\1", metin)


def _bas_buyuk(s: str) -> str:
    if not s:
        return s
    from .. import i18n
    ilk = "İ" if s[0] == "i" and i18n.dil() == "tr" else s[0].upper()
    return ilk + s[1:]


def _gizli(d: dict) -> bool:
    eylem = str(d.get("eylem") or "")
    pencere = str(d.get("pencere") or "")
    return bool(d.get("gizli")) or "***" in eylem or any(k in pencere or k in eylem for k in _gizli_kaliplar())


def _pencereli(d: dict) -> bool:
    """Satırın "pencere" alanı gerçekten bir pencere başlığı mı (pano/choose-file/akış satırlarında değil)."""
    return "etiket" in d


def pencere_metni(d: dict) -> str:
    """Pencere sütunu: başlık (URL sorgusu/parçası atılmış); kimlik ve pencere olmayan alan → ""; yasak → maske;
    gizli yazı satırında gizli kalıbı."""
    try:
        p = str(d.get("pencere") or "")
        if not p:
            return ""
        if any(k in p for k in _gizli_kaliplar()):
            return _gizli_yer()
        etiket = str(d.get("eylem") or "").partition(": ")[0]
        if d.get("tur") == "dur" or _KIMLIK.match(p) or not (_pencereli(d) or etiket == "ac"):
            return ""
        if _yasak_mi(p):
            return _(YASAK_PENCERE)
        return _url_temizle(p)[:120]
    except Exception:  # noqa: BLE001
        return ""


def _uygulama(d: dict) -> str:
    """Cümlede kullanılacak kısa uygulama adı: başlığın son "— X" / "- X" parçası."""
    p = pencere_metni(d)
    if not p or p in (_(YASAK_PENCERE), _gizli_yer()):
        return ""
    for ayrac in (" — ", " – ", " - "):
        if ayrac in p:
            p = p.rsplit(ayrac, 1)[1]
            break
    p = p.strip()
    return p if len(p) <= 40 else p[:39] + "…"


def ayrinti(d: dict) -> str:
    """Ayrıntı sütunu/ipucu: ham günlük satırı. Yalnız yasak pencere başlığı ([…] ya da '…' içinde) ve URL
    sorgusu/parçası maskelenir; gizli yazı zaten günlükte maskelidir (type ***, (gizli yazı: gizlendi))."""
    try:
        ham = str(d.get("ham") or "")

        def kapali(m):
            ic = m.group(0)[1:-1]
            if not ic or any(k in ic for k in _gizli_kaliplar()) or not _yasak_mi(ic):
                return m.group(0)
            return m.group(0)[0] + _(YASAK_PENCERE) + m.group(0)[-1]
        ham = re.sub(r"\[[^\]]*\]|'[^']*'", kapali, ham)
        return _url_temizle(ham)
    except Exception:  # noqa: BLE001
        return ""


def _tus_adi(k: str) -> str:
    parcalar = []
    for p in k.split("+"):
        a = _TUS_AD.get(p.lower())
        parcalar.append(a or (p.upper() if len(p) == 1 else p[:1].upper() + p[1:]))
    return "+".join(parcalar)


def _hedef(arg: str) -> str:
    m = _TIRNAK.search(arg)
    h = _url_temizle(m.group(1)) if m else ""
    if _yasak_mi(h):
        return _(YASAK_PENCERE)
    return h if len(h) <= 60 else h[:59] + "…"


def _sayi(s: str) -> int | None:
    m = re.search(r"(\d+) karakter", s)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- komut etiketi → eylem parçası
def komut_parcasi(etiket: str, gizli: bool = False) -> str | None:
    """Komut etiketi ("tikla (5,5) sol", "tus ctrl+s", "yaz 12 karakter") → küçük harfli eylem parçası; bilinmeyen
    → None. Gizli: içerik/uzunluk yok, gizli kalıbı var."""
    et = str(etiket or "").strip()
    if et.startswith("dizi: "):
        et = et[6:]
    kom, _b, arg = et.partition(" ")
    arg = re.sub(r"\s--\S+", "", " " + arg).strip()
    sozler = arg.split()
    if kom in ("yaz", "ogeye-yaz") and gizli:
        return _(GIZLI_YAZI).format(gizli=_gizli_yer())
    if kom in ("tus", "bas") and (gizli or "***" in arg):
        return _(GIZLI_TUS).format(gizli=_gizli_yer())
    if kom == "tikla":
        return _(TIK.get(sozler[-1] if sozler else "sol", TIK["sol"]))
    if kom == "ogeye-tikla":
        if "--eylem" in et:
            return _(OGE_ISLEM).format(hedef=_hedef(arg))
        dugme = sozler[-1] if sozler else "sol"
        return _(OGE_TIK.get(dugme, OGE_TIK["sol"])).format(hedef=_hedef(arg))
    if kom == "metne-tikla":
        return _(METNE_TIK).format(hedef=_hedef(arg))
    if kom == "simgeye-tikla":
        return _(SIMGEYE_TIK).format(hedef=_hedef(arg))
    if kom == "renge-tikla":
        return _(RENGE_TIK)
    if kom == "yaz":
        n = _sayi(arg)
        return _(YAZI).format(sayi=cogul(n, KARAKTER_TEKIL, KARAKTER_COGUL)) if n is not None else None
    if kom == "ogeye-yaz":
        n = _sayi(arg)
        if n is None:
            return None
        return _(OGEYE_YAZI).format(hedef=_hedef(arg), sayi=cogul(n, KARAKTER_TEKIL, KARAKTER_COGUL))
    if kom == "tus" and sozler:
        if len(sozler) > 1:
            return _(TUSLARA).format(sayi=cogul(len(sozler), TUS_TEKIL, TUS_COGUL))
        return _(KISAYOL if "+" in sozler[0] else TUSA).format(tus=_tus_adi(sozler[0]))
    if kom == "bas" and sozler:
        return _(BASILI).format(tus=_tus_adi(sozler[0]))
    if kom == "kaydir":
        return _(KAYDIR.get(sozler[0], KAYDIR_GENEL)) if sozler else _(KAYDIR_GENEL)
    if kom == "fare":
        return _(FARE)
    if kom == "surukle":
        return _(SURUKLE)
    if kom == "foto":
        return _(GORUNTU)
    if kom in ("metin", "agac", "bul", "erisim-oku"):
        return _(OKUNDU_GENEL)
    return None


# ---------------------------------------------------------------- satır → cümle
def _dur(eylem: str) -> str:
    if eylem.startswith("DUR anahtarı"):
        return _(T.GUNLUK_ESLEME[eylem]) if eylem in T.GUNLUK_ESLEME else _(DURDURULDU_GENEL)
    m = re.match(r"^DUR (\d+) · ([a-z-]+):", eylem)
    if not m:
        return _(DURDURULDU_GENEL)
    ad = ISLEM_ADI.get(m.group(2))
    return _(DURDURULDU).format(islem=_(ad) if ad else _(ISLEM_GENEL), kod=m.group(1))


def _onay(d: dict, eylem: str) -> str:
    etiket, _a, kalan = eylem.partition(": ")
    karar_kod = etiket.split(" ", 1)[1] if " " in etiket else ""
    karar = _(T.O_KARAR[karar_kod]) if karar_kod in T.O_KARAR else _(T.O_KARAR["bekliyor"])
    hedef = _hedef(kalan)
    return _(ONAY).format(karar=karar, hedef=hedef) if hedef else _(ONAY_HEDEFSIZ).format(karar=karar)


def _girdi(d: dict, eylem: str) -> str | None:
    etiket = str(d.get("etiket") or eylem.partition(": ")[0])
    gizli = _gizli(d)
    if "etiket" not in d and ": bırak " in eylem:  # "bas w: bırak keyup w"
        kom, _b, arg = etiket.partition(" ")
        if gizli or "***" in eylem:
            return _(GIZLI_TUS).format(gizli=_gizli_yer())
        if kom == "bas" and arg.split():
            return _(BIRAKILDI).format(tus=_tus_adi(arg.split()[0]))
        return _(BIRAKILDI_GENEL)
    if etiket == "ac":
        p = pencere_metni(d)
        return _(ACILDI).format(uygulama=p) if p else _(ACILDI_GENEL)
    if etiket.startswith("akis "):
        return _(AKIS)
    uyg = _uygulama(d)
    if etiket == "kapat":
        return _(KAPATILDI).format(uygulama=uyg) if uyg else _(KAPATILDI_GENEL)
    if etiket == "metin" and uyg:
        return _(OKUNDU).format(uygulama=uyg)
    if gizli and not etiket.startswith(("yaz", "ogeye-yaz", "tus", "bas", "dizi")):
        parca = _(GIZLI_YAZI).format(gizli=_gizli_yer())
    else:
        parca = komut_parcasi(etiket, gizli=gizli)
        if parca is None and gizli:
            parca = _(GIZLI_YAZI).format(gizli=_gizli_yer())
    if parca is None:
        parca = _(GIRDI_GENEL)
    return _(PENCEREDE).format(uygulama=uyg, eylem=parca) if uyg else parca


def _diger(eylem: str) -> str | None:
    bas, _a, kalan = eylem.partition(": ")
    if eylem.startswith("UYARI") or bas.startswith("UYARI"):
        return _(UYARI)
    if bas == "pano oku":
        return _(PANO_OKU)
    if bas == "pano yaz":
        return _(PANO_YAZ)
    if bas == "choose-file":
        return _(DOSYA_SEC)
    if bas == "erisim":
        return _(ERISIM)
    if bas == "pencere":
        islem = kalan.split(" ", 1)[0]
        return _(PENCERE_ISLEM.get(islem, PENCERE_GENEL))
    if bas.startswith("masaustu"):
        return _(MASAUSTU_KAYDI)
    if bas.startswith("bellek"):
        return _(BELLEK_KAYDI)
    if bas.startswith("girdi merkezi"):
        return _(GIRDI_MERKEZI)
    if bas.startswith(("PANEL", "panel", "anahtarlık", "kalıcı oturum")):
        return _(PANEL_KAYDI)
    return None


def insan_metni(d: dict | None) -> str:
    """Günlük satırı (ayristir sözlüğü) → etkin dilde tek cümle. Asla boş, asla istisna."""
    try:
        d = d if isinstance(d, dict) else {}
        eylem = str(d.get("eylem") or "")
        tur = d.get("tur")
        if eylem in T.GUNLUK_ESLEME:
            s = _(T.GUNLUK_ESLEME[eylem])
        elif tur == "dur":
            s = _dur(eylem)
        elif tur == "onay":
            s = _onay(d, eylem)
        elif tur == "girdi":
            s = _girdi(d, eylem)
        else:
            s = _diger(eylem)
        if s:
            ad = _uygulama(d) or pencere_metni(d)
            if ad and s.startswith(ad):  # cümle uygulama adıyla başlıyor (kcalc açıldı): ad olduğu gibi kalır
                return s
    except Exception:  # noqa: BLE001 - görüntüleme asla düşmez
        s = None
    return _bas_buyuk(s) if s else _(BILINMEYEN)
