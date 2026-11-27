"""`deskhand sessions check <alan>` (denetle): bir site için arka plan Firefox'u girişli açılır mı? SALT OKUMA.

Kullanıcının Firefox profilinde (cookies.sqlite = kalıcı çerezler; sessionstore-backups/recovery.jsonlz4 = süresiz
oturum çerezleri) ve en yeni Firefox oturum kopyasında o sitenin oturum çerezlerine bakar: var mı, kalıcı mı süresiz
mi, süresi geçmiş mi, kopyadaki değer profildekiyle aynı mı (kopya güncel mi).

Gizlilik: çerez DEĞERLERİ hiçbir çıktıya/günlüğe girmez; karşılaştırma bellekte SHA-256 özetiyle yapılır ve özet de
yazılmaz. Kaynak profil YAZILMAZ: cookies.sqlite geçici 0700 klasöre tutarlı kopyalanıp (kopya.sqlite_yedek) oradan
okunur, klasör iş bitince silinir.

Hangi çerez "oturum" (giriş) çerezidir? --cerez AD (fnmatch, tekrarlanabilir) verilirse yalnız onlar; verilmezse ad
deseni (_GIRIS_DESENI: session, sess, sid, auth, token, login, user, account, buyer…). Karar:
  profil  var           : geçerli (süresi geçmemiş) giriş çerezi var ve süresi GEÇMİŞ kalıcı giriş çerezi yok
                          (ya da geçmişin yanında geçerli bir kalıcı giriş çerezi de var)
          suresi_gecmis : kalıcı giriş çerezlerinin süresi dolmuş, geçerli kalıcı yok (örnek olay: bir satıcı
                          panelinin sec_session_id çerezi 2 saat kayan ömürlü; kullanıcı 12 saattir girmemişti, kendi
                          Firefox'u da giriş istedi; tarayıcı oturumunun PHPSESSID'i ise hâlâ duruyordu; docs/SESSIONS.md §3.4.1)
          yok           : giriş çerezi hiç yok
          politika_disi : giriş çerezleri ret listesinde / görev izni dışında (kopyaya hiç taşınmaz)
  kopya   guncel        : kopyanın kendi giriş çerezleri aynı ölçüte göre 'var' ve profilde daha yenisi yok
          eski          : profildeki geçerli giriş çerezi kopyada yok ya da kopya alındıktan SONRA yenilenmiş
          oturumsuz     : kopyanın giriş çerezleri 'var' değil
          yok           : Firefox kopyası yok (önce bağlamdaki masaüstününkiler, sonra en yeni kopya aranır)
Kalıcı depo ([oturum] kalici, kalici.py; docs/SESSIONS.md §3.8): listedeki sitede depodaki giriş çerezleri aynı ölçütle
          sınıflanır (kalici.durum: listede_degil | gorev | politika_disi | var | suresi_gecmis | yok).
Çıkış kodu: 0 = kopya 'guncel' ya da kopya yok ve profil ya da kalıcı depo 'var' (sonraki `open firefox` onu alır);
            1 = değil (kullanıcı giriş yapmalı ya da kopya tazelenmeli: `deskhand open firefox`); 2 = kullanım hatası.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time

from . import firefox, kopya, politika, tespit

_GIRIS_DESENI = re.compile(
    r"sess|(^|[_\-.])sid($|[_\-.])|^sid|auth|token|login|logged|user|account|member|buyer|customer|remember|jwt|"
    r"identity|^li_at$|^_?ga_?sess", re.I)


def alan_normu(girdi: str) -> str | None:
    """'https://www.ornek.test/yol?x' / 'ornek.test.' / '.ornek.test' → 'www.ornek.test' / 'ornek.test'. Geçersiz → None."""
    from urllib.parse import urlsplit
    s = (girdi or "").strip().lower()
    if "://" in s:
        try:
            s = urlsplit(s).hostname or ""
        except ValueError:
            return None
    s = s.split("/")[0].split(":")[0].strip(".")
    if not s or "." not in s or not re.fullmatch(r"[a-z0-9.-]+", s) or ".." in s:
        return None
    return s


def _konak_eslesir(host: str, alan: str) -> bool:
    """Çerez bu siteye gider mi (ya da sitenin alt alanına aittir mi)? host = alan, host alt alan, ya da host üst alan
    çerezi ('.ornek.test' → www.ornek.test)."""
    h = (host or "").lower()
    d = h.lstrip(".")
    if not d:
        return False
    if d == alan or d.endswith("." + alan):
        return True
    return h.startswith(".") and alan.endswith("." + d) and "." in d


def _ozet(deger) -> str:
    return hashlib.sha256(str(deger if deger is not None else "").encode("utf-8", "surrogatepass")).hexdigest()


def _ms(expiry: int, ms_birim: bool) -> int:
    return int(expiry) if ms_birim else int(expiry) * 1000


def _kalici_oku(cookies_db: str, alan: str) -> list[dict]:
    """cookies.sqlite'tan bu siteye giden kalıcı çerezler (ham kaynak dosyaya bağlanılmaz: geçici 0700 kopya)."""
    if not os.path.isfile(cookies_db):
        return []
    sonuc = []
    with tempfile.TemporaryDirectory(prefix="deskhand-denetle-") as td:
        os.chmod(td, 0o700)
        gecici = os.path.join(td, "c.sqlite")
        try:
            kopya.sqlite_yedek(cookies_db, gecici)
            con = sqlite3.connect(gecici)
            try:
                (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies").fetchone()
                ms_birim = not enbuyuk or enbuyuk > 1e11
                for name, value, host, path, expiry, oa, creation in con.execute(
                        "SELECT name, value, host, path, expiry, originAttributes, creationTime FROM moz_cookies"):
                    if not _konak_eslesir(host, alan):
                        continue
                    sonuc.append({"ad": name or "", "konak": host or "", "yol": path or "/", "oa": oa or "",
                                  "tur": "kalici", "bitis_ms": _ms(expiry or 0, ms_birim),
                                  "olusma_s": (creation or 0) / 1e6, "_oz": _ozet(value)})
            finally:
                con.close()
        except (sqlite3.Error, OSError):
            return []
    return sonuc


def _suresiz_oku(recovery: str, alan: str) -> list[dict]:
    """recovery.jsonlz4 kökündeki `cookies` (süresiz oturum çerezleri: Firefox bunları cookies.sqlite'a YAZMAZ)."""
    if not os.path.isfile(recovery):
        return []
    ham = firefox.mozlz4_coz(recovery)
    if ham is None:
        return []
    try:
        cerezler = json.loads(ham).get("cookies") or []
    except (ValueError, UnicodeDecodeError, AttributeError):
        return []
    sonuc = []
    for c in cerezler:
        if not isinstance(c, dict) or not _konak_eslesir(c.get("host", ""), alan):
            continue
        oa = firefox.oa_soneki(c.get("originAttributes", ""))
        if oa is None:
            continue
        sonuc.append({"ad": c.get("name", ""), "konak": c.get("host", ""), "yol": c.get("path", "/"), "oa": oa,
                      "tur": "suresiz", "bitis_ms": None, "olusma_s": None, "_oz": _ozet(c.get("value"))})
    return sonuc


def _profil_cerezleri(profil: str, alan: str) -> list[dict]:
    return (_kalici_oku(os.path.join(profil, "cookies.sqlite"), alan) +
            _suresiz_oku(os.path.join(profil, "sessionstore-backups", "recovery.jsonlz4"), alan))


def _anahtar(c: dict) -> tuple:
    return (c["ad"], c["konak"], c["yol"], c["oa"])


def _giris_mi(ad: str, desenler) -> bool:
    if desenler:
        return any(fnmatch.fnmatchcase(ad, d) or fnmatch.fnmatchcase(ad.lower(), d.lower()) for d in desenler)
    return bool(_GIRIS_DESENI.search(ad or ""))


def _bilinen_konaklar(profil: str) -> set[str]:
    """Hosts known from the profile, the same set firefox.hazirla passes to Politika.cerez_reddedildi (cookie hosts,
    site storage, session cookies, open tabs, places.sqlite). The profile's cookies.sqlite is NOT opened: it is read
    from a consistent temporary 0700 copy (kopya.sqlite_yedek), like _kalici_oku. Unreadable → empty set."""
    cookies_db = os.path.join(profil, "cookies.sqlite")
    rec = firefox._recovery_oku(os.path.join(profil, "sessionstore-backups", "recovery.jsonlz4"))
    with tempfile.TemporaryDirectory(prefix="deskhand-denetle-") as td:
        os.chmod(td, 0o700)
        gecici = os.path.join(td, "c.sqlite")
        try:
            if os.path.isfile(cookies_db):
                kopya.sqlite_yedek(cookies_db, gecici)
        except (sqlite3.Error, OSError):
            pass
        try:
            # no copy (missing/unreadable source): sqlite opens an empty file inside td, the query error is caught
            # inside and only the cookie hosts are missing; the other sources still count
            return firefox._bilinen_konaklar(profil, gecici, rec)
        except (sqlite3.Error, OSError):
            return set()


def _aktarim_suzgeci(bilinen_konaklar=()):
    """→ f(host) True: bu konağın çerezi kopyaya TAŞINIR (firefox.hazirla ile aynı kurallar: ret listesi, panelin
    hesap oturumu izni, görev kipinde yalnız görev siteleri). Süresiz çerez için site izni de gerekir.
    bilinen_konaklar: see Politika.cerez_reddedildi (a domain cookie sent to a rejected known subdomain is rejected)."""
    pol = politika.coz("firefox")
    from .. import gorev_kipi
    gorev = gorev_kipi.etkin()
    gorev_siteleri = gorev_kipi.siteler() if gorev else None
    if not gorev:
        from .. import liste_koruma
        try:
            pol = pol.kimlik_izni_uygula(liste_koruma.kimlik_izinleri())
        except Exception:  # noqa: BLE001 - doğrulanamadı: güvenli taraf (izin yok)
            pass

    def tasinir(host: str, suresiz: bool = False) -> bool:
        a = firefox._alan(host)
        if not a or pol.cerez_reddedildi(host, bilinen_konaklar):
            return False
        if suresiz and not pol.site_izinli(a, gorev_siteleri):
            return False
        return not gorev or firefox.gorev_izinli(pol, a, gorev_siteleri)
    return tasinir


def firefox_kopyalari() -> list[dict]:
    """Firefox oturum kopyaları (kopya.kopyalar biçiminde), önce bağlamdaki masaüstününkiler, sonra en yeni."""
    kok = os.path.realpath(politika.kopya_dizini())
    try:
        liste = [g for g in kopya.kopyalar(boyut=False) if os.path.basename(g["yol"]).startswith("firefox-")]
    except Exception:  # noqa: BLE001
        return []
    return sorted(liste, key=lambda g: (os.path.realpath(g["kok"]) == kok, g["canli"], g["zaman"]), reverse=True)


def denetle(alan: str, desenler=None, kopya_yolu: str | None = None, simdi: float | None = None) -> dict:
    """Durum sözlüğü (DEĞER YOK): {alan, profil, profil_durum, kopya, kopya_durum, kopya_zaman, cerezler[], kod, neden}."""
    simdi = time.time() if simdi is None else simdi
    simdi_ms = simdi * 1000
    sonuc = {"alan": alan, "profil": None, "profil_durum": "yok", "kopya": None, "kopya_durum": "yok",
             "kopya_zaman": None, "cerezler": [], "kod": 1, "neden": ""}
    profil = tespit.firefox_profil_dizini()
    if not profil or not os.path.isdir(profil):
        sonuc["neden"] = "profil_yok"
        return sonuc
    sonuc["profil"] = profil
    tasinir = _aktarim_suzgeci(_bilinen_konaklar(profil))
    prof = [c for c in _profil_cerezleri(profil, alan) if _giris_mi(c["ad"], desenler)]

    if kopya_yolu is None:
        k = firefox_kopyalari()
        if k:
            kopya_yolu, sonuc["kopya_zaman"] = k[0]["yol"], k[0]["zaman"]
    elif os.path.isdir(kopya_yolu):
        sonuc["kopya_zaman"] = os.lstat(kopya_yolu).st_mtime
    kop_tum: list[dict] = []
    if kopya_yolu and os.path.isdir(kopya_yolu):
        sonuc["kopya"] = kopya_yolu
        kop_tum = [c for c in _profil_cerezleri(kopya_yolu, alan) if _giris_mi(c["ad"], desenler)]
    kop = {}
    for c in kop_tum:
        if not _gecmis(c, simdi_ms):
            kop.setdefault(_anahtar(c), c)

    eski = False
    for c in prof:
        tas = tasinir(c["konak"], suresiz=c["tur"] == "suresiz")
        satir = {"ad": c["ad"], "konak": c["konak"], "tur": c["tur"], "tasinir": tas,
                 "kalan_sn": None if c["bitis_ms"] is None else int((c["bitis_ms"] - simdi_ms) / 1000)}
        if _gecmis(c, simdi_ms):
            satir["kopyada"] = None
        else:
            k = kop.get(_anahtar(c))
            if sonuc["kopya"] is None:
                satir["kopyada"] = None
            elif k is None:
                satir["kopyada"] = "yok"
                eski = eski or tas
            elif k["_oz"] == c["_oz"]:
                satir["kopyada"] = "ayni"
            else:
                # kopya alındıktan SONRA profilde yeniden oluşturulmuşsa (yeniden giriş) kopya eskidir; süresiz
                # çerezin zamanı bilinmez: kopyada da geçerli bir değer var, site kopyada döndürmüş olabilir
                yeni = (c["olusma_s"] or 0) > (sonuc["kopya_zaman"] or 0)
                satir["kopyada"] = "eski" if yeni else "farkli"
                eski = eski or (yeni and tas)
        sonuc["cerezler"].append(satir)

    sonuc["profil_durum"] = _siniflandir(prof, simdi_ms, tasinir)
    sonuc["kalici"] = _kalici_durum(alan, desenler, simdi, {_anahtar(c) for c in prof if c["tur"] == "suresiz"})
    if sonuc["kopya"] is None:
        sonuc["kopya_durum"] = "yok"
        # the next `open firefox` takes the profile's session, or the persistent store's ([oturum] kalici)
        sonuc["kod"] = 0 if "var" in (sonuc["profil_durum"], sonuc["kalici"]["durum"]) else 1
    else:
        # kopya kendi çerezleriyle aynı ölçütten geçer (kopyada da süresi geçmiş kalıcı giriş çerezi + yalnız
        # süresiz PHPSESSID = oturumsuz); kullanıcı kopyada giriş yaptıysa profil oturumsuz olsa da kopya geçerlidir
        # kopya, profilin süresiz çerezlerini kalıcı (1 gün) yazar: sınıflandırmada yine süresiz sayılır
        suresiz = {_anahtar(c) for c in prof if c["tur"] == "suresiz"}
        kd = _siniflandir([{**c, "tur": "suresiz"} if _anahtar(c) in suresiz else c for c in kop_tum],
                          simdi_ms, lambda *_a, **_k: True)
        sonuc["kopya_durum"] = "oturumsuz" if kd != "var" else ("eski" if eski else "guncel")
        sonuc["kod"] = 0 if sonuc["kopya_durum"] == "guncel" else 1
    sonuc["neden"] = "" if sonuc["kod"] == 0 else (
        "kopya_eski" if sonuc["kopya_durum"] == "eski" else sonuc["profil_durum"])
    return sonuc


def _kalici_durum(alan: str, desenler, simdi: float, profil_suresiz: set) -> dict:
    """The persistent store's answer for the site (kalici.durum, value-free): {listede, durum, cerez, kalan_sn}.
    durum: listede_degil | gorev (not used in task mode) | politika_disi (reject list) | var | suresi_gecmis | yok,
    the same login-cookie rules as the profile | okunamadi (the key ring is not available: `neden`). kayit / bitis:
    when the record was saved and when its last live cookie expires (epoch seconds; no values). A stored cookie
    that is session-only in the profile counts as session-only (the copy wrote it with a one-day expiry), like the
    copy's own cookies."""
    from .. import gorev_kipi
    from . import kalici
    kd = kalici.durum(alan, simdi=simdi)
    giris = [{"ad": c["ad"], "konak": c["konak"], "oa": "", "yol": "",
              "tur": "suresiz" if c["oturumluk"] else "kalici", "bitis_ms": c["bitis"] * 1000}
             for c in kd["cerezler"] if _giris_mi(c["ad"], desenler)]
    for c in giris:
        if any(k[0] == c["ad"] and k[1] == c["konak"] for k in profil_suresiz):
            c["tur"] = "suresiz"
    if not kd["listede"]:
        durum = "listede_degil"
    elif gorev_kipi.etkin():
        durum = "gorev"
    elif kd["reddedildi"]:
        durum = "politika_disi"
    elif kd.get("neden"):
        durum = "okunamadi"  # no key (locked wallet…): closed-fail, the store is not used
    else:
        durum = _siniflandir(giris, simdi * 1000, lambda *_a, **_k: True)
    gecerli = [c["bitis_ms"] for c in giris if not _gecmis(c, simdi * 1000)]
    return {"listede": kd["listede"], "durum": durum, "cerez": len(giris), "neden": kd.get("neden"),
            "kayit": kd.get("kayit"), "bitis": kd.get("bitis"),
            "kalan_sn": int((float(min(gecerli)) - simdi * 1000) / 1000) if gecerli and durum == "var" else None}


def _tarih(sn: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(sn))


def _gecmis(c: dict, simdi_ms: float) -> bool:
    return c["bitis_ms"] is not None and c["bitis_ms"] <= simdi_ms


def _siniflandir(cerezler: list[dict], simdi_ms: float, tasinir) -> str:
    """Giriş çerezleri kümesi → var | suresi_gecmis | yok | politika_disi (modül belgesindeki kurallar)."""
    if not cerezler:
        return "yok"
    gecerli = [c for c in cerezler if not _gecmis(c, simdi_ms)]
    gecmis_kalici = any(_gecmis(c, simdi_ms) for c in cerezler)
    if gecmis_kalici and not any(c["tur"] == "kalici" for c in gecerli):
        return "suresi_gecmis"
    if not gecerli:
        return "yok"
    if not any(tasinir(c["konak"], suresiz=c["tur"] == "suresiz") for c in gecerli):
        return "politika_disi"
    return "var"


def _sure_metni(sn: int) -> str:
    from ..i18n import _
    m = abs(sn) // 60
    s, dk = divmod(m, 60)
    g, s = divmod(s, 24)
    parca = (_("{g} gün {s} sa").format(g=g, s=s) if g else
             _("{s} sa {dk} dk").format(s=s, dk=dk) if s else _("{dk} dk").format(dk=dk))
    return _("{sure} kaldı").format(sure=parca) if sn > 0 else _("süresi {sure} önce geçti").format(sure=parca)


def metin(d: dict) -> list[str]:
    """İnsan okunur satırlar (değer YOK)."""
    from ..i18n import _
    durum_adi = {"var": _("oturum var"), "suresi_gecmis": _("oturum çerezlerinin süresi geçmiş (giriş gerekir)"),
                 "yok": _("oturum çerezi yok (giriş gerekir)"),
                 "politika_disi": _("oturum çerezleri politika dışı (ret listesi / görev izni): kopyaya taşınmaz")}
    kopya_adi = {"guncel": _("güncel, oturum var"), "eski": _("ESKİ: profilde daha yeni oturum var (tazeleyin: deskhand open firefox)"),
                 "oturumsuz": _("oturum yok (süresi geçmiş ya da eksik)"),
                 "yok": _("yok (sonraki `deskhand open firefox` profildeki oturumu alır)")}
    if d.get("neden") == "profil_yok":
        return [_("Firefox profili bulunamadı (profiles.ini)"), _("sonuç: oturum YOK")]
    satirlar = [_("site: {alan}").format(alan=d["alan"]),
                _("profil: {durum}").format(durum=durum_adi.get(d["profil_durum"], d["profil_durum"]))]
    for c in d["cerezler"]:
        tur = _("kalıcı") if c["tur"] == "kalici" else _("süresiz (tarayıcı oturumu)")
        sure = "" if c["kalan_sn"] is None else ", " + _sure_metni(c["kalan_sn"])
        kopyada = {"ayni": _("kopyada aynı"), "farkli": _("kopyada farklı değer"), "eski": _("kopyadaki ESKİ"),
                   "yok": _("kopyada YOK"), None: ""}.get(c.get("kopyada"), "")
        ek = [x for x in (kopyada, "" if c["tasinir"] else _("taşınmaz (politika)")) if x]
        satirlar.append(f"  {c['ad']} @ {c['konak']}: {tur}{sure}" + (f" — {', '.join(ek)}" if ek else ""))
    if d.get("kopya"):
        zaman = time.strftime("%H:%M:%S", time.localtime(d["kopya_zaman"])) if d.get("kopya_zaman") else "?"
        satirlar.append(_("kopya: {durum} ({ad}, {zaman})").format(
            durum=kopya_adi.get(d["kopya_durum"], d["kopya_durum"]), ad=os.path.basename(d["kopya"]), zaman=zaman))
    else:
        satirlar.append(_("kopya: {durum}").format(durum=kopya_adi["yok"]))
    k = d.get("kalici") or {}
    if k.get("listede"):
        kalici_adi = {"var": _("oturum var ({sayi} giriş çerezi)").format(sayi=k.get("cerez", 0)),
                      "suresi_gecmis": _("giriş çerezlerinin süresi geçmiş (giriş gerekir)"),
                      "yok": _("kayıt yok (giriş gerekir)"),
                      "politika_disi": _("banka/ödeme/devlet/kimlik alanı: kalıcı depoya alınmaz"),
                      "gorev": _("görev kipinde kullanılmaz"),
                      "okunamadi": _("kullanılamıyor: {neden}").format(neden=k.get("neden") or "?")}
        metin_ = kalici_adi.get(k.get("durum"), str(k.get("durum")))
        if k.get("kalan_sn") is not None:
            metin_ += ", " + _sure_metni(k["kalan_sn"])
        if k.get("kayit"):
            metin_ += "; " + _("kaydedildi: {zaman}").format(zaman=_tarih(k["kayit"]))
        if k.get("bitis"):
            metin_ += "; " + _("son kullanma: {zaman}").format(zaman=_tarih(k["bitis"]))
        satirlar.append(_("kalıcı depo: {durum}").format(durum=metin_))
    satirlar.append(_("sonuç: oturum VAR") if d["kod"] == 0 else _("sonuç: oturum YOK"))
    return satirlar

