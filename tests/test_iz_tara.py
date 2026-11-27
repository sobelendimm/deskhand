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


def kontrol(ad: str, kosul: object, ek: object = "") -> None:
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

print("4) other spellings of a home path (review ORTA-1)")
AD = "gercekad"
for ad, metin in [
    ("4a: büyük harf /HOME/<ad>/", "/HOME/" + AD + "/x"),
    ("4b: URL kodlu /home%2F<ad>", "/home%2F" + AD + "%2Fx"),
    ("4c: tam URL kodlu %2Fhome%2F<ad>", "p=%2F" + "home%2F" + AD),
    ("4d: Windows C:\\Users\\<ad>", "C:" + "\\Users\\" + AD + "\\x"),
    ("4e: kaçışlı Windows C:\\\\Users\\\\<ad>", "'C:" + "\\\\Users\\\\" + AD + "'"),
    ("4f: macOS /Users/<ad>", "/Users/" + AD + "/x"),
    ("4g: göreli ../home/<ad>", "../home/" + AD + "/x"),
]:
    rc, out, _ = tara(dosya("ev.txt", metin + "\n"))
    kontrol(ad, rc == 1 and "home-path" in out, (metin, rc, out))
serbest = ["/HOME/" + "User/a", "C:" + "\\Users\\" + "user\\a", "/Users/" + "kisi/a", "%2F" + "home%2F" + "u%2Fa",
           "../home/" + "x/a", "root" + EV + "system", "https://api.github.com/users/" + "someone"]
rc, out, _ = tara(dosya("ev2.txt", "\n".join(serbest) + "\n"))
kontrol("4h: izin listesi her yazımda geçerli; /users/ URL yolu bulgu değil", rc == 0, out)

print("5) --ek-zorunlu (review ORTA-2: fail closed)")
temiz = dosya("temiz.txt", "clean\n")
rc, out, err = tara("--ek-zorunlu", "--ek", os.path.join(DIZIN, "yok.txt"), temiz)
kontrol("5a: --ek-zorunlu + yok dosya → çıkış 2", rc == 2 and "yok.txt" in err, (rc, out, err))
rc, out, err = tara("--ek-zorunlu", temiz)
kontrol("5b: --ek-zorunlu ama --ek yok → çıkış 2", rc == 2, (rc, out, err))
bos = dosya("bos-desen.txt", "# only a comment\n\n")
rc, out, err = tara("--ek-zorunlu", "--ek", bos, temiz)
kontrol("5c: --ek-zorunlu + desensiz dosya → çıkış 2", rc == 2, (rc, out, err))
rc, out, err = tara("--ek-zorunlu", "--ek", ek, temiz)
kontrol("5d: --ek-zorunlu + dolu dosya + temiz girdi → 0", rc == 0, (rc, out, err))
rc, out, err = tara("--ek-zorunlu", "--ek", ek, y := dosya("c2.txt", UYDURMA + "\n"))
kontrol("5e: --ek-zorunlu bulguda yine 1", rc == 1 and "extra-pattern" in out, (rc, out, err))

print("6) narrower exemptions and other spellings (review DÜŞÜK)")
rc, out, _ = tara("--ileti", "ok\n\n# " + OTURUM + "\n")
kontrol("6a: '#' satırı da taranır (git -m ile '#' satırı commit'e girer)", rc == 1 and "session-trailer" in out, out)
for ad, metin in [
    ("6b: example.com alt alanı serbest değil", "ali" + "@gmail.com.example.com"),
    ("6c: .test önüne gizlenmiş adres serbest değil", "ali" + "@gmail.com.test"),
    ("6d: user@<uid>.service dışındaki .service serbest değil", "ali" + "@evil.service"),
    ("6e: çok etiketli .xpi serbest değil", "ali" + "@gmail.com.xpi"),
    ("6f: kısa oturum kimliği (session_01…) bulgu", "id " + "session_" + "01AbCdEf"),
    ("6g: tiresiz Claude Session iz satırı bulgu", "Claude " + "Session: x"),
]:
    rc, out, _ = tara(dosya("dar.txt", metin + "\n"))
    kontrol(ad, rc == 1, (metin, rc, out))
rc, out, _ = tara(dosya("git.txt", "git clone git" + "@github.com:u/r.git; session_identifier; user" + "@1000.service\n"))
kontrol("6h: git@github.com, session_identifier, user@1000.service bulgu değil", rc == 0, out)

print("7) review round 2")
MAKAS = "# ------------------------ " + ">8 ------------------------"
rc, out, _ = tara("--ileti", "clean up\n\n" + MAKAS + "\n# Do not modify or remove the line above.\n"
                  "-old " + EV + "gercekad/x\n-" + OTURUM + "\n")
kontrol("7a: makas satırından sonrası (git commit -v farkı) taranmaz", rc == 0 and out == "", out)
rc, out, _ = tara("--ileti", "clean up\n# " + OTURUM + "\n" + MAKAS + "\n-x\n")
kontrol("7b: makastan önceki '#' satırındaki iz bulgu", rc == 1 and "<ileti>:2 · session-trailer" in out, out)
rc, out, _ = tara(dosya("api.txt", "GET /users/" + "me\nPOST /USERS/" + "me/keys\n"))
kontrol("7c: küçük/büyük harf /users/ API yolu ev sayılmaz", rc == 0, out)
rc, out, _ = tara(dosya("mac.txt", "open /Users/" + AD + "/Library\n"))
kontrol("7d: macOS /Users/<ad> (büyük U) hâlâ bulgu", rc == 1 and "home-path" in out, out)

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
