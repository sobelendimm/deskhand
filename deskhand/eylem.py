"""Eylemler (girdi gönderen komutlar): tikla, tus, yaz, kaydir, bas, fare, surukle, dizi, kapat, metne-tikla,
simgeye-tikla, renge-tikla. Arka uçtan BAĞIMSIZ üst katman: pencere/görüntü/girdi işleri yalnız ArkaUc
yöntemleriyle (arka_uc.sec()); girdi dili dotool satır dilidir (docs/ARCHITECTURE.md §2).
Pencere koordinatı → ekran koordinatı dönüşümü burada (ekran_noktasi)."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import unicodedata


from . import yollar
from .arka_uc import EKRAN, ArkaUc, sec
from .gorsel import bolge_coz, pencere_goruntusu, renk_alanlari, simge_bul_ic
from .gunluk import gunluk
from . import dogrulama_sinamasi, guvenlik, ucbirim
from .guvenlik import (denetle, hassas_engel, hassas_sayfa_engel, hedef_pencere_denetle,
                       imlec_alti_denetle, onay_tusu_mu, yasak_denetle, yazi_onay_ister_mi)
from .hata import Dur, dur_denetle
from .i18n import N_, _
from .insan import HARF_SN
from .komutlar import akis_adimi
from .ocr import KAYDIR_BEKLE, YEDEK_OKUMALAR, ara, ayni_konum, bul_dongu, dogrula, kayma, kok_ekle, nokta_metni, oku, satirla, \
    yazdir_eslesme

GIRDI_KOMUTLARI = {"tikla", "tus", "yaz", "kaydir", "metne-tikla", "kapat", "simgeye-tikla", "bas", "fare",
                   "surukle", "dizi", "renge-tikla", "akis", "ogeye-tikla", "pencere", "ogeye-yaz", "git"}
OKUMA_KOMUTLARI = {"foto", "metin", "bekle", "simge-bul", "simge-kaydet", "renk-bul"}


def _au():
    return sec()


def _istege_bagli(ad, varsayilan):
    """ArkaUc'nin zorunlu olmayan yöntemi (kde'de var; yoksa güvenli varsayılan)."""
    return getattr(_au(), ad, None) or varsayilan


# ---------------------------------------------------------------- yazı hazırlığı

# klavye düzeninde OLMAYAN karakterlerin yedekleri (dotool bunları uyarıyla atlıyordu: — – …)
YEDEK = {"—": "-", "–": "-", "−": "-", "‐": "-", "‑": "-", "…": "...", "‘": "'", "’": "'", "‚": "'",
         "“": '"', "”": '"', "„": '"', " ": " ", " ": " ", " ": " ", "•": "*", "×": "x"}


def denetim_karakteri_denetle(metin):
    """Yazıda \\n, \\t (ve \\n'e çevrilen \\r) DIŞINDA denetim karakteri (C0/C1, DEL: \\x08 geri silme, \\x1b
    Esc, \\x7f…) varsa HİÇBİR ŞEY göndermeden Dur(1). Bu karakterler tuş olarak gidince (Esc → diyalog kapanır,
    geri silme → yazılanı siler) yazının görünen anlamı değişir. İleti yalnız konum ve kod verir (gizli yazı da)."""
    for i, c in enumerate(metin):
        if c not in "\n\t\r" and unicodedata.category(c) == "Cc":
            raise Dur(1, _("yazıda denetim karakteri var ({konum}. karakter, U+{kod}): yalnız \\n (Enter) ve \\t (Tab) "
                           "yazılabilir; Esc/geri silme gibi tuşlar için tus/press_key kullan. Hiçbir şey yazılmadı"
                           ).format(konum=i + 1, kod=f"{ord(c):04X}"))


def yazima_hazirla(metin, gizli=False):
    """Yazmadan ÖNCE: klavye düzeninde olmayan karakteri yedeğiyle değiştir; yedeği yoksa hiç yazmadan DUR.
    gizli=True: karakter DEĞİŞTİRİLMEZ (parola 'Café' 'Cafe' olarak yazılmasın): düzende olmayan karakterde hiç yazmadan
    DUR; iletiler karakteri değil yalnız konumu/uzunluğu verir."""
    denetim_karakteri_denetle(metin)
    yazilabilir_mi = _istege_bagli("yazilabilir_mi", lambda c: True)
    klavye_duzeni = _istege_bagli("klavye_duzeni", lambda: ("tr", ""))
    sonuc, degisen = [], {}
    for i, c in enumerate(metin):
        if c in "\n\t" or " " <= c <= "~" or yazilabilir_mi(c):
            sonuc.append(c)
            continue
        if gizli:
            raise Dur(1, _("gizli yazının {konum}. karakteri '{duzen}' düzeninde yok (uzunluk {uzunluk}); gizli yazıda "
                           "karakter değiştirilmez; hiçbir şey yazılmadı").format(
                konum=i + 1, duzen=klavye_duzeni()[0], uzunluk=len(metin)))
        y = YEDEK.get(c)
        if y is None:
            sade = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
            y = sade if sade and all(" " <= x <= "~" or yazilabilir_mi(x) for x in sade) else None
        if y is None:
            raise Dur(1, _("yazılamayan karakter {karakter} (U+{kod}): '{duzen}' düzeninde yok, yedeği yok; "
                           "hiçbir şey yazılmadı").format(karakter=repr(c), kod=f"{ord(c):04X}", duzen=klavye_duzeni()[0]))
        degisen[c] = y
        sonuc.append(y)
    if degisen:
        print(_("UYARI: '{duzen}' düzeninde olmayan karakterler değiştirildi: {liste}").format(
            duzen=klavye_duzeni()[0], liste=", ".join(f"{k!r}→{v!r}" for k, v in degisen.items())), file=sys.stderr)
    return "".join(sonuc)


# ---------------------------------------------------------------- girdi nesnesi

# dizi kipinde TEK Girdi (tek dotool kurulumu: adım başına 0,65 sn kazanç). İş parçacığına özgü: MCP'de bir akış
# onay beklerken (kilit bırakılmışken) başka bir aracın eylemi bu girdiyi devralmasın.
_DIZI = threading.local()


def _paylasilan():
    return getattr(_DIZI, "g", None)


def _bekleyen_onay_kapisi():
    """Başka bir süreç (ör. MCP sunucusu) bu masaüstü için insan onayı beklerken bu süreç girdi göndermesin: onay
    diyaloğundaki hedef araya giren girdiyle değişebilirdi → Dur 7. `onay.bekleyen_var` yoksa (eski onay modülü) yok."""
    try:
        from . import onay
    except Exception:  # noqa: BLE001
        return
    f = getattr(onay, "bekleyen_var", None)
    if f is None:
        return
    import os
    if f("arka" if _au().ad == "sanal" else "ekran", haric_pid=os.getpid()):
        raise Dur(7, _("onay bekleniyor: başka bir Deskhand sürecinin insan onayı sürerken girdi gönderilmez"))


def girdi_al(etiket="", gizli=False):
    """Girdi nesnesi: arka ucun girdisi, üst katmanın güvenlik denetimi (guvenlik.denetle) bağlı."""
    guvenlik.eylem_basladi()
    _bekleyen_onay_kapisi()
    pg = _paylasilan()
    if pg is not None:
        pg.etiket, pg.gizli = f"dizi: {etiket}", gizli
        return pg
    return _au().girdi(etiket, gizli, denetle=denetle)


def girdi_birak(g, k=None):
    """k: girdinin gittiği pencere (bilinmiyorsa/masaüstü kipinde tüm pencereler kirli sayılır)."""
    try:
        if g is not _paylasilan():
            g.kapat()
    finally:
        # girdi gitti: sayfa değişmiş olabilir (o pencerenin sınama kaydı kirlenir; "sınama yok" + odak önbellekleri silinir)
        dogrulama_sinamasi.girdi_oldu(k)


def basili_bekle(g, k, desen, sure, beklenen_fare=None):
    """Bir şey BASILIYKEN bekle; ~10 ms'de bir: etkin pencere, başlık, fare (insan önceliği). Değişirse Dur
    fırlatır — çağıran `finally` içinde MUTLAKA bırakır."""
    bitis = time.monotonic() + sure
    f0 = beklenen_fare or _au().fare()[:2]
    while True:
        kalan = bitis - time.monotonic()
        if kalan <= 0:
            return
        dur_denetle()  # DUR anahtarı: çağıranın finally'si bırakır
        hedef = _au().aktif() if k == EKRAN else k
        if k != EKRAN and _au().aktif() != k:
            raise Dur(3, _("basılıyken aktif pencere değişti → {baslik}; bırakıldı").format(
                baslik=repr(_au().baslik(_au().aktif()))))
        if desen and not re.search(desen, _au().baslik(hedef), re.I):
            raise Dur(4, _("basılıyken başlık değişti; bırakıldı"))
        f = _au().fare()[:2]
        if f[0] is not None and f0[0] is not None and (abs(f[0] - f0[0]) > 2 or abs(f[1] - f0[1]) > 2):
            raise Dur(12, _("basılıyken kullanıcı fareyi oynattı (insan önceliği); bırakıldı"))
        if g.etk is not None and g.etk.insan(g.son_etk):  # basılı tutarken biz girdi üretmeyiz: her girdi insanın
            raise Dur(12, _("basılıyken kullanıcı klavye/fare kullandı (insan önceliği); bırakıldı"))
        koruma = getattr(g, "koruma_denetle", None)  # kde: kullanıcı film/oyun açtıysa ya da karar soruluyorsa bırak
        if koruma is not None:
            koruma(her_zaman=False)
        time.sleep(min(0.01, kalan))


def ekran_noktasi(k, x, y, geo=None):
    """Pencere noktası → (dotool mouseto kesirleri, ekran pikseli). Dışarıdaysa DUR."""
    X, Y, W, H = geo or _au().geometri(k)
    x, y = round(x), round(y)
    if not (0 <= x < W and 0 <= y < H):
        raise Dur(2, _("({x},{y}) pencerenin dışında ({genislik}x{yukseklik})").format(x=x, y=y, genislik=W, yukseklik=H))
    px, py = X + x, Y + y
    sx0, sy0, sx1, sy1 = _au().ekran_alani()
    if not (sx0 <= px < sx1 and sy0 <= py < sy1):
        raise Dur(2, _("ekran noktası ({x},{y}) görünür alanın dışında").format(x=px, y=py))
    return (px + 0.5 - sx0) / (sx1 - sx0), (py + 0.5 - sy0) / (sy1 - sy0), px, py


# tıklama değiştirici tuşları: dotool Linux adları (tek başına 'shift' dotool'da geçersiz: sol tuş adı kullanılır)
TIKLA_DEGISTIRICI = {"ctrl": "leftctrl", "control": "leftctrl", "shift": "leftshift", "alt": "leftalt",
                     "meta": "leftmeta", "super": "leftmeta", "win": "leftmeta"}
TIKLA_TUS = {"sol": "left", "sag": "right", "orta": "middle", "cift": "left", "uclu": "left"}
TIKLA_SAYI = {"cift": 2, "uclu": 3}  # tek `gonder` çağrısındaki click sayısı (bölünmez: atomik)


def mod_coz(mod):
    """Değiştirici tuşlar ('ctrl+shift' ya da ['ctrl', 'shift'] ya da boş) → dotool tuş adları (yinelenmeden,
    sırayla). Bilinmeyen ad Dur(1); hiçbir girdi gönderilmeden ÖNCE çağrılmalı."""
    if not mod:
        return []
    adlar = re.split(r"[+\s,]+", mod.strip()) if isinstance(mod, str) else list(mod)
    sonuc = []
    for ad in adlar:
        if not ad:
            continue
        t = TIKLA_DEGISTIRICI.get(str(ad).lower())
        if t is None:
            raise Dur(1, _("bilinmeyen değiştirici tuş: {tus} (ctrl, shift, alt, meta)").format(tus=repr(ad)))
        if t not in sonuc:
            sonuc.append(t)
    return sonuc


def ekran_pencere_ayni(w, px, py):
    """MASAÜSTÜ kipi (EKRAN): insan-doğrulama kapısının sınadığı pencere `w` HÂLÂ imlecin altında mı ve imleç hedef noktada
    (px, py) mı? Kapıdan sonra (ve her tık/basmadan önce) çağrılır: arada pencere değiştiyse (üstteki pencere kapandı/açıldı) ya da
    imleç oynadıysa Dur(3): hiçbir şey gönderilmez."""
    fx, fy, w2 = _au().fare()
    if (w2 or "") != (w or "") or (fx is not None and (abs(fx - px) > 2 or abs(fy - py) > 2)):
        raise Dur(3, _("imlecin altındaki pencere ya da imleç değişti (insan doğrulaması kapısı başka pencereyi sınadı); "
                       "tıklanmadı"))


def tikla_ic(g, k, desen, x, y, dugme="sol", geo=None, basili=0.0, tekrar=1, mod=()):
    """mod: mod_coz çıktısı (dotool tuş adları). Değiştirici: keydown → tıklama → keyup; bırakma HER durumda
    (hata, kesinti, DUR) `zorla` ile yapılır (basili_bekle/k_bas ile aynı güvence)."""
    if mod:
        guvenlik.seviye_denetle(k, "klavye")  # değiştirici tuş basılı tıklama klavye girdisidir: 'tikla' seviyesinde yok
    if dugme == "orta":  # kde: orta tık birincil seçimi yapıştırır → pano okuma onayının arka kapısı olmasın
        guvenlik.yapistirma_engel(k, getattr(g, "onayli", False), "secim")
    geo = geo or _au().geometri(k)
    fx, fy, px, py = ekran_noktasi(k, x, y, geo)
    _au().one_getir(k)
    if _au().geometri(k) != tuple(geo):
        raise Dur(8, _("pencere taşındı ya da boyutu değişti; tıklanmadı"))
    g.gonder(k, desen, f"mouseto {fx:.6f} {fy:.6f}")
    time.sleep(0.04)  # imleç üzerine gelme (hover) olayı işlensin
    w = None
    if k == EKRAN:  # masaüstü kipi: noktadaki pencere bir sistem istemiyse (polkit, KWallet…) önce insan onayı
        w = _au().fare()[2]
        insan_dogrulama_ekran(px, py, w, getattr(g, "ekran_metinler", ()))  # CAPTCHA: imlecin altındaki pencere + nokta
        ekran_pencere_ayni(w, px, py)  # kapıdan hemen sonra: sınanan pencere hâlâ imlecin altında (pencere değişimi → 3)
        if w and guvenlik.sistem_istemi_mi(w):
            guvenlik.sistem_istemi_engel(w, getattr(g, "onayli", False), _("tıklama"))
    imlec_alti_denetle(k, px, py)
    onay_hedefi_dogrula(g, k, x, y)
    g.son_fare = (px, py)
    if k != EKRAN:
        ucbirim.tampon_isle(_au(), k, kirli=True)  # uçbirimde tık imleci taşıyabilir: satır artık bilinmez
    tus = TIKLA_TUS[dugme]
    mod = list(mod or ())
    bastik = []
    try:
        for m in mod:
            bastik.append(m)  # keydown denemesinden ÖNCE kaydedilir: yarım kalsa bile bırakılır
            g.gonder(k, desen, f"keydown {m}")
        if mod:
            time.sleep(0.03)  # uygulama değiştiriciyi görsün
        if basili > 0:  # fare düğmesini BASILI tut (ör. oyunda kazma): ne olursa olsun bırak
            if k == EKRAN:
                ekran_pencere_ayni(w, px, py)
            g.gonder(k, desen, f"buttondown {tus}")
            try:
                basili_bekle(g, k, desen, basili, (px, py))
            finally:
                g.zorla(f"buttonup {tus}")
            print(_("basılı tutuldu ({dugme}, {sn} sn): pencere ({x},{y}) = ekran ({ex},{ey})").format(
                dugme=dugme, sn=basili, x=round(x), y=round(y), ex=px, ey=py))
            return
        for i in range(max(1, tekrar)):
            if i:
                time.sleep(0.06)
                imlec_alti_denetle(k, px, py)  # tekrarlar arasında da insan/pencere denetimi
            if k == EKRAN:  # masaüstü kipi: çift/üçlü tık TEK TEK gönderilir; her tıktan önce pencere + imleç yeniden denetlenir
                for _j in range(TIKLA_SAYI.get(dugme, 1)):  # (ilk tık üstteki pencereyi kapatırsa ikincisi alttakine inmesin)
                    ekran_pencere_ayni(w, px, py)
                    g.gonder(k, desen, f"click {tus}")
            else:
                g.gonder(k, desen, *([f"click {tus}"] * TIKLA_SAYI.get(dugme, 1)))
    finally:
        for m in reversed(bastik):
            g.zorla(f"keyup {m}")
    print(_("tıklandı ({dugme}{tekrar}): pencere ({x},{y}) = ekran ({ex},{ey})").format(
        dugme=dugme, tekrar=f" x{tekrar}" if tekrar > 1 else "", x=round(x), y=round(y), ex=px, ey=py))
    if mod:
        print(_("değiştirici tuşlar: {mod}").format(mod="+".join(mod)))


# dotool: wheel artı = yukarı, hwheel artı = sağ (test sayfasında scrollY ile ölçüldü)
KAYDIR_YON = {"asagi": ("wheel", -1), "yukari": ("wheel", 1), "sag": ("hwheel", 1), "sol": ("hwheel", -1)}


def kaydir_ic(g, k, desen, yon, adim, nokta=None):
    if k != EKRAN:
        guvenlik.sistem_istemi_engel(k, False, _("kaydırma"))
    X, Y, W, H = geo = _au().geometri(k)
    x, y = nokta or (W // 2, H // 2)
    fx, fy, px, py = ekran_noktasi(k, x, y, geo)
    _au().one_getir(k)
    eksen, isaret = KAYDIR_YON[yon]
    g.gonder(k, desen, f"mouseto {fx:.6f} {fy:.6f}")
    time.sleep(0.03)
    imlec_alti_denetle(k, px, py)
    g.son_fare = (px, py)
    g.gonder(k, desen, f"{eksen} {isaret * adim}")


def _yazi_hassas(g, k, onayli, metin, goruntu_al=True):
    """Yazının onay gerektiren yanları: (1) Enter/Tab/boşluklu yazı hassas sayfada onay ister (\\n = formu gönder;
    Tab + boşluk = odaktaki düğmeye bas); (2) hedef pencere bir UÇBİRİMse ve metin yıkıcı komut kalıbına uyuyorsa
    (rm -r, sudo, curl | sh…) onay ister — komut yazılmadan ÖNCE, Enter ayrı gönderilse bile. Yapıştırarak/parça
    parça yazan her yol bu işlevden geçmeli. goruntu_al=False: onay isteğine görüntü eklenmez
    (odak almayan erişilebilirlik yolu). → onay gerektiren bir durum vardı mı (onaylandı)."""
    goster = guvenlik._yazilacak(metin, g.gizli)
    sayfa = False
    if any(c.isspace() for c in metin):
        sayfa = hassas_sayfa_engel(k, onayli, _("yazı (Enter/Tab/boşluk içeriyor)"),
                                   ek=_("yazılacak: {metin}").format(metin=goster), goruntu_al=goruntu_al,
                                   metin=metin)  # goto: adres çubuğu çıkışı (guvenlik.sayfadan_cikis)
    komut = guvenlik.ucbirim_komut_engel(k, onayli, metin, g.gizli, goruntu_al=goruntu_al)
    return sayfa or komut


# ---------------------------------------------------------------- yapıştırarak yazma (Faz 9a)

YAPISTIR_ESIK = 200  # bundan uzun yazı panoya konup yapıştırılır (harf harf yazmak ~10 ms/harf)
YAPISTIR_BEKLE = 0.2  # yapıştır tuşundan sonra eski panoyu geri yüklemeden önce (hedef içeriği okusun); arka uç
#                       `pano_bekle` özniteliğiyle değiştirebilir
# Yapıştırma tuşu ctrl+shift+v olan uçbirimler: TEK liste guvenlik.UCBIRIM_SINIFLARI (yıkıcı komut onayıyla ortak).
ucbirim_mi = guvenlik.ucbirim_mi


def _pano_var():
    return type(_au()).pano_yaz is not ArkaUc.pano_yaz  # arka uç pano uyguluyor mu


def _yazilamayan_var(metin):
    yazilabilir_mi = _istege_bagli("yazilabilir_mi", lambda c: True)
    return any(c not in "\n\t" and not (" " <= c <= "~") and not yazilabilir_mi(c) for c in metin)


def yapistirarak_mi(metin):
    """Yazı panoya konup yapıştırılsın mı: arka uç panoyu destekliyor VE (klavye düzeninde olmayan karakter —
    emoji vb. — var ya da yazı YAPISTIR_ESIK'ten uzun) VE panoya konacak bir satır var."""
    return (_pano_var() and (len(metin) > YAPISTIR_ESIK or _yazilamayan_var(metin))
            and any(p for p in re.split(r"[\n\t]", metin)))


def _pano_kullanici_degistirdi(au, son_pano):
    """Geri yüklemeden hemen önce: pano artık bizim son yazdığımız metinden FARKLI mı (kullanıcı kopyaladı)? Hiçbir
    şey yazmadıysak ya da okuma başarısızsa False (eski pano geri yüklenir)."""
    if son_pano is None:
        return False
    try:
        simdiki = au.pano_oku()
    except Exception:  # noqa: BLE001 - okunamadı: bugünkü davranış (geri yükle)
        return False
    return simdiki != son_pano


def _yapistirarak_yaz(g, k, desen, metin, onayli):
    """Metni panoya koyup yapıştırır. \\n → Enter, \\t → Tab tuşu (harf harf yoldaki anlamıyla); aradaki parçalar
    yapıştırılır. Eski pano içeriği önceden alınır, SONRA (hata/kesinti dahil) geri yüklenir. Her gönderim `g.gonder`
    üzerinden (DUR, başlık/sınıf kilidi, ön plan koruması, insan önceliği) gider. → yapıldı mı (False: pano
    kullanılamadı, hiçbir şey gönderilmedi; çağıran harf harf yazmaya döner)."""
    au = _au()
    try:
        yedek = au.pano_yedekle()
    except Dur as e:
        if e.kod != 9:
            raise
        print(_("UYARI: pano kullanılamadı ({neden}); harf harf yazılıyor").format(neden=e.mesaj), file=sys.stderr)
        return False
    tus = "ctrl+shift+v" if ucbirim_mi(au.sinif(k)) else "ctrl+v"
    bekle = getattr(au, "pano_bekle", YAPISTIR_BEKLE)
    parcalar = re.split(r"(\n|\t)", metin)
    yazilan = 0
    adet = sum(1 for p in parcalar if p)
    son_pano = None  # panoya EN SON yazdığımız metin (geri yüklemeden önce hâlâ bu mu diye bakılır)
    g.izle(k, desen)
    try:
        for p in parcalar:
            if not p:
                continue
            denetle(k, desen)  # parça başında tam denetim (yasak pencere dahil); gönderimde yine denetlenir
            if yazi_onay_ister_mi(p):  # yazarken sayfa ödeme sayfasına geçtiyse: onay
                _yazi_hassas(g, k, onayli, metin)
            try:
                g.etk_denetle(_("yazma kesildi"))
            except Dur as e:
                raise Dur(e.kod, _("{mesaj} ({yazilan}/{toplam} karakter tamam)").format(
                    mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
            if g.kesildi:
                e = g.kesildi
                raise Dur(e.kod, _("{mesaj}; yazma kesildi ({yazilan}/{toplam} karakter tamam)").format(
                    mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
            try:
                if p in "\n\t":
                    if p == "\n":
                        _enter_oncesi(g, k, desen, onayli)
                    g.gonder(k, desen, "key enter" if p == "\n" else "key tab")
                else:
                    au.pano_yaz(p, hassas=True)  # pano yöneticisi (Klipper) geçmişine yazılmasın
                    son_pano = p
                    g.gonder(k, desen, f"key {tus}")
                    time.sleep(bekle)
            except Dur as e:
                if e.kod != 13:
                    raise
                raise Dur(e.kod, _("{mesaj} ({yazilan}/{toplam} karakter tamam)").format(
                    mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
            yazilan += len(p)
            gunluk(f"{g.etiket} | [{au.baslik(k)}] | " + ("yapistir ***" if g.gizli else
                   f"yapistir {p[:200]!r}" if p not in "\n\t" else ("key enter" if p == "\n" else "key tab")))
    finally:
        g.izle_bitir()
        try:
            if _pano_kullanici_degistirdi(au, son_pano):
                uyari = None  # kullanıcının yeni pano içeriği ezilmesin
                gunluk(f"{g.etiket} | pano geri yüklenmedi: pano bu arada kullanıcı tarafından değiştirildi")
            else:
                uyari = au.pano_geri_yukle(yedek)  # denetimsiz: DUR ya da kesintide de eski pano geri gelir
        except Exception as e:  # noqa: BLE001 - geri yükleme hatası asıl hatayı gizlemesin
            uyari = _("eski pano içeriği geri yüklenemedi: {hata}").format(hata=getattr(e, "mesaj", e))
        if g.gizli and son_pano is not None:  # gizli yazı panoda KALMASIN (eski pano geri yüklenemediyse: temizle)
            uyari = _gizli_pano_temizle(au, son_pano, uyari)
        if uyari:
            print(_("UYARI: {uyari}").format(uyari=uyari), file=sys.stderr)
    print(_("yazıldı: {karakter} karakter, {parca} parça (panodan yapıştırıldı)").format(karakter=len(metin), parca=adet))
    return True


def _gizli_pano_temizle(au, son_pano, uyari):
    """Gizli yapıştırmadan sonra pano hâlâ gizli parçayı tutuyorsa (eski pano çok büyük/geri yüklenemedi) panoyu
    denetimsiz temizler. → (güncellenmiş) uyarı."""
    try:
        kalan = au.pano_oku()
    except Exception:  # noqa: BLE001 - okunamadı: güvenli tarafta temizle
        kalan = son_pano
    if kalan != son_pano:
        return uyari
    try:
        au.pano_geri_yukle({"bos": True})  # denetimsiz temizleme (DUR/ön plan koruması bile olsa gizli yazı kalmasın)
    except Exception as e:  # noqa: BLE001
        return _("gizli yazı panoda kalmış olabilir: pano temizlenemedi ({hata})").format(hata=getattr(e, "mesaj", e))
    return (uyari + "; " if uyari else "") + _("gizli yazı panodan silindi (pano boş)")


def yaz_ic(g, k, desen, metin, onayli=False):
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")
    denetim_karakteri_denetle(metin)  # iki arka uç + yapıştırma yolu: hiçbir şey gönderilmeden
    guvenlik.seviye_denetle(k, "klavye")  # uygulama erişim seviyesi: onay diyaloğundan ÖNCE (boşuna sormasın)
    onay = False
    if yazi_onay_ister_mi(metin) and _yazi_hassas(g, k, onayli, metin):  # yazmadan ÖNCE (bir eylem = bir onay)
        onay = True
    # uçbirim ENTER KAPISI: yazının ilk satırı mevcut giriş satırına eklenip çalışacak (parça parça yazılmış komut)
    g._enter_satirlar = metin.split("\n")
    g._enter_onaylar = []
    for i, satir in enumerate(g._enter_satirlar[:-1]):  # bir Enter = bir onay; ilk satır mevcut satıra eklenir
        g._enter_onaylar.append(ucbirim.enter_kapisi(k, onayli, ek=satir, gizli=g.gizli, yalniz_ek=i > 0))
    g._enter_sira = 0
    if any(g._enter_onaylar):
        onay = True
    if onay:
        _onayli_etiket(g)
        _au().one_getir(k)  # onay diyaloğu odağı almış olabilir
    tamam = False
    try:
        if yapistirarak_mi(metin):
            if _yapistirarak_yaz(g, k, desen, metin, onayli):
                tamam = True
                return
            metin = yazima_hazirla(metin, gizli=g.gizli)  # pano yok: eski yol (yedekli karakterler değişir, yedeği yoksa DUR)
        _harf_harf_yaz(g, k, desen, metin, onayli)
        tamam = True
    finally:  # uçbirim tamponu: yarıda kesilen yazıda satırın içeriği bilinmez
        ucbirim.tampon_isle(_au(), k, yazi=metin if tamam else None, kirli=not tamam, onayli=onay and tamam)


def _enter_oncesi(g, k, desen, onayli):
    """Yazının içindeki bir Enter gönderilmeden HEMEN önce: önceden onaylanmadıysa pencere yeniden hesaplanır ve
    uçbirimse (bu arada gömülü uçbirim açılmış olabilir) şimdi onay sorulur. Onay diyaloğu odağı aldıysa gözcü
    yeniden kurulur."""
    i = getattr(g, "_enter_sira", 0)
    g._enter_sira = i + 1
    onaylar = getattr(g, "_enter_onaylar", [])
    if i < len(onaylar) and onaylar[i]:
        return
    satirlar = getattr(g, "_enter_satirlar", [""])
    if ucbirim.enter_kapisi(k, onayli, ek=satirlar[i] if i < len(satirlar) else "", gizli=g.gizli, yalniz_ek=i > 0):
        _onayli_etiket(g)
        g.izle_bitir()
        _au().one_getir(k)
        g.izle(k, desen)


def _harf_harf_yaz(g, k, desen, metin, onayli):
    g.gonder(k, desen, "typedelay 4", "typehold 6")
    # kelime + ardındaki boşluk birer parça; uzun kelimeler 6 harfte bölünür (sızıntı üst sınırı küçük kalsın)
    parcalar = []
    for p in re.findall(r"\n|\t|[^\n\t ]+[ ]*|[ ]+", metin):
        parcalar += [p] if p in "\n\t" else [p[i:i + 6] for i in range(0, len(p), 6)]
    yazilan = 0
    g.izle(k, desen)
    try:
        for p in parcalar:
            denetle(k, desen)  # kelime başında tam denetim (yasak pencere dahil); harf aralarını gözcü izler
            guvenlik.seviye_denetle(k, "klavye")
            if yazi_onay_ister_mi(p):  # yazarken sayfa ödeme sayfasına geçtiyse (ilk Enter formu gönderdi): onay
                _yazi_hassas(g, k, onayli, metin)
            try:  # kelime başında klavye/fare: kendi yazımızın dışında insan girdisi var mı
                g.etk_denetle(_("yazma kesildi"))
            except Dur as e:
                raise Dur(e.kod, _("{mesaj} ({yazilan}/{toplam} karakter tamam)").format(
                    mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
            for c in p:
                if g.kesildi:
                    e = g.kesildi
                    if g.gizli:  # gizli yazının harfleri iletiye/günlüğe taşınmaz: yalnız uzunluk
                        raise Dur(e.kod, _("{mesaj}; yazma kesildi ({yazilan}/{toplam} karakter tamam). Son 1-2 harf "
                                           "yeni yere gitmiş olabilir, oraya bak").format(
                            mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
                    raise Dur(e.kod, _("{mesaj}; yazma kesildi ({yazilan}/{toplam} karakter tamam). Son 1-2 harf "
                                       "({son}) yeni yere gitmiş olabilir, oraya bak").format(
                        mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin), son=repr(metin[max(0, yazilan - 2):yazilan])))
                if c == "\n":
                    _enter_oncesi(g, k, desen, onayli)
                try:
                    g.ham({"\n": "key enter", "\t": "key tab", " ": "key space"}.get(c, f"type {c}"))
                except Dur as e:
                    if e.kod != 13:
                        raise
                    raise Dur(e.kod, _("{mesaj} ({yazilan}/{toplam} karakter tamam)").format(
                        mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
                time.sleep(HARF_SN)  # dotool harfi yazsın (typehold 6 + typedelay 4 ms); kuyruk birikmesin
                yazilan += 1
            gunluk(f"{g.etiket} | [{_au().baslik(k)}] | " + ("type ***" if g.gizli else f"type {p!r}"))
    finally:
        g.izle_bitir()
    print(_("yazıldı: {karakter} karakter, {parca} parça").format(karakter=len(metin), parca=len(parcalar)))


def kaydirarak_ara(g, a, bolge, geo, ilk_im):
    """ARDIŞIK DÜZEN: kare i okunurken (arka planda) kaydırıp kare i+1 alınır; OCR ~1,1 sn ile
    kaydır+bekle+görüntü ~0,7 sn örtüşür. Hedef kare i'de bulunursa bir adım geri kaydırılır; aynı konuma
    dönüldüğü doğrulanınca kare i koordinatları kullanılır, doğrulanmazsa yeniden okunur.
    → (eşleşmeler, geo, adım sayısı)"""
    k, metin = a.kimlik, a.metin
    tik = max(3, round((bolge[3] if bolge else geo[3]) * 0.85 / 120))  # görünenin ~%85'i (örtüşme payı)

    # kaydırma noktası: bölge verildiyse ONUN ortası (yan menü gibi ayrı kayan alan), yoksa pencere ortası
    nokta = (bolge[0] + bolge[2] // 2, bolge[1] + bolge[3] // 2) if bolge else None

    hedef_px = (bolge[3] if bolge else geo[3]) * 0.85

    def kaydir_al(yon):
        """Kaydır, sonra görüntü DURANA dek bekle: Firefox'un yumuşak kaydırması sabit KAYDIR_BEKLE'den uzun
        sürebiliyor; animasyon ortasındaki kare 'sayfa sonu' ya da yanlış kayma sanılıyordu (gerçek ekran testi)."""
        kaydir_ic(g, k, a.baslik, yon, tik, nokta)
        time.sleep(KAYDIR_BEKLE)
        return pencere_goruntusu(k, bolge, kararli=True)

    onceki = ilk_im
    cur, geo, kok = kaydir_al("asagi")
    # Tekerlek adımı tarayıcıya göre değişir (Chromium ~120 px, Firefox çoğu zaman daha az): ilk adımın GERÇEK
    # kaymasını ölç, görünenin ~%85'ini kaydıracak adım sayısına uyarla (en çok 4 kat).
    d = kayma(onceki, cur)
    if d and 0 < d < hedef_px * 0.6:
        tik = min(tik * 4, max(tik, round(tik * hedef_px / d)))
    adim = 1
    while True:
        if ayni_konum(onceki, cur):
            print(_("# sayfa sonu ({adim}. kaydırmada görüntü değişmedi)").format(adim=adim))
            return [], geo, adim
        sonuc = {}

        def ocr_is(im=cur):
            try:
                ms_ = ara(satirla(oku(im)), metin)
                if not ms_:  # web düğmesi yazısı varsayılan okumada görünmeyebilir: düğme odaklı yedek okuma
                    ms_ = ara(satirla(oku(im, **YEDEK_OKUMALAR[1])), metin)
                if not ms_:  # ekran kartı sıcaksa (~0,2 sn; açık değilse beklenmez)
                    ms_ = ara(satirla(oku(im, motor="gpu")), metin)
                sonuc["ms"] = ms_
            except Exception as e:  # ana iş parçacığında yeniden fırlatılır
                sonuc["hata"] = e

        th = threading.Thread(target=ocr_is, daemon=True)
        th.start()
        nxt = None
        if adim < a.kaydirarak:
            nxt, geo2, kok2 = kaydir_al("asagi")  # OCR sürerken bir sonraki kare
        th.join()
        if "hata" in sonuc:
            raise sonuc["hata"]
        ms = [kok_ekle(m, kok) for m in sonuc["ms"]]
        if ms:
            if nxt is None:
                return ms, geo, adim
            # bir adım fazla kaydırıldı. 1) hedef sonraki karede hâlâ görünüyor mu? (sayfa sonunda kaydırma
            # kısa kalır: ör. 840 yerine 639 px) → kaymayı ölç, noktayı küçük okumayla DOĞRULA
            d = kayma(cur, nxt) if geo2 == geo else None
            if d is not None:
                ms2 = [x for m in ms for x in dogrula(nxt, kok2, metin, m["cx"], m["cy"] - d)]
                if ms2:
                    return ms2, geo2, adim
            # 2) görünmüyor: geri kaydır; aynı konuma dönüldüyse eski koordinatlar, değilse kaymayı ölçüp doğrula
            kaydir_ic(g, k, a.baslik, "yukari", tik, nokta)
            time.sleep(KAYDIR_BEKLE)
            geri, geo3, kok3 = pencere_goruntusu(k, bolge)
            if geo3 == geo and ayni_konum(cur, geri):
                return ms, geo, adim
            d = kayma(geri, cur) if geo3 == geo else None
            if d is not None:
                ms2 = [x for m in ms for x in dogrula(geri, kok3, metin, m["cx"], m["cy"] + d)]
                if ms2:
                    return ms2, geo3, adim
            ms2, geo3, *_x = bul_dongu(k, metin, bolge, 0)  # son çare: yeniden oku
            return ms2, geo3, adim
        if nxt is None:
            return [], geo, adim
        onceki, cur, geo, kok = cur, nxt, geo2, kok2
        adim += 1


# ---------------------------------------------------------------- komutlar

def _onayli_etiket(g):
    if not g.etiket.endswith(" --onayli"):
        g.etiket += " --onayli"


def sistem_istemi_onay(k, onayli, ne, goruntu_al=True):
    """Hedef (yazı/simge/renk/öge) ARANMADAN önce: pencere bir sistem yetki/parola/izin istemiyse insan onayı sorulur
    (koordinatlı tık, ref/text/element tıklaması ve erişilebilirlik eylemi AYNI: hepsi sorar; gözetimsiz kipte ret →
    10). Sorulmadan önce yasak, ajanın kendi istemcisi ve erişim seviyesi denetlenir (onay diyaloğu bunlardan sonra).
    Onay bu eylem boyunca o pencere için geçerlidir; sonraki denetle/hassas_nokta yeniden sormaz. → onaylandı mı."""
    if not k or k == EKRAN or not guvenlik.sistem_istemi_mi(k):
        return False
    yasak_denetle(k)
    guvenlik.kendi_istemci_denetle(k)
    guvenlik.seviye_denetle(k, "fare")
    return guvenlik.sistem_istemi_engel(k, onayli, ne, goruntu_al=goruntu_al)


def sistem_istemi_on(g, k, onayli, ne=None):
    """sistem_istemi_onay + girdi etiketine --onayli (fare yolları: metin/simge/renk/öge tıklaması)."""
    if sistem_istemi_onay(k, onayli, ne or _("tıklama")):
        _onayli_etiket(g)


def insan_dogrulama_nokta(k, x, y, metinler=()):
    """İnsan doğrulaması (CAPTCHA) kapısı, FARE: koordinat/metin/öge/simge/renk/web/sürükleme başlangıcı ve bitişi hep buradan
    geçer (CLI, MCP ve akış). Nokta sınama kutusundaysa Dur(18): hiçbir şey gönderilmez, çözülmez/atlatılmaz."""
    r = dogrulama_sinamasi.nokta_engeli(k, x, y, metinler)
    if r is not None:
        raise dogrulama_sinamasi.dur(r)


def insan_dogrulama_oge(k, oge):
    """İnsan doğrulaması kapısı, ÖGE: web ögesi bir sınama çerçevesinin (iframe) içindeyse (belge adresi reCAPTCHA/hCaptcha/
    Turnstile…) Dur(18); görünür olmasına, ögenin ref/erişilebilirlik eylemi ya da fare yoluyla hedeflenmesine bakılmaz."""
    r = dogrulama_sinamasi.oge_engeli(k, oge)
    if r is not None:
        raise dogrulama_sinamasi.dur(r)


def insan_dogrulama_ekran(px, py, pencere=None, metinler=()):
    """İnsan doğrulaması kapısı, FARE, MASAÜSTÜ kipi (EKRAN): imleç (px, py) ekran pikselinde duruyor (mouseto sonrası, tıklamadan
    ÖNCE); imlecin altındaki pencere çözülür ve kapı o pencere + pencereye göre nokta ile çağrılır. Dur(18)."""
    r = dogrulama_sinamasi.ekran_nokta_engeli(_au(), px, py, metinler, pencere)
    if r is not None:
        raise dogrulama_sinamasi.dur(r)


def insan_dogrulama_klavye(k, dizi=None):
    """İnsan doğrulaması (CAPTCHA) kapısı, KLAVYE: sayfanın tamamı sınamaysa ya da odak sınama kutusundaysa (onay kutusu,
    kaydırıcı, çerçeve içi, resimli güvenlik kodu alanı) Dur(18). Sınama durumu yoksa ek maliyet yok. dizi: gönderilecek
    tuş akorları / metin parçaları (sınama varken Tab'dan sonra başka girdi gelirse ret)."""
    r = dogrulama_sinamasi.klavye_engeli(k, dizi=dizi)
    if r is not None:
        raise dogrulama_sinamasi.dur(r)


def hassas_nokta(g, k, onayli, ne, x, y, yakin, ek_metinler=(), ek_basliklar=()):
    """Tıklanacak nokta ve oradaki yazı belli olduktan SONRA tek onay (bir eylem = bir onay): ödeme sayfası ve/veya
    hassas düğme. Onay isteği noktadaki yazıyı + hassas düğme metnini + çevresinin küçük görüntüsünü taşır.
    ek_basliklar: pencere başlığına ek denetlenen sayfa başlıkları (web belge başlığı)."""
    guvenlik.seviye_denetle(k, "fare")  # erişim seviyesi: onay diyaloğundan ÖNCE
    insan_dogrulama_nokta(k, x, y, [*ek_metinler, *yakin])  # CAPTCHA: tıklanan NOKTA sınama kutusundaysa 18 (çözülmez)
    if k == EKRAN:  # masaüstü kipi: pencere imleç konunca bilinir (tikla_ic / sürükleme insan_dogrulama_ekran çağırır)
        g.ekran_metinler = [*ek_metinler, *yakin]
    g.onayli = onayli
    if k != EKRAN and guvenlik.sistem_istemi_engel(k, onayli, ne):  # polkit/KWallet/parola sorucusu: onay
        _onayli_etiket(g)
    metinler = [*ek_metinler, *yakin]
    once = getattr(guvenlik._EYLEM, "onaylandi", False)
    panelden = not guvenlik.onayli_gecerli_kati(onayli)
    if hassas_sayfa_engel(k, onayli, ne, yakin=metinler, nokta=(x, y), ek_basliklar=ek_basliklar):  # True = hassas sayfa VE onaylandı
        _onayli_etiket(g)
        onayli = True
    if hassas_engel(onayli, *metinler, hedef=_au().baslik(k), k=k, nokta=(x, y)):
        _onayli_etiket(g)
    if panelden and not once and getattr(guvenlik._EYLEM, "onaylandi", False):
        # panelden onay verildi: tıklamadan hemen önce noktadaki yazı yeniden okunup onaylananla karşılaştırılır
        g.onay_hedefi = (round(x), round(y), [m for m in metinler if m])


ONAY_BENZERLIK = 0.85  # onay verilen hedefteki yazı ile tıklamadan hemen önceki yazının en düşük benzerliği


def ayni_hedef_mi(onaylanan, simdiki):
    """Onay anındaki yazılar ile şimdiki yazılar aynı hedefi mi gösteriyor (OCR gürültüsüne dayanıklı bulanık
    karşılaştırma)? Onay anında yazı yoksa şimdi de olmamalı."""
    import difflib
    from .ocr import katla
    a = [katla(t).strip() for t in onaylanan if t and t.strip()]
    b = [katla(t).strip() for t in simdiki if t and t.strip()]
    if not a:
        return not b
    if not b:
        return False
    return max(difflib.SequenceMatcher(None, x, y).ratio() for x in a for y in b) >= ONAY_BENZERLIK


def onay_hedefi_dogrula(g, k, x, y):
    """Hassas tık panelden onaylandıysa, tıklamadan HEMEN önce noktadaki yazı yeniden okunur; onaylanandan farklıysa
    (onay beklenirken sayfa/düğme değişti) tık yapılmaz → Dur 10."""
    h = getattr(g, "onay_hedefi", None)
    if not h or (h[0], h[1]) != (round(x), round(y)):
        return
    g.onay_hedefi = None
    simdi = nokta_metni(k, x, y)
    if not ayni_hedef_mi(h[2], simdi):
        raise Dur(10, _("onay verilen hedef değişti: noktadaki yazı artık {simdi} (onaylanan: {onaylanan}); "
                        "tıklanmadı").format(simdi=" | ".join(simdi) or _("(yok)"),
                                             onaylanan=" | ".join(h[2]) or _("(yok)")))


def k_tikla(a):
    x, y, geo = a.x, a.y, None
    if a.foto:
        try:
            with open(yollar.son_foto()) as fp:
                s = json.load(fp)
        except (OSError, ValueError):
            raise Dur(1, _("--foto: önce `ekran foto` alınmalı"))
        if s["kimlik"] != a.kimlik:
            raise Dur(1, _("--foto: son foto başka pencereye ait ({kimlik})").format(kimlik=s["kimlik"]))
        geo = tuple(s["geo"])
        if _au().geometri(a.kimlik) != geo:
            raise Dur(8, _("--foto: pencere fotoğraftan sonra taşındı/boyut değişti; yeniden foto al"))
        kx, ky = s.get("kenar", (0, 0))
        x, y = s["kok"][0] + (a.x - kx) / s["olcek"], s["kok"][1] + (a.y - ky) / s["olcek"]
    mod = mod_coz(getattr(a, "mod", None))
    g = girdi_al(f"tikla ({round(x)},{round(y)}) {a.dugme}")
    try:
        ekran_noktasi(a.kimlik, x, y, geo)  # dışarıdaysa OCR'a hiç girme
        yakin = nokta_metni(a.kimlik, x, y)  # dotool kurulurken: noktada ne yazıyor?
        if yakin:
            print(_("noktadaki yazı: {yazi}").format(yazi=" | ".join(yakin)))
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), x, y, yakin)
        tikla_ic(g, a.kimlik, a.baslik, x, y, a.dugme, geo, a.basili, a.tekrar, mod)
    finally:
        girdi_birak(g, a.kimlik)


TUS_TAKMA = {"return": "enter", "escape": "esc", "page_up": "pageup", "prior": "pageup", "page_down": "pagedown",
             "next": "pagedown", "del": "delete", "ins": "insert", "control": "ctrl", "meta": "super", "win": "super",
             "altgr": "altgr", "bksp": "backspace", "print": "sysrq"}


DEGISTIRICI = {"super", "altgr", "ctrl", "alt", "shift"}
# Ölçüm: `ekran tus K shift` → dotool "impossible key for layout: shift", hiçbir tuş basılmadı (araç 'tuş: shift'
# dedi). Tek başına kullanılan değiştirici gerçek (sol) tuşuna çevrilir.
TEK_DEGISTIRICI = {"shift": "leftshift", "ctrl": "leftctrl", "alt": "leftalt", "super": "leftmeta", "altgr": "rightalt"}


def tus_coz(kombinasyon, ayri_tuslar=False):
    """X/xdotool adlarını (Return, Escape, Page_Down…) dotool'un Linux adlarına çevirir; bilinmeyen tuşta DUR.
    '+' yalnız DEĞİŞTİRİCİ ile (ctrl+s). dotool 'w+d' gibi akoru 'unknown modifier' uyarısıyla YOK SAYIYORDU
    (araç 'basıldı' diyordu, hiçbir tuş basılmıyordu) → ayri_tuslar=True (bas): w+d = w ve d ayrı ayrı;
    aksi halde açık hata."""
    gecerli = _istege_bagli("gecerli_tuslar", lambda: None)()
    gecerli = None if gecerli is None else set(gecerli) | {"super", "altgr", "ctrl", "alt", "shift"}
    cikti = []
    for akor in kombinasyon.split():
        parcalar = []
        for t in akor.split("+"):
            if t.startswith("k:"):  # ham evdev tuş kodu: klavye tuşları < 0x100; 0x100+ BTN_* (fare düğmeleri) → tuş değil
                try:
                    kod = int(t[2:])
                except ValueError:
                    kod = -1
                if not 0 < kod < 0x100:
                    raise Dur(1, _("ham tuş kodu geçersiz: {tus} (klavye tuşları 1-255; 256 ve üstü fare düğmeleridir)").format(
                        tus=repr(t)))
                parcalar.append(t)
                continue
            if t.startswith("x:") or (len(t) == 1 and t.isupper()):
                parcalar.append(t)
                continue
            t2 = TUS_TAKMA.get(t.lower(), t.lower())
            if gecerli is not None and t2 not in gecerli:
                raise Dur(1, _("bilinmeyen tuş: {tus} (dotool --list-keys)").format(tus=repr(t)))
            parcalar.append(t2)
        if len(parcalar) > 1 and any(x.lower() not in DEGISTIRICI for x in parcalar[:-1]):
            if not ayri_tuslar:
                raise Dur(1, _("'{akor}' geçersiz: '+' yalnız ctrl/alt/shift/super/altgr ile kullanılır; aynı anda "
                               "basılı tutmak için: ekran bas <k> {akor} <sn>").format(akor=akor))
            cikti.extend(TEK_DEGISTIRICI.get(x, x) for x in parcalar)  # bas: w+d → w d (ikisi de basılı)
            continue
        if len(parcalar) == 1:  # TEK BAŞINA değiştirici: dotool 'shift'i yalnız akorda tanır, tek başına
            parcalar = [TEK_DEGISTIRICI.get(parcalar[0], parcalar[0])]  # 'impossible key' deyip HİÇ basmıyordu
        cikti.append("+".join(parcalar))
    return " ".join(cikti)


def _tus_onaylari(g, k, onayli, kombinasyon, birlikte=False):
    """tus/bas onayları (bir eylem = bir onay): sistem istemi, riskli tuş, yapıştırma (kde: kullanıcının panosu),
    ödeme sayfasında Enter/boşluk, uçbirimde satırı çalıştıran tuş (Enter kapısı)."""
    if guvenlik.sistem_istemi_engel(k, onayli, _("tuş")):
        _onayli_etiket(g)
    if guvenlik.riskli_tus_engel(k, onayli, kombinasyon, birlikte=birlikte):  # ctrl+alt+del, meta+l…
        _onayli_etiket(g)
    birlesik = "+".join(kombinasyon.split()) if birlikte else kombinasyon  # bas: tuşlar aynı anda basılı
    menu = ucbirim.menu_acik_mi(_au(), k)  # klavye menüsü az önce (3 sn) açıldıysa p/y yapıştırmadır
    if (guvenlik.yapistir_tusu_mu(birlesik, menu_acik=menu) or guvenlik.yapistir_tusu_mu(kombinasyon, menu_acik=menu)) \
            and guvenlik.yapistirma_engel(k, onayli):
        _onayli_etiket(g)
    yazi_n = guvenlik.yazi_tusu_sayisi(kombinasyon)  # parola alanı kapısı: tek karakterli tuşlar yazıdır (k_yaz ile tutarlı)
    if yazi_n and _parola_alani_mi(k):
        g.gizli = True  # parola tuşları günlüğe yazılmaz
        if guvenlik.parola_alani_engel(k, onayli, yazi_n, _("tuş")):  # hepsi: onay · kart: onaysız (k_yaz ile aynı kural)
            _onayli_etiket(g)
    if guvenlik.onay_kapsami() == "kart":  # tek tuşla kart numarası: rakam tuşları pencere başına tamponda birleştirilir
        tus_yazisi = guvenlik.tus_metni(kombinasyon)
        son4 = guvenlik.kart_tampon_denetle(k, tus_yazisi)
        if son4 or any(c.isdigit() for c in tus_yazisi):  # tampona rakam giren her tuş girdisi günlüğe gizli gider
            g.gizli = True
        if son4:
            guvenlik.kart_bilgisi_engel(k, onayli, "", False, _("tuş"), son4=son4)
    # Enter/boşluk ÇÖZÜLMÜŞ tuşa göre (x:Return, k:28, kpenter… dahil); onay öne getirmeden önce sorulur
    if onay_tusu_mu(kombinasyon) and hassas_sayfa_engel(
            k, onayli, _("Enter/boşluk"), ek=_("tuş: {kombinasyon}").format(kombinasyon=kombinasyon)):
        _onayli_etiket(g)
    onaylar = ucbirim.tus_dizisi_kapisi(k, onayli, birlesik)  # her Enter ayrı onay (uçbirimse)
    if onaylar:
        _onayli_etiket(g)
    return onaylar or []


def _tus_gonder(g, k, desen, kombinasyon, onayli, onaylar):
    """Tuş dizisini gönder. Enter içeriyorsa Enter'larda bölünür: her Enter'dan HEMEN önce pencere yeniden hesaplanır
    (dizinin ortasında da: F4 ile açılan gömülü uçbirimin kabuğu bu arada doğmuş olabilir) ve önceden onaylanmamış Enter
    uçbirime gidecekse şimdi onay sorulur."""
    akorlar = kombinasyon.split()
    if not any(guvenlik.enter_tusu_mu(a) for a in akorlar):
        g.gonder(k, desen, f"key {kombinasyon}")
        return
    bekleyen, sira = [], 0
    for akor in akorlar:
        if not guvenlik.enter_tusu_mu(akor):
            bekleyen.append(akor)
            continue
        if bekleyen:
            g.gonder(k, desen, "key " + " ".join(bekleyen))
            ucbirim.tus_sonrasi(_au(), k, " ".join(bekleyen))
            bekleyen = []
        if not (sira < len(onaylar) and onaylar[sira]) and ucbirim.enter_kapisi(k, onayli):
            _onayli_etiket(g)
            _au().one_getir(k)  # onay diyaloğu odağı almış olabilir
        sira += 1
        g.gonder(k, desen, f"key {akor}")
    if bekleyen:
        g.gonder(k, desen, "key " + " ".join(bekleyen))


def k_tus(a):
    kombinasyon = tus_coz(a.kombinasyon)
    if a.kimlik == EKRAN:  # masaüstü kipi: tuş o an etkin pencereye gider → ona kilitlen
        a.kimlik = _au().aktif()
        if not a.kimlik:
            raise Dur(3, _("etkin pencere belirlenemedi; tuş gönderilmedi"))
        yasak_denetle(a.kimlik)
    g = girdi_al(f"tus {kombinasyon}")
    try:
        guvenlik.seviye_denetle(a.kimlik, "klavye")  # erişim seviyesi: onay diyaloğundan ÖNCE
        insan_dogrulama_klavye(a.kimlik, kombinasyon.split())
        onaylar = _tus_onaylari(g, a.kimlik, getattr(a, "onayli", False), kombinasyon)
        _au().one_getir(a.kimlik)
        try:
            _tus_gonder(g, a.kimlik, a.baslik, kombinasyon, getattr(a, "onayli", False), onaylar)
        except Dur:
            ucbirim.tampon_isle(_au(), a.kimlik, kirli=True)
            raise
        finally:
            ucbirim.tus_sonrasi(_au(), a.kimlik, kombinasyon)  # uçbirim açma tuşu / klavye menüsü işareti
        ucbirim.tampon_isle(_au(), a.kimlik, tus=kombinasyon)
    finally:
        girdi_birak(g, a.kimlik)
    print(_("tuş: {kombinasyon}").format(kombinasyon=kombinasyon))


def _parola_alani_mi(k):
    """Pencerede odaklı öge AT-SPI'de parola alanı mı? (erişilebilirlik kapalıysa açılmaz: bilinmez → False)"""
    if k == EKRAN or not k:
        return False
    try:
        from .erisim import odakli_parola_mi
        return odakli_parola_mi(k)
    except Exception:  # noqa: BLE001
        return False


def _kart_alani_mi(k):
    """Pencerede odaklı öge bir kart bilgisi alanı mı (ad/etiket/autocomplete)? Yalnız onay kapsamı "kart"ta sorulur;
    erişilebilirlik kapalıysa açılmaz (bilinmez → False)."""
    if k == EKRAN or not k or guvenlik.onay_kapsami() != "kart":
        return False
    try:
        from .erisim import odakli_kart_mi
        return odakli_kart_mi(k)
    except Exception:  # noqa: BLE001
        return False


def k_yaz(a):
    ham = a.metin.replace("\r\n", "\n").replace("\r", "\n")
    denetim_karakteri_denetle(ham)
    # yapıştırılacak yazıda klavye düzeninde olmayan karakter (emoji…) sorun değil: yazima_hazirla yalnız harf harf yazılacaksa
    metin = ham if yapistirarak_mi(ham) else yazima_hazirla(ham, gizli=getattr(a, "gizli", False))
    if a.kimlik == EKRAN:  # masaüstü kipi: yazı o an etkin pencereye gider → ona kilitlen (değişirse durur)
        a.kimlik = _au().aktif()
        if not a.kimlik:
            raise Dur(3, _("etkin pencere belirlenemedi; yazı gönderilmedi"))
        yasak_denetle(a.kimlik)
    g = girdi_al(f"yaz {len(metin)} karakter", gizli=a.gizli)
    try:
        onayli = getattr(a, "onayli", False)
        insan_dogrulama_klavye(a.kimlik, dogrulama_sinamasi.metin_dizisi(metin))
        if guvenlik.sistem_istemi_engel(a.kimlik, onayli, _("yazı")):
            _onayli_etiket(g)
        if _parola_alani_mi(a.kimlik):  # odaklı öge parola alanı: metin kendiliğinden gizli + insan onayı
            g.gizli = True
            if guvenlik.parola_alani_engel(a.kimlik, onayli, len(metin), _("yazı")):
                _onayli_etiket(g)
                onayli = True
        if guvenlik.onay_kapsami() == "kart":  # kart bilgisi: hedef alan kart alanı ya da metinde Luhn'lu numara
            alan_kart = _kart_alani_mi(a.kimlik)  # tek sorgu (AT-SPI)
            son4 = guvenlik.kart_tampon_denetle(a.kimlik, metin)  # metin + aynı pencereye son 60 sn'de yazılan parçalar
            if alan_kart or son4 or guvenlik.kart_tampon_dolu(a.kimlik) or guvenlik.gizli_rakamli_mi(metin):
                g.gizli = True  # tam numara (ve henüz tamamlanmamış parçası) günlüğe/iletiye hiç yazılmaz
            if alan_kart or son4:
                guvenlik.kart_bilgisi_engel(a.kimlik, onayli, metin, alan_kart, _("yazı"), son4=son4)
        _au().one_getir(a.kimlik)
        yaz_ic(g, a.kimlik, a.baslik, metin, onayli)
    finally:
        girdi_birak(g, a.kimlik)


def k_kaydir(a):
    nokta = tuple(int(v) for v in a.nokta.split(",")) if a.nokta else None
    g = girdi_al(f"kaydir {a.yon} {a.adim}")
    try:
        kaydir_ic(g, a.kimlik, a.baslik, a.yon, a.adim, nokta)
    finally:
        girdi_birak(g, a.kimlik)
    print(_("kaydırıldı: {yon} {adim}").format(yon=a.yon, adim=a.adim))


def k_bas(a):
    """Tuş(lar)ı SÜRE boyunca basılı tut (oyunda yürüme: w, w+d). Basılıyken gözcü; ne olursa olsun bırakır."""
    kombinasyon = tus_coz(a.tuslar, ayri_tuslar=True)
    if a.kimlik == EKRAN:
        a.kimlik = _au().aktif()
        if not a.kimlik:
            raise Dur(3, _("etkin pencere belirlenemedi; tuş gönderilmedi"))
        yasak_denetle(a.kimlik)
    if not 0 < a.sure <= 30:
        raise Dur(1, _("süre 0-30 sn olmalı"))
    g = girdi_al(f"bas {kombinasyon} {a.sure} sn")
    try:
        guvenlik.seviye_denetle(a.kimlik, "klavye")
        insan_dogrulama_klavye(a.kimlik, sorted(kombinasyon.split(), key=lambda t: not dogrulama_sinamasi._tab_mu(t)))
        _tus_onaylari(g, a.kimlik, getattr(a, "onayli", False), kombinasyon, birlikte=True)
        ucbirim.tampon_isle(_au(), a.kimlik, kirli=True)  # basılı tuş tekrarlar: satırın içeriği bilinmez
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"keydown {kombinasyon}")
        ucbirim.tus_sonrasi(_au(), a.kimlik, kombinasyon)
        if g.etk is not None:  # ölçüm: basılı tuş ~0,57 sn sonra otomatik TEKRARLANIR ve bırakılana dek etkinlik
            g.etk.kendi_girdi(time.monotonic(), time.monotonic() + a.sure)  # kesintisizdir → tutuş süresi bizim girdimiz;
            g.son_etk = time.monotonic()  # bu sırada insanı fare gözcüsü yakalar (fare düğmesi tutuşunda tekrar yok)
        try:
            basili_bekle(g, a.kimlik, a.baslik, a.sure, g.son_fare if g is _paylasilan() else None)
        finally:
            g.zorla(f"keyup {kombinasyon}")
    finally:
        girdi_birak(g, a.kimlik)
    print(_("basılı tutuldu: {kombinasyon} {sn} sn").format(kombinasyon=kombinasyon, sn=a.sure))


def k_fare(a):
    """Fareyi noktaya götür, TIKLAMA (üzerine gelme: açıklama baloncuğu, menü vurgusu)."""
    g = girdi_al(f"fare ({round(a.x)},{round(a.y)})")
    try:
        if a.kimlik != EKRAN:
            guvenlik.sistem_istemi_engel(a.kimlik, False, _("fare hareketi"))
        geo = _au().geometri(a.kimlik)
        fx, fy, px, py = ekran_noktasi(a.kimlik, a.x, a.y, geo)
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"mouseto {fx:.6f} {fy:.6f}")
        time.sleep(0.04)
        imlec_alti_denetle(a.kimlik, px, py)
        g.son_fare = (px, py)
    finally:
        girdi_birak(g, a.kimlik)
    print(_("fare: pencere ({x},{y}) = ekran ({ex},{ey})").format(x=round(a.x), y=round(a.y), ex=px, ey=py))


def k_surukle(a):
    """x1,y1'de bas → sürede x2,y2'ye götür → bırak (konveyör çekme, seçim kutusu, eşya taşıma). BİTİŞ noktası da
    başlangıç gibi denetlenir: onaydan önce iki noktanın yazısı (hassas düğme/ödeme sayfası, sistem istemi, seviye),
    bırakmadan HEMEN önce imlecin altındaki pencere (yasak / ajanın kendi istemcisi / onaysız sistem istemi / başka
    uygulama → bırakılmaz: imleç başlangıca geri götürülüp bırakılır = sürükleme iptal). Ara hareketlerde gözcü
    (etkin pencere, başlık kilidi, DUR)."""
    tus = {"sol": "left", "sag": "right", "orta": "middle"}[a.dugme]
    g = girdi_al(f"surukle ({round(a.x1)},{round(a.y1)})→({round(a.x2)},{round(a.y2)}) {a.dugme}")
    try:
        geo = _au().geometri(a.kimlik)
        f1x, f1y, p1x, p1y = ekran_noktasi(a.kimlik, a.x1, a.y1, geo)
        f2x, f2y, p2x, p2y = ekran_noktasi(a.kimlik, a.x2, a.y2, geo)
        yakin1 = nokta_metni(a.kimlik, a.x1, a.y1)
        yakin2 = nokta_metni(a.kimlik, a.x2, a.y2) if a.kimlik != EKRAN else []
        # tek onay (bir eylem = bir onay): başlangıç ve BİTİŞ noktasının yazıları birlikte
        hassas_nokta(g, a.kimlik, a.onayli, _("sürükleme"), a.x1, a.y1, yakin1, ek_metinler=yakin2)
        insan_dogrulama_nokta(a.kimlik, a.x2, a.y2)  # bitiş noktası da sınama kutusunda olamaz
        g.onay_hedefi = None  # bitiş de onaylı metne dahil; tık doğrulaması yok (sürüklemede nokta iki tane)
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"mouseto {f1x:.6f} {f1y:.6f}")
        time.sleep(0.04)
        imlec_alti_denetle(a.kimlik, p1x, p1y)
        if a.kimlik == EKRAN:  # masaüstü kipi: başlangıç noktasındaki pencere (tarayıcıdaki sınama kutusu) basmadan ÖNCE
            w1 = _au().fare()[2]
            insan_dogrulama_ekran(p1x, p1y, w1, yakin1)
            ekran_pencere_ayni(w1, p1x, p1y)  # kapıdan sonra, buttondown'dan ÖNCE: pencere + imleç yeniden denetlenir
        g.gonder(a.kimlik, a.baslik, f"buttondown {tus}")
        birakildi = False
        try:
            if a.kimlik != EKRAN:  # gözcü: etkin pencere + başlık kilidi (fareyi biz oynatıyoruz: fare izlenmez)
                try:
                    g.izle(a.kimlik, a.baslik, fare_izle=False)
                except TypeError:
                    g.izle(a.kimlik, a.baslik)
            adim = max(5, int(a.sure / 0.02))
            for i in range(1, adim + 1):
                t = i / adim
                x, y = a.x1 + (a.x2 - a.x1) * t, a.y1 + (a.y2 - a.y1) * t
                fx, fy, *_x = ekran_noktasi(a.kimlik, x, y, geo)
                g.ham(f"mouseto {fx:.6f} {fy:.6f}")  # gözcü kesintisi (kesildi) burada Dur fırlatır
                time.sleep(a.sure / adim)
                if a.kimlik != EKRAN and _au().aktif() != a.kimlik:
                    raise Dur(3, _("sürüklerken aktif pencere değişti → {baslik}; bırakıldı").format(
                        baslik=repr(_au().baslik(_au().aktif()))))
            time.sleep(0.03)
            g.izle_bitir()
            if g.kesildi:
                raise g.kesildi
            f = _au().fare()[:2]
            if f[0] is not None and (abs(f[0] - p2x) > 3 or abs(f[1] - p2y) > 3):
                raise Dur(12, _("sürükleme sonunda imleç hedefte değil ({imlec} ≠ {hedef}): kullanıcı fareyi oynattı; "
                                "bırakıldı").format(imlec=f, hedef=(p2x, p2y)))
            # bırakmadan HEMEN önce: bitiş noktasının altındaki pencere (yasak / kendi istemci / sistem istemi / başka
            # uygulama) + DUR + seviye
            dur_denetle()
            imlec_alti_denetle(a.kimlik, p2x, p2y)
            if a.kimlik != EKRAN:
                hedef_pencere_denetle(a.kimlik)
            else:  # masaüstü kipi: bırakılacak noktadaki pencere sınama kutusuysa bırakılmaz (iptal yoluna düşer)
                insan_dogrulama_ekran(p2x, p2y)
            g.zorla(f"buttonup {tus}")
            birakildi = True
        finally:
            g.izle_bitir()
            if not birakildi:  # bitişte bırakılmaz: başlangıca geri götürüp bırak (sürükleme iptal)
                g.zorla(f"mouseto {f1x:.6f} {f1y:.6f}")
                time.sleep(0.02)
                g.zorla(f"buttonup {tus}")
        g.son_fare = (p2x, p2y)
        ucbirim.tampon_isle(_au(), a.kimlik, kirli=True)
    finally:
        girdi_birak(g, a.kimlik)
    print(_("sürüklendi ({dugme}): ({x1},{y1}) → ({x2},{y2}) {sn} sn").format(
        dugme=a.dugme, x1=round(a.x1), y1=round(a.y1), x2=round(a.x2), y2=round(a.y2), sn=a.sure))


def k_uyu(a):
    time.sleep(max(0.0, min(a.sn, 60.0)))
    print(_("beklendi: {sn} sn").format(sn=a.sn))


def k_dizi(a):
    """Adımları TEK süreçte, TEK dotool kurulumuyla çalıştır (oyunlar için hız). Her satır bir ekran komutu,
    kimliksiz: `bas w 1.2`, `tikla 640 360 sag --basili 2`, `uyu 0.3`, `metne-tikla "Kaydet"`. Her adımın
    tüm denetimleri ayrı yapılır; ilk DURDURULDU'da dizi durur (sonraki adımlar çalışmaz). -b/-s tüm adımlara."""
    kaynak = open(a.dosya).read() if a.dosya else sys.stdin.read()
    satirlar = [l.strip() for l in kaynak.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not satirlar:
        raise Dur(1, _("dizi boş"))
    t0 = time.monotonic()
    adimlari_calistir(a, satirlar)
    print(_("dizi tamam: {adim} adım, {sn} sn").format(adim=len(satirlar), sn=f"{time.monotonic() - t0:.2f}"))


YASAK_ADIMLAR = ("dizi", "kapat", "akis", "ac", "erisim")
_GIZLI_ADIM = re.compile(r"(?:^|\s)['\"]?--(?:gizli|secret)['\"]?(?=\s|$)")


def gizli_adim_mi(satir):
    """Dizi/akış adımı gizli (--secret / --gizli) mi? Satır ayrıştırılamasa da ham metinden bakılır."""
    return bool(_GIZLI_ADIM.search(satir or ""))


def adim_metni(satir):
    """Yazdırılacak/günlüğe yazılacak adım metni: gizli adımın yalnız komut adı ve uzunluğu görünür."""
    if not gizli_adim_mi(satir):
        return satir
    return f"{(satir.split() or ['?'])[0]} *** ({len(satir)}, --secret)"


def adimlari_calistir(a, satirlar, etiket="dizi", etk=None, onek=""):
    """Kimliksiz ekran komut satırlarını TEK dotool kurulumuyla sırayla çalıştır (dizi ve akis). Her adımın tüm
    denetimleri ayrı yapılır; adımlar arasında insan önceliği (fare + klavye); ilk DUR'da durur."""
    import shlex
    from .cli import ayristirici
    p = ayristirici(sessiz=True)
    pg = _DIZI.g = _au().girdi(etiket, etk=etk, denetle=denetle)
    try:
        for no, satir in enumerate(satirlar, 1):
            gosterim = adim_metni(satir)
            try:
                parca = akis_adimi(shlex.split(satir))  # İngilizce komut adı → Türkçe iç ad (sleep → uyu …)
                argv = parca if parca[0] == "uyu" else [parca[0], a.kimlik_ham] + parca[1:]
                b = p.parse_args(argv)
            except (SystemExit, ValueError, IndexError) as e:
                ek = f" ({e})" if isinstance(e, ValueError) and gosterim == satir else ""
                raise Dur(1, _("{etiket} {no}. satır hatalı: {satir}").format(etiket=etiket, no=no, satir=repr(gosterim)) + ek)
            if b.komut in YASAK_ADIMLAR:
                raise Dur(1, _("{etiket} içinde '{komut}' kullanılamaz").format(etiket=etiket, komut=b.komut))
            if getattr(b, "onayli", False) and not getattr(a, "onayli_izin", True):
                # MCP: akışın önceden onaylı adımları için kullanıcı onayı alınmadı (dosya sonradan değişmiş olabilir)
                raise Dur(10, _("{etiket} {no}. satır önceden onaylı (--onayli) ama kullanıcı onayı alınmadı: {satir}"
                                ).format(etiket=etiket, no=no, satir=repr(gosterim)))
            if hasattr(b, "kimlik"):
                b.kimlik = a.kimlik
            if getattr(b, "baslik", None) is None:
                b.baslik = a.baslik
            if no > 1 and pg.hazir:
                pg.insan_kontrol()
            if b.komut in GIRDI_KOMUTLARI:
                yasak_denetle(b.kimlik)
            print(f"{onek}[{no}/{len(satirlar)}] {gosterim}")
            b.f(b)
    finally:
        _DIZI.g = None
        pg.kapat()


def hedef_pencere_denetle_onayli(k, onayli, ne):
    """Girdi nesnesi kullanmayan pencere eylemleri (kapat, pencere yönetimi): yasak, ajanın kendi istemcisi (10),
    sistem istemine insan onayı (onaysız 10)."""
    yasak_denetle(k)
    guvenlik.kendi_istemci_denetle(k)
    guvenlik.sistem_istemi_engel(k, onayli, ne)


def k_kapat(a):
    """Pencereyi kapatır (pencere yöneticisi ile, alt+F4 gibi). Başlık kilidi ZORUNLU; yasak pencere kapanmaz.
    Neden: bazı tarayıcılarda son sekme ctrl+w ile kapanınca pencere başlangıç sayfası olarak açık kalıyor."""
    if a.kimlik == EKRAN:
        raise Dur(1, _("masaüstü kapatılamaz; pencere kimliği/adı ver"))
    if not a.baslik:
        raise Dur(1, _("kapat için -b <başlık deseni> zorunlu (yanlış pencere kapanmasın)"))
    dur_denetle()
    guvenlik.eylem_basladi()
    hedef_pencere_denetle_onayli(a.kimlik, getattr(a, "onayli", False), _("pencere kapatma"))
    guvenlik.seviye_denetle(a.kimlik, "klavye")  # pencereyi kapatmak fare/klavye ötesi bir eylem: 'tam' ister
    b = _au().baslik(a.kimlik)
    if not re.search(a.baslik, b, re.I):
        raise Dur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/); kapatılmadı").format(baslik=repr(b), desen=a.baslik))
    guvenlik.insan_onceligi(_("pencere kapatma"))  # kullanıcı klavye/fare kullanıyorsa bekle, sonra 12
    dur_denetle()
    hedef_pencere_denetle(a.kimlik)
    _au().kapat(a.kimlik)
    gunluk(f"kapat | [{b}] | windowclose")
    for _i in range(30):
        try:
            _au().geometri(a.kimlik)
        except Dur:
            print(_("kapatıldı: {baslik}").format(baslik=b))
            return
        time.sleep(0.1)
    raise Dur(8, _("pencere kapanmadı (kaydedilmemiş iş sorusu açık olabilir): {baslik}").format(baslik=b))


PENCERE_ISLEMLERI = ("tasi", "boyut", "kucult", "buyut", "geri")
_PENCERE_ISLEM_AD = {"tasi": N_("taşıma"), "boyut": N_("boyutlandırma"), "kucult": N_("küçültme"),
                     "buyut": N_("büyütme"), "geri": N_("geri yükleme")}


def _geo_bekle(k, tut, sure=1.0):
    """Pencere geometrisi tut(geo) sağlanana dek (en çok `sure` sn) bekle → son geometri. Pencere kapandıysa Dur 8."""
    bitis = time.monotonic() + sure
    while True:
        geo = _au().geometri(k)
        if tut(geo) or time.monotonic() >= bitis:
            return geo
        time.sleep(0.05)


def pencere_yonet(k, islem, x=None, y=None, g=None, h=None, desen=None):
    """Pencereyi taşı/boyutlandır/küçült/büyüt/geri yükle (CLI `pencere`, MCP manage_window). Denetimler (arka uçtan
    önce): DUR (13), yasak pencere (10), sınıf (-s) ve başlık (-b) kilidi (4), hedef konum/boyut ekran alanının dışına
    taşıyorsa 2. kde'de kullanıcı oyunda/film izliyorsa arka uç 15 verir. Günlüğe yazılır.
    → {"onceki": (x,y,g,y), "geometri": (x,y,g,y), "baslik": str, "uyari": str (boş = istenen oldu)}."""
    dur_denetle()
    if islem not in PENCERE_ISLEMLERI:
        raise Dur(1, _("bilinmeyen pencere işlemi: {islem}").format(islem=repr(islem)))
    if k == EKRAN:
        raise Dur(1, _("masaüstü kipi taşınamaz/boyutlandırılamaz; pencere kimliği/adı ver"))
    au = _au()
    guvenlik.eylem_basladi()
    hedef_pencere_denetle_onayli(k, False, _("pencere yönetimi"))
    guvenlik.sinif_denetle(k)
    guvenlik.seviye_denetle(k, "fare")  # pencereyi oynatmak girdi sayılır: 'goruntule' seviyesinde yok
    b = au.baslik(k)
    if desen and not re.search(desen, b, re.I):
        raise Dur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/); pencere işlemi yapılmadı").format(
            baslik=repr(b), desen=desen))
    onceki = tuple(au.geometri(k))
    gx, gy, gg, gh = onceki
    ex0, ey0, ex1, ey1 = au.ekran_alani()
    if islem == "tasi":
        if x is None or y is None:
            raise Dur(1, _("taşıma için x ve y gerekli"))
        hedef = (int(x), int(y), gg, gh)
    elif islem == "boyut":
        if g is None or h is None:
            raise Dur(1, _("boyutlandırma için genişlik ve yükseklik gerekli"))
        if int(g) < 1 or int(h) < 1:
            raise Dur(1, _("genişlik ve yükseklik en az 1 olmalı"))
        hedef = (gx, gy, int(g), int(h))
    else:
        hedef = None
    if hedef is not None and not (hedef[0] >= ex0 and hedef[1] >= ey0 and hedef[0] + hedef[2] <= ex1
                                  and hedef[1] + hedef[3] <= ey1):
        raise Dur(2, _("hedef pencere ekran alanının dışına taşıyor: konum {x},{y} boyut {g}x{h}; ekran alanı "
                       "{x0},{y0}..{x1},{y1}").format(x=hedef[0], y=hedef[1], g=hedef[2], h=hedef[3],
                                                      x0=ex0, y0=ey0, x1=ex1, y1=ey1))
    guvenlik.insan_onceligi(_("pencere işlemi"))  # kullanıcı klavye/fare kullanıyorsa bekle, sonra 12
    dur_denetle()
    guvenlik.hedef_pencere_denetle(k)  # onay beklenmiş olabilir: yeniden
    try:
        if islem == "tasi":
            au.tasi(k, hedef[0], hedef[1])
            geo = _geo_bekle(k, lambda c: abs(c[0] - hedef[0]) <= 1 and abs(c[1] - hedef[1]) <= 1)
        elif islem == "boyut":
            au.boyutlandir(k, hedef[2], hedef[3])
            geo = _geo_bekle(k, lambda c: abs(c[2] - hedef[2]) <= 1 and abs(c[3] - hedef[3]) <= 1)
        else:
            {"kucult": au.kucult, "buyut": au.buyut, "geri": au.geri_yukle}[islem](k)
            # küçültmede geometri değişmez; büyütme/geri yüklemede yeni geometri otursun
            geo = _geo_bekle(k, lambda c: islem == "kucult" or tuple(c) != onceki, 0.2 if islem == "kucult" else 0.6)
    finally:  # taşıma/boyut/büyütme sayfayı yeniden düzenler: sınama kutuları artık yerinde değil (kayıt kirlenir)
        dogrulama_sinamasi.girdi_oldu(k)
    geo = tuple(geo)
    uyari = ""
    if hedef is not None and any(abs(a_ - b_) > 1 for a_, b_ in zip(geo, hedef)):
        uyari = _("pencere yöneticisi istenenden farklı bir geometri verdi: istenen {istenen}, olan {olan}").format(
            istenen=hedef, olan=geo)
    degerler = " ".join(str(v) for v in (x, y, g, h) if v is not None)
    gunluk(f"pencere | [{b}] | {islem}{' ' + degerler if degerler else ''} | {onceki} → {geo}")
    return {"onceki": onceki, "geometri": geo, "baslik": b, "uyari": uyari}


def k_pencere(a):
    """Pencere yönetimi: `pencere <kimlik> tasi X Y | boyut G Y | kucult | buyut | geri`. Başlık kilidi isteğe bağlı
    (-b); yasak pencere ve DUR çekirdekte (pencere_yonet)."""
    d = list(a.deger or [])
    gerekli = {"tasi": 2, "boyut": 2}.get(a.islem, 0)
    if len(d) != gerekli:
        raise Dur(1, _("pencere {islem}: {gerekli} sayı gerekli (verilen {verilen})").format(
            islem=a.islem, gerekli=gerekli, verilen=len(d)))
    try:
        sayilar = [int(v) for v in d]
    except ValueError:
        raise Dur(1, _("pencere {islem}: değerler tam sayı (piksel) olmalı: {deger}").format(
            islem=a.islem, deger=" ".join(d))) from None
    x, y = (sayilar + [None, None])[:2] if a.islem == "tasi" else (None, None)
    g, h = (sayilar + [None, None])[:2] if a.islem == "boyut" else (None, None)
    r = pencere_yonet(a.kimlik, a.islem, x, y, g, h, a.baslik)
    gx, gy, gg, gh = r["geometri"]
    print(_("{islem} tamam: {baslik} | konum {x},{y} boyut {g}x{h}").format(
        islem=_(_PENCERE_ISLEM_AD[a.islem]), baslik=r["baslik"], x=gx, y=gy, g=gg, h=gh))
    if r["uyari"]:
        print(_("UYARI: {uyari}").format(uyari=r["uyari"]), file=sys.stderr)


def k_simgeye_tikla(a):
    mod = mod_coz(getattr(a, "mod", None))
    g = girdi_al(f"simgeye-tikla '{a.ad}' {a.dugme}")
    try:
        _au().one_getir(a.kimlik)
        sistem_istemi_on(g, a.kimlik, a.onayli)  # polkit/KWallet: aramadan önce onay (koordinatlı tık gibi)
        denetle(a.kimlik, a.baslik)
        kesin, yakin, geo = simge_bul_ic(a)
        if not kesin:
            ipucu = _("; en yakın aday benzerliği {benzerlik}").format(benzerlik=f"{yakin[0][0]:.3f}") if yakin else ""
            raise Dur(6, _("simge '{ad}' bulunamadı (eşik {esik}{ipucu})").format(ad=a.ad, esik=a.esik, ipucu=ipucu))
        bulunan = kesin
        if a.sira is None and (len(kesin) > 1 or yakin):
            for i, (sk, cx, cy) in enumerate(kesin, 1):
                print(f"  #{i} ({cx:.0f},{cy:.0f}) benzerlik {sk:.3f}")  # koordinat satırı: çevrilmez
            for sk, cx, cy in yakin:
                print(f"  ~ ({cx:.0f},{cy:.0f}) benzerlik {sk:.3f} (eşiğe yakın: karışabilir)")
            raise Dur(5, _("birden çok (ya da eşiğe yakın) eşleşme; --sira N ile seç ya da --bolge ile daralt"))
        sira = a.sira or 1
        if not 1 <= sira <= len(bulunan):
            raise Dur(1, _("--sira 1..{en_cok} olmalı").format(en_cok=len(bulunan)))
        sk, cx, cy = bulunan[sira - 1]
        # simgenin yanında "Satın al" vb. yazıyor mu; ödeme sayfasında her tıklama (tek onay, noktadaki yazıyla)
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), cx, cy, nokta_metni(a.kimlik, cx, cy))
        print(_("bulundu: simge '{ad}' ({x},{y}) benzerlik {benzerlik}").format(
            ad=a.ad, x=f"{cx:.0f}", y=f"{cy:.0f}", benzerlik=f"{sk:.3f}"))
        tikla_ic(g, a.kimlik, a.baslik, cx, cy, a.dugme, geo, mod=mod)
    finally:
        girdi_birak(g, a.kimlik)


def k_renge_tikla(a):
    """Bölgedeki en büyük (ya da --sira N.) renk alanının ortasına tıkla: yazısı okunamayan yeşil/kırmızı düğmeler."""
    mod = mod_coz(getattr(a, "mod", None))
    g = girdi_al(f"renge-tikla {a.renk} {a.dugme}")
    try:
        _au().one_getir(a.kimlik)
        sistem_istemi_on(g, a.kimlik, a.onayli)  # polkit/KWallet: aramadan önce onay (koordinatlı tık gibi)
        denetle(a.kimlik, a.baslik)
        im, geo, kok = pencere_goruntusu(a.kimlik, bolge_coz(a.bolge))
        alanlar = renk_alanlari(im, a.renk, a.en_az)
        if not alanlar:
            raise Dur(6, _("'{renk}' renkli alan yok (en az {en_az} piksel)").format(renk=a.renk, en_az=a.en_az))
        sira = a.sira or 1
        if sira > len(alanlar):
            raise Dur(1, _("--sira 1..{en_cok}").format(en_cok=len(alanlar)))
        alan, cx, cy, _kutu = alanlar[sira - 1]
        x, y = cx + kok[0], cy + kok[1]
        yakin = nokta_metni(a.kimlik, x, y)
        if yakin:
            print(_("noktadaki yazı: {yazi}").format(yazi=" | ".join(yakin)))
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), x, y, yakin)
        print(_("renk alanı: {renk} ({x},{y}) {alan} piksel").format(renk=a.renk, x=f"{x:.0f}", y=f"{y:.0f}", alan=alan))
        tikla_ic(g, a.kimlik, a.baslik, x, y, a.dugme, geo, mod=mod)
    finally:
        girdi_birak(g, a.kimlik)


def k_metne_tikla(a):
    mod = mod_coz(getattr(a, "mod", None))
    g = girdi_al(f"metne-tikla '{a.metin}' {a.dugme}")  # dotool kurulumu OCR ile aynı anda
    bolge = bolge_coz(a.bolge)
    try:
        _au().one_getir(a.kimlik)
        sistem_istemi_on(g, a.kimlik, a.onayli)  # polkit/KWallet: aramadan önce onay (koordinatlı tık gibi)
        denetle(a.kimlik, a.baslik)  # yanlış sekme / yasak pencerede boşuna okuma yapma
        ms, geo, kok, sure, ozet, im = bul_dongu(a.kimlik, a.metin, bolge, a.bekle, son_care=not a.kaydirarak)
        if not ms and a.kaydirarak:  # sayfayı aşağı kaydırarak ara (ardışık düzen)
            t0 = time.monotonic()
            ms, geo, adim = kaydirarak_ara(g, a, bolge, geo, im)
            sure += time.monotonic() - t0
            print(_("# {adim} kez kaydırıldı ({sn} sn)").format(adim=adim, sn=f"{sure:.1f}"))
        if not ms:
            raise Dur(6, _("'{metin}' bulunamadı ({sn} sn). İpucu: `ekran metin {kimlik}` ile satırlara bak").format(
                metin=a.metin, sn=f"{sure:.1f}", kimlik=a.kimlik))
        if a.sira is None and len(ms) > 1:
            print(_("# '{metin}' için {sayi} eşleşme:").format(metin=a.metin, sayi=len(ms)))
            yazdir_eslesme(ms)
            raise Dur(5, _("birden çok eşleşme; --sira N ile seç"))
        sira = a.sira or 1
        if not 1 <= sira <= len(ms):
            raise Dur(1, _("--sira 1..{en_cok} olmalı").format(en_cok=len(ms)))
        m = ms[sira - 1]
        dx, dy = (0, 0)
        if a.kay:
            dx, dy = (int(v) for v in a.kay.split(","))
        # tek onay, tıklanacak yazı belli olduktan SONRA: ödeme sayfası + hassas düğme (aranan metin, satırı ve
        # kaydırılmışsa o noktadaki yazı: orada başka bir düğme olabilir)
        yakin = nokta_metni(a.kimlik, m["cx"] + dx, m["cy"] + dy) if a.kay else []
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), m["cx"] + dx, m["cy"] + dy, yakin,
                     ek_metinler=[a.metin, m["satir"], *([] if a.kay else [m["t"]])])
        if a.kimlik == EKRAN:  # pencere kilidi yok: ekran bu arada değişmiş olabilir → taze görüntüde DOĞRULA
            im2, _geo2, kok2 = pencere_goruntusu(EKRAN, (round(m["cx"]) - 260, round(m["cy"]) - 40, 520, 80))
            if not dogrula(im2, kok2, a.metin, m["cx"], m["cy"]):
                raise Dur(6, _("'{metin}' artık ({x},{y}) noktasında değil (ekran değişti); tıklanmadı").format(
                    metin=a.metin, x=f"{m['cx']:.0f}", y=f"{m['cy']:.0f}"))
        benz = "" if m["skor"] == 1.0 else _(", benzerlik {benzerlik}").format(benzerlik=f"{m['skor']:.2f}")
        print(_("bulundu: '{metin}' ({x},{y}) güven {guven}{benzerlik}, {sn} sn").format(
            metin=m["t"], x=f"{m['cx']:.0f}", y=f"{m['cy']:.0f}", guven=f"{m['conf']:.0f}", benzerlik=benz,
            sn=f"{sure:.2f}"))
        tikla_ic(g, a.kimlik, a.baslik, m["cx"] + dx, m["cy"] + dy, a.dugme, geo, mod=mod)
    finally:
        girdi_birak(g, a.kimlik)
