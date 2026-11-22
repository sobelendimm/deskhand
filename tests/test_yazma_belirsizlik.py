"""type_text(element=…) belirsizliği: etiket (label) ile giriş alanı aynı adı taşıyınca `[5] birden çok eşleşme`.
Düzeltme: değer yazmada ad birden çok ögeye uyup yalnız BİRİ yazılabilirse (entry/text/password text/spin button) o
seçilir; role ve nth verilebilir (click ile aynı). Ekransız birim testi: erisim._oge_secimi sentetik öge listesiyle,
api.ogeye_yaz / MCP type_text imzası.

Çalıştır:  python3 tests/test_yazma_belirsizlik.py"""
import inspect
import sys
import types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import api, erisim, mcp_sunucu
from deskhand.hata import Dur

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def oge(rol, ad, etkin=True, no=0):
    return {"rol": rol, "ad": ad, "etkin": etkin, "cx": 10 * no, "cy": 5, "w": 8, "h": 8, "yol": [no]}


def sec(ogeler, ad, rol=None, sira=None, tercih=False):
    a = types.SimpleNamespace(ad=ad, rol=rol, sira=sira, kimlik="x", ref_oge=None, yazilabilir_tercih=tercih)
    try:
        o, kademe = erisim._oge_secimi(a, ogeler, 0.0)
        return ("ok", o["rol"], o["yol"])
    except Dur as e:
        return ("dur", e.kod)


L = [oge("label", "E-posta", no=1), oge("entry", "E-posta", no=2), oge("button", "Gönder", no=3)]
kontrol("etiket + giriş aynı ad: tercihsiz (tıklama yolu) hâlâ [5] belirsiz", sec(L, "E-posta") == ("dur", 5))
kontrol("etiket + giriş aynı ad: yazma tercihi → yazılabilir tek öge (entry) seçilir",
        sec(L, "E-posta", tercih=True) == ("ok", "entry", [2]))
kontrol("role=entry → entry (tercihsiz de)", sec(L, "E-posta", rol="entry") == ("ok", "entry", [2]))
kontrol("role=label → etiket", sec(L, "E-posta", rol="label") == ("ok", "label", [1]))
kontrol("nth=2 → ikinci eşleşme (açık seçim tercihi aşar)", sec(L, "E-posta", sira=2, tercih=True) == ("ok", "entry", [2]))
kontrol("nth=1 → birinci eşleşme (etiket; yazılamaz hatası sonra gelir)",
        sec(L, "E-posta", sira=1, tercih=True) == ("ok", "label", [1]))
iki = [oge("entry", "Ad", no=1), oge("entry", "Ad", no=2), oge("label", "Ad", no=3)]
kontrol("iki yazılabilir öge: hâlâ [5] (tahmin yok), nth ile seçilir",
        sec(iki, "Ad", tercih=True) == ("dur", 5) and sec(iki, "Ad", sira=2, tercih=True) == ("ok", "entry", [2]))
kontrol("hiç yazılabilir öge yok: [5] (tahmin yok)",
        sec([oge("label", "A", no=1), oge("button", "A", no=2)], "A", tercih=True) == ("dur", 5))
kontrol("parola alanı + etiket → parola alanı seçilir",
        sec([oge("label", "Parola", no=1), oge("password text", "Parola", no=2)], "Parola", tercih=True)
        == ("ok", "password text", [2]))
# bulanık kademeler (içerir/benzer): tek yazılabilir alanı KENDİLİĞİNDEN seçme yok → eski davranış [5]
B = [oge("label", "E-posta adresiniz", no=1), oge("entry", "E-posta adresi", no=2), oge("button", "Gönder", no=3)]
kontrol("bulanık (içerir) eşleşme: yazma tercihi olsa da [5] belirsiz (tam eşleşme yok)",
        sec(B, "posta adres", tercih=True) == ("dur", 5) and sec(B, "posta adres") == ("dur", 5))
kontrol("bulanık (benzer) eşleşme: [5] belirsiz",
        sec([oge("label", "Kullanici adiniz", no=1), oge("entry", "Kullanici adinzi", no=2)], "Kullanici adinizi",
            tercih=True) == ("dur", 5))
kontrol("bulanık eşleşmede nth ile seçim sürer", sec(B, "posta adres", sira=2, tercih=True) == ("ok", "entry", [2]))
kontrol("tam eşleşme kademesi hâlâ tercihle çözülür (kademe tam)",
        sec([oge("label", "Ad", no=1), oge("entry", "AD", no=2)], "ad", tercih=True) == ("ok", "entry", [2]))
# role süzgeci: yazma yolunda TAM eşleşme ("text" parola alanını ("password text") kapsamasın); tıklama yolu aynen
P = [oge("text", "Gizli", no=1), oge("password text", "Gizli", no=2)]
kontrol("yazma yolu role=text → YALNIZ text (parola alanı alt dizge olarak girmez)",
        sec(P, "Gizli", rol="text", tercih=True) == ("ok", "text", [1]))
kontrol("yazma yolu role=password text → parola alanı", sec(P, "Gizli", rol="password text", tercih=True)
        == ("ok", "password text", [2]))
kontrol("yazma yolu role büyük/küçük duyarsız", sec(P, "Gizli", rol="Password Text", tercih=True)
        == ("ok", "password text", [2]))
kontrol("tıklama yolu (tercihsiz) role=text eski alt dizge davranışı: iki öge → [5]",
        sec(P, "Gizli", rol="text") == ("dur", 5))
kontrol("tek eşleşme etkilenmez", sec([oge("entry", "Ad", no=1)], "Ad", tercih=True) == ("ok", "entry", [1]))

p = inspect.signature(api.ogeye_yaz).parameters
kontrol("api.ogeye_yaz rol parametresi var", "rol" in p)
kontrol("api.ogeye_yaz yazılabilir tercihini açar (kaynak)", "yazilabilir_tercih=True" in inspect.getsource(api.ogeye_yaz))
q = inspect.signature(mcp_sunucu.type_text.fn if hasattr(mcp_sunucu.type_text, "fn") else mcp_sunucu.type_text).parameters
kontrol("MCP type_text: role ve nth parametreleri var", "role" in q and "nth" in q, str(list(q)))

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
