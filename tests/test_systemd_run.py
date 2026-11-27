"""systemd-run argument-expansion class check (deskhand/sistemd.py).

systemd >= 254 expands "${VAR}" in systemd-run arguments by default (with --scope, systemd-run does it itself), so a
path containing "$" could change meaning. Every systemd-run call in deskhand/ must add genisleme_kapali() (which is
["--expand-environment=no"] on >= 254, [] on older/unknown systemd, where the flag would be an error).
Nothing is started: systemctl is faked through the module's runner hook.

Run:  python3 tests/test_systemd_run.py"""
import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)
import ast
import os
import subprocess
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


try:
    from deskhand import sistemd
except ImportError as e:  # red phase: module missing
    sistemd = None
    kontrol("0: deskhand.sistemd içe aktarılır", False, str(e))


def _sahte(cikti=None, hata=None, yardim=None, yardim_hata=None):
    """systemctl --version -> cikti/hata; systemd-run --help -> yardim/yardim_hata (default: help without the flag)."""
    def calistir(argv, **kw):
        if argv[0] == "systemd-run":
            if yardim_hata is not None:
                raise yardim_hata
            return subprocess.CompletedProcess(argv, 0, stdout=YARDIM_ESKI if yardim is None else yardim, stderr="")
        if hata is not None:
            raise hata
        return subprocess.CompletedProcess(argv, 0, stdout=cikti, stderr="")
    return calistir


YARDIM_ESKI = "systemd-run [OPTIONS...] COMMAND [ARGUMENTS...]\n\n  --scope   Run this as scope rather than service\n"
YARDIM_YENI = YARDIM_ESKI + "     --expand-environment=BOOL    Control expansion of environment variables\n"
B = ["--expand-environment=no"]


def _dene(cikti=None, hata=None, **yardim):
    if sistemd is None:
        return None
    sistemd._onbellek.clear()
    eski = sistemd._calistir
    sistemd._calistir = _sahte(cikti, hata, **yardim)
    try:
        return sistemd.genisleme_kapali()
    finally:
        sistemd._calistir = eski
        sistemd._onbellek.clear()


kontrol("1a: 253 → []", _dene("systemd 253 (253.7-1-arch)\n+PAM +AUDIT\n") == [])
kontrol("1b: 254 → bayrak", _dene("systemd 254 (254.1-1)\n+PAM\n") == ["--expand-environment=no"])
kontrol("1b2: 262 → bayrak", _dene("systemd 262 (262.2-1-arch)\n") == ["--expand-environment=no"])
kontrol("1c: systemctl yok, systemd-run yardımında bayrak yok → []", _dene(hata=FileNotFoundError("systemctl")) == [])
kontrol("1d: okunamayan sürüm, yardımda bayrak yok → []", _dene("garbage\n") == [])
kontrol("1e: zaman aşımı, yardımda bayrak yok → []", _dene(hata=subprocess.TimeoutExpired("systemctl", 2)) == [])
# version unreadable: fall back to probing `systemd-run --help` for the flag (H1-KALAN)
kontrol("1g: okunamayan sürüm + yardımda bayrak → bayrak", _dene("garbage\n", yardim=YARDIM_YENI) == B)
kontrol("1h: systemctl zaman aşımı + yardımda bayrak → bayrak",
        _dene(hata=subprocess.TimeoutExpired("systemctl", 2), yardim=YARDIM_YENI) == B)
kontrol("1i: systemctl yok + yardımda bayrak → bayrak", _dene(hata=FileNotFoundError("systemctl"), yardim=YARDIM_YENI) == B)
kontrol("1j: sürüm okunur (253) → yardım yoklanmaz bile", _dene("systemd 253 (253)\n", yardim=YARDIM_YENI) == [])
# both probes fail: systemd-run missing -> [] (no call can be made anyway); help times out / is garbage -> fail closed
kontrol("1k: sürüm ve systemd-run ikisi de yok → []",
        _dene(hata=FileNotFoundError("systemctl"), yardim_hata=FileNotFoundError("systemd-run")) == [])
kontrol("1l: sürüm okunamaz + yardım zaman aşımı → bayrak (açık-kapalı)",
        _dene("garbage\n", yardim_hata=subprocess.TimeoutExpired("systemd-run", 2)) == B)
kontrol("1m: sürüm okunamaz + yardım anlamsız → bayrak (açık-kapalı)", _dene("garbage\n", yardim="???\n") == B)

# cached for the process lifetime: second call does not run systemctl again
if sistemd is not None:
    sistemd._onbellek.clear()
    sayac = [0]
    eski = sistemd._calistir

    def _sayan(argv, **kw):
        sayac[0] += 1
        return subprocess.CompletedProcess(argv, 0, stdout="systemd 255 (255)\n", stderr="")
    sistemd._calistir = _sayan
    try:
        a, b = sistemd.genisleme_kapali(), sistemd.genisleme_kapali()
        a.append("x")  # caller mutation must not poison the cache
        c = sistemd.genisleme_kapali()
    finally:
        sistemd._calistir = eski
        sistemd._onbellek.clear()
    kontrol("1f: önbellekli (systemctl bir kez) ve kopya döner", sayac[0] == 1 and b == c == ["--expand-environment=no"],
            f"sayac={sayac[0]} c={c}")
else:
    kontrol("1f: önbellekli (systemctl bir kez) ve kopya döner", False, "modül yok")

# fallback path is cached too: systemctl + systemd-run --help run once each
if sistemd is not None:
    sistemd._onbellek.clear()
    cagrilar = []
    eski = sistemd._calistir

    def _sayan2(argv, **kw):
        cagrilar.append(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout="garbage\n" if argv[0] == "systemctl" else YARDIM_YENI,
                                           stderr="")
    sistemd._calistir = _sayan2
    try:
        sonuc = [sistemd.genisleme_kapali() for _ in range(3)]
    finally:
        sistemd._calistir = eski
        sistemd._onbellek.clear()
    kontrol("1n: yedek yoklama önbellekli (her araç bir kez)",
            cagrilar == ["systemctl", "systemd-run"] and all(x == B for x in sonuc), f"{cagrilar} {sonuc}")
else:
    kontrol("1n: yedek yoklama önbellekli (her araç bir kez)", False, "modül yok")


# 2: AST scan — every list literal starting with systemd-run carries *genisleme_kapali()
def _systemd_run_mi(n):
    if isinstance(n, ast.Constant) and n.value == "systemd-run":
        return True
    return (isinstance(n, ast.Call) and any(isinstance(a, ast.Constant) and a.value == "systemd-run" for a in n.args))


def _yardimci_mi(n):
    if not isinstance(n, ast.Starred) or not isinstance(n.value, ast.Call):
        return False
    f = n.value.func
    ad = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    return ad == "genisleme_kapali"


eksik, bulunan = [], 0
for kok, _dizinler, dosyalar in os.walk(os.path.join(KOK, "deskhand")):
    for ad in dosyalar:
        if not ad.endswith(".py"):
            continue
        yol = os.path.join(kok, ad)
        agac = ast.parse(open(yol, encoding="utf-8").read(), yol)
        for n in ast.walk(agac):
            if isinstance(n, ast.List) and n.elts and _systemd_run_mi(n.elts[0]):
                bulunan += 1
                if not any(_yardimci_mi(e) for e in n.elts):
                    eksik.append(f"{os.path.relpath(yol, KOK)}:{n.lineno}")
kontrol("2: deskhand/ altında 'systemd-run' geçen her çağrı genisleme_kapali() kullanıyor",
        bulunan >= 4 and not eksik, f"bulunan={bulunan} eksik={eksik}")

# 3: gorev argv: first four items unchanged, flag right after them
os.environ.setdefault("XDG_CONFIG_HOME", "/nonexistent-deskhand-test")
from deskhand import gorev  # noqa: E402

argv = gorev.komut_olustur("/x/claude", "/x/mcp.json", "sonnet", kafes=True)
kontrol("3: gorev argv ilk dört öge değişmedi", argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"], str(argv[:6]))
if sistemd is not None:
    beklenen = sistemd.genisleme_kapali()
    kontrol("3b: gorev bayrağı 4. ögeden sonra", argv[4:4 + len(beklenen)] == beklenen, str(argv[:6]))

# 4: ocr_gpu's gpu-is branch does not call systemd-run itself; gpu-is passes --expand-environment=no on its own.
# The rationale is pinned next to the branch, and checked against the installed wrapper when there is one.
from deskhand import ocr_gpu  # noqa: E402
import inspect  # noqa: E402
import shutil  # noqa: E402

satirlar = inspect.getsource(ocr_gpu._baslat_komutu).splitlines()
gpu_dal = next((i for i, x in enumerate(satirlar) if 'shutil.which("gpu-is")' in x), None)
yakin = "\n".join(satirlar[max(0, (gpu_dal or 0) - 2):(gpu_dal or 0) + 3]) if gpu_dal is not None else ""
kontrol("4: ocr_gpu gpu-is dalında genişleme gerekçesi yazılı", "expand-environment" in yakin, yakin)
gpu_is = shutil.which("gpu-is")
if gpu_is:
    with open(os.path.realpath(gpu_is), encoding="utf-8", errors="replace") as f:
        govde = f.read()
    kontrol("4b: kurulu gpu-is systemd-run'a --expand-environment=no geçiriyor",
            "systemd-run" not in govde or "--expand-environment=no" in govde, gpu_is)
eski_which = ocr_gpu.shutil.which
ocr_gpu.shutil.which = lambda ad: "/usr/bin/" + ad
try:
    gk = ocr_gpu._baslat_komutu("/usr/bin/python3")
finally:
    ocr_gpu.shutil.which = eski_which
kontrol("4c: gpu-is dalı systemd-run çağırmıyor (sarmalayıcıya devreder)",
        gk[0] == "gpu-is" and "systemd-run" not in gk, str(gk[:4]))

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
