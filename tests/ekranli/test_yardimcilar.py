"""EKRANSIZ birim testleri: ekranlı takımların yardımcıları (PID ayrımı, Firefox profili, MPRIS yanıtları,
tepsi ögesi ayrıştırma, insan müdahalesi kaydı). Ekrana girdi göndermez, pencere açmaz, firefox başlatmaz.

Çalıştır:  python3 -m unittest tests/ekranli/test_yardimcilar.py   (ya da doğrudan python3 ile)"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402  (DESKHAND_* geçici klasörler)
import firefox_test  # noqa: E402
import mpris_test  # noqa: E402
import testler_yeni  # noqa: E402


class PidAyrimi(unittest.TestCase):
    def test_soy_pidleri_sahte_agac(self):
        ebeveyn = {1: 0, 100: 1, 101: 100, 102: 101, 103: 100, 200: 1, 201: 200}
        self.assertEqual(ortak.soy_pidleri(100, ebeveyn), {100, 101, 102, 103})
        self.assertEqual(ortak.soy_pidleri(200, ebeveyn), {200, 201})
        self.assertEqual(ortak.soy_pidleri(999, ebeveyn), {999})  # yaprak / bilinmeyen

    def test_soy_pidleri_dongu_guvenli(self):
        self.assertEqual(ortak.soy_pidleri(5, {5: 6, 6: 5}), {5, 6})

    def test_soy_pidleri_gercek_proc(self):
        p = subprocess.Popen(["sleep", "5"])
        try:
            kume = ortak.soy_pidleri(os.getpid())
            self.assertIn(os.getpid(), kume)
            self.assertIn(p.pid, kume)
            self.assertNotIn(1, kume)
        finally:
            p.kill()
            p.wait()

    def test_ebeveynler_parantezli_ad(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "42"))
            with open(os.path.join(d, "42", "stat"), "w") as f:
                f.write("42 (Web Content) (x) S 7 42 42 0 -1\n")  # ad boşluk ve parantez içeriyor
            os.makedirs(os.path.join(d, "self"))
            self.assertEqual(ortak.ebeveynler(d), {42: 7})

    def test_pid_coz_ve_bizim_mi(self):
        self.assertEqual(ortak.pid_coz("1234\n"), 1234)
        for k in ("", None, "abc", "0", "-3"):
            self.assertIsNone(ortak.pid_coz(k))
        kume = {10, 11}
        self.assertTrue(ortak.bizim_mi(11, kume))
        self.assertFalse(ortak.bizim_mi(12, kume))
        self.assertFalse(ortak.bizim_mi(None, kume))  # pid bilinmiyor → kullanıcının penceresi sayılır

    def test_pencere_secimi_pid_ile(self):
        """pencere_bekle: başlık eşleşse bile pid bizim değilse seçilmez (arka uç taklit edilir)."""
        eski_ara, eski_pid, eski_soy = ortak.ara, ortak.pid, ortak.soy_pidleri
        try:
            ortak.ara = lambda desen: ["{kullanici}", "{bizim}"]
            ortak.pid = lambda k: {"{kullanici}": 500, "{bizim}": 901}[k]
            ortak.soy_pidleri = lambda kok, ebeveyn=None: {900, 901}
            self.assertEqual(ortak.pencere_bekle("x", sure=0.2, kok_pid=900), "{bizim}")
            ortak.pid = lambda k: 500
            self.assertIsNone(ortak.pencere_bekle("x", sure=0.2, kok_pid=900, aralik=0.05))
            self.assertEqual(ortak.pencere_bekle("x", sure=0.2), "{kullanici}")  # pid süzgeci yoksa ilk
        finally:
            ortak.ara, ortak.pid, ortak.soy_pidleri = eski_ara, eski_pid, eski_soy


class Kod12(unittest.TestCase):
    def test_kod12_bildir(self):
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "k12")
            eski = os.environ.get("HEPSI_KOD12")
            os.environ["HEPSI_KOD12"] = yol
            try:
                ortak.kod12_bildir(0, ["click"])
                ortak.kod12_bildir(12, ["tikla", "K", "1", "2"], beklenen=True)
                self.assertFalse(os.path.exists(yol))
                ortak.kod12_bildir(12, ["click", "K", "1", "2"])
                with open(yol) as f:
                    self.assertEqual(f.read(), "click K 1 2\n")
            finally:
                if eski is None:
                    os.environ.pop("HEPSI_KOD12", None)
                else:
                    os.environ["HEPSI_KOD12"] = eski

    def test_yasak_yaz_gecici(self):
        from deskhand import yollar
        yol = ortak.yasak_yaz("ekran-test YASAK")
        self.assertTrue(yol.startswith(ortak._yalitim.GECICI))
        self.assertTrue(yol == yollar.yasak_dosya())
        with open(yol) as f:
            self.assertIn("ekran-test YASAK\n", f.read())
        ortak.yasak_yaz()
        with open(yol) as f:
            self.assertNotIn("ekran-test YASAK", f.read())


class Firefox(unittest.TestCase):
    def test_user_js(self):
        m = firefox_test.user_js_metni({"a.b": True, "c": 0, "d": 'x"y', "e": False})
        self.assertEqual(m, 'user_pref("a.b", true);\nuser_pref("c", 0);\nuser_pref("d", "x\\"y");\n'
                            'user_pref("e", false);\n')
        tam = firefox_test.user_js_metni()
        for k in ("browser.shell.checkDefaultBrowser", "browser.sessionstore.resume_from_crash",
                  "toolkit.telemetry.enabled", "datareporting.policy.dataSubmissionEnabled", "browser.aboutwelcome.enabled",
                  "browser.warnOnQuit"):
            self.assertIn(f'user_pref("{k}", false);', tam)

    def test_profil_guvenli(self):
        taban = ortak._yalitim.GECICI
        p = firefox_test.profil_olustur(taban)
        try:
            self.assertTrue(firefox_test.profil_guvenli_mi(p, taban))
            self.assertTrue(os.path.isfile(os.path.join(p, "user.js")))
        finally:
            import shutil
            shutil.rmtree(p)
        ev = os.path.expanduser("~")
        for kotu in (os.path.join(ev, ".mozilla", "firefox", "abc.default-release"),
                     os.path.join(taban, "baska-klasor"), os.path.join(taban, ".mozilla", "deskhand-ff-x"), "/tmp"):
            self.assertFalse(firefox_test.profil_guvenli_mi(kotu, taban), kotu)

    def test_argv(self):
        a = firefox_test.argv_olustur("/x/deskhand-ff-1", "http://127.0.0.1:5/")
        self.assertEqual(a[:4], ["firefox", "--new-instance", "--no-remote", "--profile"])
        self.assertEqual(a[4:], ["/x/deskhand-ff-1", "http://127.0.0.1:5/"])


class Mpris(unittest.TestCase):
    def test_yanit(self):
        t = mpris_test.ozellikler("deskhandmpristest", "Playing")
        self.assertEqual(mpris_test.yanit(mpris_test.OZELLIK_ARAYUZ, "Get", (mpris_test.OYNATICI_ARAYUZ, "PlaybackStatus"), t),
                         ("tamam", "v", (("s", "Playing"),)))
        tur, imza, govde = mpris_test.yanit(mpris_test.OZELLIK_ARAYUZ, "GetAll", (mpris_test.KOK_ARAYUZ,), t)
        self.assertEqual((tur, imza), ("tamam", "a{sv}"))
        self.assertIn("Identity", govde[0])
        self.assertEqual(mpris_test.yanit(mpris_test.OZELLIK_ARAYUZ, "Get", (mpris_test.OYNATICI_ARAYUZ, "Yok"), t)[0], "hata")
        self.assertEqual(mpris_test.yanit("x.y", "Play", (), t)[0], "hata")
        self.assertEqual(mpris_test.yanit("org.freedesktop.DBus.Introspectable", "Introspect", (), t)[1], "s")

    def test_ad_eslemesi(self):
        """mesgul oynatıcı adını '.instanceN' sonekinden arındırır → test penceresinin app_id'si ile aynı olmalı."""
        from deskhand import mesgul
        m = mpris_test.MprisSunucu(testler_yeni.MPRIS_AD)
        self.assertEqual(mesgul.oynatici_adi(m.bus_adi), testler_yeni.MPRIS_AD)


class Tepsi(unittest.TestCase):
    def test_sni_ayir(self):
        self.assertEqual(testler_yeni.sni_ayir("org.kde.StatusNotifierItem-1234-1/StatusNotifierItem"),
                         ("org.kde.StatusNotifierItem-1234-1", "/StatusNotifierItem"))
        self.assertEqual(testler_yeni.sni_ayir(":1.42/org/ayatana/NotificationItem/x"),
                         (":1.42", "/org/ayatana/NotificationItem/x"))
        self.assertEqual(testler_yeni.sni_ayir(":1.7"), (":1.7", "/StatusNotifierItem"))

    def test_senaryo_secimi(self):
        self.assertEqual(testler_yeni.main(["yok-boyle"]), 2)  # bilinmeyen ad: hiçbir şey çalışmaz


if __name__ == "__main__":
    unittest.main()
