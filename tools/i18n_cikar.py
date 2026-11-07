#!/usr/bin/env python3
"""Arayüz metinlerini çıkarır: ``_("…")`` / ``N_("…")`` / ``h_("…")`` → deskhand/i18n/kaynak.json.

    python3 tools/i18n_cikar.py              # deskhand/ tara (gui/ dahil) → deskhand/i18n/kaynak.json
    python3 tools/i18n_cikar.py --denetle    # yalnız denetle: f-string / birleştirme /
                                             # .format()'lı _() + bozuk yer tutucular → çıkış 1
    python3 tools/i18n_cikar.py --denetle --ayrinti   # + dinamik (değişkenli) çağrılar listesi
    python3 tools/i18n_cikar.py --kok DIR --cikti FILE

The scan is pure AST (nothing is imported or executed). A constant first argument is a
msgid (implicitly concatenated literals are already one constant for the parser); an
f-string, a "+"/"%" built text or ``_("…".format())`` is an ERROR (the msgid would be
the formatted text); a plain variable / attribute / call argument (``_(MESAJLAR[k])``,
``_(YARDIM_GIRIS)``) is the documented N_()-at-use pattern → reported as INFO only.
Output: {msgid: ["dosya.py:satır", …]} sorted by msgid, locations sorted → stable diffs.
The activity log (gunluk) is never translated, so it is not scanned for.

This module is stdlib-only on purpose (i18n_denetle.py imports its helpers). Deskhand's command/option
names are read from deskhand/komutlar.py by file path (that module imports nothing), so the tools
never import the app package. Adapted from Kulak Kesil's tools/i18n_cikar.py (same author).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import runpy
import string
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAKET = ROOT / "deskhand"
KATALOG_DIZINI = PAKET / "i18n"
KAYNAK_DOSYASI = KATALOG_DIZINI / "kaynak.json"

# Target languages (deskhand/i18n.py DILLER without the Turkish source; a test keeps the two
# in sync — duplicated so the tools never import the app package).
DILLER = ("en",)
ISLEVLER = ("_", "N_", "h_")

_FMT = string.Formatter()
# printf-style tokens: %s %d %(ad)s %5.1f %% … — not followed by a letter, so Turkish
# "%50" / "%{n}" (percent sign before the number) is NOT a placeholder.
YUZDE_RE = re.compile(r"%(?:\([^)]+\))?[-#0 +]*\d*(?:\.\d+)?[sdifrxXeEgGc%]"
                      r"(?![A-Za-zÇĞİÖŞÜçğıöşü])")


# ---------------------------------------------------------------- korunan adlar (çevrilmez)

def _komutlar() -> dict:
    """deskhand/komutlar.py (içe aktarma yapmayan modül) dosya yolundan okunur: paket içe aktarılmaz."""
    return runpy.run_path(str(PAKET / "komutlar.py"))


_K = _komutlar()
KOMUT_EN_TR: dict = dict(_K["EN_TR"])
KOMUT_TR: frozenset = frozenset(_K["TR_EN"]) | frozenset(_K["EK_TAKMA"])
SECENEK_EN_TR: dict = {en: tr for tr, en in _K["SECENEKLER"].items()} | {"--timeout": "--sure", "--duration": "--sure"}

# Program / paket / özel adlar: çeviride AYNEN kalmalı (büyük/küçük harf duyarlı).
OZEL_ADLAR = (
    "Deskhand", "deskhand-bg", "deskhand-sessiz", "Claude Code", "MCP", "KDE Plasma", "Wayland", "Xvfb", "openbox",
    "kdotool", "dotool", "xdotool", "spectacle", "kscreen-doctor", "tesseract", "pactl", "systemd-run", "dbus-daemon",
    "busctl", "AT-SPI", "python-gobject", "at-spi2-core", "xorg-server-xvfb", "uinput", "Flatpak", "Electron",
    "userData", "WM_DELETE_WINDOW", "keysym", "mouseto", "D-Bus", "Qt/GTK", "regex", "OCR", "MPRIS",
)

# ayarlar.toml bölüm adları (deskhand/ayarlar.py VARSAYILAN): "[karar]" gibi yazılır, çevrilmez
AYAR_BOLUMLERI = tuple(sorted(set(re.findall(r'^    "([a-z_]+)": \{', (PAKET / "ayarlar.py").read_text("utf-8"), re.M))))

KORUNAN_RE = re.compile(
    r"(?P<komut>\b(?P<prog>ekran|deskhand) (?:-b \S+ )?(?P<soz>-?-?[a-zçğıöşü][a-zçğıöşü0-9-]*))"  # ekran devam
    r"|(?P<takma>\((?:[a-zçğıöşü-]+)(?: \| [a-zçğıöşü-]+)*\))"                  # (bul) / (dur | devam | durum)
    r"|(?P<secenek>(?<![\w-])--[a-z][a-z0-9-]*)"                                  # --onayli / --approved
    r"|(?P<kisa>(?<![\w-])-[bs](?= ))"                                            # -b DESEN / -s SINIF
    r"|(?P<ortam>\$?\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b(?:=[^\s,;)]+)?)"               # DESKHAND_HEDEF=arka
    r"|(?P<yol>~/[^\s),;:]+|(?<![\w.])/(?:[\w.-]+/)+[\w.-]*)"                     # ~/.config/… /usr/share/…
    r"|(?P<dosya>\b[\w-]+\.(?:toml|txt|jsonl?|akis|png|ini|desktop|py)\b)"        # ayarlar.toml
    r"|(?P<anahtar>\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b(?:=[^\s,;)]+)?)"            # shot_id, tam_ekranda_sor=false
    r"|(?P<atama>\b[a-z]+=(?:'[^']*'|[^\s,;)]+))"                                  # desktop='background', kind=icon
    r"|(?P<bolum>\[(?:" + "|".join(AYAR_BOLUMLERI) + r")\])"                          # [karar]
    r"|(?P<ozel>" + "|".join(re.escape(a) for a in sorted(OZEL_ADLAR, key=len, reverse=True)) + r")(?![\w-])"
)


def _kanonik(m: re.Match) -> str | None:
    """Korunan bir eşleşmenin karşılaştırma biçimi: komut/seçenek adının İngilizcesi ile Türkçesi AYNI sayılır
    (ekran resume ≡ ekran devam, --approved ≡ --onayli). Komut sözcüğü olmayan "ekran xyz" korunmaz → None."""
    t = m.group(0)
    if m.group("komut"):
        on, soz = m.group("prog"), m.group("soz")  # "-b DESEN" atlanır (metavar çevrilebilir)
        if soz.startswith("--"):
            soz = SECENEK_EN_TR.get(soz, soz)
        elif soz in KOMUT_EN_TR:
            soz = KOMUT_EN_TR[soz]
        elif soz not in KOMUT_TR:
            return None  # "ekran tanıma", "ekran görüntüsü": düz sözcük
        return f"deskhand {soz}"  # ekran ≡ deskhand (uyumluluk adı; çeviri ürün adını kullanabilir)
    if m.group("takma"):
        sozler = t[1:-1].split(" | ")
        return t if all(x in KOMUT_TR for x in sozler) else None
    if m.group("secenek"):
        return SECENEK_EN_TR.get(t, t)
    return t


def korunan_adlar(text: str) -> Counter:
    """Çeviride kaybolmaması gereken adların çoklu kümesi: komut/seçenek adları (İngilizce ≡ Türkçe), ortam
    değişkenleri, yollar, dosya adları, kod anahtarları, program adları. {yer tutucu} içi sayılmaz."""
    duz = re.sub(r"\{[^{}]*\}", " ", text.replace("{prog} ", "deskhand "))  # {prog} = ekran | deskhand
    return Counter(k for m in KORUNAN_RE.finditer(duz) if (k := _kanonik(m)) is not None)


def bicim_alanlari(text: str) -> list[str]:
    """str.format replacement fields as written ("{ad}", "{db:+.1f}", "{x!r}").

    Raises ValueError on syntax str.format cannot parse ("{ad", "a}b")."""
    out = []
    for _lit, field, spec, conv in _FMT.parse(text):
        if field is None:
            continue
        tok = "{" + field + (f"!{conv}" if conv else "") + (f":{spec}" if spec else "") + "}"
        out.append(tok)
        if spec and "{" in spec:              # nested field in a spec: validate it too
            bicim_alanlari(spec)
    return out


def yer_tutucular(text: str) -> Counter:
    """Multiset of every placeholder a translation must keep: {…} fields + %-tokens.

    Unparseable brace syntax → ValueError (callers report it)."""
    c = Counter(bicim_alanlari(text))
    c.update(m.group(0) for m in YUZDE_RE.finditer(text) if m.group(0) != "%%")
    return c


def yer_tutucu_hatasi(text: str) -> str | None:
    """None when the msgid is fine, else a short reason (Turkish, for the report)."""
    try:
        alanlar = bicim_alanlari(text)
    except ValueError as e:
        return f"yer tutucu sözdizimi bozuk: {e}"
    for tok in alanlar:
        name = re.split(r"[!:.\[]", tok[1:-1], maxsplit=1)[0]
        if name == "" or name.isdigit():
            return f"konumsal yer tutucu {tok} (adlandırılmış olmalı: {{ad}})"
    return None


@dataclass
class Uyari:
    yer: str          # "dosya.py:satır"
    neden: str
    kod: str = ""
    ciddi: bool = True   # False = dynamic argument (info only, not an error)

    def __str__(self) -> str:
        return f"{self.yer}: {self.neden}" + (f"  → {self.kod}" if self.kod else "")


def _islev_adi(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):        # i18n._("…")
        return node.attr
    return None


def _metin_insasi(node: ast.AST) -> bool:
    """"a" + b, "…%s" % x, "…".format(…), f-strings inside → a built text, not a msgid."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return any(isinstance(n, (ast.Constant, ast.JoinedStr)) and
                   isinstance(getattr(n, "value", ""), str) for n in (node.left, node.right)) \
            or _metin_insasi(node.left) or _metin_insasi(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("format", "format_map", "join"):
        return isinstance(node.func.value, (ast.Constant, ast.JoinedStr))
    return False


def dosya_tara(path: Path, goreli: str) -> tuple[list[tuple[str, str]], list[Uyari]]:
    """[(msgid, "dosya.py:satır")], [Uyari] of one file."""
    try:
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        return [], [Uyari(goreli, f"dosya ayrıştırılamadı: {e}")]
    bulunan, uyarilar = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _islev_adi(node.func) not in ISLEVLER:
            continue
        yer = f"{goreli}:{node.lineno}"
        ad = _islev_adi(node.func)
        if len(node.args) != 1 or node.keywords:
            uyarilar.append(Uyari(yer, f"{ad}() tam olarak bir metin argümanı almalı",
                                  ast.unparse(node)[:80]))
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if not arg.value.strip():
                uyarilar.append(Uyari(yer, f"{ad}() boş metin"))
                continue
            bulunan.append((arg.value, yer))
        elif isinstance(arg, ast.JoinedStr):
            uyarilar.append(Uyari(yer, f"{ad}() f-string ile çağrılmış (çıkarılamaz; "
                                       '_("… {ad} …").format(ad=…) kullan)', ast.unparse(arg)[:80]))
        elif _metin_insasi(arg):
            uyarilar.append(Uyari(yer, f"{ad}() içinde metin birleştirme/biçimleme (msgid "
                                       "biçimlenmiş metin olur; .format() _() DIŞINDA olmalı)",
                                  ast.unparse(arg)[:80]))
        else:
            uyarilar.append(Uyari(yer, f"{ad}() dinamik argüman (çıkarılmaz; N_() ile "
                                       "işaretli olmalı)", ast.unparse(arg)[:80], ciddi=False))
    return bulunan, uyarilar


def tara(kok: Path = PAKET) -> tuple[dict[str, list[str]], list[Uyari]]:
    """Scan every .py under ``kok`` → ({msgid: sorted locations}, warnings)."""
    kok = Path(kok)
    msgs: dict[str, set[str]] = {}
    uyarilar: list[Uyari] = []
    for path in sorted(kok.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        goreli = path.relative_to(kok).as_posix()
        bulunan, u = dosya_tara(path, goreli)
        uyarilar.extend(u)
        for msgid, yer in bulunan:
            msgs.setdefault(msgid, set()).add(yer)

    def yer_anahtari(y: str):
        f, _, n = y.rpartition(":")
        return f, int(n) if n.isdigit() else 0

    sonuc = {m: sorted(msgs[m], key=yer_anahtari) for m in sorted(msgs)}
    for msgid, yerler in sonuc.items():
        h = yer_tutucu_hatasi(msgid)
        if h:
            uyarilar.append(Uyari(yerler[0], h, repr(msgid)[:80]))
    return sonuc, uyarilar


def json_yaz(path: Path, data) -> None:
    """Atomic UTF-8 JSON write (readable, stable)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.chmod(tmp, 0o644)  # paketle dağıtılan veri dosyası (mkstemp 0600 açar)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def kaynak_oku(path: Path = KAYNAK_DOSYASI) -> dict[str, list[str]]:
    data = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON nesnesi bekleniyordu")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="_()/N_()/h_() metinlerini kaynak.json'a çıkarır.")
    ap.add_argument("--kok", type=Path, default=PAKET, help="taranacak paket dizini")
    ap.add_argument("--cikti", type=Path, default=KAYNAK_DOSYASI, help="kaynak.json yolu")
    ap.add_argument("--denetle", action="store_true",
                    help="yazma; çıkarılamayan çağrılar/bozuk yer tutucular varsa çıkış 1")
    ap.add_argument("--ayrinti", action="store_true", help="dinamik çağrıları da listele")
    a = ap.parse_args(argv)
    msgs, uyarilar = tara(a.kok)
    ciddi = [u for u in uyarilar if u.ciddi]
    bilgi = [u for u in uyarilar if not u.ciddi]
    for u in ciddi:
        print(f"HATA {u}", file=sys.stderr)
    if a.ayrinti:
        for u in bilgi:
            print(f"BİLGİ {u}", file=sys.stderr)
    if a.denetle:
        print(f"{len(msgs)} metin, {len(ciddi)} sorun, {len(bilgi)} dinamik çağrı (bilgi)")
        return 1 if ciddi else 0
    json_yaz(a.cikti, msgs)
    print(f"{len(msgs)} metin → {a.cikti} ({len(ciddi)} sorun, {len(bilgi)} dinamik çağrı)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
