"""Uygulama başına oturum politikası (docs/SESSIONS.md §8).

Varsayılanlar paket içindeki data/oturum.toml'dan okunur; kullanıcı CONFIG_DIR/oturum.toml ile üstüne yazar
(yalnız verdiği anahtarlar birleştirilir; vermediği varsayılanda kalır). Bilinmeyen uygulama `_varsayilan`
politikasını alır (kapali_iken=paylas, acik_iken=bekle; "açık mı" BİLİNEMİYORSA açık sayılır → bekle).

Eşleme: her bölümün `adlar` (tam ad/takma ad) ve `kimlik` (fnmatch: .desktop/Flatpak kimliği) listeleri.
`eslesen_anahtarlar(ad)` bir adın uyduğu TÜM bölümleri döndürür; birden çok aday addan gelen kararlar
`en_kisitlayici` ile birleştirilir (kapali > on > bekle > kopya > paylas).

Karar değerleri: kopya | paylas | bekle | kapali | on  (anlamları data/oturum.toml başında).

Site listeleri: `reddet` (çerez/deposu/kayıtlı parolası asla kopyalanmayan alanlar: banka/ödeme/devlet/merkezi
kimlik) ve görev bazlı `izin` (yalnız bu origin'ler kopyalanır). Eşleşme fnmatch kalıbı (`*bank*` gibi), alt alan
adları dahil; alan çerezi (`.google.com`) ret listesindeki bir alt alana gönderiliyorsa o da reddedilir.

Hesap oturumu izni (`Politika.kimlik_izni_uygula`): kullanıcı panelden bir sağlayıcıya (microsoft | google | edevlet)
izin verdiyse o sağlayıcının ret girdileri (KIMLIK_ALANLARI; YALNIZ bu tam girdiler) ret listesinden çıkar → o alanların
ve alan çerezlerinin (.live.com, .google.com, *.gov.tr) oturumu + kayıtlı girişleri + deposu kopyaya girer. Banka/ödeme
desenleri ve diğer girdiler hiçbir izinle etkilenmez (bir alan kalan herhangi bir girdiye uyarsa yine reddedilir). İzin kaynağı panel (liste_koruma.kimlik_izinleri); görev kipinde hiç uygulanmaz.
"""
from __future__ import annotations

import fnmatch
import functools
import os
import tomllib
import unicodedata

from .. import yollar

KARARLAR = ("kopya", "paylas", "bekle", "kapali", "on")

# Kimlik sağlayıcı → ret listesinde (data/oturum.toml [site] reddet "merkezi kimlik") duran alanları. Panelden izin
# verilirse YALNIZ bu tam girdiler ret listesinden çıkarılır (liste_koruma.KIMLIK_SAGLAYICILARI ile aynı adlar).
KIMLIK_ALANLARI = {
    "microsoft": ("login.live.com", "login.microsoftonline.com"),
    "google": ("accounts.google.com", "securetoken.googleapis.com"),
    # e-Devlet / devlet siteleri: reddet'teki devlet girdilerinin TAMAMI (desenler dahil). Banka/ödeme desenleri
    # (`*bank*`, `*odeme*`, `*payment*`…) HİÇBİR sağlayıcıda yok: hiçbir izinle açılmaz.
    "edevlet": ("*e-devlet*", "*edevlet*", "turkiye.gov.tr", "gib.gov.tr", "sgk.gov.tr", "*.gov.tr"),  # "*.gov" (ABD devlet: pay.gov…) DIŞARIDA
}
KIMLIK_ADLARI = {"microsoft": "Microsoft", "google": "Google", "edevlet": "e-Devlet"}  # özel ad: çevrilmez
_VARSAYILAN_AD = "_varsayilan"


def kimlik_alani_mi(alan: str) -> bool:
    """Alan (çerez alanı, baştaki nokta önemsiz) bir kimlik sağlayıcısının merkezi kimlik alanı ya da onun üst alanı mı
    (".google.com" çerezi accounts.google.com'a da gider). Kapanış uyarısı yalnız bunları kullanıcıya gösterir."""
    alan = _alan_normu(alan or "")[0].lstrip(".")
    if not alan:
        return False
    for kaliplar in KIMLIK_ALANLARI.values():
        if _alan_eslesir(alan, kaliplar):
            return True
        if any("*" not in k and (k == alan or k.endswith("." + alan)) and "." in alan for k in kaliplar):
            return True
    return False

# Paket içindeki varsayılan politika (yollar.PAKET_DIZIN = .../deskhand)
_PAKET_TOML = os.path.join(yollar.PAKET_DIZIN, "data", "oturum.toml")


def _oku_toml(yol: str) -> dict:
    try:
        with open(yol, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _birlestir(taban: dict, ust: dict) -> dict:
    """ust'ü taban'ın üstüne derin birleştir (sözlükler iç içe; diğer değerler ust kazanır)."""
    sonuc = dict(taban)
    for k, v in ust.items():
        if isinstance(v, dict) and isinstance(sonuc.get(k), dict):
            sonuc[k] = _birlestir(sonuc[k], v)
        else:
            sonuc[k] = v
    return sonuc


def yukle() -> dict:
    """Varsayılan + kullanıcı politikasını birleştirip döndür (her çağrıda okunur: testler yola bağlı)."""
    taban = _oku_toml(_PAKET_TOML)
    kull = _oku_toml(os.path.join(yollar.config_dir(), "oturum.toml"))
    return _birlestir(taban, kull)


# Kısıtlayıcılık sırası (büyük = daha kısıtlayıcı)
KISIT = {"paylas": 0, "kopya": 1, "bekle": 2, "on": 3, "kapali": 4}

# Ad sonundaki sürüm/kanal ekleri: google-chrome-beta → google-chrome, steam-native → steam
_EKLER = ("-beta", "-nightly", "-stable", "-unstable", "-dev", "-developer", "-canary", "-snapshot", "-browser",
          "-bin", "-native", "-git", "-desktop", "-esr", "-launcher", "-wayland", "-x11")


def en_kisitlayici(kararlar) -> str | None:
    """Kararlar içinden en kısıtlayıcısı (bilinmeyen değer en kısıtlayıcı sayılır)."""
    kararlar = [k for k in kararlar if k]
    if not kararlar:
        return None
    return max(kararlar, key=lambda k: KISIT.get(k, len(KISIT)))


def _ad_normu(uygulama: str) -> str:
    """Adı eşleme biçimine indir: küçük harf, yol ve .desktop/.exe eki atılır."""
    a = (uygulama or "").strip().lower()
    a = os.path.basename(a.rstrip("/"))
    for ek in (".desktop", ".exe", ".appimage"):
        if a.endswith(ek):
            a = a[: -len(ek)]
    return a


def _ad_varyantlari(ad: str) -> list[str]:
    """ad + sürüm/kanal ekleri atılmış hâlleri (sırayla): brave-browser-nightly → brave-browser → brave."""
    sonuc = [ad]
    degisti = True
    while degisti:
        degisti = False
        for ek in _EKLER:
            if ad.endswith(ek) and len(ad) > len(ek):
                ad = ad[: -len(ek)]
                sonuc.append(ad)
                degisti = True
    return sonuc


def eslesen_anahtarlar(uygulama: str, yapilandirma: dict | None = None) -> list[str]:
    """Adın uyduğu politika bölümleri (`_varsayilan` hariç). Ad: ham ad, .desktop kimliği, ikili adı ya da Flatpak
    kimliği olabilir. Eşleşme: bölüm adı, `adlar`, `kimlik` kalıpları; ekleri atılmış varyantlar da denenir."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    uygulamalar = yap.get("uygulama", {})
    a = _ad_normu(uygulama)
    if not a:
        return []
    varyantlar = _ad_varyantlari(a)
    # ters-DNS kimliğinin son parçası da (org.kde.kmail2 → kmail2); yalnız adlarla karşılaştırılır
    if "." in a and " " not in a:
        varyantlar += [v for v in _ad_varyantlari(a.rsplit(".", 1)[-1]) if v not in varyantlar]
    bulunan = []
    for anahtar, ham in uygulamalar.items():
        if anahtar == _VARSAYILAN_AD or not isinstance(ham, dict):
            continue
        adlar = {anahtar.lower(), *(str(x).lower() for x in ham.get("adlar", ()))}
        if ham.get("flatpak"):
            adlar.add(str(ham["flatpak"]).lower())
        kaliplar = [str(x).lower() for x in ham.get("kimlik", ())]
        if any(v in adlar for v in varyantlar) or any(fnmatch.fnmatchcase(a, k) for k in kaliplar):
            bulunan.append(anahtar)
    return bulunan


class Politika:
    """Tek uygulamanın çözülmüş politikası."""

    def __init__(self, uygulama: str, ham: dict, site: dict):
        self.uygulama = uygulama
        self.kapali_iken = ham.get("kapali_iken", "bekle")
        self.acik_iken = ham.get("acik_iken", "bekle")
        self.keyring = bool(ham.get("keyring", False))
        self.senkron = bool(ham.get("senkron", False))
        self.flatpak = ham.get("flatpak") or None
        self.disla = tuple(ham.get("disla", ()))
        self.not_ = ham.get("not") or ""
        # ev dizini beyaz liste girdileri (uygulama başına, ev dizinine göreli; salt okunur; varsayılan YOK): arka plan
        # ad alanında ev dizini boştur, uygulamanın kendi ayarı gerekiyorsa yalnız bu yolla verilir (geçersiz girdi atılır)
        from ..arka_ortak import gecerli_politika_ev_girdisi
        self.ev = tuple(g for g in (ham.get("ev") or ()) if gecerli_politika_ev_girdisi(g)) \
            if isinstance(ham.get("ev"), (list, tuple)) else ()
        # rules keep their written text; every comparison uses all their spellings (_bicimler, cached): equivalent
        # spellings (trailing dot, case, IDNA dots, Unicode ↔ punycode) behave the same and none is lost
        self._reddet = tuple(str(k).strip() for k in site.get("reddet", ()))
        self._izin = tuple(str(k).strip() for k in site.get("izin", ()))
        self.bilinen = True

    def karar(self, calisiyor: bool) -> str:
        return self.acik_iken if calisiyor else self.kapali_iken

    def kimlik_izni_uygula(self, saglayicilar) -> "Politika":
        """İzin verilen kimlik sağlayıcılarının merkezi kimlik alanları ret listesinden çıkarılmış KOPYA (self
        değişmez). Yalnız KIMLIK_ALANLARI'ndaki tam girdiler çıkar; desenler (`*bank*`, `*.gov.tr`) ve diğer alanlar
        aynen kalır. Bilinmeyen sağlayıcı adı yok sayılır. Çağıran görev kipinde ÇAĞIRMAZ."""
        import copy
        cikar = {_kural_anahtari(a) for s in (saglayicilar or ()) for a in KIMLIK_ALANLARI.get(s, ())}
        if not cikar:
            return self
        yeni = copy.copy(self)
        # equivalent spellings of the same entry (`login.live.com.`, `.LOGIN.LIVE.COM`) are the same entry
        yeni._reddet = tuple(k for k in self._reddet if _kural_anahtari(k) not in cikar)
        return yeni

    # ---- site süzme ----
    def site_reddedildi(self, alan: str) -> bool:
        """alan ret listesinde mi (kendisi ya da üst alanı)? Any spelling (_bicimler: ANY spelling matching rejects); a host whose IDNA label cannot
        be converted is rejected (closed-fail: its real name is unknown)."""
        if alan and not _alan_normu(alan)[1]:
            return True
        return _alan_eslesir(alan, self._reddet)

    def cerez_reddedildi(self, host: str, bilinen_konaklar=()) -> bool:
        """Çerez/giriş kaydı konağı reddedilmeli mi? Alanın kendisi (ya da üstü) ret listesindeyse; ayrıca ALAN
        çerezi (".google.com", baştaki nokta) ret listesindeki bir alt alana (accounts.google.com) da
        gönderildiği için reddedilir. host baştaki noktayla verilmezse yalnız ilk kural.
        Domain cookie rule (docs/SESSIONS.md §8 "Alan çerezi"):
          - a rule whose end is fixed (plain domain `accounts.google.com`, `*.bank.com`, `*.gov.tr`, `login?.x.com`)
            rejects `.alan` when it could match ANY subdomain of alan (some `X.alan`), decided from the rule alone
            (_alt_alana_uyabilir), without the profile: closed-safe;
          - a rule ending in `*` (`*bank*`, `bank.*`) can match a subdomain of EVERY domain (`bank.<alan>`); taken
            literally it would drop every domain cookie, so it only rejects `.alan` with evidence: a host known from
            the profile (`bilinen_konaklar`: cookie hosts, site storage, session cookies, open tabs, places.sqlite
            history incl. its WAL) that is a subdomain of alan and is rejected.
          The fixed part before the trailing `*`s is still decided from the rule alone (`*.bank.com*` → as
          `*.bank.com`: `*` may match the empty string), so a trailing `*` never weakens a fixed-tail rule.
        Every spelling of host and rules is tried (_bicimler: case, trailing dots, IDNA dots, Unicode and punycode);
        a host with an unconvertible IDNA label is rejected (closed-fail).
        Residual limit: a trailing-`*` rule does not cover a subdomain the profile has never seen."""
        r, u, a, tamam = _bicimler(str(host or ""))
        alan = r.lstrip(".")
        if not alan:
            return False
        if not tamam or self.site_reddedildi(alan):
            return True
        if not r.startswith("."):
            return False
        # every spelling of the domain (raw / unicode / ace, same index as _bicimler) against every spelling of a rule
        alanlar = (alan, u.lstrip("."), a.lstrip(".") if a is not None else None)
        adaylar = tuple(dict.fromkeys(x for x in alanlar if x))
        for kural in self._reddet:
            for k in _formlar(kural):
                for al in adaylar:
                    # plain rule equal to / under alan (also a leading-dot rule `.bank.com` → `.bank.com`)
                    if "*" not in k and "?" not in k and "[" not in k and (k == al or k.endswith("." + al)):
                        return True
                    # the ONLY switch between "decided from the rule" and "needs evidence": the trailing `*`; its
                    # fixed part (the rule with the trailing `*`s removed) is decided from the rule as well
                    sabit = k.rstrip("*")
                    if sabit and _alt_alana_uyabilir(sabit, al):
                        return True
        for b in bilinen_konaklar or ():
            br, bu, ba, b_tamam = _bicimler(str(b))
            for bx, ax in zip((br, bu, ba), alanlar, strict=True):  # the same spelling on both sides
                if bx is None or ax is None:
                    continue
                bx = bx.lstrip(".")
                if bx != ax and bx.endswith("." + ax) and (not b_tamam or self.site_reddedildi(bx)):
                    return True
        return False

    def site_izinli(self, alan: str, gorev_siteleri=None) -> bool:
        """izin listesi (politika + göreve özel) boşsa her alan izinli; doluysa yalnız eşleşenler.
        Ret her zaman izni ezer."""
        if self.site_reddedildi(alan):
            return False
        izin = tuple(self._izin) + tuple(gorev_siteleri or ())
        if not izin:
            return True
        return _alan_eslesir(alan, izin, hepsi=True)  # allow: both spellings of alan must match


def _glob_parcala(kural: str) -> list[tuple[str, str]]:
    """fnmatch pattern → tokens ("*", ""), ("?", ""), ("[", class pattern), ("=", literal char). Classes follow
    fnmatch.translate: `[!...]` negates, a `]` right after `[` / `[!` is literal, an unclosed `[` is a literal `[`."""
    parca, i, n = [], 0, len(kural)
    while i < n:
        c = kural[i]
        i += 1
        if c == "*":
            if not parca or parca[-1] != ("*", ""):
                parca.append(("*", ""))
        elif c == "?":
            parca.append(("?", ""))
        elif c == "[":
            j = i
            if j < n and kural[j] == "!":
                j += 1
            if j < n and kural[j] == "]":
                j += 1
            while j < n and kural[j] != "]":
                j += 1
            if j >= n:
                parca.append(("=", "["))
            else:
                parca.append(("[", kural[i - 1:j + 1]))
                i = j + 1
        else:
            parca.append(("=", c))
    return parca


def _alt_alana_uyabilir(kural: str, alan: str) -> bool:
    """Can the fnmatch rule match SOME subdomain host `X.alan` (X non-empty)? Exact search over the product of the
    pattern automaton and the language Σ⁺ "." alan (a few hundred states at most; no enumeration). Over-approximates
    only for a character class with no member at all (treated as matching some character): closed-safe."""
    import fnmatch
    parca = _glob_parcala(kural)
    m = len(parca)
    ek = "." + alan
    L = len(ek)
    # target states: -2 = nothing read yet, -1 = inside X (≥1 char), q ≥ 1 = q chars of ".alan" read (L = accept)

    def hedef_adimlari(q):  # → [(next state, required char or None = any char)]
        if q == -2:
            return [(-1, None)]
        if q == -1:
            return [(-1, None), (1, ek[0])]
        return [(q + 1, ek[q])] if q < L else []

    def uyar(tur, deger, ch):  # can pattern token accept char ch (None = some char of our choosing)?
        if tur in ("*", "?"):
            return True
        if tur == "=":
            return ch is None or ch == deger
        return ch is None or fnmatch.fnmatchcase(ch, deger)

    gorulen, yigin = set(), [(0, -2)]
    while yigin:
        i, q = yigin.pop()
        if (i, q) in gorulen:
            continue
        gorulen.add((i, q))
        if i == m and q == L:
            return True
        if i < m and parca[i][0] == "*":
            yigin.append((i + 1, q))  # `*` matches the empty string
        for q2, ch in hedef_adimlari(q):
            if i < m and parca[i][0] == "*":
                yigin.append((i, q2))  # `*` eats one more char
            elif i < m and uyar(parca[i][0], parca[i][1], ch):
                yigin.append((i + 1, q2))
    return False


# IDNA label separators besides "." (UTS #46 / RFC 3490 §3.1): a rule or host written with them is the same name
_IDNA_NOKTALARI = ("。", "．", "｡")


_GLOB = ("*", "?", "[")


@functools.lru_cache(maxsize=16384)
def _bicimler(metin: str) -> tuple[str, str, str | None, bool]:
    """The spellings of a host name or a reject/allow rule, so that equivalent spellings meet:
      raw     whitespace trimmed, IDNA dots → ".", lower case, trailing dot(s) dropped (labels as written);
      unicode every non-ASCII or ACE (`xn--…`) label → its nameprep'd Unicode form (`bankası`, `xn--bankas-u9a`);
      ace     every label of the unicode form that is still non-ASCII → its ACE form (None when a label cannot be
              encoded, or for a rule label mixing glob characters with non-ASCII text: no meaningful ACE pattern).
    ASCII labels, empty labels (a leading dot keeps its meaning) and glob characters are left as they are. A REJECT
    decision tries every spelling of the host against every spelling of the rule (any match rejects: a rule written
    in ACE, `*xn--*`, and `*bank*` against `xn--bank-cpa` keep working); an ALLOW decision needs the unicode AND the
    ace spelling of the host to match (_alan_eslesir hepsi=True).
    converted=False when some label could not be converted (broken punycode, an ACE label that decodes to ASCII or to
    upper-case / unnormalised text, a character nameprep prohibits, a label too long for ACE); that label is kept
    lower-cased as written. Callers treat an unconvertible HOST as rejected (closed-fail)."""
    s = str(metin or "").strip()
    for n in _IDNA_NOKTALARI:
        s = s.replace(n, ".")
    s = s.lower().rstrip(".")
    if s.isascii() and "xn--" not in s:
        return s, s, s, True  # fast path: plain ASCII names (almost every host)
    from encodings import idna
    uni: list[str] = []
    ace: list[str] | None = []
    tamam = True
    for e in s.split("."):
        u = e
        try:
            if e.startswith("xn--"):
                d = e[4:].encode("ascii").decode("punycode")
                if not d or d.isascii():
                    raise UnicodeError("ACE label without non-ASCII characters")
                if unicodedata.normalize("NFC", d).lower() != d:  # IDNA never encodes upper case / unnormalised
                    raise UnicodeError("non-canonical ACE label")   # text (`xn--bankas-n9a` = "bankasİ")
                u = idna.nameprep(d)
            elif not e.isascii():
                u = idna.nameprep(e)
        except (UnicodeError, ValueError):
            tamam = False
            u = e
        uni.append(u)
        if ace is None:
            continue
        if u.isascii():
            ace.append(u)
        elif any(g in u for g in _GLOB):
            ace = None  # a glob inside a non-ASCII rule label has no ACE equivalent
        else:
            try:
                ace.append(idna.ToASCII(u).decode("ascii"))
            except (UnicodeError, ValueError):
                ace, tamam = None, False
    return s, ".".join(uni), (".".join(ace) if ace is not None else None), tamam


@functools.lru_cache(maxsize=16384)
def _formlar(metin: str) -> tuple[str, ...]:
    """Distinct non-empty spellings (raw, unicode, ace) of _bicimler."""
    r, u, a, _ = _bicimler(metin)
    return tuple(dict.fromkeys(f for f in (r, u, a) if f))


def _alan_normu(metin: str) -> tuple[str, bool]:
    """(unicode spelling, converted) of _bicimler: one canonical form for display / equality."""
    _, u, _, tamam = _bicimler(str(metin or ""))
    return u, tamam


def _kural_anahtari(kural) -> str:
    """Identity of a rule for kimlik_izni_uygula: unicode spelling; a plain rule without its leading dot
    (`.login.live.com` is the same entry as `login.live.com`)."""
    u = _alan_normu(str(kural))[0]
    return u if any(g in u for g in _GLOB) else u.lstrip(".")


def _tek_eslesir(alan: str, k: str) -> bool:
    """One spelling of a host against one spelling of a rule: fnmatch, or a plain rule (no `*`, `?`) covering
    subdomains; a leading dot on a plain rule (`.bank.com`) means the same as `bank.com`."""
    if fnmatch.fnmatchcase(alan, k):
        return True
    duz = k.lstrip(".")
    return bool(duz) and "*" not in k and "?" not in k and (alan == duz or alan.endswith("." + duz))


def _alan_eslesir(alan: str, kaliplar, hepsi: bool = False) -> bool:
    """alan matches one of the fnmatch rules, every spelling (_bicimler) of the rules considered.
    hepsi=False (reject lists): ANY spelling of alan matching rejects.
    hepsi=True (allow lists): the unicode AND the ace spelling of alan must each match (no spelling widens access).
    An unconvertible alan only matches as written: callers that reject decide closed-fail themselves
    (Politika.site_reddedildi)."""
    if not alan:
        return False
    r, u, a, _ = _bicimler(str(alan))
    if not r:
        return False
    kurallar = [f for k in kaliplar for f in _formlar(str(k))]
    if not kurallar:
        return False
    adaylar = tuple(dict.fromkeys(f for f in (u, a) if f)) if hepsi else _formlar(str(alan))
    sec = all if hepsi else any
    return sec(any(_tek_eslesir(h, k) for k in kurallar) for h in adaylar)


def coz(uygulama: str, yapilandirma: dict | None = None) -> Politika:
    """Tek ad için politika nesnesi. Ad birden çok bölüme uyarsa en kısıtlayıcısı (kapalıyken, sonra açıkken
    kararına göre); hiçbirine uymazsa `_varsayilan` (Politika.uygulama = normlanmış ad, bilinen=False)."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    anahtarlar = eslesen_anahtarlar(uygulama, yap)
    if anahtarlar:
        return max((anahtar_politikasi(k, yap) for k in anahtarlar),
                   key=lambda p: (KISIT.get(p.kapali_iken, len(KISIT)), KISIT.get(p.acik_iken, len(KISIT))))
    return anahtar_politikasi(_VARSAYILAN_AD, yap, ad=_ad_normu(uygulama))


def anahtar_politikasi(anahtar: str, yapilandirma: dict | None = None, ad: str | None = None) -> Politika:
    """Bölüm adından Politika (anahtar yoksa `_varsayilan`)."""
    yap = yapilandirma if yapilandirma is not None else yukle()
    uygulamalar = yap.get("uygulama", {})
    bilinen = anahtar != _VARSAYILAN_AD and anahtar in uygulamalar
    ham = uygulamalar.get(anahtar) if bilinen else None
    ham = ham or uygulamalar.get(_VARSAYILAN_AD) or {"kapali_iken": "bekle", "acik_iken": "bekle", "keyring": False}
    pol = Politika(anahtar if bilinen else (ad or anahtar), ham, yap.get("site", {}))
    pol.bilinen = bilinen
    if not bilinen:  # ev beyaz listesi YALNIZ uygulama başına: `_varsayilan`daki `ev` bilinmeyen uygulamalara verilmez
        pol.ev = ()
    return pol


def kopya_dizini(ad: str | None = None) -> str:
    """Kopyaların kök dizini (0700): masaüstü BAŞINA (ad None: bağlamdaki masaüstü, masalar.secili()). Varsayılan
    masaüstü RUNTIME_DIR/oturum (eskisiyle aynı); adlı masaüstü RUNTIME_DIR/masa/<ad>/oturum."""
    from .. import masalar
    return masalar.oturum_koku(ad)


def flatpak_kayit(ad: str | None = None) -> str:
    """Deskhand'nin o masaüstünde başlattığı Flatpak örneklerinin kaydı (<kopya_dizini(ad)>/flatpak.json)."""
    return os.path.join(kopya_dizini(ad), "flatpak.json")
