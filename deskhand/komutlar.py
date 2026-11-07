"""Komut, seçenek ve değer adları: İngilizce birincil, Türkçe takma ad (ikisi de çalışır).

İçeride HER ŞEY Türkçe kalır: argparse alt komutu `komut` alanına Türkçe adı yazar (set_defaults), seçeneklerin
dest'i Türkçedir, değerler (sol/asagi/yesil/baslat…) ayrıştırılırken Türkçeye çevrilir. Böylece komut kodu,
günlük satırları ve çıkış kodları değişmez. `dizi` adımları ve `.akis` dosyaları da aynı eşlemeyi kullanır.
Bu modül hiçbir şey içe aktarmaz (cli/eylem/akis döngüsel içe aktarma olmadan kullanır)."""
from __future__ import annotations

# (Türkçe iç ad, İngilizce ad) — yardımda "windows (bul)" biçiminde, bu sırayla
KOMUTLAR = (
    ("bul", "windows"), ("foto", "screenshot"), ("tikla", "click"), ("tus", "key"), ("yaz", "type"),
    ("kaydir", "scroll"), ("metin", "read"), ("metne-tikla", "click-text"), ("bekle", "wait"), ("kapat", "close"),
    ("bas", "hold"), ("surukle", "drag"), ("fare", "move"), ("dizi", "batch"), ("uyu", "sleep"),
    ("renk-bul", "find-color"), ("renge-tikla", "click-color"), ("simge-kaydet", "save-icon"),
    ("simge-bul", "find-icon"), ("simgeye-tikla", "click-icon"), ("ac", "open"), ("akis", "flow"),
    ("erisim", "a11y"), ("agac", "tree"), ("ogeye-tikla", "click-element"), ("dur", "stop"), ("devam", "resume"),
    ("durum", "status"), ("mesgul", "busy"), ("karar", "decide"), ("panel", "panel"), ("masaustu", "desktop"),
    ("oturum", "sessions"), ("mcp", "mcp"), ("yardım", "help"),
)
TR_EN = dict(KOMUTLAR)
EN_TR = {en: tr for tr, en in KOMUTLAR}
EK_TAKMA = {"yardim": "yardım"}  # ASCII yazım


def ic_ad(ad: str) -> str:
    """Komut sözcüğü (İngilizce / Türkçe / takma) → Türkçe iç ad; bilinmeyen sözcük aynen döner."""
    return EN_TR.get(ad) or EK_TAKMA.get(ad) or ad


def takma_adlar(tr: str) -> list[str]:
    """Bir komutun İngilizce ad dışındaki adları (argparse aliases)."""
    out = [] if TR_EN[tr] == tr else [tr]
    return out + [k for k, v in EK_TAKMA.items() if v == tr]


# Türkçe seçenek → İngilizce. `--sure` anlamına göre (bekleme sınırı → --timeout, eylem süresi → --duration)
# çağıran yerde seçilir; burada yok.
SECENEKLER = {
    "--baslik": "--title", "--sinif": "--class", "--arka": "--background", "--ekranimda": "--on-my-screen",
    "--sira": "--nth", "--bolge": "--region", "--bekle": "--wait", "--kay": "--offset",
    "--kaydirarak": "--scroll-search", "--onayli": "--approved", "--hassas": "--precise", "--hepsi": "--all",
    "--derin": "--deep", "--izgara": "--grid", "--genislik": "--width", "--basili": "--hold",
    "--tekrar": "--repeat", "--komut": "--command", "--gizli": "--secret", "--yok": "--gone",
    "--esik": "--threshold", "--dosya": "--file", "--kal": "--stay", "--nokta": "--point", "--rol": "--role",
    "--en-az": "--min-pixels", "--foto": "--shot", "--boyut": "--size", "--openbox-yok": "--no-openbox",
}

# konumsal değerler: İngilizce → Türkçe (içeride Türkçe)
DUGME = {"left": "sol", "right": "sag", "double": "cift", "middle": "orta"}
YON = {"down": "asagi", "up": "yukari", "left": "sol", "right": "sag"}
RENK = {"green": "yesil", "red": "kirmizi", "blue": "mavi"}
MASAUSTU = {"start": "baslat", "stop": "durdur", "status": "durum"}
OTURUM = {"status": "durum", "prepare": "hazirla", "policy": "politika", "clear": "sil"}
ERISIM = {"on": "ac", "off": "kapat", "status": "durum"}

# .akis dosyası: yönerge ve özel adım sözcükleri (komut adları ic_ad ile)
AKIS_YONERGE = {"screen": "ekran", "timeout": "sure", "repeat": "tekrar", "region": "bolge", "success": "basari",
                "error": "hata"}
AKIS_BASARI = {"text": "metin", "gone": "yok", "command": "komut"}
AKIS_ADIM = {"done": "bitti"}  # "stop" → "dur" komut eşlemesinden gelir


def cevirici(esleme: dict):
    """argparse type=: İngilizce değeri Türkçeye çevirir, gerisini aynen bırakır (choices denetimi sonra)."""
    def cevir(deger: str) -> str:
        return esleme.get(deger, deger)
    cevir.__name__ = "deger"  # argparse hata iletisinde "invalid deger value" yerine tür adı
    return cevir


def secimler(esleme: dict, turkce) -> tuple:
    """choices: önce İngilizce, sonra Türkçe adlar (ikisi de geçerli; tür dönüşümü Türkçeye indirger)."""
    tr = list(turkce)
    return tuple([en for en, t in esleme.items() if t in tr] + tr)


def akis_adimi(adim: list[str]) -> list[str]:
    """Bir akış/dizi adımının ilk sözcüğünü Türkçe iç ada çevir (bitti/dur/bekle/uyu ve komutlar)."""
    if not adim:
        return adim
    return [AKIS_ADIM.get(adim[0]) or ic_ad(adim[0]), *adim[1:]]
