"""MCP sonuç sözleşmesi: beklenmeyen istisna ve okuma araçlarının hataları da yapılandırılmış hata sonucu döner
(status=error, sent, next); hata iletilerinde CLI seçenek adları yerine MCP parametre adları. Ekransız (sahte işlevler).

Çalıştır:  python3 tests/test_mcp_sozlesme.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from deskhand import gonderim, guvenlik, mcp_sunucu

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def yapisal(r):
    return r.structured_content or {}


@mcp_sunucu.arac(None, title="test patla")
def _test_patla_gonderdi():
    gonderim.artir()
    raise RuntimeError("iç hata 42")


@mcp_sunucu.arac(dict, title="test patla 2")
def _test_patla_gondermedi():
    raise KeyError("anahtar")


r = _test_patla_gonderdi.mcp_sarili()
y = yapisal(r)
kontrol("girdi aracı: beklenmeyen istisna → CallToolResult is_error (sunucu çökmez, sözleşme korunur)",
        isinstance(r, CallToolResult) and r.is_error, str(r)[:200])
kontrol("girdi aracı: [9] kod + 'beklenmeyen hata' + istisna türü", y.get("error", {}).get("code") == 9 and
        "beklenmeyen hata" in y["error"]["message"] and "RuntimeError" in y["error"]["message"], str(y))
kontrol("girdi aracı: girdi gönderilmişti → sent=maybe_partial, effect=unverifiable",
        y.get("sent") == "maybe_partial" and y.get("effect") == "unverifiable" and y.get("status") == "error", str(y))
kontrol("girdi aracı: metin içerikte sent + next satırı", "sent: maybe_partial" in r.content[0].text and
        "next:" in r.content[0].text, r.content[0].text)
y = yapisal(_test_patla_gondermedi.mcp_sarili())
kontrol("girdi aracı: hiç girdi yoksa sent=nothing_sent", y.get("sent") == "nothing_sent" and
        y.get("error", {}).get("code") == 9, str(y))
try:
    _test_patla_gonderdi()
    kontrol("çekirdek işlev (batch/testler) istisnayı aynen yükseltir", False)
except RuntimeError:
    kontrol("çekirdek işlev (batch/testler) istisnayı aynen yükseltir", True)

# okuma araçları: hepsi okuma_araci ile kayıtlı
for ad in ("get_status", "choose_desktop", "manage_desktop", "screenshot", "read_text", "listen", "find"):
    kontrol(f"okuma aracı {ad}: sözleşmeli sarmalayıcıyla kayıtlı", hasattr(getattr(mcp_sunucu, ad), "mcp_sarili"))

eski = guvenlik.dur_acik
try:
    guvenlik.dur_acik = lambda: (_ for _ in ()).throw(OSError("durum dosyası okunamadı"))
    r = mcp_sunucu.get_status.mcp_sarili()
    y = yapisal(r)
    kontrol("get_status: beklenmeyen OSError → yapılandırılmış hata (status=error, code 9, sent=nothing_sent)",
            isinstance(r, CallToolResult) and r.is_error and y.get("status") == "error" and
            y.get("error", {}).get("code") == 9 and y.get("sent") == "nothing_sent", str(y))
    guvenlik.dur_acik = lambda: (_ for _ in ()).throw(ToolError("[1] --region x,y,w,h olmalı"))
    y = yapisal(mcp_sunucu.get_status.mcp_sarili())
    kontrol("get_status: ToolError → yapılandırılmış hata, next satırlı", y.get("error", {}).get("code") == 1 and
            y["error"].get("next"), str(y))
    kontrol("hata iletisi: CLI '--region' yerine MCP 'region'", "--region" not in y["error"]["message"] and
            "region x,y,w,h" in y["error"]["message"], y["error"]["message"])
finally:
    guvenlik.dur_acik = eski
r = mcp_sunucu.get_status.mcp_sarili()
kontrol("get_status: başarılı sonuç aynen (sözlük)", isinstance(r, dict) and "stop_switch" in r, str(r)[:200])
for cli, mcp_ in (("--sira 2 ver", "nth 2 ver"), ("--bolge a", "region a"), ("--role entry", "role entry"),
                  ("bkz. --regionx", "bkz. --regionx"), ("--secret ile", "secret ile")):
    kontrol(f"mcp_adlari({cli!r}) → {mcp_!r}", mcp_sunucu.mcp_adlari(cli) == mcp_, mcp_sunucu.mcp_adlari(cli))

print(f"\n{GECEN}/{TOPLAM} MCP sözleşme testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
