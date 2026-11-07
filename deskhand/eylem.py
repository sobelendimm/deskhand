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
from .arka_uc import EKRAN, sec
from .gorsel import bolge_coz, pencere_goruntusu, renk_alanlari, simge_bul_ic
from .gunluk import gunluk
from . import guvenlik
from .guvenlik import (denetle, hassas_engel, hassas_sayfa_engel, imlec_alti_denetle, onay_tusu_mu, yasak_denetle,
                       yazi_onay_ister_mi)
from .hata import Dur, dur_denetle
from .i18n import _
from .insan import HARF_SN
from .komutlar import akis_adimi
from .ocr import KAYDIR_BEKLE, YEDEK_OKUMALAR, ara, ayni_konum, bul_dongu, dogrula, kayma, kok_ekle, nokta_metni, oku, satirla, \
    yazdir_eslesme

GIRDI_KOMUTLARI = {"tikla", "tus", "yaz", "kaydir", "metne-tikla", "kapat", "simgeye-tikla", "bas", "fare",
                   "surukle", "dizi", "renge-tikla", "akis", "ogeye-tikla"}
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


def yazima_hazirla(metin):
    """Yazmadan ÖNCE: klavye düzeninde olmayan karakteri yedeğiyle değiştir; yedeği yoksa hiç yazmadan DUR."""
    yazilabilir_mi = _istege_bagli("yazilabilir_mi", lambda c: True)
    klavye_duzeni = _istege_bagli("klavye_duzeni", lambda: ("tr", ""))
    sonuc, degisen = [], {}
    for c in metin:
        if c in "\n\t" or " " <= c <= "~" or yazilabilir_mi(c):
            sonuc.append(c)
            continue
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


def girdi_al(etiket="", gizli=False):
    """Girdi nesnesi: arka ucun girdisi, üst katmanın güvenlik denetimi (guvenlik.denetle) bağlı."""
    guvenlik.eylem_basladi()
    pg = _paylasilan()
    if pg is not None:
        pg.etiket, pg.gizli = f"dizi: {etiket}", gizli
        return pg
    return _au().girdi(etiket, gizli, denetle=denetle)


def girdi_birak(g):
    if g is not _paylasilan():
        g.kapat()


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


def tikla_ic(g, k, desen, x, y, dugme="sol", geo=None, basili=0.0, tekrar=1):
    geo = geo or _au().geometri(k)
    fx, fy, px, py = ekran_noktasi(k, x, y, geo)
    _au().one_getir(k)
    if _au().geometri(k) != tuple(geo):
        raise Dur(8, _("pencere taşındı ya da boyutu değişti; tıklanmadı"))
    g.gonder(k, desen, f"mouseto {fx:.6f} {fy:.6f}")
    time.sleep(0.04)  # imleç üzerine gelme (hover) olayı işlensin
    imlec_alti_denetle(k, px, py)
    g.son_fare = (px, py)
    tus = {"sol": "left", "sag": "right", "orta": "middle", "cift": "left"}[dugme]
    if basili > 0:  # fare düğmesini BASILI tut (ör. oyunda kazma): ne olursa olsun bırak
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
        g.gonder(k, desen, *([f"click {tus}"] * (2 if dugme == "cift" else 1)))
    print(_("tıklandı ({dugme}{tekrar}): pencere ({x},{y}) = ekran ({ex},{ey})").format(
        dugme=dugme, tekrar=f" x{tekrar}" if tekrar > 1 else "", x=round(x), y=round(y), ex=px, ey=py))


# dotool: wheel artı = yukarı, hwheel artı = sağ (test sayfasında scrollY ile ölçüldü)
KAYDIR_YON = {"asagi": ("wheel", -1), "yukari": ("wheel", 1), "sag": ("hwheel", 1), "sol": ("hwheel", -1)}


def kaydir_ic(g, k, desen, yon, adim, nokta=None):
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


def _yazi_hassas(g, k, onayli, metin):
    """Enter/Tab/boşluklu yazı hassas sayfada onay ister (\\n = formu gönder; Tab + boşluk = odaktaki düğmeye bas).
    → sayfa hassas ve onaylandı mı."""
    goster = f"***({len(metin)})" if g.gizli else repr(metin if len(metin) <= 120 else metin[:117] + "…")
    return hassas_sayfa_engel(k, onayli, _("yazı (Enter/Tab/boşluk içeriyor)"),
                              ek=_("yazılacak: {metin}").format(metin=goster))


def yaz_ic(g, k, desen, metin, onayli=False):
    metin = metin.replace("\r\n", "\n").replace("\r", "\n")
    if yazi_onay_ister_mi(metin) and _yazi_hassas(g, k, onayli, metin):  # yazmadan ÖNCE (bir eylem = bir onay)
        g.etiket += " --onayli"
        _au().one_getir(k)  # onay diyaloğu odağı almış olabilir
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
                    raise Dur(e.kod, _("{mesaj}; yazma kesildi ({yazilan}/{toplam} karakter tamam). Son 1-2 harf "
                                       "({son}) yeni yere gitmiş olabilir, oraya bak").format(
                        mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin), son=repr(metin[max(0, yazilan - 2):yazilan])))
                try:
                    g.ham({"\n": "key enter", "\t": "key tab", " ": "key space"}.get(c, f"type {c}"))
                except Dur as e:
                    if e.kod != 13:
                        raise
                    raise Dur(e.kod, _("{mesaj} ({yazilan}/{toplam} karakter tamam)").format(
                        mesaj=e.mesaj, yazilan=yazilan, toplam=len(metin)))
                time.sleep(HARF_SN)  # dotool harfi yazsın (typehold 6 + typedelay 4 ms); kuyruk birikmesin
                yazilan += 1
            gunluk(f"{g.etiket} | [{_au().baslik(k)}] | " + (f"type ***({len(p)})" if g.gizli else f"type {p!r}"))
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


def hassas_nokta(g, k, onayli, ne, x, y, yakin, ek_metinler=()):
    """Tıklanacak nokta ve oradaki yazı belli olduktan SONRA tek onay (bir eylem = bir onay): ödeme sayfası ve/veya
    hassas düğme. Onay isteği noktadaki yazıyı + hassas düğme metnini + çevresinin küçük görüntüsünü taşır."""
    metinler = [*ek_metinler, *yakin]
    if hassas_sayfa_engel(k, onayli, ne, yakin=metinler, nokta=(x, y)):  # True = hassas sayfa VE onaylandı
        _onayli_etiket(g)
        onayli = True
    if hassas_engel(onayli, *metinler, hedef=_au().baslik(k), k=k, nokta=(x, y)):
        _onayli_etiket(g)


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
    g = girdi_al(f"tikla ({round(x)},{round(y)}) {a.dugme}")
    try:
        ekran_noktasi(a.kimlik, x, y, geo)  # dışarıdaysa OCR'a hiç girme
        yakin = nokta_metni(a.kimlik, x, y)  # dotool kurulurken: noktada ne yazıyor?
        if yakin:
            print(_("noktadaki yazı: {yazi}").format(yazi=" | ".join(yakin)))
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), x, y, yakin)
        tikla_ic(g, a.kimlik, a.baslik, x, y, a.dugme, geo, a.basili, a.tekrar)
    finally:
        girdi_birak(g)


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
            if t.startswith(("x:", "k:")) or (len(t) == 1 and t.isupper()):
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


def k_tus(a):
    kombinasyon = tus_coz(a.kombinasyon)
    if a.kimlik == EKRAN:  # masaüstü kipi: tuş o an etkin pencereye gider → ona kilitlen
        a.kimlik = _au().aktif()
        if not a.kimlik:
            raise Dur(3, _("etkin pencere belirlenemedi; tuş gönderilmedi"))
        yasak_denetle(a.kimlik)
    g = girdi_al(f"tus {kombinasyon}")
    try:
        # Enter/boşluk ÇÖZÜLMÜŞ tuşa göre (x:Return, k:28, kpenter… dahil); onay öne getirmeden önce sorulur
        if onay_tusu_mu(kombinasyon) and hassas_sayfa_engel(
                a.kimlik, a.onayli, _("Enter/boşluk"), ek=_("tuş: {kombinasyon}").format(kombinasyon=kombinasyon)):
            g.etiket += " --onayli"
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"key {kombinasyon}")
    finally:
        girdi_birak(g)
    print(_("tuş: {kombinasyon}").format(kombinasyon=kombinasyon))


def k_yaz(a):
    metin = yazima_hazirla(a.metin)
    if a.kimlik == EKRAN:  # masaüstü kipi: yazı o an etkin pencereye gider → ona kilitlen (değişirse durur)
        a.kimlik = _au().aktif()
        if not a.kimlik:
            raise Dur(3, _("etkin pencere belirlenemedi; yazı gönderilmedi"))
        yasak_denetle(a.kimlik)
    g = girdi_al(f"yaz {len(metin)} karakter", gizli=a.gizli)
    try:
        _au().one_getir(a.kimlik)
        yaz_ic(g, a.kimlik, a.baslik, metin, getattr(a, "onayli", False))
    finally:
        girdi_birak(g)


def k_kaydir(a):
    nokta = tuple(int(v) for v in a.nokta.split(",")) if a.nokta else None
    g = girdi_al(f"kaydir {a.yon} {a.adim}")
    try:
        kaydir_ic(g, a.kimlik, a.baslik, a.yon, a.adim, nokta)
    finally:
        girdi_birak(g)
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
        if onay_tusu_mu(kombinasyon) and hassas_sayfa_engel(
                a.kimlik, a.onayli, _("Enter/boşluk"), ek=_("tuş: {kombinasyon}").format(kombinasyon=kombinasyon)):
            g.etiket += " --onayli"
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"keydown {kombinasyon}")
        if g.etk is not None:  # ölçüm: basılı tuş ~0,57 sn sonra otomatik TEKRARLANIR ve bırakılana dek etkinlik
            g.etk.kendi_girdi(time.monotonic(), time.monotonic() + a.sure)  # kesintisizdir → tutuş süresi bizim girdimiz;
            g.son_etk = time.monotonic()  # bu sırada insanı fare gözcüsü yakalar (fare düğmesi tutuşunda tekrar yok)
        try:
            basili_bekle(g, a.kimlik, a.baslik, a.sure, g.son_fare if g is _paylasilan() else None)
        finally:
            g.zorla(f"keyup {kombinasyon}")
    finally:
        girdi_birak(g)
    print(_("basılı tutuldu: {kombinasyon} {sn} sn").format(kombinasyon=kombinasyon, sn=a.sure))


def k_fare(a):
    """Fareyi noktaya götür, TIKLAMA (üzerine gelme: açıklama baloncuğu, menü vurgusu)."""
    g = girdi_al(f"fare ({round(a.x)},{round(a.y)})")
    try:
        geo = _au().geometri(a.kimlik)
        fx, fy, px, py = ekran_noktasi(a.kimlik, a.x, a.y, geo)
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"mouseto {fx:.6f} {fy:.6f}")
        time.sleep(0.04)
        imlec_alti_denetle(a.kimlik, px, py)
        g.son_fare = (px, py)
    finally:
        girdi_birak(g)
    print(_("fare: pencere ({x},{y}) = ekran ({ex},{ey})").format(x=round(a.x), y=round(a.y), ex=px, ey=py))


def k_surukle(a):
    """x1,y1'de bas → sürede x2,y2'ye götür → bırak (konveyör çekme, seçim kutusu, eşya taşıma)."""
    tus = {"sol": "left", "sag": "right", "orta": "middle"}[a.dugme]
    g = girdi_al(f"surukle ({round(a.x1)},{round(a.y1)})→({round(a.x2)},{round(a.y2)}) {a.dugme}")
    try:
        geo = _au().geometri(a.kimlik)
        f1x, f1y, p1x, p1y = ekran_noktasi(a.kimlik, a.x1, a.y1, geo)
        *_x, p2x, p2y = ekran_noktasi(a.kimlik, a.x2, a.y2, geo)
        hassas_nokta(g, a.kimlik, a.onayli, _("sürükleme"), a.x1, a.y1, nokta_metni(a.kimlik, a.x1, a.y1))
        _au().one_getir(a.kimlik)
        g.gonder(a.kimlik, a.baslik, f"mouseto {f1x:.6f} {f1y:.6f}")
        time.sleep(0.04)
        imlec_alti_denetle(a.kimlik, p1x, p1y)
        g.gonder(a.kimlik, a.baslik, f"buttondown {tus}")
        try:
            adim = max(5, int(a.sure / 0.02))
            for i in range(1, adim + 1):
                t = i / adim
                x, y = a.x1 + (a.x2 - a.x1) * t, a.y1 + (a.y2 - a.y1) * t
                fx, fy, *_x = ekran_noktasi(a.kimlik, x, y, geo)
                g.ham(f"mouseto {fx:.6f} {fy:.6f}")
                time.sleep(a.sure / adim)
                if a.kimlik != EKRAN and _au().aktif() != a.kimlik:
                    raise Dur(3, _("sürüklerken aktif pencere değişti → {baslik}; bırakıldı").format(
                        baslik=repr(_au().baslik(_au().aktif()))))
            time.sleep(0.03)
            f = _au().fare()[:2]
            if f[0] is not None and (abs(f[0] - p2x) > 3 or abs(f[1] - p2y) > 3):
                raise Dur(12, _("sürükleme sonunda imleç hedefte değil ({imlec} ≠ {hedef}): kullanıcı fareyi oynattı; "
                                "bırakıldı").format(imlec=f, hedef=(p2x, p2y)))
        finally:
            g.zorla(f"buttonup {tus}")
        g.son_fare = (p2x, p2y)
    finally:
        girdi_birak(g)
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


def adimlari_calistir(a, satirlar, etiket="dizi", etk=None, onek=""):
    """Kimliksiz ekran komut satırlarını TEK dotool kurulumuyla sırayla çalıştır (dizi ve akis). Her adımın tüm
    denetimleri ayrı yapılır; adımlar arasında insan önceliği (fare + klavye); ilk DUR'da durur."""
    import shlex
    from .cli import ayristirici
    p = ayristirici(sessiz=True)
    pg = _DIZI.g = _au().girdi(etiket, etk=etk, denetle=denetle)
    try:
        for no, satir in enumerate(satirlar, 1):
            parca = akis_adimi(shlex.split(satir))  # İngilizce komut adı → Türkçe iç ad (sleep → uyu …)
            argv = parca if parca[0] == "uyu" else [parca[0], a.kimlik_ham] + parca[1:]
            try:
                b = p.parse_args(argv)
            except (SystemExit, ValueError) as e:
                ek = f" ({e})" if isinstance(e, ValueError) else ""
                raise Dur(1, _("{etiket} {no}. satır hatalı: {satir}").format(etiket=etiket, no=no, satir=repr(satir)) + ek)
            if b.komut in YASAK_ADIMLAR:
                raise Dur(1, _("{etiket} içinde '{komut}' kullanılamaz").format(etiket=etiket, komut=b.komut))
            if getattr(b, "onayli", False) and not getattr(a, "onayli_izin", True):
                # MCP: akışın önceden onaylı adımları için kullanıcı onayı alınmadı (dosya sonradan değişmiş olabilir)
                raise Dur(10, _("{etiket} {no}. satır önceden onaylı (--onayli) ama kullanıcı onayı alınmadı: {satir}"
                                ).format(etiket=etiket, no=no, satir=repr(satir)))
            if hasattr(b, "kimlik"):
                b.kimlik = a.kimlik
            if getattr(b, "baslik", None) is None:
                b.baslik = a.baslik
            if no > 1 and pg.hazir:
                pg.insan_kontrol()
            if b.komut in GIRDI_KOMUTLARI:
                yasak_denetle(b.kimlik)
            print(f"{onek}[{no}/{len(satirlar)}] {satir}")
            b.f(b)
    finally:
        _DIZI.g = None
        pg.kapat()


def k_kapat(a):
    """Pencereyi kapatır (pencere yöneticisi ile, alt+F4 gibi). Başlık kilidi ZORUNLU; yasak pencere kapanmaz.
    Neden: bazı tarayıcılarda son sekme ctrl+w ile kapanınca pencere başlangıç sayfası olarak açık kalıyor."""
    if a.kimlik == EKRAN:
        raise Dur(1, _("masaüstü kapatılamaz; pencere kimliği/adı ver"))
    if not a.baslik:
        raise Dur(1, _("kapat için -b <başlık deseni> zorunlu (yanlış pencere kapanmasın)"))
    b = _au().baslik(a.kimlik)
    if not re.search(a.baslik, b, re.I):
        raise Dur(4, _("başlık uymadı: {baslik} (beklenen /{desen}/); kapatılmadı").format(baslik=repr(b), desen=a.baslik))
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


def k_simgeye_tikla(a):
    g = girdi_al(f"simgeye-tikla '{a.ad}' {a.dugme}")
    try:
        _au().one_getir(a.kimlik)
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
        tikla_ic(g, a.kimlik, a.baslik, cx, cy, a.dugme, geo)
    finally:
        girdi_birak(g)


def k_renge_tikla(a):
    """Bölgedeki en büyük (ya da --sira N.) renk alanının ortasına tıkla: yazısı okunamayan yeşil/kırmızı düğmeler."""
    g = girdi_al(f"renge-tikla {a.renk} {a.dugme}")
    try:
        _au().one_getir(a.kimlik)
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
        tikla_ic(g, a.kimlik, a.baslik, x, y, a.dugme, geo)
    finally:
        girdi_birak(g)


def k_metne_tikla(a):
    g = girdi_al(f"metne-tikla '{a.metin}' {a.dugme}")  # dotool kurulumu OCR ile aynı anda
    bolge = bolge_coz(a.bolge)
    try:
        _au().one_getir(a.kimlik)
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
        tikla_ic(g, a.kimlik, a.baslik, m["cx"] + dx, m["cy"] + dy, a.dugme, geo)
    finally:
        girdi_birak(g)
