"""Persistent session store — fixes of the independent security review of H3 (rapor-H3-inceleme.md, items 1–10).
EKRANSIZ; the real Firefox profile and the real KDE Wallet are never touched (fake HOME, fake key ring; see
tests/test_oturum_kalici.py, whose helpers are reused). Item 6 (panel authority of the site list) is in
tests/test_kalici_koruma.py.

  I1  a copy that never got the record (apply failed / site not visited) does not delete it on close; a copy that got
      it and logged out does; an apply error is visible (bilgi + log)
  I2  per cookie the newer one wins; a stale copy cannot write back a session another copy logged out of
  I3  documentation and code comments match the lifetime rule (no one-day cap)
  I4  `sessions check` with no Firefox profile still reports the persistent store (exit stays 1: no copy can be made)
  I5  absurd numbers (10**400) in a record: no exception, the record is not used
  I7  a dead copy swept late: a session-only cookie's deadline counts from the copy's last use, not from the sweep
  I8  one invalid entry in [oturum] kalici does not empty the whole list (doctor warns about the invalid one)
  I9  the temporary file name is not predictable (a planted path does not block the save)
  I10 a partitioned cookie whose top-level site is on the reject list is neither stored nor applied

Çalıştır:  python3 tests/test_oturum_kalici_inceleme.py
"""
import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici; Deskhand'den ÖNCE)

from deskhand import gorev_kipi, liste_koruma
from deskhand.oturum import kopya

import test_oturum_kalici as T  # helpers only (its main() runs under __name__ == "__main__")

kalici = T.kalici
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def dene(ad, fn, ek=""):
    try:
        sonuc = fn()
    except Exception as e:  # noqa: BLE001
        kontrol(ad, False, f"{type(e).__name__}: {e}")
        return
    try:
        ek = ek() if callable(ek) else ek
    except Exception as e:  # noqa: BLE001
        ek = f"{type(e).__name__}: {e}"
    kontrol(ad, sonuc, ek)


def panel_ac():
    """The panel's authoritative list in this process (accepts what the file lists: the user approved)."""
    try:
        liste_koruma.panel_durdur()
        return liste_koruma.panel_baslat(onayla=lambda siteler: True)
    except TypeError:  # older liste_koruma without the approval callback: the file is read directly
        return None


def tazele(k):
    if k is not None:
        sessiz = getattr(k, "denetle", None)
        if sessiz:
            sessiz()


def deger(site, ad):
    r = T.kayit(site) or {}
    return [c.get("value") for c in r.get("cerezler", ()) if c.get("name") == ad]


def kopyaya(k, satirlar, erisim=None):
    T.cerez_yaz(os.path.join(k, "cookies.sqlite"), satirlar, erisim=erisim)


def kopyadan_sil(k, host_deseni):
    con = sqlite3.connect(os.path.join(k, "cookies.sqlite"))
    con.execute("DELETE FROM moz_cookies WHERE host LIKE ?", (host_deseni,))
    con.commit()
    con.close()


def main():
    tdir = tempfile.mkdtemp(prefix="deskhand-kalici-inc-")
    eski_home = os.environ.get("HOME")
    os.environ["HOME"] = tdir
    os.environ.pop("XDG_CONFIG_HOME", None)
    for ad in (gorev_kipi.ORTAM, gorev_kipi.SITE_ORTAM):
        os.environ.pop(ad, None)
    anahtarlik = T.SahteAnahtarlik()
    T.sessiz(lambda: kalici.anahtarlik_ayarla(anahtarlik))
    try:
        T.sahte_profil(os.path.join(tdir, ".config", "mozilla", "firefox"))
        T.ayar_yaz("dukkan.test, panel.test")
        panel = panel_ac()

        # ---- seed: a record for dukkan.test
        k0 = T.yeni_kopya()
        kopyaya(k0, [("www.dukkan.test", "sec_session_id", "V1", T._ms(7200))])
        T.kapat(k0)
        kontrol("hazırlık: kayıt var (V1)", deger("dukkan.test", "sec_session_id") == ["V1"],
                str(T.depo_dosyalari()))

        # ---- I1: a copy that never got the record (key ring unavailable while preparing) must not delete it
        anahtarlik.neden = "cüzdan kilitli"
        try:
            k1 = T.yeni_kopya()
        finally:
            anahtarlik.neden = None
        kopyadan_sil(k1, "%dukkan.test")  # the profile's own old row too: the copy has nothing for the site
        T.kapat(k1)
        dene("I1a: kaydı almamış kopya kapanınca kayıt SİLİNMEZ", lambda: deger("dukkan.test", "sec_session_id") == ["V1"],
             lambda: str(T.kayit("dukkan.test")))
        k2 = T.yeni_kopya()  # gets V1
        kopyadan_sil(k2, "%dukkan.test")  # the user logged out inside this copy
        T.kapat(k2)
        dene("I1b: kaydı almış kopyada çıkış yapıldıysa kayıt düşer",
             lambda: deger("dukkan.test", "sec_session_id") == [])

        def gorunur_hata():
            from deskhand.oturum import firefox, politika
            eski = kalici.DEPO.uygula

            def patlat(*a, **k):
                raise RuntimeError("deneme")
            kalici.DEPO.uygula = patlat
            try:
                b = firefox.hazirla(politika.coz("firefox"))
            finally:
                kalici.DEPO.uygula = eski
            kopya.temizle(b.get("kopya_yolu"))
            return b.get("durum") is None and "deneme" in str(b.get("kalici_hata", ""))
        dene("I1c: uygulama hatası yutulmaz (bilgi['kalici_hata'])", gorunur_hata)

        # ---- I2: newer wins per cookie; a stale copy cannot bring back a logged-out session
        k = T.yeni_kopya()
        kopyaya(k, [("www.dukkan.test", "sec_session_id", "V2", T._ms(7200))])
        T.kapat(k)
        ka, kb = T.yeni_kopya(), T.yeni_kopya()  # both get V2
        kopyaya(ka, [("www.dukkan.test", "sec_session_id", "V3", T._ms(7200))], erisim=time.time() + 60)
        T.kapat(ka)  # the active copy saves V3
        T.kapat(kb)  # the stale copy (still V2, older use) closes later
        dene("I2a: bayat kopya yeni değeri ezmez (V3 kalır)", lambda: deger("dukkan.test", "sec_session_id") == ["V3"],
             lambda: str(deger("dukkan.test", "sec_session_id")))
        ka, kb = T.yeni_kopya(), T.yeni_kopya()  # both get V3
        kopyadan_sil(ka, "%dukkan.test")
        T.kapat(ka)  # logout in A
        T.kapat(kb)  # stale B still holds V3
        dene("I2b: çıkış yapılmış oturumu bayat kopya geri yazamaz",
             lambda: deger("dukkan.test", "sec_session_id") == [], lambda: str(T.kayit("dukkan.test")))
        k = T.yeni_kopya()
        kopyaya(k, [("www.dukkan.test", "sec_session_id", "V4", T._ms(7200))], erisim=time.time() + 120)
        T.kapat(k)
        dene("I2c: çıkıştan sonra YENİ giriş kaydedilir", lambda: deger("dukkan.test", "sec_session_id") == ["V4"])

        # ---- I3: documents and comments follow the lifetime rule
        kok = _yalitim.KOK

        def belge():
            en = open(os.path.join(kok, "docs", "SESSIONS.md"), encoding="utf-8").read()
            tr = open(os.path.join(kok, "docs", "SESSIONS.tr.md"), encoding="utf-8").read()
            kod = open(os.path.join(kok, "deskhand", "oturum", "kalici.py"), encoding="utf-8").read()
            en38 = en.split("### 3.8", 1)[1].split("\n## ", 1)[0]
            tr38 = tr.split("### 3.8", 1)[1].split("\n## ", 1)[0]
            return ("at most 1 day" not in en38 and "refreshes the day" not in en38 and "en çok 1 gün" not in tr38
                    and "günü tazeler" not in tr38 and "at most ONE day" not in kod and "refreshes the day" not in kod
                    and "30" in en38 and "30" in tr38 and "kalici_sure_gun" in en38 and "kalici_sure_gun" in tr38)
        dene("I3: belge (EN+TR §3.8) ve kod yorumu ömür kuralıyla tutarlı", belge)

        # ---- I4: no Firefox profile: the persistent store still answers
        from deskhand.oturum import cli, denetle
        k = T.yeni_kopya()
        kopyaya(k, [("panel.test", "sec_session_id", "PANEL", T._ms(7200))])
        T.kapat(k)
        ini = os.path.join(tdir, ".config", "mozilla", "firefox", "profiles.ini")
        os.rename(ini, ini + ".yok")
        try:
            d = denetle.denetle("panel.test")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                kod = cli.main(["check", "panel.test"])
        finally:
            os.rename(ini + ".yok", ini)
        # exit 1 stays right: with no Firefox profile no copy can be prepared, so the store cannot be applied either
        dene("I4: profil yokken kalıcı depo durumu gizlenmez (raporlanır; kopya kurulamadığından çıkış 1)",
             lambda: d.get("kalici", {}).get("durum") == "var" and kod == 1 and "kalıcı depo: oturum var" in out.getvalue(),
             lambda: f"{d} {out.getvalue()}")

        # ---- I5: absurd numbers
        def sacma():
            r = T.kayit("panel.test")
            r["kayit"] = 10 ** 400
            kalici.DEPO._yaz("panel.test", r, anahtarlik.k) if _yaz_3() else kalici.DEPO._yaz("panel.test", r)
            d = kalici.durum("panel.test")
            k = T.yeni_kopya()
            n = kalici.uygula(k, {"panel.test"})
            kopya.temizle(k)
            return d["kayit"] is None and n == 0

        def _yaz_3():
            import inspect
            return len(inspect.signature(kalici.DEPO._yaz).parameters) >= 3
        dene("I5: kayit=10**400 → istisna yok, kayıt kullanılmaz", sacma)

        # ---- I7: a dead copy swept days later: the session-only deadline counts from the copy's last use
        k = T.yeni_kopya()
        T.mozlz4_yaz(os.path.join(k, "sessionstore-backups", "recovery.jsonlz4"), {"cookies": [
            {"host": "panel.test", "name": "PHPSESSID", "value": "GEC", "path": "/", "originAttributes": {}}]})
        eski_zaman = time.time() - 5 * T.GUN
        for ad in os.listdir(k):
            if ad.startswith("cookies.sqlite") or ad == "sessionstore-backups":
                os.utime(os.path.join(k, ad), (eski_zaman, eski_zaman))
        os.utime(os.path.join(k, "sessionstore-backups", "recovery.jsonlz4"), (eski_zaman, eski_zaman))
        T.kopya_bekcisi.sahip_yaz(k, {"pid": 2 ** 22 + 9, "bas": "1", "zaman": eski_zaman})
        kopya.supur()
        r = T.kayit("panel.test") or {}
        gec = [c for c in r.get("cerezler", ()) if c.get("name") == "PHPSESSID"]
        dene("I7: sahipsiz kopyada süresiz çerezin süresi kopyanın son kullanımından sayılır",
             lambda: gec and abs(gec[0]["expiry"] - (eski_zaman + 30 * T.GUN)) < 300, lambda: str(gec))

        # ---- I8: one invalid entry does not empty the list
        T.ayar_yaz("dukkan.test, *.joker.test, panel.test")
        tazele(panel)
        from deskhand import doktor
        dene("I8a: geçersiz girdi atlanır, geçerliler kalır",
             lambda: kalici.ayar_siteleri() == {"dukkan.test", "panel.test"}, lambda: str(kalici.ayar_siteleri()))
        dene("I8b: doctor geçersiz girdiyi uyarır",
             lambda: doktor.satir_kalici_oturum()["durum"] == "uyari"
             and "joker" in doktor.satir_kalici_oturum()["ayrinti"], lambda: str(doktor.satir_kalici_oturum()))
        T.ayar_yaz("dukkan.test, panel.test")
        tazele(panel)

        # ---- I9: a planted path at the old predictable temporary name does not block the save
        d = T.depo_dizini()
        for site in ("dukkan.test", "panel.test"):
            os.makedirs(os.path.join(d, f".{site}.{os.getpid()}.tmp"), exist_ok=True)
        k = T.yeni_kopya()
        kopyaya(k, [("panel.test", "sec_session_id", "TUZAK", T._ms(7200))], erisim=time.time() + 600)
        T.kapat(k)
        dene("I9: öngörülebilir geçici ada dikilen yol kaydı engellemez",
             lambda: deger("panel.test", "sec_session_id") == ["TUZAK"], lambda: str(deger("panel.test", "sec_session_id")))
        for site in ("dukkan.test", "panel.test"):
            shutil.rmtree(os.path.join(d, f".{site}.{os.getpid()}.tmp"), ignore_errors=True)

        # ---- I10: partitioned cookie under a rejected top-level site
        k = T.yeni_kopya()
        con = sqlite3.connect(os.path.join(k, "cookies.sqlite"))
        mikro = int(time.time() * 1e6) + 900_000_000
        for oa, deger_ in (("^partitionKey=%28https%2Cisbank.com.tr%29", "BOLUM-BANKA"),
                           ("^partitionKey=%28https%2Cornek.test%29", "BOLUM-IYI")):
            con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry,lastAccessed,creationTime,"
                        "isSecure,isHttpOnly) VALUES (?,?,?,?,?,?,?,?,1,1)",
                        (oa, "bolum", deger_, "panel.test", "/", T._ms(7200), mikro, mikro))
        con.commit()
        con.close()
        T.kapat(k)
        dene("I10a: üst sitesi ret listesindeki bölümlenmiş çerez depolanmaz",
             lambda: "BOLUM-BANKA" not in T.depo_metni() and "BOLUM-IYI" in T.depo_metni())

        def bolum_uygula():
            r = T.kayit("panel.test")
            r["cerezler"].append({**r["cerezler"][0], "originAttributes": "^partitionKey=%28https%2Cisbank.com.tr%29",
                                  "name": "elle", "value": "ELLE-BANKA"})
            kalici.DEPO._yaz("panel.test", r)
            k = T.yeni_kopya()
            c = T.cerezler(k)
            kopya.temizle(k)
            return all(v[0] != "ELLE-BANKA" for v in c.values())
        dene("I10b: elle eklenmiş böyle bir çerez uygulanmaz", bolum_uygula)
    finally:
        T.sessiz(liste_koruma.panel_durdur)
        if eski_home:
            os.environ["HOME"] = eski_home
        shutil.rmtree(tdir, ignore_errors=True)
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
