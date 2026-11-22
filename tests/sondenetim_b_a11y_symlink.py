"""Kanıt: bwrap'teki uygulama, yazılabilir bağlanan oturum at-spi dizinine (kwin: <cdir>/at-spi, xvfb: <cdir>/run/at-spi)
kullanıcının GERÇEK a11y veri yoluna sembolik bağ bırakabilir; Deskhand'in a11y bağlantısında karşı taraf denetimi yok.
Gerçek oturuma yalnız connect()+close (SO_PEERCRED okuması); mesaj gönderilmez."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deskhand import arka_ortak as ao, erisim  # noqa: E402

uid = os.getuid()
gercek = f"/run/user/{uid}/at-spi/bus_0"
kok = tempfile.mkdtemp(prefix="sondenetim-b2-", dir=os.environ.get("KANIT_DIZIN") or None)
cdir = os.path.join(kok, "kwin-x")
os.makedirs(os.path.join(cdir, "at-spi"), mode=0o700)
baglar = [(os.path.join(cdir, "at-spi"), False)]  # kwin_oturum.uygulama_baglari ile aynı (salt_okunur=False)
argv = ao.korumali_argv(["/bin/sh", "-c", f"ln -s {gercek} {cdir}/at-spi/bus_0 && echo ICERDE_TAMAM"],
                        os.path.join(kok, "rt"), baglar)
r = subprocess.run(argv, capture_output=True, text=True, env={"PATH": ao.GUVENLI_PATH})
print("bwrap:", r.returncode, r.stdout.strip(), r.stderr.strip()[:200])
yol = f"{cdir}/at-spi/bus_0"
print("disarida symlink:", os.path.islink(yol), "->", os.readlink(yol) if os.path.islink(yol) else None)
print("_atspi_veri_yolu_saglam:", erisim._atspi_veri_yolu_saglam(f"unix:path={yol}"))
karsi = ao.soket_karsi_pid(yol)
print("karsi pid:", karsi, open(f"/proc/{karsi}/cmdline").read().replace("\0", " ")[:160] if karsi else None)
