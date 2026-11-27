"""tools/iz_tara.py (personal-trace scanner) tests. No screen, no input; the scanner runs as a subprocess on
temporary files under the _yalitim temp dir. The real ~/.config/deskhand/iz-desenleri.txt is NEVER read or written:
the extra-pattern file is generated in the temp dir with a made-up word.

Trace strings are built by concatenation so that this file itself stays clean for the scanner.

Run:  python3 tests/test_iz_tara.py"""
import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before anything else)

import os
import subprocess
import sys
import tempfile

KOK = _yalitim.KOK
ARAC = os.path.join(KOK, "tools", "iz_tara.py")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(("  ✓ " if kosul else "  ✗ ") + ad + ("" if kosul or not ek else f"  [{ek}]"))


DIZIN = tempfile.mkdtemp(prefix="iz-", dir=_yalitim.GECICI)


def dosya(ad, icerik):
    yol = os.path.join(DIZIN, ad)
    with open(yol, "w", encoding="utf-8") as f:
        f.write(icerik)
    return yol


def tara(*arg):
    r = subprocess.run([sys.executable, ARAC, *arg], capture_output=True, text=True, timeout=60, cwd=DIZIN)
    return r.returncode, r.stdout, r.stderr


EV = "/home/"
OTURUM = "Claude-" + "Session: https://claude.ai/code/" + "session_" + "01AbCdEfGhIjKlMnOpQrStUv"

print("1) general patterns")
y = dosya("a.txt", "ok line\npath " + EV + "gercekad/proje/x.py\n")
rc, out, err = tara(y)
kontrol(f"1a: {EV}gercekad/ yolu bulgu", rc == 1 and f"{y}:2 · home-path" in out, (rc, out, err))

y = dosya("b.txt", f"{EV}u/a\n{EV}x/b\n{EV}user/c\n{EV}user\nroot{EV}system dir\n")
rc, out, err = tara(y)
kontrol("1b: /home/u, /home/x, /home/user serbest", rc == 0 and out == "", (rc, out, err))

rc, out, err = tara("--ileti", "fix: something\n\nCo-Authored-By: X <noreply@anthropic.com>\n" + OTURUM + "\n")
kontrol("1c: --ileti içindeki Claude-Session bulgu", rc == 1 and "session-trailer" in out and "<ileti>:4" in out,
        (rc, out, err))
rc, out, err = tara("--ileti", "fix: something\n\nCo-Authored-By: X <noreply@anthropic.com>\n")
kontrol("1c2: noreply e-postalı temiz ileti geçer", rc == 0 and out == "", (rc, out, err))

UYDURMA = "Zeytinovalı"
ek = dosya("iz-desenleri.txt", "# comment line\n\n" + UYDURMA + "\n")
y = dosya("c.txt", "nothing\nthe city is " + UYDURMA.upper() + " here\n")
rc, out, err = tara("--ek", ek, y)
ls = subprocess.run(["git", "-C", KOK, "ls-files", "--error-unmatch", ek], capture_output=True)
kontrol("1d: --ek dosyasındaki sözcük bulgu, dosyanın kendisi depoda yok",
        rc == 1 and f"{y}:2 · extra-pattern" in out and ls.returncode != 0 and not ek.startswith(KOK + os.sep),
        (rc, out, err))
kontrol("1d2: bulgu satırı ek desenin kendisini yazmaz", UYDURMA.lower() not in (out + err).lower(), out + err)
rc, out, err = tara("--ek", os.path.join(DIZIN, "yok.txt"), dosya("d.txt", "clean\n"))
kontrol("1d3: --ek dosyası yoksa uyarı, çıkış 0", rc == 0 and "yok.txt" in err, (rc, out, err))

print("2) other kinds")
y = dosya("e.txt", "a = '/tmp/claude-" + "1000/x'\n")
rc, out, _ = tara(y)
kontrol(f"2a: claude-{1000} bulgu", rc == 1 and "claude-tmp" in out, out)
y = dosya("f.txt", "url = 'https://claude.ai/code/" + "session_" + "01AbCdEfGhIjKlMnOpQr'\n")
rc, out, _ = tara(y)
kontrol("2b: oturum kimliği bulgu", rc == 1 and "session-id" in out, out)
y = dosya("g.txt", "cookie sec_session_id; s['session_choice']; resume_session_once\n")
rc, out, _ = tara(y)
kontrol("2c: sec_session_id gibi çerez/anahtar adları bulgu değil", rc == 0, out)
y = dosya("h.txt", "mail ali.veli" + "@gmail.com\n")
rc, out, _ = tara(y)
kontrol("2d: noreply olmayan e-posta bulgu", rc == 1 and "email" in out, out)
y = dosya("i.txt", "1@users.noreply.github.com a@example.com b@shop.test ext@x.xpi c@örnek.com user@1000.service\n")
rc, out, _ = tara(y)
kontrol("2e: noreply / example / .test / eklenti kimliği serbest", rc == 0, out)
y = dosya("j.txt", "sample " + EV + "kullanici/proje and " + EV + "kisi/Belgeler\n")
rc, out, _ = tara(y)
kontrol("2f: yer tutucu ev adları (kullanici, kisi) serbest", rc == 0, out)
y = os.path.join(DIZIN, "k.bin")
with open(y, "wb") as f:
    f.write(b"\x00\x01" + (EV + "gercekad/").encode())
rc, out, _ = tara(y)
kontrol("2g: ikili dosya atlanır", rc == 0, out)

print("3) repository")
rc, out, err = tara(ARAC, os.path.abspath(__file__))
kontrol("3a: tarayıcı ve bu test kendi desenlerine takılmaz", rc == 0, out)
ls = subprocess.run(["git", "-C", KOK, "ls-files", "-z"], capture_output=True)
if ls.returncode == 0 and ls.stdout:
    dosyalar = [os.path.join(KOK, d) for d in ls.stdout.decode().split("\0") if d]
    rc, out, err = tara(*dosyalar)
    kontrol("3b: depo ağacında genel desenlerle iz yok (git ls-files)", rc == 0, out[:2000])
else:
    print("  - 3b skipped: not a git checkout")

print(f"\n{gecen}/{toplam} iz_tara testi geçti")
sys.exit(0 if gecen == toplam else 1)
