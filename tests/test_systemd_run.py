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


def _sahte(cikti=None, hata=None):
    def calistir(argv, **kw):
        if hata is not None:
            raise hata
        return subprocess.CompletedProcess(argv, 0, stdout=cikti, stderr="")
    return calistir


def _dene(cikti=None, hata=None):
    if sistemd is None:
        return None
    sistemd._onbellek.clear()
    eski = sistemd._calistir
    sistemd._calistir = _sahte(cikti, hata)
    try:
        return sistemd.genisleme_kapali()
    finally:
        sistemd._calistir = eski
        sistemd._onbellek.clear()


kontrol("1a: 253 → []", _dene("systemd 253 (253.7-1-arch)\n+PAM +AUDIT\n") == [])
kontrol("1b: 254 → bayrak", _dene("systemd 254 (254.1-1)\n+PAM\n") == ["--expand-environment=no"])
kontrol("1b2: 262 → bayrak", _dene("systemd 262 (262.2-1-arch)\n") == ["--expand-environment=no"])
kontrol("1c: systemctl yok → []", _dene(hata=FileNotFoundError("systemctl")) == [])
kontrol("1d: okunamayan sürüm → []", _dene("garbage\n") == [])
kontrol("1e: zaman aşımı → []", _dene(hata=subprocess.TimeoutExpired("systemctl", 2)) == [])

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

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
