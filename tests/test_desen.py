"""ReDoS sınırı (deskhand/desen.py) testleri: ajanın verdiği başlık/pencere desenleri uzunluk + iç içe niceleyici
sezgisinden geçer. EKRANSIZ: reddedilen desen hiçbir arka uca ulaşmaz (api çağrıları `api.hedef("sanal")` içinde, ama
desen denetimi arka uçtan ÖNCE çalıştığı için görünmez masaüstü bile başlamaz); gerçek ekrana girdi/pencere/bildirim yok.

Çalıştır:  python3 tests/test_desen.py"""
import os
import re
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler + gerçek ekran kilidi; Deskhand'den ÖNCE)

from deskhand import api, desen, mcp_sunucu as s  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


KOTU = ["(a+)+$", "(a*)*b", "(.*a){5,}x", "(a{2,9})*", "(a|a)+$", "(a|ab)*c", ".*.*.*.*.*x", "(x+x+)+y", r"^(\w+\s?)*$",
        "((a+)b)+", "(?:a+)+", "(a+){2}", "a" * (desen.MAKS_UZUNLUK + 1)]
IYI = ["Mozilla Firefox", "^Firefox$", "(Firefox|Chrome) - .*", r"Kate.*\.txt", r"^a.txt \* — KWrite$", "(?i)foo(bar)?",
       r"\s*[*●•]?\s*foo", r"(\d+)-(\d+)", "(foo|bar)+", "[a-z]+ [0-9]+", "(a|b)*", "x{2,3}y", "(ab)+", r"\(a+\)+", "[(]a+[)]+",
       "(foo|foobar)", "[+*]+", "{3b7e0a2c-0000-0000-0000-000000000000}", "arka:0x1a00004", "a" * desen.MAKS_UZUNLUK]

# ---------------------------------------------------------------- 1) sezgi
for k in KOTU:
    kontrol(f"reddedilir: {k[:24]!r}", desen.sorun(k) is not None)
for k in IYI:
    kontrol(f"geçer: {k[:24]!r}", desen.sorun(k) is None, str(desen.sorun(k)))
kontrol("geçersiz sözdizimi: neden bildirilir", "geçersiz desen" in (desen.sorun("[a") or ""))
t0 = time.monotonic()
for _ in range(200):
    desen.sorun("(Firefox|Chrome) - .*" * 10)
kontrol("denetim ucuz (200 çağrı < 1 sn)", time.monotonic() - t0 < 1.0)
try:
    desen.denetle("(a+)+$")
    kontrol("denetle: Dur(1)", False)
except Dur as e:
    kontrol("denetle: Dur(1) kullanım hatası, neden iletide", e.kod == 1 and "iç içe" in e.mesaj, e.mesaj)
kontrol("denetle: boş/None dokunmaz", desen.denetle(None) is None and desen.denetle("") == "")
# Deskhand'in KENDİ ürettiği kilit kalıbı (uzun başlık, çok boşluk) sınıra takılmaz: yalnız ajanın deseni denetlenir
uzun = " ".join(["Belge"] * 80) + " — KWrite"
kontrol("üretilmiş başlık kilidi (degisiklik_toleransli) uzun başlıkta bile reddedilmez",
        s.degisiklik_toleransli(uzun).startswith("^") and re.search(s.degisiklik_toleransli(uzun), uzun) is not None)

# ---------------------------------------------------------------- 2) api (arka uçtan önce reddeder)
with api.hedef("sanal"):
    for ad, f, arg in (("api.pencere", api.pencere, "(a+)+$"), ("api.pencereler", api.pencereler, "(a+)+$"),
                       ("api.uygulama_ac başlık", lambda b: api.uygulama_ac(["true"], "x", [], None, b), "(a+)+$")):
        try:
            f(arg)
            kontrol(f"{ad}: kötü desen reddedilir", False)
        except Dur as e:
            kontrol(f"{ad}: kötü desen → Dur(1)", e.kod == 1, str(e))
    try:
        api.pencere("a" * 400)
        kontrol("api.pencere: 400 karakterlik desen reddedilir", False)
    except Dur as e:
        kontrol("api.pencere: 400 karakterlik desen → Dur(1) 'çok uzun'", e.kod == 1 and "çok uzun" in e.mesaj, str(e))
    kontrol("api.pencere: 'ekran' / boş desen etkilenmez", api.pencere(None) == api.pencere("ekran"))

# ---------------------------------------------------------------- 3) MCP: başlık kilidi + wait_for
try:
    s.baslik_kilidi("(a+)+$", "{aaaaaaaa-0000-0000-0000-000000000000}")
    kontrol("mcp.baslik_kilidi: kötü desen reddedilir", False)
except Dur as e:
    kontrol("mcp.baslik_kilidi: kötü desen → Dur(1)", e.kod == 1, str(e))
kontrol("mcp.baslik_kilidi: iyi desen aynen döner",
        s.baslik_kilidi("Firefox - .*", "{aaaaaaaa-0000-0000-0000-000000000000}") == "Firefox - .*")
kontrol("mcp.baslik_kilidi: ref başlığı (üretilmiş) denetlenmez",
        s.baslik_kilidi(None, "{aaaaaaaa-0000-0000-0000-000000000000}", "(a+)+ özel başlık") == "^" + re.escape("(a+)+ özel başlık") + "$")
import asyncio  # noqa: E402


async def bekle_kotu():
    from mcp import Client
    async with Client(s.mcp) as c:
        return await c.call_tool("wait_for", {"condition": "window", "value": "(a+)+$", "timeout_s": 1, "desktop": "background"})

try:
    r = asyncio.run(bekle_kotu())
    metin = "\n".join(getattr(c, "text", "") for c in r.content)
    kontrol("mcp wait_for(window, kötü desen): [1] hata, bekleme yok", r.is_error and metin.startswith("[1]") and "iç içe" in metin, metin[:120])
except Exception as e:  # noqa: BLE001
    kontrol("mcp wait_for(window, kötü desen): [1] hata, bekleme yok", False, repr(e)[:200])

# ---------------------------------------------------------------- 4) CLI: arka uç açılmadan reddeder
env = dict(os.environ, DESKHAND_HEDEF="sanal")
for argv in (["tus", "ekran", "a", "-b", "(a+)+$"], ["bul", "(a+)+$"], ["tus", "ekran", "a", "-b", "x" * 400]):
    p = subprocess.run([sys.executable, "-m", "deskhand", *argv], capture_output=True, text=True, cwd=_yalitim.KOK, env=env, timeout=30)
    kontrol(f"cli {argv[0]} {argv[-1][:12]!r}: reddedildi (çıkış 1), arka uç başlamadı",
            p.returncode == 1 and "desen reddedildi" in p.stderr, f"{p.returncode} {p.stderr[-200:]}")

print(f"\n{gecen}/{toplam} desen testi geçti")
sys.exit(0 if gecen == toplam else 1)
