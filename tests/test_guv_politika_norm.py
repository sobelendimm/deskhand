"""Site reject rule normalisation (surum-091, card DHG POLITIKA-NORM) and the places.sqlite temp-dir fallback.

Headless: temp profile folders, fake data (*.test / example.com / made-up bank names); no real browser profile,
no real cookie, no network, no screen.
Covers:
  N1 equivalent spellings of a reject rule reject the same domain cookie / host as the plain spelling:
     trailing dot(s) (`*.bank.com.`), upper case, IDNA dots (U+3002 / U+FF0E / U+FF61), a Unicode rule against a
     punycode (ACE) cookie domain and the other way round, a trailing `*` after a fixed tail (`*.bank.com*`),
     a leading-dot plain rule (`.bank.com`) for host cookies and site storage
  N2 a cookie domain that cannot be converted (broken ACE label) is rejected (closed-fail)
  N3 no false positive: non-bank domains stay allowed under the same rules and under the default list
  N4 identity-provider permit (kimlik_izni_uygula) still removes the equivalent spelling of its entries only
  F1 places.sqlite: when the temporary directory cannot be created (OSError), the known hosts still come from the
     main file (no WAL) instead of crashing hazirla

Run:  python3 tests/test_guv_politika_norm.py
"""
import os
import sqlite3
import sys
import tempfile
from unittest import mock

import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)

from deskhand.oturum import firefox, politika  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def pol(reddet):
    return politika.Politika("firefox", {"kapali_iken": "kopya"}, {"reddet": list(reddet)})


ACE = "bankası".encode("idna").decode("ascii")  # xn--bankas-u9a (canonical ACE of the Unicode label)


def test_n1_esdeger_yazim():
    vakalar = [
        ("sonda nokta kural *.bank.com. → .bank.com", ["*.bank.com."], ".bank.com"),
        ("sonda iki nokta kural *.bank.com.. → .bank.com", ["*.bank.com.."], ".bank.com"),
        ("büyük harf kural *.BANK.COM → .bank.com", ["*.BANK.COM"], ".bank.com"),
        ("IDNA noktası kural *.bank。com → .bank.com", ["*.bank。com"], ".bank.com"),
        ("tam genişlik nokta kural *.bank．com → .bank.com", ["*.bank．com"], ".bank.com"),
        ("çerez IDNA noktası .bank｡com", ["*.bank.com"], ".bank｡com"),
        ("Unicode kural *.bankası.com → ACE çerez", ["*.bankası.com"], f".{ACE}.com"),
        ("ACE kural *.xn--… → Unicode çerez", [f"*.{ACE}.com"], ".bankası.com"),
        ("Unicode düz kural bankası.com → ACE çerez", ["bankası.com"], f".{ACE}.com"),
        ("Unicode genel desen *bankası* → ACE alt alan çerezi", ["*bankası*"], f".giris.{ACE}.com"),
        ("sonu * olan sabit kural *.bank.com* → .bank.com", ["*.bank.com*"], ".bank.com"),
        ("sonu ** olan sabit kural *.bank.com** → .bank.com", ["*.bank.com**"], ".bank.com"),
        ("baştaki nokta kural .bank.com → konak çerezi login.bank.com", [".bank.com"], "login.bank.com"),
        ("baştaki nokta kural .bank.com → konak çerezi bank.com", [".bank.com"], "bank.com"),
    ]
    for ad, r, h in vakalar:
        kontrol(f"N1 {ad}", pol(r).cerez_reddedildi(h), f"reddet={r} host={h!r}")
    # site (storage / logins) path: the same equivalence
    site = [
        ("site: sonda nokta kural", ["*.bank.com."], "login.bank.com"),
        ("site: Unicode kural ↔ ACE konak", ["*.bankası.com"], f"login.{ACE}.com"),
        ("site: ACE kural ↔ Unicode konak", [f"*.{ACE}.com"], "login.bankası.com"),
        ("site: baştaki nokta kural", [".bank.com"], "login.bank.com"),
        ("site: konak sonda nokta + büyük harf", ["*.bank.com"], "LOGIN.BANK.COM."),
    ]
    for ad, r, h in site:
        kontrol(f"N1 {ad}", pol(r).site_reddedildi(h), f"reddet={r} host={h!r}")
    # izin listesi (görev siteleri) Unicode ↔ ACE: same normalisation, the reject list still wins
    p = pol(["*bank*"])
    kontrol("N1 izin: Unicode görev sitesi ACE konakla eşleşir",
            p.site_izinli("www.xn--rnek-4qa.example", ["örnek.example"]))


def test_n2_donusturulemeyen():
    p = pol(["*.bank.com"])
    for h in (".xn--zz!!.example.com", "xn--zz!!.example.com", ".xn--.example.com", ".xn--abc-.example.com",
              ".xn--bankas-n9a.com"):  # last: decodes to "bankasİ" (upper case) = no canonical IDNA label
        kontrol(f"N2 dönüştürülemeyen ACE çerez alanı reddedilir: {h}", p.cerez_reddedildi(h))
    kontrol("N2 dönüştürülemeyen ACE konak site_reddedildi", p.site_reddedildi("xn--zz!!.example.com"))
    kontrol("N2 dönüştürülemeyen ACE konak izinli değil", not p.site_izinli("xn--zz!!.example.com"))


def test_n3_yanlis_pozitif_yok():
    p = pol(["*.bank.com.", "*.bankası.com", "*.bank.com*", ".bank.com", "*bank*"])
    for h in (".example.com", ".github.com", "www.example.com", ".xn--rnek-4qa.example", ".örnek.example",
              ".banco.example", ".com.tr", ".xn--strae-oqa.example"):
        kontrol(f"N3 banka olmayan alan reddedilmez: {h}", not p.cerez_reddedildi(h))
    for h in ("www.example.com", "xn--rnek-4qa.example"):
        kontrol(f"N3 banka olmayan site reddedilmez: {h}", not p.site_reddedildi(h))
    v = politika.coz("firefox", politika.yukle())
    for h in (".example.com", ".github.com", ".mozilla.org", ".wikipedia.org", ".örnek.com.tr", ".xn--rnek-4qa.com.tr"):
        kontrol(f"N3 varsayılan listede ret yok: {h}", not v.cerez_reddedildi(h, set()))
    for h in (".isbank.com.tr", ".paypal.com", ".bank.example", ".gib.gov.tr"):
        kontrol(f"N3 varsayılan listede ret sürüyor: {h}", v.cerez_reddedildi(h, set()))
    # a trailing-`*` rule still needs evidence when its fixed part cannot reach the domain
    kontrol("N3 *bank* kanıtsız .example.com'a dokunmaz", not pol(["*bank*"]).cerez_reddedildi(".example.com"))
    kontrol("N3 *bank* kanıtla .example.com'u reddeder",
            pol(["*bank*"]).cerez_reddedildi(".example.com", {"bank.example.com"}))
    kontrol("N3 *bank* kanıt ACE konak (Unicode alan çerezi)",
            pol(["*bankası*"]).cerez_reddedildi(".örnek.example", {f"{ACE}.xn--rnek-4qa.example"}))


def test_n4_kimlik_izni():
    p = politika.Politika("firefox", {}, {"reddet": ["login.live.com.", "LOGIN.LIVE.COM", "*bank*"]})
    acik = p.kimlik_izni_uygula(["microsoft"])
    kontrol("N4 izin eşdeğer yazımı da çıkarır", not acik.site_reddedildi("login.live.com"))
    kontrol("N4 izin banka desenine dokunmaz", acik.site_reddedildi("www.bank.example"))
    kontrol("N4 asıl nesne değişmez", p.site_reddedildi("login.live.com"))


def test_f1_gecici_dizin_yok():
    with tempfile.TemporaryDirectory(prefix="deskhand-pn-") as kok:
        prof = os.path.join(kok, "profil")
        os.mkdir(prof)
        con = sqlite3.connect(os.path.join(prof, "places.sqlite"))
        con.execute("CREATE TABLE moz_origins (id INTEGER PRIMARY KEY, prefix TEXT, host TEXT)")
        con.execute("INSERT INTO moz_origins (prefix, host) VALUES ('https://', 'bank.example.com')")
        con.commit()
        con.close()
        once = sorted(os.listdir(prof))

        def bozuk(*a, **k):
            raise OSError(28, "No space left on device")

        with mock.patch.object(firefox.tempfile, "TemporaryDirectory", bozuk):
            try:
                konaklar = firefox._bilinen_konaklar(prof, os.path.join(kok, "cookies.sqlite"), {})
                hata = None
            except OSError as e:
                konaklar, hata = set(), e
        kontrol("F1 geçici dizin açılamazsa OSError dışarı taşmaz", hata is None, repr(hata))
        kontrol("F1 ana dosyadan konak okunur", "bank.example.com" in konaklar, repr(konaklar))
        kontrol("F1 profil klasörü değişmez", sorted(os.listdir(prof)) == once, repr(os.listdir(prof)))


def main():
    print("deskhand:", os.path.dirname(politika.__file__))
    for f in (test_n1_esdeger_yazim, test_n2_donusturulemeyen, test_n3_yanlis_pozitif_yok, test_n4_kimlik_izni,
              test_f1_gecici_dizin_yok):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failure, the others still run
            kontrol(f"{f.__name__} çöktü", False, f"{type(e).__name__}: {e}")
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
