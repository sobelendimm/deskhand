"""Akış: ekranı tanı → o ekranın adımları (durum makinesi). Dosya biçimi akis_oku()'da.
Komut: akis."""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import time

from . import yollar
from .arka_uc import sec
from .eylem import GIRDI_KOMUTLARI, adimlari_calistir
from .gorsel import bolge_coz, pencere_goruntusu
from .gunluk import gunluk
from .hata import Dur, dur_denetle
from .i18n import _
from .komutlar import AKIS_BASARI, AKIS_YONERGE, akis_adimi
from .ocr import ara, derin_oku, kaba, kok_ekle, norm, oku, satirla

AKIS_ALTINDA = (900, 260)  # --altinda: eşleşen başlığın altındaki şerit (genişlik, yükseklik)


def akis_oku(yol):
    """Akış dosyası (satır tabanlı, # yorum):
      sure 120 · tekrar 5 · bolge %18,18,82,85 (pencereye oransal x0,y0,x1,y1) ya da x,y,g,y (piksel)
      basari metin "Ana menü" · basari yok "Bağlanılıyor" (en az bir eylemden sonra) · basari komut "kabuk; 0=başarı"
      hata "Sürüm uyuşmuyor"            bu yazı görünürse DUR 11
      ekran "anahtar 1" | "anahtar 2"   bu yazılardan BİRİ ekrandaysa (bulanık) girintili adımları çalıştır:
          metne-tikla "Devam" · renge-tikla yesil --altinda[=YÜKSEKLİK] · tus ctrl+a · yaz "…" ·
          bekle [SN] · bitti (başarı) · dur "neden" (DUR 11)  — ve diğer kimliksiz ekran komutları
    Bloklar SIRAYLA denenir → özgül ekranı (diyalog) genel ekrandan (ana menü) ÖNCE yaz.
    İngilizce adlar da geçerli (içeride Türkçeye çevrilir): screen / timeout / repeat / region / success text|gone|
    command / error, adımlarda komutların İngilizce adları (click-text, wait, sleep …), done (bitti), stop (dur),
    --below (--altinda)."""
    import shlex
    ayar = {"sure": 120.0, "tekrar": 5, "bolge": None, "basari": [], "hata": []}
    ekranlar = []
    try:
        satirlar = open(yol).read().splitlines()
    except OSError as e:
        raise Dur(1, _("akış dosyası okunamadı: {hata}").format(hata=e))
    for no, ham in enumerate(satirlar, 1):
        s = ham.strip()
        if not s or s.startswith("#"):
            continue
        try:
            p = shlex.split(s, comments=True)
        except ValueError as e:
            raise Dur(1, f"{yol}:{no}: {e}")
        if not p:
            continue
        if ham[:1] in (" ", "\t"):
            if not ekranlar:
                raise Dur(1, _("{yol}:{no}: girintili adım bir 'ekran' bloğunun altında olmalı").format(yol=yol, no=no))
            p = akis_adimi(p)  # İngilizce komut/adım adı → Türkçe iç ad
            p = ["--altinda" + t[7:] if t.startswith("--below") and t[7:8] in ("", "=") else t for t in p]
            ekranlar[-1]["adimlar"].append(shlex.join(p))  # satır sonu yorumu atılmış, tırnaklar korunmuş
            continue
        p = [AKIS_YONERGE.get(p[0], p[0]), *p[1:]]
        if p[0] == "basari" and len(p) == 3:
            p[1] = AKIS_BASARI.get(p[1], p[1])
        if p[0] == "ekran":
            anahtarlar = [x for x in p[1:] if x != "|"]
            if not anahtarlar:
                raise Dur(1, _("{yol}:{no}: 'ekran' en az bir anahtar yazı ister").format(yol=yol, no=no))
            ekranlar.append({"anahtarlar": anahtarlar, "adimlar": [], "no": no, "ad": anahtarlar[0]})
        elif p[0] == "sure" and len(p) == 2:
            ayar["sure"] = float(p[1])
        elif p[0] == "tekrar" and len(p) == 2:
            ayar["tekrar"] = int(p[1])
        elif p[0] == "bolge" and len(p) == 2:
            ayar["bolge"] = p[1]
        elif p[0] == "basari" and len(p) == 3 and p[1] in ("metin", "yok", "komut"):
            ayar["basari"].append((p[1], p[2]))
        elif p[0] == "hata" and len(p) >= 2:
            ayar["hata"].append(p[-1])
        else:
            raise Dur(1, _("{yol}:{no}: anlaşılmadı: {satir}").format(yol=yol, no=no, satir=repr(s)))
    if not ekranlar and not ayar["basari"]:
        raise Dur(1, _("{yol}: hiç 'ekran' bloğu ya da 'basari' yok").format(yol=yol))
    return ayar, ekranlar


def onayli_adimlar(yol):
    """Akıştaki önceden onaylı (--onayli / --approved) adımlar. Alt dize değil, adım AYRIŞTIRILIR (kısaltmasız
    ayrıştırıcı: `--onay`, `--appr`, `--onay''li` gibi yazımlar da doğru sayılır/reddedilir). Ayrıştırılamayan adım
    çalışırken de reddedilir (1), sayılmaz. → adım satırları listesi."""
    import shlex
    from .cli import AyristirmaHatasi, ayristirici
    _ayar, ekranlar = akis_oku(yol)
    p = ayristirici(sessiz=True)
    sonuc = []
    for e in ekranlar:
        for x in e["adimlar"]:
            parca = akis_adimi(shlex.split(x))
            if not parca or parca[0] in ("bitti", "dur", "uyu"):
                continue
            parca = [t for t in parca if not re.fullmatch(r"--altinda(=\d+)?", t)]  # akışa özgü (çalışırken --bolge)
            try:
                b = p.parse_args([parca[0], "_", *parca[1:]])
            except (AyristirmaHatasi, SystemExit):
                continue
            if getattr(b, "onayli", False):
                sonuc.append(x)
    return sonuc


def akis_bolge(tanim, geo):
    if not tanim:
        return None
    if tanim.startswith("%"):
        v = [float(t) for t in tanim[1:].split(",")]
        if len(v) != 4:
            raise Dur(1, _("bolge %x0,y0,x1,y1 olmalı: {tanim}").format(tanim=repr(tanim)))
        W, H = geo[2], geo[3]
        return [round(W * v[0] / 100), round(H * v[1] / 100), round(W * (v[2] - v[0]) / 100), round(H * (v[3] - v[1]) / 100)]
    return bolge_coz(tanim)


def bulanik_icerir(metin_n, anahtar, esik=0.8):
    """Ekran metninde (norm + kaba uygulanmış) anahtar var mı: Türkçe harf/boşluk duyarsız, OCR farklarına karşı
    benzerlik ≥ esik (ör. 'kurulamadı' bir okumada 'kuruladı'). ≤4 harfli anahtarda yalnız tam eşleşme."""
    k = kaba(norm(anahtar))
    if not k:
        return False
    if k in metin_n:
        return True
    n = len(k)
    if n <= 4 or len(metin_n) < n - 2:
        return False
    sm = difflib.SequenceMatcher(None, "", k, autojunk=False)
    for i in range(0, max(1, len(metin_n) - n + 1)):
        sm.set_seq1(metin_n[i:i + n])
        if sm.real_quick_ratio() >= esik and sm.quick_ratio() >= esik and sm.ratio() >= esik:
            return True
    return False


def k_akis(a):
    """Ekran tanıma akışı: ekranı BİR KEZ oku → hangi ekran → o ekranın adımları; başarıya/zaman aşımına dek.
    Tekrar koruması (aynı ekran üst üste 'tekrar' kez işlendiyse DUR 7: korumasız bir akış başlığa 52 kez tıklamıştı),
    insan önceliği (kullanıcı bilgisayardaysa okumaz/öne getirmez, bekler), dürüst rapor (sonucu benim eylemim mi
    sağladı yoksa dış etki mi)."""
    yol = a.dosya
    if not os.path.exists(yol):
        yol = os.path.join(yollar.akis_dizin(), a.dosya if a.dosya.endswith(".akis") else a.dosya + ".akis")
    ayar, ekranlar = akis_oku(yol)
    sure = a.sure or ayar["sure"]
    k = a.kimlik
    etkinlik = getattr(sec(), "etkinlik", None)  # insan önceliği izleyicisi (arka uca özgü)
    etk = etkinlik() if etkinlik else None
    t0 = time.monotonic()
    adimlar, son_eylem, eylem_sayisi = [], None, 0
    ard_blok, ard_sayi = None, 0
    son_bakis = t0

    def bitti(neden):
        simdi = time.monotonic()
        if not eylem_sayisi:
            kim = _("hiç eylem gerekmedi")
        elif son_eylem and simdi - son_eylem < 30:
            kim = _("son eylemim '{adim}' ({sn} sn önce)").format(adim=adimlar[-1], sn=f"{simdi - son_eylem:.0f}")
        else:
            kim = _("BENİM EYLEMİM DIŞINDA (kullanıcı/dış etki)")
        print(_("akış tamam ({neden}); adımlar: {adimlar}; sonucu sağlayan: {kim} ({sn} sn)").format(
            neden=neden, adimlar=" → ".join(adimlar) or "-", kim=kim, sn=f"{simdi - t0:.1f}"))

    try:
        while time.monotonic() - t0 < sure:
            dur_denetle()
            if etk is not None and etk.insan(son_bakis):  # kullanıcı bilgisayarda: öne getirme/okuma yok
                print(_("bekleniyor: kullanıcı klavye/fare kullanıyor…"), file=sys.stderr)
                while time.monotonic() - t0 < sure and not etk.sessiz_mi(1.5):
                    time.sleep(0.1)
                if not etk.sessiz_mi(1.5):
                    raise Dur(12, _("akış süresince kullanıcı bilgisayarı kullandı (insan önceliği); durduruldu"))
            for tur, deger in ayar["basari"]:
                if tur == "komut" and subprocess.run(deger, shell=True, capture_output=True, timeout=30).returncode == 0:
                    return bitti(_("komut: {komut}").format(komut=deger))
            bolge = akis_bolge(ayar["bolge"], sec().geometri(k))
            im, geo, kok = pencere_goruntusu(k, bolge)
            son_bakis = time.monotonic()
            blok = None
            for derin in (False, True):  # önce tek okuma; hiçbir şey tanınmazsa renkli düğmeleri de gören derin okuma
                satirlar = derin_oku(im) if derin else satirla(oku(im))
                metin_n = kaba(norm(" ".join(s["t"] for s in satirlar)))
                for h in ayar["hata"]:
                    if bulanik_icerir(metin_n, h):
                        raise Dur(11, _("akış hata ekranı: '{hata}'; adımlar: {adimlar}").format(
                            hata=h, adimlar=" → ".join(adimlar) or "-"))
                for tur, deger in ayar["basari"]:
                    if tur == "metin" and bulanik_icerir(metin_n, deger):
                        return bitti(_("ekranda '{metin}'").format(metin=deger))
                    if tur == "yok" and eylem_sayisi and not derin and not bulanik_icerir(metin_n, deger):
                        satirlar_d = derin_oku(im)  # 'yok' kararını tek okumaya bırakma
                        if not bulanik_icerir(kaba(norm(" ".join(s["t"] for s in satirlar_d))), deger):
                            return bitti(_("'{metin}' artık yok").format(metin=deger))
                blok = next(((e, an) for e in ekranlar for an in e["anahtarlar"] if bulanik_icerir(metin_n, an)), None)
                if blok:
                    break
            if not blok:
                time.sleep(1.0)
                continue
            e, anahtar = blok
            yalniz_bekle = all(x.split()[0] in ("bekle", "uyu") for x in e["adimlar"])
            ard_sayi = ard_sayi + 1 if ard_blok is e else 1
            ard_blok = e
            if ard_sayi > ayar["tekrar"] and not yalniz_bekle:
                raise Dur(7, _("'{ekran}' ekranı üst üste {sayi} kez işlendi, ekran değişmedi; adımlar: {adimlar}").format(
                    ekran=e["ad"], sayi=ard_sayi - 1, adimlar=" → ".join(adimlar)))
            # adımları hazırla: --altinda → eşleşen anahtarın altındaki şerit; bekle [SN] → uyu
            m = next(iter(kok_ekle(x, kok) for x in ara(satirlar, anahtar)), None)
            hazir, son_mu, ozet = [], False, []
            for x in e["adimlar"]:
                p0 = x.split()[0]
                if p0 == "bitti":
                    son_mu = True
                    continue
                if p0 == "dur":
                    raise Dur(11, _("akış durdu ('{ekran}' ekranı): {neden}").format(ekran=e["ad"], neden=x[3:].strip()))
                if p0 == "bekle" and all(re.fullmatch(r"[\d.]+", t) for t in x.split()[1:]):
                    hazir.append(f"uyu {(x.split() + ['1'])[1]}")
                    continue
                am = re.search(r"--altinda(?:=(\d+))?", x)  # --below akis_oku'da --altinda'ya çevrildi
                if am:
                    yuk = int(am.group(1) or AKIS_ALTINDA[1])
                    if m:
                        bx = max(0, round(m["cx"]) - AKIS_ALTINDA[0] // 2)
                        x = x.replace(am.group(0), f"--bolge {bx},{round(m['y2']) + 4},{AKIS_ALTINDA[0]},{yuk}")
                    else:
                        x = x.replace(am.group(0), "")
                hazir.append(x)
            print(_("[ekran] '{anahtar}' → {sayi} adım").format(anahtar=anahtar, sayi=len(hazir))
                  + (_(" (başlık {x},{y})").format(x=f"{m['cx']:.0f}", y=f"{m['cy']:.0f}") if m else ""))
            gunluk(f"akis {os.path.basename(yol)} | ekran {e['ad']!r} | {' ; '.join(hazir) or '-'}")
            girdili = any(x.split()[0] in GIRDI_KOMUTLARI for x in hazir)
            try:
                if girdili:
                    adimlari_calistir(a, hazir, etiket=f"akis {e['ad']}", etk=etk, onek="  ")
                else:
                    for x in hazir:
                        if x.startswith("uyu "):
                            time.sleep(min(60.0, float(x.split()[1])))
                ozet.append(e["ad"])
            except Dur as d:
                if d.kod not in (5, 6, 7):  # güvenlik / insan / pencere durdurmaları akışı durdurur
                    raise
                ozet.append(f"{e['ad']}(DUR {d.kod})")
                print(_("  adım durdu ({kod}): {mesaj}").format(kod=d.kod, mesaj=d.mesaj.splitlines()[0]), file=sys.stderr)
            adimlar.extend(ozet)
            if girdili:
                son_eylem, eylem_sayisi = time.monotonic(), eylem_sayisi + 1
            if son_mu:
                return bitti(_("'{ekran}' ekranında 'bitti'").format(ekran=e["ad"]))
            son_bakis = time.monotonic()
            time.sleep(0.5)
        raise Dur(7, _("{sn} sn içinde bitmedi; adımlar: {adimlar}").format(
            sn=f"{sure:.0f}", adimlar=" → ".join(adimlar) or _("hiçbir ekran tanınmadı")))
    finally:
        if etk is not None:
            etk.kapat()

