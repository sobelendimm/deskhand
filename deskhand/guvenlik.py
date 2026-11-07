"""Güvenlik katmanı (iki arka uçta da AYNEN, docs/ARCHITECTURE.md §4):

- Yasak pencereler (CONFIG_DIR/yasak-pencereler.txt): hiçbir girdi gönderilmez, uygulama başlatılmaz (10).
- Hassas düğme (ödeme/yetki/hesap silme) ve ödeme sayfası başlığı: --onayli olmadan tıklanmaz (10).
  --onayli YALNIZ kullanıcı o adımı sohbette açıkça onayladıysa verilir.
- Başlık (-b) ve sınıf (-s) kilidi: her girdiden hemen önce (4).
- DUR anahtarı (RUNTIME_DIR/dur): her girdi satırından önce (13); `dur` oluşturur, `devam` siler. Yazma/kaldırma
  atomik: kullanıcının (arayüzden) koyduğu DUR'u ajan hiçbir yarışta kaldıramaz ya da ezemez.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading

from . import yollar
from .arka_uc import EKRAN, sec
from .hata import KULLANICI_DUR, Dur, dur_dosyasi
from .i18n import N_, _
from .ocr import katla

SINIF_DESEN = None  # -s: hedef (masaüstü kipinde etkin) pencerenin SINIFI bu desene uymalı (başlıksız pencereler: krunner)

VARSAYILAN_YASAK = N_("""# Bu desenlere (regex, büyük/küçük harf duyarsız) uyan pencere BAŞLIĞI ya da SINIFINA hiçbir girdi
# (tıklama/tuş/yazı/kaydırma) gönderilmez ve uygulama başlatılmaz. Okuma serbesttir. Varsayılan: boş.
# Örnekler (başındaki # işaretini kaldırarak açın):
# KeePassXC
# ^Online Banking
""")  # dosyaya ilk açılışta, seçili dilde yazılır
# Ödeme / yetki verme / hesap silme: kullanıcının kararı. Türkçe harfler katlanmış (ş→s, ı→i…) metinde aranır.
HASSAS = re.compile(
    r"\b(satin al\w*|simdi al|hemen al|ode|odeme yap\w*|odemeyi (tamamla|onayla)\w*|siparis ver\w*|"
    r"siparisi (tamamla|onayla)\w*|alisverisi tamamla\w*|buy( now)?|purchase|pay( now)?|place order|"
    r"complete (order|purchase|payment)|confirm (order|payment|purchase)|authori[sz]e|yetkilendir\w*|"
    r"izin ver\w*|allow|grant( access)?|hesab\w* sil\w*|delete (my )?account|kalici olarak sil\w*|"
    r"permanently delete)\b")
# başlığı ödeme/sipariş onayı olan sayfada HER tıklama ve Enter/boşluk onay ister: OCR'ın okuyamadığı
# ödeme düğmesine (ör. orta ton zeminde beyaz yazı) koordinatla basılmasın. Form doldurmak (yaz) serbest; ama
# yazı Enter/Tab/boşluk içeriyorsa (\n = gönder, Tab+boşluk = odaktaki düğmeye bas) o da onay ister.
HASSAS_SAYFA = re.compile(r"\b(odeme|checkout|payment|siparisi (onayla|tamamla)\w*|siparis ozeti|"
                          r"order (review|summary)|kasa|billing)\b")

# Enter/boşluk eşdeğerleri (tus_coz SONRASI çözülmüş tuş): ad, X keysym (x:…) ve evdev kodu (k:…). Hassas sayfada
# bunlardan biri onay ister; çözülemeyen x:/k: tuşu da (güvenli taraf) onay ister.
ONAY_TUS_ADLARI = {"enter", "kpenter", "space", "linefeed", "return", "kp_enter", "kp_space", "iso_enter"}
# Return, KP_Enter, ISO_Enter, space, KP_Space, Linefeed, 3270_Enter, nobreakspace
ONAY_KEYSYM = {0xff0d, 0xff8d, 0xfe34, 0x20, 0xff80, 0xff0a, 0xfd1e, 0xa0}
ONAY_EVDEV = {28, 57, 96, 101}  # KEY_ENTER, KEY_SPACE, KEY_KPENTER, KEY_LINEFEED


def _keysym(ad):
    """x:AD → keysym sayısı | None (çözülemedi). Ad (Return), 0xff0d, U+000D / U000D, tek karakter."""
    m = re.fullmatch(r"0x([0-9a-f]+)", ad, re.I)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"U\+?([0-9a-f]{1,6})", ad, re.I)
    if m:
        return 0x1000000 + int(m.group(1), 16)
    if len(ad) == 1:
        return ord(ad) if ord(ad) < 0x100 else 0x1000000 + ord(ad)
    try:
        from Xlib import XK
        return XK.string_to_keysym(ad) or None
    except Exception:  # noqa: BLE001 - python-xlib yoksa çözülemedi say (güvenli taraf)
        return None


def onay_tusu_mu(kombinasyon):
    """Çözülmüş tuş dizisinde (eylem.tus_coz çıktısı: 'ctrl+enter x:Return k:28') Enter/boşluk eşdeğeri var mı?"""
    for akor in (kombinasyon or "").split():
        for t in akor.split("+"):
            if t.startswith("k:"):
                try:
                    if int(t[2:]) in ONAY_EVDEV:
                        return True
                except ValueError:
                    return True
            elif t.startswith("x:"):
                ks = _keysym(t[2:])
                if ks is None or t[2:].lower() in ONAY_TUS_ADLARI or ks in ONAY_KEYSYM:
                    return True
                kod = ks - 0x1000000 if ks >= 0x1000000 else ks  # Unicode keysym → kod noktası
                if kod < 0x110000 and chr(kod).isspace():  # U+000D, U+000A, U+0020, U+00A0…
                    return True
            elif t.lower() in ONAY_TUS_ADLARI:
                return True
    return False


def yazi_onay_ister_mi(metin):
    """Yazı Enter (\n), Tab ya da boşluk (her tür Unicode boşluk: nbsp da Space tuşuyla yazılır) içeriyor mu
    (hassas sayfada formu gönderme / odaktaki düğmeye basma olabilir)."""
    return any(c.isspace() for c in metin)


# ---------------------------------------------------------------- yasak pencereler

# Kullanıcı dosyasından BAĞIMSIZ, silinemeyen yasaklar: Deskhand paneli ve onay diyaloğu. Ajan bunlara girdi
# gönderebilseydi kendi isteğini onaylayabilir ya da kullanıcının DUR'unu kaldırabilirdi.
YERLESIK_YASAK = (r"^deskhand$", r"^Deskhand — Onay")


def yasak_desenler():
    return list(YERLESIK_YASAK) + _kullanici_yasaklari()


def _kullanici_yasaklari():
    yol = yollar.yasak_dosya()
    if not os.path.exists(yol):
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, "w") as f:
            f.write(_(VARSAYILAN_YASAK))
    with open(yol) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def yasak_denetle(k):
    if k == EKRAN or not k:
        return  # masaüstü kipinde: klavye → etkin pencere (denetle), fare → imlecin altındaki pencere denetlenir
    au = sec()
    b, sinif = au.baslik(k), au.sinif(k)
    for d in yasak_desenler():
        if re.search(d, b, re.I) or re.search(d, sinif, re.I):
            raise Dur(10, _("YASAK pencere: {baslik} (sınıf {sinif}) /{desen}/ ile eşleşti; hiçbir girdi gönderilmez "
                            "({dosya})").format(baslik=repr(b), sinif=repr(sinif), desen=d, dosya=yollar.yasak_dosya()))


def baslatma_yasak_denetle(*metinler):
    """Yasak listesindeki uygulama BAŞLATILMAZ. Steam oyun kimliği (rungameid/ID, -applaunch ID) pencere
    sınıfı biçimine (steam_app_ID) çevrilip o desenlerle de karşılaştırılır."""
    ek = [f"steam_app_{n}" for m in metinler for n in re.findall(r"(?:rungameid/|steam://run/|-applaunch\s+)(\d+)", m or "")]
    for d in yasak_desenler():
        for m in (*metinler, *ek):
            if m and re.search(d, m, re.I):
                raise Dur(10, _("YASAK uygulama: {uygulama} /{desen}/ ile eşleşti; başlatılmadı ({dosya})").format(
                    uygulama=repr(m), desen=d, dosya=yollar.yasak_dosya()))


# ---------------------------------------------------------------- pencere / başlık / sınıf kilidi

def sinif_denetle(k):
    if SINIF_DESEN:
        sinif = sec().sinif(k)
        if not re.search(SINIF_DESEN, sinif, re.I):
            raise Dur(4, _("pencere sınıfı uymadı: {sinif} (beklenen /{desen}/); girdi gönderilmedi").format(
                sinif=repr(sinif), desen=SINIF_DESEN))


def denetle(k, desen):
    """Girdi göndermeden HEMEN önce: pencere hâlâ aktif mi, yasak değil mi, başlık (sekme) doğru mu."""
    au = sec()
    if k == EKRAN:  # masaüstü kipi: etkin pencere yasak olmasın; -b verildiyse etkin pencerenin başlığı uysun
        a = au.aktif()
        if not a:  # boşsa yasak denetimi atlanırdı (yasak pencere öndeyken bile) → doğrulanamadı = dur
            raise Dur(3, _("etkin pencere belirlenemedi; girdi gönderilmedi"))
        yasak_denetle(a)
        if desen and not re.search(desen, au.baslik(a), re.I):
            raise Dur(4, _("etkin pencere başlığı uymadı: {baslik} (beklenen /{desen}/)").format(
                baslik=repr(au.baslik(a)), desen=desen))
        sinif_denetle(a)
        return
    a = au.aktif()  # boşsa doğrulanamadı → a != k → durur (güvenli taraf)
    if a != k:
        raise Dur(3, _("aktif pencere değişti → {baslik}; girdi gönderilmedi").format(baslik=repr(au.baslik(a))))
    yasak_denetle(k)
    if desen:
        b = au.baslik(k)
        if not re.search(desen, b, re.I):
            raise Dur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/); girdi gönderilmedi").format(
                baslik=repr(b), desen=desen))
    sinif_denetle(k)


def imlec_alti_denetle(k, px=None, py=None):
    """mouseto'dan sonra, tıklamadan ÖNCE (tek sorgu): (1) imleç gerçekten hedef noktada mı — kullanıcı
    arada fareyi oynattıysa tıklama başka yere düşerdi → 12; (2) altındaki pencere hedef mi? Yasak → 10; başka
    uygulamanın penceresi (bildirim, üstte duran pencere) → 3. Aynı uygulamanın açılır menüsü serbest."""
    au = sec()
    fx, fy, w = au.fare()
    if px is not None and fx is not None and (abs(fx - px) > 2 or abs(fy - py) > 2):
        raise Dur(12, _("imleç hedefte değil ({fx},{fy} ≠ {px},{py}): kullanıcı fareyi oynattı (insan önceliği); "
                        "tıklanmadı").format(fx=fx, fy=fy, px=px, py=py))
    if not w:  # imlecin altı bilinemedi: neyin üstüne tıklanacağı doğrulanamaz → dur (güvenli taraf)
        raise Dur(3, _("imlecin altındaki pencere doğrulanamadı; tıklanmadı"))
    if w == k:
        return
    yasak_denetle(w)
    if k == EKRAN:
        return
    if au.sinif(w) != au.sinif(k):
        raise Dur(3, _("imlecin altında başka pencere var: {baslik}; tıklanmadı").format(baslik=repr(au.baslik(w))))


# ---------------------------------------------------------------- hassas düğme / ödeme sayfası

_EYLEM = threading.local()  # iş parçacığı başına: bu eylem için insan onayı alındı mı


def eylem_basladi():
    """Her eylemin başında (eylem.girdi_al) çağrılır: önceki eylemin onayı yeni eyleme TAŞINMAZ."""
    _EYLEM.onaylandi = False


def _panelden_onay(eylem, hedef, ayrinti, goruntu=None):
    """Paneldeki insandan bir kez izin (CONTRACT §8). → (izin, neden). Panel/onay modülü yoksa (False, neden).
    Aynı eylemde ikinci hassas denetim (sayfa + düğme) yeniden sormaz: bir eylem = bir onay.
    goruntu: hedefin küçük görüntüsü (PIL) — kullanıcı NEYİ onayladığını görür."""
    if getattr(_EYLEM, "onaylandi", False):
        return True, _("bu eylem için zaten onaylandı")
    try:
        from . import onay
    except Exception as e:  # noqa: BLE001
        return False, _("onay modülü yüklenemedi: {hata}").format(hata=e)
    s = onay.iste_sonuc(eylem, hedef, ayrinti, masaustu=sec().ad, goruntu=goruntu)
    if s.izin:
        _EYLEM.onaylandi = True
    return s.izin, s.mesaj


ONAY_GORUNTU = (480, 200)  # onay isteğindeki küçük görüntü: tıklama noktasının çevresi (pencere pikseli)


def hedef_goruntusu(k, nokta=None):
    """Onay isteği için hedefin küçük görüntüsü: nokta verildiyse çevresi (nokta kırmızı çerçeveyle işaretli),
    yoksa pencerenin küçültülmüşü. Alınamazsa None (onay yine sorulur, yalnız görüntüsüz)."""
    try:
        from PIL import ImageDraw

        from .gorsel import pencere_goruntusu
        if nokta is None:
            im, _geo, _kok = pencere_goruntusu(k)
            im = im.copy()
            im.thumbnail((640, 400))
            return im
        x, y = round(nokta[0]), round(nokta[1])
        gw, gh = ONAY_GORUNTU
        im, _geo, (bx, by) = pencere_goruntusu(k, (x - gw // 2, y - gh // 2, gw, gh))
        im = im.convert("RGB")
        d = ImageDraw.Draw(im)
        px, py = x - bx, y - by
        d.rectangle([px - 14, py - 14, px + 14, py + 14], outline=(230, 30, 30), width=3)
        return im
    except Exception:  # noqa: BLE001 - görüntü isteğe bağlı
        return None


def _nokta_ayrintisi(nokta, yakin):
    if nokta is None:
        return ""
    yazi = " | ".join(t for t in yakin if t) or _("(okunamadı)")
    return "\n" + _("{x},{y} noktasındaki yazı: {yazi}").format(x=round(nokta[0]), y=round(nokta[1]), yazi=yazi)


def hassas_sayfa_engel(k, onayli, ne, yakin=(), nokta=None, ek=""):
    """Başlığı ödeme/onay sayfası olan pencerede eylem (tıklama, Enter/boşluk, Enter/boşluklu yazı) onay ister.
    yakin: tıklanacak noktadaki yazılar, nokta: (x, y) pencere pikseli, ek: ayrıntıya eklenecek satır (tuş, yazı).
    Onay isteği noktadaki yazıyı, hassas düğme metnini ve hedefin küçük görüntüsünü taşır (kullanıcı NEYİ
    onayladığını görür); aynı eylemdeki hassas düğme denetimi yeniden sormaz. → sayfa hassas mı."""
    b = sec().baslik(k)
    m = HASSAS_SAYFA.search(katla(b))
    if m and not onayli:
        ayrinti = _("Sayfa başlığı ödeme/onay sayfası gibi: {eslesen}").format(eslesen=repr(m.group(0)))
        ayrinti += _nokta_ayrintisi(nokta, yakin)
        dugme = next((t for t in yakin if t and HASSAS.search(katla(t))), None)
        if dugme:
            ayrinti += "\n" + _("Hassas düğme: “{dugme}”").format(dugme=dugme)
        if ek:
            ayrinti += "\n" + ek
        goruntu = None if getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k, nokta)
        izin, neden = _panelden_onay(_("Hassas sayfada {eylem}").format(eylem=ne), b, ayrinti, goruntu)
        if not izin:
            raise Dur(10, _("HASSAS sayfa ({eslesen} ← {baslik}): bu sayfada {eylem} kullanıcının onayını ister "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=repr(m.group(0)), baslik=repr(b), eylem=ne, neden=neden), tur="hassas")
    return bool(m)


def hassas_mi(*metinler):
    for t in metinler:
        m = HASSAS.search(katla(t or ""))
        if m:
            return m.group(0)
    return None


def hassas_engel(onayli, *metinler, hedef="", k=None, nokta=None):
    """Hassas düğme (Satın al / Öde / Yetkilendir / Hesabı sil…) onay ister. k + nokta verildiyse onay isteği
    noktadaki yazıyı ve çevresinin küçük görüntüsünü taşır."""
    eslesen = hassas_mi(*metinler)
    if eslesen and not onayli:
        yakin = [m for m in metinler if m]
        asil = next((m for m in yakin if HASSAS.search(katla(m))), eslesen)  # kullanıcıya ekrandaki yazı gösterilir
        ayrinti = _("Ödeme/yetki/hesap silme gibi hassas bir düğme") + _nokta_ayrintisi(nokta, yakin)
        goruntu = None if k is None or getattr(_EYLEM, "onaylandi", False) else hedef_goruntusu(k, nokta)
        izin, neden = _panelden_onay(_("Düğmeye tıkla: “{dugme}”").format(dugme=asil), hedef or " / ".join(yakin[:2]),
                                     ayrinti, goruntu)
        if not izin:
            raise Dur(10, _("HASSAS düğme ('{eslesen}' ← {yakin}): ödeme/yetki/hesap silme kullanıcının kararı "
                            "({neden}); kullanıcı sohbette açıkça onayladıysa --onayli ile tekrarla").format(
                eslesen=eslesen, yakin=yakin, neden=neden), tur="hassas")
    return eslesen


# ---------------------------------------------------------------- DUR anahtarı

def dur_acik():
    return os.path.exists(dur_dosyasi())


def _icerik(kaynak):
    return f"{kaynak} {os.getpid()}\n"


def _gecici_yaz(dizin, icerik):
    """Aynı dizinde geçici dosya (atomik link/replace için). → yol."""
    fd, yol = tempfile.mkstemp(prefix=".dur-", dir=dizin)
    with os.fdopen(fd, "w") as f:
        f.write(icerik)
    return yol


def dur_ac(kaynak="cli"):
    """DUR anahtarını aç: bundan sonra hiçbir deskhand süreci girdi göndermez (13); basılı tuşlar bırakılır.
    kaynak: "kullanici" (arayüz/tepsi/kısayol: insanın kararı) ya da "cli" (ajan/komut satırı).
    Atomik: okuyan hiçbir an yarım/boş dosya görmez. Ajan (cli) var olan DUR'a dokunmaz (os.link: yalnız yoksa
    oluşturur), böylece kullanıcının DUR'u hiçbir yarışta ajanınkiyle ezilmez; kullanıcınınki her zaman yazılır."""
    yol = dur_dosyasi()
    dizin = os.path.dirname(yol)
    os.makedirs(dizin, mode=0o700, exist_ok=True)
    gecici = _gecici_yaz(dizin, _icerik(kaynak))
    try:
        if kaynak == "kullanici":
            os.replace(gecici, yol)
            gecici = None
        else:
            try:
                os.link(gecici, yol)  # yoksa oluştur; varsa (kimin olursa olsun) olduğu gibi kalsın
            except FileExistsError:
                pass
    finally:
        if gecici:
            try:
                os.remove(gecici)
            except OSError:
                pass
    return yol


def _kaynak_coz(metin):
    ilk = metin.split()
    return "kullanici" if ilk and ilk[0] == "kullanici" else "cli"


def dur_kaynagi():
    """Açık DUR'u kim koydu: "kullanici" | "cli" | None (kapalı)."""
    try:
        with open(dur_dosyasi()) as f:
            return _kaynak_coz(f.read())
    except OSError:
        return None


def dur_kapat(kaynak="cli"):
    """DUR anahtarını kapat. → önceden açık mıydı. Kullanıcının (arayüzden) koyduğu DUR'u yalnız kullanıcı
    kaldırır: ajan 'devam' diyerek insanın durdurma kararını geri alamaz → Dur(13).
    Yarışsız: ajan dosyayı önce geçici ada TAŞIR (atomik), sonra taşıdığı dosyanın içeriğine bakar; o arada
    kullanıcı DUR koyduysa (içerik 'kullanici') dosyayı geri koyar ve 13 verir."""
    yol = dur_dosyasi()
    if kaynak == "kullanici":
        try:
            os.remove(yol)
            return True
        except FileNotFoundError:
            return False
    if dur_kaynagi() == "kullanici":  # sıradan durum: hiç dokunmadan reddet
        raise Dur(KULLANICI_DUR, _("DUR'u kullanıcı koydu; yalnız kullanıcı Deskhand panelinden/tepsiden kaldırabilir"))
    tasinan = f"{yol}.kaldir-{os.getpid()}-{threading.get_ident()}"
    try:
        os.rename(yol, tasinan)
    except FileNotFoundError:
        return False
    try:
        with open(tasinan) as f:
            sahip = _kaynak_coz(f.read())
    except OSError:
        sahip = "kullanici"  # okunamadı: güvenli taraf (geri koy)
    if sahip == "kullanici":
        try:
            os.link(tasinan, yol)  # yerinde yeni bir DUR yoksa geri koy
        except FileExistsError:
            os.replace(tasinan, yol)  # yeni DUR (ajanınki ya da kullanıcınınki) varsa: kullanıcınınki kazanır
            tasinan = None
        finally:
            if tasinan:
                os.remove(tasinan)
        raise Dur(KULLANICI_DUR, _("DUR'u kullanıcı koydu; yalnız kullanıcı Deskhand panelinden/tepsiden kaldırabilir"))
    os.remove(tasinan)
    return True
