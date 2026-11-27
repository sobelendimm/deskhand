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
  N5 review round 1: rules are also tried against the ACE spelling (`*xn--*`, `xn--*`, `*bank*` vs xn--bank-cpa);
     allow lists need BOTH spellings of a host to match
  N6 regression gate: every (rules, host, known hosts) the da2db0e code rejected is rejected here too (seeded
     random + exhaustive single-rule set; the da2db0e decision is copied into this file)
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
    p2 = politika.Politika("firefox", {}, {"reddet": [".login.live.com", "*bank*"]})
    kontrol("N4 baştaki noktalı yazım reddeder", p2.site_reddedildi("login.live.com"))
    kontrol("N4 baştaki noktalı yazımı izin de çıkarır", not p2.kimlik_izni_uygula(["microsoft"]).site_reddedildi(
        "login.live.com"))
    p3 = politika.Politika("firefox", {}, {"reddet": ["*.login.live.com", "login.live.com.evil.example"]})
    acik3 = p3.kimlik_izni_uygula(["microsoft"])
    kontrol("N4 izin desen/başka alan girdisini çıkarmaz", acik3.site_reddedildi("a.login.live.com")
            and acik3.site_reddedildi("login.live.com.evil.example"))


def test_n5_ace_bicimi():
    """Review round 1 (HIGH): a rule must still be tried against the ACE (punycode) spelling of a host."""
    vakalar = [
        ("*xn--* (bütün IDN) → ACE alan çerezi", ["*xn--*"], f".{ACE}.com"),
        ("*xn--* → Unicode alan çerezi", ["*xn--*"], ".bankası.com"),
        ("xn--* → ACE konak", ["xn--*"], f"{ACE}.com"),
        ("xn--* → Unicode konak", ["xn--*"], "bankası.com"),
        ("*bank* → xn--bank-cpa.com (baénk.com)", ["*bank*"], "xn--bank-cpa.com"),
        ("*bank* → .xn--bank-cpa.com alan çerezi", ["*bank*"], ".xn--bank-cpa.com"),
        ("*bank* → baénk.com Unicode yazımı", ["*bank*"], "baénk.com"),
        ("*xn--* → ß içeren IDNA2008 ACE", ["*xn--*"], ".xn--strae-oqa.example"),
    ]
    for ad, r, h in vakalar:
        kontrol(f"N5 {ad}", pol(r).cerez_reddedildi(h), f"reddet={r} host={h!r}")
    for ad, r, h in (("site: *xn--*", ["*xn--*"], f"www.{ACE}.com"), ("site: *bank*", ["*bank*"], "xn--bank-cpa.com")):
        kontrol(f"N5 {ad} → {h}", pol(r).site_reddedildi(h))
    for h in (".example.com", "www.example.com", "example.com", ".github.com"):
        kontrol(f"N5 negatif: *xn--* / xn--* ASCII alana dokunmaz: {h}", not pol(["*xn--*", "xn--*"]).cerez_reddedildi(h))
    # allow direction: a task site matches only when BOTH spellings of the host match
    p = pol([])
    kontrol("N5 izin: xn--* görev sitesi Unicode konağa izin vermez", not p.site_izinli("bankası.com", ["xn--*"]))
    kontrol("N5 izin: ACE görev sitesi Unicode konağa izin verir", p.site_izinli("bankası.com", [f"{ACE}.com"]))
    kontrol("N5 görev kipi: Unicode görev sitesi ACE konak", firefox.gorev_izinli(p, f"{ACE}.com", ["bankası.com"]))


# ---- regression gate: every (rules, host) the da2db0e code rejected is still rejected -------------------------
# The da2db0e decision, copied verbatim (raw lower-case spelling only); _alt_alana_uyabilir did not change.

def _eski_alan_eslesir(alan, kaliplar):
    import fnmatch
    alan = (alan or "").strip().lower().rstrip(".")
    if not alan:
        return False
    for k in kaliplar:
        k = str(k).strip().lower()
        if not k:
            continue
        if fnmatch.fnmatch(alan, k):
            return True
        if "*" not in k and "?" not in k and (alan == k or alan.endswith("." + k)):
            return True
    return False


def _eski_cerez_reddedildi(reddet, host, bilinen_konaklar=()):
    h = (host or "").strip().lower()
    alan = h.lstrip(".").rstrip(".")
    if not alan:
        return False
    if _eski_alan_eslesir(alan, reddet):
        return True
    if not h.startswith("."):
        return False
    for k in reddet:
        k = str(k).strip().lower()
        if not k:
            continue
        if "*" not in k and "?" not in k and "[" not in k and (k == alan or k.endswith("." + alan)):
            return True
        if not k.endswith("*") and politika._alt_alana_uyabilir(k, alan):
            return True
    for b in bilinen_konaklar or ():
        b = str(b).strip().lower().lstrip(".").rstrip(".")
        if b != alan and b.endswith("." + alan) and _eski_alan_eslesir(b, reddet):
            return True
    return False


KURALLAR = ["*bank*", "*xn--*", "xn--*", "*.bank.com", "bank.com", "*.gov.tr", "*bankası*", f"*.{ACE}.com",
            "login?.bank.com", "[l]ogin.bank.com", "*bank*.com", "pay*.com", ".bank.com", "*.bank.com.",
            "accounts.google.com", "*e-devlet*", "*.xn--bank-cpa.com", "*BANK*", "*.bank.com*", "bank.*", "*ı*",
            "xn--bank-cpa.com", "*.örnek.example", "*-cpa*", "*xn--b*"]
ETIKETLER = ["bank", "xn--bank-cpa", "baénk", "bankası", ACE, "login", "www", "example", "com", "tr", "gov",
             "xn--strae-oqa", "straße", "BANK", "xn--zz!!", "örnek", "xn--rnek-4qa", "google", "accounts", "e-devlet",
             "pay", "cpa", "ı", "xn--bankas-n9a"]


def _rastgele_konak(r):
    ad = ".".join(r.choice(ETIKETLER) for _ in range(r.randint(1, 4)))
    if r.random() < 0.5:
        ad = "." + ad
    if r.random() < 0.15:
        ad += "."
    return ad


def test_n6_gerileme_kapisi():
    import random
    r = random.Random(20261127)  # noqa: S311 - test data, not cryptography
    kacan, sayac, eski_ret = [], 0, 0
    for _ in range(6000):
        kurallar = r.sample(KURALLAR, r.randint(1, 3))
        host = _rastgele_konak(r)
        bilinen = {_rastgele_konak(r).lstrip(".") for _ in range(r.randint(0, 2))}
        sayac += 1
        if _eski_cerez_reddedildi(kurallar, host, bilinen):
            eski_ret += 1
            if not pol(kurallar).cerez_reddedildi(host, bilinen):
                kacan.append((kurallar, host, sorted(bilinen)))
        if _eski_alan_eslesir(host.lstrip("."), kurallar) and not pol(kurallar).site_reddedildi(host.lstrip(".")):
            kacan.append((kurallar, "site:" + host))
    # every single rule × every single-label / two-label host, exhaustively
    for k in KURALLAR:
        for a in ETIKETLER:
            for b in ETIKETLER + [""]:
                for nokta in ("", "."):
                    host = nokta + a + ("." + b if b else "")
                    sayac += 1
                    if _eski_cerez_reddedildi([k], host):
                        eski_ret += 1
                        if not pol([k]).cerez_reddedildi(host):
                            kacan.append(([k], host))
    kontrol(f"N6 gerileme kapısı: eski kodun reddettiği her (kural, konak) yeni kodda da reddedilir "
            f"({sayac} vaka, eski ret {eski_ret})", not kacan, repr(kacan[:5]))


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
              test_n5_ace_bicimi, test_n6_gerileme_kapisi, test_f1_gecici_dizin_yok):
        try:
            f()
        except Exception as e:  # noqa: BLE001 - a crashing case is a failure, the others still run
            kontrol(f"{f.__name__} çöktü", False, f"{type(e).__name__}: {e}")
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
