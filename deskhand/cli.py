"""Komut satırı (argparse). Komut ve seçenek adları İngilizce, Türkçe adlar (ekran v3.2) takma ad olarak çalışır
(komutlar.py); içeride komut adı ve seçenek dest'leri Türkçedir. Çıktı biçimi ve çıkış kodları ekran v3.2 ile aynı.
Yardım metni yardim_metni()'nde (paragraf paragraf çevrilir); `deskhand help` tamamını, argümansız çağrı komut
listesini verir."""
from __future__ import annotations

import argparse
import re
import os
import sys

from . import __version__, api, desen, guvenlik, hata, yollar
from .akis import k_akis
from .arka_uc import ARKA_ONEK, EKRAN, hedef_ad, sec
from .doktor import k_doktor
from .dosya_sec import k_dosya_sec
from .erisim import k_agac, k_erisim, k_ogeye_tikla, k_ogeye_yaz
from .eylem import (GIRDI_KOMUTLARI, KAYDIR_YON, OKUMA_KOMUTLARI, k_bas, k_dizi, k_fare, k_kapat, k_kaydir,
                    k_metne_tikla, k_pencere, k_renge_tikla, k_simgeye_tikla, k_surukle, k_tikla, k_tus, k_uyu,
                    k_yaz)
from .gezin import k_git
from .gorsel import k_foto, k_renk_bul, k_simge_bul, k_simge_kaydet
from .gunluk import gunluk, temizle
from .guvenlik import yasak_denetle
from .hata import SANAL_KAPALI, Dur, dur_denetle, dur_dosyasi
from .i18n import N_, _, h_
from .komutlar import DUGME, ERISIM, PENCERE, RENK, SECENEKLER, TR_EN, YON, cevirici, ic_ad, secimler, takma_adlar
from .mesgul import k_karar, k_mesgul
from .ocr import k_bekle, k_metin
from .web import k_web
from .uygulama import k_ac

# Yardım metni: her paragraf (komut listesinde her komut) ayrı bir msgid → çeviri kısa parçalarla yapılır.
# Komut adları İngilizcedir, Türkçe ad parantezde; ikisi de çalışır (komutlar.py).
YARDIM_GIRIS = N_("Deskhand {surum}: yapay zekâ ajanları için güvenli masaüstü kontrolü (KDE Plasma Wayland) — senin ekranında\n"
                  "ya da görünmez ikinci bir masaüstünde. kdotool pencere bulur, dotool fare/klavye sürer, spectacle görüntü\n"
                  "alır, tesseract (tur+eng) metin okur (OCR). 'ekran' komutu eski adıdır, aynı şekilde çalışır.")
YARDIM_GUVENLIK = (
    N_("GÜVENLİK: her girdi (tıklama/tuş/yazı/kaydırma) hedef pencere öne gelip AKTİF olduğu doğrulanınca\n"
       "gönderilir. -b DESEN verilirse pencere BAŞLIĞI da (tarayıcıda sekme) her girdiden HEMEN önce\n"
       "denetlenir. Yazılar kelime kelime gönderilir, her parçadan önce yeniden denetlenir."),
    N_("Yasak pencerelere (~/.config/deskhand/yasak-pencereler.txt; varsayılan boş) hiç girdi gitmez. Ödeme/yetki/hesap\n"
       "silme düğmelerine (Satın al, Öde, Authorize, İzin ver…) --approved olmadan tıklanmaz: --approved YALNIZ\n"
       "kullanıcı o adımı açıkça onayladıysa verilir. Her girdi ~/.local/state/deskhand/ günlüğüne yazılır."),
    N_("İNSAN ÖNCELİĞİ: kullanıcı fareyi YA DA klavyeyi kullanıyorsa (Wayland boşta bildirimi, yetkisiz) girdi\n"
       "gönderilmez: 1,5 sn sessizlik beklenir (en çok 8 sn), olmazsa 12. Basılı tutarken insan girdisi → hemen bırakır."),
    N_("ONAY İSTEYEN RİSKLİ EYLEMLER (yasak değil, insan onayı; --approved ya da panelden): oturumu/ekranı sonlandıran\n"
       "tuşlar (ctrl+alt+delete/backspace/F1-F12, meta+l, alt+sysrq+…) ve uçbirime yıkıcı komut yazma (rm -r, sudo,\n"
       "curl | sh, mkfs, dd of=/dev/…, git push --force…). ~/.config/deskhand/uygulama-seviyeleri.txt (varsayılan: yok)\n"
       "uygulama başına 'DESEN = goruntule | tikla | tam' ile girdiyi sınırlar (goruntule: girdi yok; tikla: klavye yok)."),
    N_("DUR ANAHTARI: 'ekran stop' sonrası hiçbir deskhand süreci girdi göndermez (13), basılı tuşlar bırakılır; "
       "yalnız kullanıcı kaldırır (Deskhand paneli ya da DUR kısayolu)."),
)
YARDIM_KOMUT_BASI = (
    N_("Komutlar (koordinatlar pencereye göre, piksel; <kimlik> yerine tek pencereye uyan ad da verilebilir;\n"
       "<kimlik> = \"ekran\" (masaüstü kipi): tüm ekran — panel, masaüstü, menüler, başlatıcı; okuma odağı çalmaz,\n"
       "klavye o an etkin pencereye gider ve ona kilitlenir, fare imlecin altındaki pencereyi denetler).\n"
       "Parantezdeki Türkçe komut adları ve Türkçe seçenekler (--baslik, --bolge, --sure …) de çalışır:"),
)
YARDIM_KOMUTLAR = (
    N_("  ekran windows (bul) [desen]             kimlik | başlık | x y genişlik yükseklik (desensiz: tüm pencereler)"),
    N_("  ekran screenshot (foto) [kimlik] [png] [--out DOSYA] [--region x,y,g,y] [--width N] [--grid [ADIM]]\n"
       "                                          kimliksiz: --background ise tüm görünmez masaüstü, değilse etkin pencere;\n"
       "                                          --width N: küçültülmüş görüntü (yapay zekâ bağlamı için)"),
    N_("  ekran click (tikla) <kimlik> <x> <y> [right|double|triple|middle] [--mod ctrl+shift] [--shot] [--approved]"),
    N_("  ekran key (tus) <kimlik> <kombinasyon> [--approved]   ör. ctrl+s, Return, alt+F4"),
    N_("  ekran type (yaz) <kimlik> <metin> [--secret]   \\n → Return, \\t → Tab, \\\\ → \\; --secret günlüğe metni yazmaz;\n"
       "                                          '-' ile başlayan metin: ekran type <kimlik> -- \"-5 derece\""),
    N_("  ekran scroll (kaydir) <kimlik> [down|up|left|right] [ADIM] [--point x,y]   (ADIM varsayılan 3; nokta:\n"
       "                                          scroll <kimlik> X Y [yön] [ADIM] ya da --at x,y)"),
    N_("  ekran read (metin) <kimlik> [desen] [--region ..] [--precise] [--all] [--deep]   yazılar + koordinatlar"),
    N_("  ekran click-text (metne-tikla) <kimlik> <metin> [right|double] [--nth N] [--wait SN] [--offset dx,dy]\n"
       "                    [--region ..] [--scroll-search [N]] [--approved]"),
    N_("  ekran wait (bekle) <kimlik> <metin> [--timeout SN] [--gone] [--region ..]"),
    N_("  ekran -b DESEN close (kapat) <kimlik>   pencereyi kapatır (başlık kilidi zorunlu)"),
    N_("  ekran window (pencere) <kimlik> move (tasi) X Y | resize (boyut) G Y | minimize (kucult) | maximize (buyut) |\n"
       "                                          restore (geri)   pencereyi taşı/boyutlandır/küçült/büyüt/geri yükle\n"
       "                                          (ekran pikseli; ekran dışına taşarsa 2)"),
    N_("  ekran hold (bas) <kimlik> <tuş[+tuş]> <SN>   tuşu basılı tut (oyunda yürüme); kesintide hemen bırakır"),
    N_("  ekran clipboard (pano) read|write [metin] [--approved]   pano: metni oku (ön planda onay ister) / yaz\n"
       "                                          (stdin'den de yazılır); yazma geçmişe düşmez, DUR ve oyun/film korumalıdır"),
    N_("  ekran click ... --hold SN | --repeat N   fare düğmesini basılı tut (kazma) / N kez tıkla"),
    N_("  ekran drag (surukle) <kimlik> x1 y1 x2 y2 [left|right] [--duration 0.4]   sürükle-bırak"),
    N_("  ekran move (fare) <kimlik> x y          tıklamadan gezdir (açıklama baloncuğu)"),
    N_("  ekran batch (dizi) <kimlik> [--file F] <<EOF   adımlar tek süreçte (tek dotool kurulumu, oyunlar için hız)"),
    N_("  ekran sleep (uyu) SN                    (dizi içinde) bekle"),
    N_("  ekran find-color (renk-bul) <kimlik> green|red|blue|R,G,B [--region]   renkli alanlar (yazısı okunmayan "
       "düğmeler)"),
    N_("  ekran click-color (renge-tikla) <kimlik> <renk> [--region] [--nth N]   en büyük renk alanının ortasına tıkla"),
    N_("  ekran save-icon (simge-kaydet) <kimlik> <ad> --region x,y,g,y   yazısız simgeyi kaydet "
       "(~/.local/share/deskhand/simgeler)"),
    N_("  ekran find-icon (simge-bul) <kimlik> <ad> [--threshold 0.9] [--region ..]"),
    N_("  ekran click-icon (simgeye-tikla) <kimlik> <ad> [right|double] [--nth N] [--threshold 0.9] [--region ..]\n"
       "                    [--approved]"),
    N_("  ekran goto (git) <kimlik> <http(s)-adres> [--approved]   tarayıcı penceresinde adres çubuğuyla adrese git\n"
       "                                          (ctrl+l → adres → Return; tüm girdi denetimleri aynen; yalnız http/https)"),
    N_("  ekran choose-file (dosya-sec) <diyalog-kimliği> <TAM-YOL>   dosya seçicide dosyayı seç: konum girdisi odakta\n"
       "                                          mı, yazılan yol geri okunur, eşleşmezse Enter'a basılmaz; diyalog kapanır"),
    N_("  ekran open (ac) <uygulama [http(s)-adres] | --command \"KOMUT\"> [--url ADRES] [-b DESEN] [-s SINIF] [--timeout 30]\n"
       "                                          başlat → YENİ penceresini bekle → kimlik | başlık | sınıf "
       "(yasak: başlatılmaz).\n"
       "                                          --background: görünmez masaüstü kapalıysa kendiliğinden başlar"),
    N_("  ekran flow (akis) <kimlik> <dosya|ad> [--timeout SN]   ekran tanıma akışı "
       "(~/.local/share/deskhand/akislar/AD.akis):\n"
       "                                          ekranı oku → hangi ekran → o ekranın adımları; başarıya dek, "
       "tekrar korumalı"),
    N_("  ekran a11y (erisim) [on|off|status]     erişilebilirlik ağacını aç/kapat (Qt/GTK düğmeleri ad + konumla)"),
    N_("  ekran tree (agac) <kimlik> [desen] [--role R] [--all]   penceredeki ögeler: (merkez x,y) rol: ad"),
    N_("  ekran web <kimlik> [sorgu] [--role R] [--all] [--page N]   tarayıcı penceresindeki web sayfasının ögeleri\n"
       "                                          (tarayıcının erişilebilirlik ağacından, OCR'sız): #no (merkez x,y) rol: ad [durum];\n"
       "                                          sayfa 60 öge, --all: görünmeyenler dahil hepsi; click-element bunları tıklar"),
    N_("  ekran click-element (ogeye-tikla) <kimlik> <ad> [right|double] [--role R] [--nth N] [--approved]\n"
       "                    [--action [EYLEM]]    ADIYLA tıkla (OCR'sız; tarayıcıda web sayfası ögeleri dahil); --action: fare/odak\n"
       "                                          YOK, ögenin AT-SPI eylemi"),
    N_("  ekran set-element (ogeye-yaz) <kimlik> <ad> <metin> [--role R] [--nth N] [--secret] [--approved]\n"
       "                                          ögenin değerini AT-SPI ile yaz (metin alanı, kaydırgaç; klavye/odak YOK)"),
    N_("  ekran stop | resume | status (dur | devam | durum)   DUR anahtarı: aç (hiçbir girdi gönderilmez) / "
       "kaldırma isteği (kullanıcı panelde onaylar) / göster"),
    N_("  ekran desktop (masaustu) start|stop|status|list [--name AD] [--json]   görünmez arka plan masaüstü; --background "
       "komutları onu kullanır"),
    N_("  ekran mcp [--desktop auto|background]  MCP sunucusu (stdio) — Claude Code vb. için araçlar"),
    N_("  ekran sessions (oturum) status|policy|clear   arka plan oturum aktarımı (hangi uygulama girişli açılır)"),
    N_("  ekran sessions check (denetle) <site> [--cerez AD] [--json]   site oturumu profilde ve kopyada var mı\n"
       "                                          (salt okuma, değer yazmaz; çıkış 0 = var, 1 = giriş/tazeleme gerekir)"),
    N_("  ekran panel [--tepsi]                   izleme paneli + tepsi simgesi (DUR, Devral, onaylar, ayarlar)"),
    N_("  ekran busy (mesgul) [--json]            kullanıcı meşgul mü (tam ekran, çalan medya, klavye/fare, oyun, "
       "kilit);\n"
       "                                          yalnız okur, girdi göndermez"),
    N_("  ekran decide (karar) \"görev özeti\" [--json]   işi nerede yapayım: on | arka | sonra (çıkış kodu 0 | 20 | 21).\n"
       "                                          Meşgulse ayara göre (~/.config/deskhand/ayarlar.toml [karar]) "
       "bildirimle\n"
       "                                          sorar: Arka planda yap / Ekranımda yap / Sonra. \"arka\" → komutlara "
       "--background"),
    N_("  ekran doctor (doktor) [--json]          kurulum ve oturum sağlığı: bağımlılıklar, oturum, panel, yardımcılar "
       "(salt okunur;\n"
       "                                          zorunlu bağımlılık eksikse çıkış kodu 9)"),
    N_("  ekran help (yardım)                     bu metin"),
)
YARDIM_ORTAK = (
    N_("Ortak: -b/--title (--baslik) DESEN  başlık bu deseni (regex, büyük/küçük harf duyarsız) içermezse DUR."),
    N_("       -s/--class (--sinif) DESEN   pencere sınıfı (ör. krunner, vivaldi-stable) uymazsa DUR (başlıksız "
       "pencereler için)."),
    N_("       --background (--arka)        görünmez ikinci masaüstünde çalış (sanal arka uç; ortam: "
       "DESKHAND_HEDEF=arka)."),
    N_("       --desktop-name AD            (komuttan önce ya da sonra) adlı görünmez masaüstünü kullan (ortam: "
       "DESKHAND_MASAUSTU; boş = varsayılan)."),
    N_("       --on-my-screen (--ekranimda) kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı "
       "açıkça izin verdiyse)."),
    N_("       --unattended (--gozetimsiz)  gözetimsiz kip (ortam: DESKHAND_GOZETIMSIZ=1): onay gerektiren her eylem "
       "panel diyaloğu açılmadan reddedilir (10)."),
    N_("screenshot/read/wait bitince önceki pencere geri öne gelir (--stay: gelmesin)."),
)
YARDIM_CIKIS = (
    N_("Çıkış kodları: 0 tamam, 1 kullanım, 2 nokta pencere/ekran dışında, 3 pencere aktif değil,\n"
       "4 başlık uymadı, 5 birden çok eşleşme (--nth ver), 6 metin bulunamadı, 7 zaman aşımı,\n"
       "8 pencere yok/taşındı, 9 dotool/tesseract çalışmadı, 10 yasak pencere / hassas düğme (onay gerekir),"),
    N_("11 akış hata ekranı / 'dur' adımı, 12 kullanıcı bilgisayarı kullanıyor (insan önceliği),\n"
       "13 kullanıcı DUR dedi (yalnız kullanıcı kaldırır), 14 sanal masaüstü kullanılamıyor,\n"
       "15 kullanıcı oyunda/film izliyor (ekranına müdahale yok; --background),\n"
       "16 uygulama arka planda açılamaz (kullanıcının ekranında açık ya da yalnız ön plan),\n"
       "17 gerçek ekran bu süreçte kapalı (DESKHAND_GERCEK_EKRAN; --background);\n"
       "18 insan doğrulaması (CAPTCHA) sınaması: girdi gönderilmedi, çözülmez/atlatılmaz; kullanıcıya devret\n"
       "(MCP: request_human; CLI: kullanıcıya haber ver);\n"
       "karar: 0 on, 20 arka, 21 sonra"),
)


def komut_listesi():
    """Komutlar paragrafı (argümansız çağrının çıktısı): başlık + komut satırları + ortak seçenekler."""
    return "\n".join(_(m) for m in (*YARDIM_KOMUT_BASI, *YARDIM_KOMUTLAR, *YARDIM_ORTAK))


def yardim_metni():
    """`yardım` / -h metni (çevrilmiş). Komut satırları programın çağrıldığı adla başlar (deskhand ya da ekran)."""
    metin = "\n\n".join((_(YARDIM_GIRIS).format(surum=__version__),
                         "\n".join(_(m) for m in YARDIM_GUVENLIK),
                         komut_listesi(),
                         "\n".join(_(m) for m in YARDIM_CIKIS))) + "\n"
    return re.sub(r"(?m)^(\s+)(?:ekran|deskhand)(?=\s)", lambda m: m.group(1) + prog_adi(), metin)


# `deskhand --help` komut tablosu: Türkçe iç ad → tek satırlık açıklama (argparse alt komut listesi). Ayrıntılı söz
# dizimi `deskhand help` ve `deskhand KOMUT -h` içindedir.
KISA_ACIKLAMA = {
    "bul": N_("pencereleri listele (desensiz: hepsi)"),
    "foto": N_("pencere/masaüstü görüntüsü al (--out, --width)"),
    "tikla": N_("pencerede x,y noktasına tıkla"),
    "tus": N_("tuş ya da kısayol gönder"),
    "yaz": N_("metin yaz"),
    "kaydir": N_("kaydır"),
    "metin": N_("penceredeki yazıyı oku (OCR) + koordinatlar"),
    "metne-tikla": N_("görünen metne tıkla"),
    "bekle": N_("metin görünene (ya da kaybolana) dek bekle"),
    "kapat": N_("pencereyi kapat (başlık kilidi zorunlu)"),
    "bas": N_("tuşu basılı tut (oyun)"),
    "surukle": N_("sürükle-bırak"),
    "fare": N_("fareyi tıklamadan gezdir"),
    "dizi": N_("adımları tek süreçte çalıştır"),
    "uyu": N_("(dizi içinde) bekle"),
    "pano": N_("panoyu oku/yaz"),
    "git": N_("tarayıcı penceresinde http(s) adresine git"),
    "dosya-sec": N_("dosya seçici diyaloğunda dosyayı doğrulayarak seç (yol geri okunur)"),
    "renk-bul": N_("renkli alanları bul"),
    "renge-tikla": N_("en büyük renk alanına tıkla"),
    "simge-kaydet": N_("yazısız simgeyi kaydet"),
    "simge-bul": N_("kayıtlı simgeyi bul"),
    "simgeye-tikla": N_("kayıtlı simgeye tıkla"),
    "ac": N_("uygulamayı aç (--url ADRES; --background: masaüstü kendiliğinden başlar)"),
    "akis": N_("ekran tanıma akışını çalıştır"),
    "erisim": N_("erişilebilirlik ağacını aç/kapat/göster"),
    "agac": N_("penceredeki ögeleri listele (erişilebilirlik ağacı)"),
    "web": N_("tarayıcı sayfasının ögelerini listele"),
    "ogeye-tikla": N_("ögeye adıyla tıkla"),
    "dur": N_("DUR anahtarını aç (hiçbir girdi gönderilmez)"),
    "devam": N_("DUR kaldırma isteği (kullanıcı panelde onaylar)"),
    "ogeye-yaz": N_("ögenin değerini yaz"),
    "durum": N_("arka uç ve DUR durumunu göster"),
    "mesgul": N_("kullanıcı meşgul mü (salt okunur)"),
    "karar": N_("işi nerede yapayım: on | arka | sonra"),
    "panel": N_("izleme paneli + tepsi simgesi"),
    "masaustu": N_("görünmez arka plan masaüstü: start | stop | status"),
    "oturum": N_("arka plan oturum aktarımı: status | policy | clear"),
    "mcp": N_("MCP sunucusu (stdio)"),
    "pencere": N_("pencereyi taşı/boyutlandır/küçült/büyüt/geri yükle"),
    "doktor": N_("kurulum ve oturum sağlığı"),
    "yardım": N_("ayrıntılı yardım metnini yaz"),
}


KOMUTSUZ_ARKA_UC = {"dur", "devam", "durum", "yardım", "yardim", "uyu", "mesgul", "karar", "panel", "masaustu", "oturum", "mcp",
                    "doktor"}  # arka uç gerekmeyen komutlar


def prog_adi():
    ad = os.path.basename(sys.argv[0] or "")
    return "ekran" if ad == "ekran" else "deskhand"


def arka_al():
    """Bu komutun arka ucu. Sanal arka uç yüklenemezse Dur(14)."""
    try:
        return sec()
    except ImportError as e:
        if hedef_ad() != "sanal":
            raise
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kullanılamıyor ({hata})").format(hata=e))


# ---------------------------------------------------------------- küçük komutlar

def k_bul(a):
    """Pencere listesi; desen verilmezse TÜM pencereler. Yasak pencerelerin başlığı gösterilmez (MCP list_windows gibi)."""
    for w, b, geo in arka_al().pencereler(a.desen):
        try:
            if api.yasak_mi(w):
                b = _("(yasak pencere)")
        except Dur:
            continue
        print(f"{w} | {b} | {' '.join(map(str, geo))}")


PANO_ISLEM = {"read": "oku", "write": "yaz"}


def k_pano(a):
    """Pano: oku | yaz [metin]. Ön planda (kullanıcının gerçek panosu) okuma hassas eylemdir: --onayli yoksa panelden
    insan onayı (hassas düğmelerle aynı kalıp). Yazma DUR (13) ve oyun/film korumasına (15) tabidir; pano yöneticisi
    geçmişine yazılmaz. Metin verilmezse ve stdin bir boru ise stdin'den okunur."""
    dur_denetle()
    guvenlik.eylem_basladi()
    au = arka_al()
    if a.islem == "yaz":
        metin = a.metin
        if metin is None:
            if sys.stdin.isatty():
                raise Dur(1, _("yazılacak metin yok: pano yaz <metin> ya da metni stdin'den ver"))
            metin = sys.stdin.read()
        guvenlik.pano_yazma_engel(metin)  # kart kipi: panoya yazılan Luhn'lu kart numarası onay ister
        if au.ad == "kde":  # kullanıcının panosu: kullanıcı klavye/fare kullanıyorsa bekle, sonra 12
            guvenlik.insan_onceligi(_("pano yazma"))
        au.pano_yaz(metin, hassas=True)
        guvenlik.kendi_pano_ekle(metin)  # bu metni okumak/yapıştırmak onay istemez (özet; içerik tutulmaz)
        gunluk(f"pano yaz | {au.ad} | {len(metin)} karakter")  # içerik günlüğe yazılmaz
        print(_("panoya yazıldı: {karakter} karakter").format(karakter=len(metin)))
        return
    if a.metin is not None:
        raise Dur(1, _("pano oku metin almaz"))
    metin = au.pano_oku()
    # gözetimsiz kipte --onayli geçmez (onayli_gecerli); Deskhand'in bu oturumda yazdığı metin onay istemez
    if au.ad == "kde" and metin is not None and not guvenlik.onayli_gecerli(a.onayli) and \
            not guvenlik.kendi_pano_mu(metin) and not guvenlik.onaysiz_serbest("pano oku (CLI)"):
        izin, neden = guvenlik._panelden_onay(
            _("Panoyu oku"), _("pano"), _("Bir yapay zekâ ajanı kullanıcının panosunun metnini okumak istiyor"))
        if not izin:
            raise Dur(10, _("HASSAS pano okuma: panonun içeriği kullanıcının onayını ister ({neden}); kullanıcı "
                            "sohbette açıkça onayladıysa --onayli ile tekrarla").format(neden=neden), tur="hassas")
    gunluk(f"pano oku | {au.ad} | {len(metin) if metin is not None else 'boş'}" + (" --onayli" if a.onayli else ""))
    if metin is None:
        raise Dur(6, _("pano boş ya da metin içermiyor"))
    sys.stdout.write(metin + ("\n" if sys.stdout.isatty() and not metin.endswith("\n") else ""))


def k_dur(a):
    yol = guvenlik.dur_ac()
    gunluk("DUR anahtarı açıldı")
    print(_("DUR: açık ({yol}); hiçbir girdi gönderilmez. {kaldirma}").format(
        yol=yol, kaldirma=_(guvenlik.DUR_KALDIRMA_MESAJI)))


def k_devam(a):
    """Removing DUR is the user's decision: a panel dialog (default No); panel closed / unattended → Dur 13."""
    acikti = guvenlik.dur_kaldir_iste()
    if acikti:
        gunluk("DUR anahtarı kaldırıldı (kullanıcı panelde onayladı)")
    print(_("DUR: kapalı") if acikti else _("DUR: kapalı (zaten kapalıydı)"))


def k_durum(a):
    dur = (_("AÇIK ({yol})").format(yol=dur_dosyasi()) if guvenlik.dur_acik() else _("kapalı"))
    print(_("deskhand {surum} | arka uç: {arka_uc} (DESKHAND_HEDEF={hedef}) | DUR: {dur}").format(
        surum=__version__, arka_uc=hedef_ad(), hedef=os.environ.get("DESKHAND_HEDEF", "on"), dur=dur))


_KOMUT_SATIRI = False  # main() was called with the process's own argv (not an in-process call with a list)


def _yalitik_mi() -> bool:
    return bool(sys.flags.isolated)


def panel_argv_yalitik(arg: list[str]) -> list[str]:
    """The panel's own command line: `python3 -I <src>/bin/deskhand panel …`. -I: no user site-packages, no PYTHON*
    variables, no script/current directory on sys.path, so a shadow package (e.g. a `secretstorage` that raises
    ImportError to make the Secret Service look absent) cannot be loaded (review INC6 Not-A, ANA R9)."""
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, "-I", os.path.join(kok, "bin", "deskhand"), "panel", *arg]


def k_panel(a):
    """İzleme paneli + tepsi (PyQt6). --tepsi: yalnız tepsiyle başla. The panel always runs in an isolated interpreter
    (panel_argv_yalitik): started from a command line without -I, it re-executes itself once with -I. An in-process
    call (main(argv) with a list: tests, embedding) never replaces the calling process."""
    argv = panel_argv_yalitik(list(a.arg))
    if _KOMUT_SATIRI and not _yalitik_mi() and sys.executable and os.path.isfile(argv[2]):
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, argv)
    from .gui.__main__ import main as panel_main
    raise SystemExit(panel_main(a.arg))


def sir_degeri(ad: str) -> str:
    """The user's named secret from the selected key store (anahtar_deposu). Never printed, never logged."""
    from .anahtar_deposu import DepoHatasi, kullanici_adi_mi, secili_depo
    if not kullanici_adi_mi(ad):
        raise Dur(1, _("geçersiz gizli bilgi adı: {ad}").format(ad=ad if isinstance(ad, str) else "?"))
    try:
        v = secili_depo().oku(ad)
    except DepoHatasi as e:
        raise Dur(10, _("gizli bilgi okunamadı ({ad}): {neden}").format(ad=ad, neden=e.neden)) from None
    if v is None:
        raise Dur(1, _("kayıtlı gizli bilgi yok: {ad} (deskhand secret set {ad})").format(ad=ad))
    try:
        return v.decode("utf-8")
    except UnicodeDecodeError:
        raise Dur(1, _("gizli bilgi metin değil: {ad}").format(ad=ad)) from None


def _pencere_bilgisi(k) -> tuple[str, str]:
    """(title, window class) of the target window ('' when unknown). The class comes from the window manager, not from
    the page."""
    try:
        au = sec()
        return str(au.baslik(k) or ""), str(au.sinif(k) or "").lower()
    except Exception:  # noqa: BLE001 - unknown
        return "", ""


def _sir_hedef_denetle(ad: str, k, sinif: str) -> None:
    """The secret's binding (anahtar_deposu.sir_hedefi_oku): window class must be equal; site: the page address last
    read from the window's accessibility tree (dogrulama_sinamasi.son_adres) must be the site or a subdomain of it.
    Unknown → refused (closed-fail)."""
    from .anahtar_deposu import DepoHatasi, sir_hedefi_oku
    try:
        h = sir_hedefi_oku(ad)
    except DepoHatasi as e:
        raise Dur(10, _("gizli bilgi hedefi okunamadı ({ad}): {neden}").format(ad=ad, neden=e.neden)) from None
    if h.get("uygulama") and h["uygulama"] != sinif:
        raise Dur(10, _("kayıtlı parola ({ad}) yalnız {uygulama} penceresine yazılır (hedef: {sinif})").format(
            ad=ad, uygulama=h["uygulama"], sinif=sinif or "?"))
    if h.get("site"):
        from urllib.parse import urlsplit
        from . import dogrulama_sinamasi
        try:
            konak = (urlsplit(dogrulama_sinamasi.son_adres(k) or "").hostname or "").lower().rstrip(".")
        except ValueError:
            konak = ""
        if not konak or not (konak == h["site"] or konak.endswith("." + h["site"])):
            raise Dur(10, _("kayıtlı parola ({ad}) yalnız {site} sitesine yazılır; sayfa adresi {konak} (önce sayfayı "
                            "gözlemleyin)").format(ad=ad, site=h["site"], konak=konak or "?"))


def k_yaz_sir(a):
    """`type`: with --secret-ref AD the value comes from the key store (never argv, never the log, never the result) and
    goes ONLY into a field the accessibility tree reports as a password field (so a stored password cannot be typed
    into a chat box, a terminal or a page field an agent controls); the usual password-field approval applies.
    MCP type_text(secret_ref=…) uses the same function. a.sir_ek: text appended to the value (submit's Enter)."""
    ad = getattr(a, "sir_ref", None)
    if ad is None:
        if getattr(a, "metin", None) is None:
            raise Dur(1, _("yazılacak metin ya da --secret-ref gerekli"))
        return k_yaz(a)
    if getattr(a, "metin", None) is not None:
        raise Dur(1, _("metin ile --secret-ref birlikte verilmez"))
    from . import eylem
    if eylem._parola_alani_mi(a.kimlik) is not True:
        raise Dur(10, _("--secret-ref yalnız parola alanına yazılır: odaklı alan parola alanı değil ya da alan türü "
                        "belirlenemedi (erişilebilirlik: deskhand a11y on)"))
    deger = sir_degeri(ad)  # exists + readable before anything is asked
    baslik, sinif = _pencere_bilgisi(a.kimlik)
    _sir_hedef_denetle(ad, a.kimlik, sinif)
    # ALWAYS the user's approval in the panel, whatever the approval scope and --onayli say (a stored password may
    # leave the machine only with the user's Yes; the dialog names the secret and the target, never the value)
    izin, neden = guvenlik._panelden_onay(
        _("Kayıtlı parolayı yaz"), baslik,
        _("Ajan kayıtlı \"{ad}\" parolasını bu pencerenin parola alanına yazmak istiyor: {baslik} ({sinif}).").format(
            ad=ad, baslik=baslik or "?", sinif=sinif or "?"), konu="parola")
    if not izin:
        raise Dur(10, _("HASSAS: kayıtlı parola ({ad}) yalnız kullanıcının panel onayıyla yazılır ({neden})").format(
            ad=ad, neden=neden), tur="hassas")
    a.metin, a.gizli = deger + (getattr(a, "sir_ek", "") or ""), True
    try:
        return k_yaz(a)
    finally:
        a.metin = None


def k_sir(argv: list[str]) -> int:
    """`deskhand secret set|list|rm|status`: the user's named secrets in the key store (anahtar_deposu). `set` reads
    the value from stdin (a terminal: hidden input, asked twice); it is never an argument and never printed."""
    import getpass
    import json
    from . import anahtar_deposu as ad_
    p = argparse.ArgumentParser(prog=f"{prog_adi()} secret", allow_abbrev=False,
                                description=_("Anahtar deposundaki adlandırılmış gizli bilgiler (değer yalnız stdin'den)."))
    alt = p.add_subparsers(dest="islem", required=True)
    s = alt.add_parser("set", help=_("değeri stdin'den (uçbirimde gizli giriş) kaydet")); s.add_argument("ad")
    s.add_argument("--app", dest="uygulama", default=None, help=_("yalnız bu pencere sınıfına yazılsın"))
    s.add_argument("--site", default=None, help=_("yalnız bu siteye (alt alan adları dahil) yazılsın"))
    alt.add_parser("list", help=_("kayıtlı adlar (değer gösterilmez)"))
    s = alt.add_parser("rm", help=_("sil")); s.add_argument("ad")
    s = alt.add_parser("status", help=_("seçili depo ve durumu")); s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    depo = ad_.secili_depo()
    try:
        if a.islem == "status":
            d = depo.durum()
            print(json.dumps(d, ensure_ascii=False) if a.json else
                  f"{_(ad_.TUR_ADLARI.get(d['tur'], d['tur']))}: " + (_("hazır") if d["hazir"] else str(d["neden"])))
            return 0 if d["hazir"] else 10
        if a.islem == "list":
            for ad in depo.listele():
                print(ad)
            return 0
        if not ad_.kullanici_adi_mi(a.ad):
            print(_("geçersiz ya da ayrılmış ad: {ad}").format(ad=a.ad), file=sys.stderr)
            return 1
        if a.islem == "rm":
            ad_.sir_hedefi_yaz(a.ad)  # the binding goes with the secret
            if depo.sil(a.ad):
                print(_("silindi: {ad}").format(ad=a.ad))
                return 0
            print(_("kayıtlı değil: {ad}").format(ad=a.ad), file=sys.stderr)
            return 1
        if sys.stdin.isatty():
            v1 = getpass.getpass(_("Değer: "))
            if getpass.getpass(_("Yeniden: ")) != v1:
                print(_("değerler aynı değil; kaydedilmedi"), file=sys.stderr)
                return 1
            veri = v1.encode("utf-8")
        else:
            veri = sys.stdin.buffer.read(64 * 1024 + 2)
            if veri.endswith(b"\n"):
                veri = veri[:-1]
            if veri.endswith(b"\r"):
                veri = veri[:-1]
        if not veri:
            print(_("boş değer kaydedilmez"), file=sys.stderr)
            return 1
        try:
            ad_.sir_hedefi_yaz(a.ad, a.uygulama, a.site)  # validates before the value is stored
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        depo.yaz(a.ad, veri)
        print(_("kaydedildi: {ad} ({depo})").format(ad=a.ad, depo=_(ad_.TUR_ADLARI.get(depo.tur, depo.tur))))
        return 0
    except ad_.DepoHatasi as e:
        print(_("anahtar deposu: {neden}").format(neden=e.neden), file=sys.stderr)
        return 10


def k_oturum(a):
    """Arka plan oturum aktarımı: durum | hazirla <uygulama> | politika | sil."""
    from .oturum.cli import main as oturum_main
    raise SystemExit(oturum_main(a.arg))


def k_mcp(a):
    """MCP sunucusu (stdio): yapay zekâ ajanları araçları doğrudan görür. Kayıt: README.md (MCP)."""
    from .mcp_sunucu import main as mcp_main
    ek = ["--desktop-name", a.desktop_name] if getattr(a, "desktop_name", None) is not None else []
    raise SystemExit(mcp_main(["--desktop", a.desktop, *ek]))


def k_masaustu(a):
    """Görünmez arka plan masaüstü: baslat | durdur | durum [--json]."""
    from .masaustu import main as masaustu_main
    raise SystemExit(masaustu_main(a.arg))


def k_yardim(a):
    print(yardim_metni())


# ---------------------------------------------------------------- ayrıştırıcı

def secenek(s, *adlar, en=None, **kw):
    """Seçenek ekle: İngilizce ad birincil (yardımda önce), Türkçe ad takma ad, dest Türkçe ad.
    adlar: kısa ad (-b) ve/veya Türkçe uzun ad (--baslik); en: İngilizce ad (verilmezse SECENEKLER'den)."""
    uzun = [x for x in adlar if x.startswith("--")]
    kisa = [x for x in adlar if not x.startswith("--")]
    en = en or SECENEKLER.get(uzun[0])
    kw.setdefault("dest", uzun[0][2:].replace("-", "_"))
    if kw.get("action") not in ("store_true", "store_false", "append_const", "count") and "metavar" not in kw:
        kw["metavar"] = (en or uzun[0])[2:].upper().replace("-", "_")
    return s.add_argument(*kisa, *([en] if en and en not in uzun else []), *uzun, **kw)


class _YardimBicimleyici(argparse.RawDescriptionHelpFormatter):
    """Komut tablosunda ad ve açıklama aynı satırda kalsın (uzun adlarda argparse açıklamayı alt satıra atıyordu)."""
    def __init__(self, prog, **kw):
        super().__init__(prog, max_help_position=30, **kw)


class AyristirmaHatasi(ValueError):
    """sessiz ayrıştırıcıda argparse hatası (yazdırıp çıkmak yerine)."""


class _Ayristirici(argparse.ArgumentParser):
    """Kullanım hatasında çıkış kodu 1 (argparse'ın 2'si Deskhand'de "nokta dışarıda" demek)."""
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: {_('hata')}: {message}\n")


class _SessizAyristirici(argparse.ArgumentParser):
    def error(self, message):
        raise AyristirmaHatasi(message)


_KACIS = {"n": "\n", "t": "\t", "\\": "\\"}


def kacis_coz(metin):
    """`type` metnindeki kaçışlar: \\n → Enter, \\t → Tab, \\\\ → tek ters bölü (kabuk çift tırnakta \\n'i olduğu
    gibi iletir; çevrilmezse adres çubuğuna '\\n' harfleri yazılıyordu). Başka ters bölüler dokunulmadan kalır.
    Yalnız komut satırı/dizi/akış için: MCP'de JSON gerçek satır sonu taşır, orada çevrilmez."""
    return re.sub(r"\\([nt\\])", lambda m: _KACIS[m.group(1)], metin)


def ayristirici(prog=None, sessiz=False):
    """Komut satırı ayrıştırıcısı. Seçenek KISALTMASI YOK (allow_abbrev=False, alt komutlar dahil): `--onay` ya da
    `--appr` `--onayli`/`--approved` sayılmasın (akış/dizi adımlarındaki önceden onay denetimi tam adla yapılır).
    sessiz=True: hata yazdırıp çıkmak yerine AyristirmaHatasi (dizi/akış adımları, ön tarama)."""
    sinif = _SessizAyristirici if sessiz else _Ayristirici
    ortak = sinif(add_help=False, allow_abbrev=False)
    secenek(ortak, "-b", "--baslik", default=argparse.SUPPRESS, help=h_("başlık kilidi (regex)"))
    secenek(ortak, "-s", "--sinif", default=argparse.SUPPRESS, help=h_("pencere sınıfı kilidi (regex), ör. krunner"))
    secenek(ortak, "--baslik-kilitsiz", action="store_true", default=argparse.SUPPRESS,
            help=h_("kimlikle verilen girdi komutunda otomatik tam başlık kilidini kapat"))
    okuma = sinif(add_help=False, allow_abbrev=False)
    secenek(okuma, "--kal", action="store_true", help=h_("bitince önceki pencereyi geri getirme"))
    p = sinif(prog=prog or prog_adi(), description=yardim_metni(), formatter_class=_YardimBicimleyici,
              allow_abbrev=False)
    secenek(p, "-b", "--baslik", default=None, help=h_("başlık kilidi (regex)"))
    secenek(p, "-s", "--sinif", default=None, help=h_("pencere sınıfı kilidi (regex), ör. krunner"))
    p.add_argument("--version", action="version", version=f"deskhand {__version__}", help=h_("sürümü yaz ve çık"))
    alt = p.add_subparsers(dest="komut", required=True, metavar=_("KOMUT"))
    secenek(ortak, "--arka", action="store_true", default=argparse.SUPPRESS,
            help=h_("görünmez ikinci masaüstünde (sanal arka uç)"))
    for ap_ in (p, ortak):  # komuttan önce de sonra da: `--desktop-name X windows`, `windows --desktop-name X`
        ap_.add_argument("--desktop-name", dest="masa", metavar="AD",
                         default=None if ap_ is p else argparse.SUPPRESS,
                         help=h_("adlı görünmez masaüstü (ortam: DESKHAND_MASAUSTU)"))
    secenek(p, "--arka", action="store_true", default=False, help=h_("görünmez ikinci masaüstünde (sanal arka uç)"))
    secenek(p, "--ekranimda", action="store_true", default=False,
            help=h_("kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı açıkça izin verdiyse)"))
    secenek(ortak, "--ekranimda", action="store_true", default=argparse.SUPPRESS,  # komuttan sonra da kabul
            help=h_("kullanıcı oyunda/film izlerken bile ekranında çalış (YALNIZ kullanıcı açıkça izin verdiyse)"))
    secenek(p, "--gozetimsiz", action="store_true", default=False,
            help=h_("gözetimsiz kip: onay gerektiren eylem diyalog açılmadan reddedilir (10); ortam: DESKHAND_GOZETIMSIZ=1"))
    secenek(ortak, "--gozetimsiz", action="store_true", default=argparse.SUPPRESS,  # komuttan sonra da kabul
            help=h_("gözetimsiz kip: onay gerektiren eylem diyalog açılmadan reddedilir (10)"))
    dugmeler = ["sol", "sag", "cift", "uclu", "orta"]

    def komut(tr, f, **kw):
        """Alt komut: İngilizce adla, Türkçe ad(lar) takma ad; `komut` alanı her zaman Türkçe iç ad."""
        if tr in KISA_ACIKLAMA:
            kw.setdefault("help", h_(KISA_ACIKLAMA[tr]))  # `--help` komut tablosu
        s = alt.add_parser(TR_EN[tr], aliases=takma_adlar(tr), allow_abbrev=False, **kw)
        s.set_defaults(f=f, komut=tr)
        return s

    def dugme(s, secenekler=dugmeler):
        s.add_argument("dugme", nargs="?", default="sol", type=cevirici(DUGME), choices=secimler(DUGME, secenekler),
                       metavar="{" + ",".join(en for en, t in DUGME.items() if t in secenekler) + "}")

    def degistirici(s):
        """Tıklamaya değiştirici tuş: --mod ctrl+shift (keydown → tık → keyup; bırakma her durumda)."""
        secenek(s, "--degistirici", en="--mod", dest="mod", default=None,
                help=h_("tık sırasında basılı tutulacak tuşlar: ctrl, shift, alt, meta (ör. ctrl+shift)"))

    s = komut("bul", k_bul, parents=[ortak]); s.add_argument("desen", nargs="?", default=None)
    s = komut("foto", k_foto, parents=[ortak, okuma]); s.add_argument("kimlik", nargs="?", default=None)
    s.add_argument("cikti", nargs="?")
    secenek(s, "--cikti", en="--out", dest="cikti_dosya", help=h_("çıktı dosyası (konumsal [png] ile aynı)"))
    secenek(s, "--bolge")
    secenek(s, "--genislik", type=int, help=h_("görüntüyü bu genişliğe küçült (yapay zekâ bağlamı için)"))
    secenek(s, "--izgara", type=int, nargs="?", const=100)
    s = komut("tikla", k_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("x", type=float)
    s.add_argument("y", type=float); dugme(s); degistirici(s)
    secenek(s, "--foto", action="store_true", help=h_("x,y son fotoğrafın pikseli (bölge/ölçek eşlenir)"))
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    secenek(s, "--basili", type=float, default=0.0, help=h_("düğmeyi SN basılı tut (oyunda kazma)"))
    secenek(s, "--tekrar", type=int, default=1, help=h_("N kez tıkla"))
    s = komut("bas", k_bas, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("tuslar")
    s.add_argument("sure", type=float); secenek(s, "--onayli", action="store_true")
    s = komut("fare", k_fare, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("x", type=float)
    s.add_argument("y", type=float)
    s = komut("surukle", k_surukle, parents=[ortak]); s.add_argument("kimlik")
    for ad in ("x1", "y1", "x2", "y2"):
        s.add_argument(ad, type=float)
    dugme(s, ["sol", "sag", "orta"])
    secenek(s, "--sure", en="--duration", type=float, default=0.4); secenek(s, "--onayli", action="store_true")
    s = komut("pano", k_pano, parents=[ortak]); s.add_argument("islem", type=cevirici(PANO_ISLEM),
                                                              choices=secimler(PANO_ISLEM, PANO_ISLEM.values()),
                                                              metavar="{read,write}")
    s.add_argument("metin", nargs="?", default=None)
    secenek(s, "--onayli", action="store_true", help=h_("ön plan panosunu okumak için: kullanıcı AÇIKÇA onayladı"))
    s = komut("uyu", k_uyu); s.add_argument("sn", type=float)
    s = komut("dizi", k_dizi, parents=[ortak]); s.add_argument("kimlik"); secenek(s, "--dosya")
    s = komut("tus", k_tus, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("kombinasyon")
    secenek(s, "--onayli", action="store_true", help=h_("ödeme sayfasında Enter/boşluk: kullanıcı AÇIKÇA onayladı"))
    s = komut("kapat", k_kapat, parents=[ortak]); s.add_argument("kimlik")
    s = komut("pencere", k_pencere, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("islem", type=cevirici(PENCERE), choices=secimler(PENCERE, ["tasi", "boyut", "kucult", "buyut", "geri"]),
                   metavar="{move,resize,minimize,maximize,restore}")
    s.add_argument("deger", nargs="*", metavar="PX", help=h_("move: X Y (ekran pikseli); resize: GENİŞLİK YÜKSEKLİK"))
    s = komut("yaz", k_yaz_sir, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("metin", type=kacis_coz, nargs="?", default=None)
    s.add_argument("--secret-ref", dest="sir_ref", metavar="AD", default=None,
                   help=h_("metin yerine anahtar deposundaki AD gizli bilgisini yaz (yalnız parola alanına; değer "
                           "komut satırında ve günlükte görünmez)"))
    secenek(s, "--gizli", action="store_true", help=h_("günlüğe metni yazma"))
    secenek(s, "--onayli", action="store_true",
            help=h_("ödeme sayfasında Enter/Tab/boşluk içeren yazı: kullanıcı AÇIKÇA onayladı"))
    s = komut("kaydir", k_kaydir, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("yon", nargs="?", default="asagi", type=cevirici(YON), choices=secimler(YON, KAYDIR_YON),
                   metavar="{" + ",".join(YON) + "}")
    s.add_argument("adim", nargs="?", type=int, default=KAYDIR_ADIM)
    secenek(s, "--nokta", "--at", help=h_("x,y (varsayılan: pencere ortası)"))
    _kaydir_bicimi(s)
    s = komut("metin", k_metin, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("desen", nargs="?")
    secenek(s, "--bolge"); secenek(s, "--hassas", action="store_true")
    secenek(s, "--hepsi", action="store_true", help=h_("gürültü süzgeci kapalı"))
    secenek(s, "--derin", action="store_true", help=h_("3 okuma yöntemi birlikte: renkli düğmeler de görünür"))
    s = komut("metne-tikla", k_metne_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("metin")
    dugme(s); degistirici(s)
    secenek(s, "--sira", type=int); secenek(s, "--bekle", type=float, default=0.0)
    secenek(s, "--kay", help=h_("dx,dy: metnin merkezinden kaydırarak tıkla (ör. etiketin sağındaki kutu)"))
    secenek(s, "--kaydirarak", type=int, nargs="?", const=10, default=0,
            help=h_("bulunamazsa sayfayı aşağı kaydırıp ara (en çok N kez, varsayılan 10)"))
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    secenek(s, "--bolge")
    s = komut("simge-kaydet", k_simge_kaydet, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("ad")
    secenek(s, "--bolge")
    s = komut("simge-bul", k_simge_bul, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("ad")
    secenek(s, "--esik", type=float, default=0.9); secenek(s, "--bolge")
    s = komut("simgeye-tikla", k_simgeye_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("ad")
    dugme(s); degistirici(s)
    secenek(s, "--esik", type=float, default=0.9); secenek(s, "--sira", type=int); secenek(s, "--bolge")
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    s = komut("renk-bul", k_renk_bul, parents=[ortak, okuma]); s.add_argument("kimlik")
    s.add_argument("renk", type=cevirici(RENK))
    secenek(s, "--bolge"); secenek(s, "--en-az", type=int, default=250)
    s = komut("renge-tikla", k_renge_tikla, parents=[ortak]); s.add_argument("kimlik")
    s.add_argument("renk", type=cevirici(RENK)); dugme(s); degistirici(s); secenek(s, "--bolge")
    secenek(s, "--en-az", type=int, default=250); secenek(s, "--sira", type=int)
    secenek(s, "--onayli", action="store_true")
    s = komut("bekle", k_bekle, parents=[ortak, okuma]); s.add_argument("kimlik"); s.add_argument("metin")
    secenek(s, "--sure", en="--timeout", type=float, default=10.0); secenek(s, "--yok", action="store_true")
    secenek(s, "--bolge")
    s = komut("ac", k_ac, parents=[ortak]); s.add_argument("uygulama", nargs="?")
    s.add_argument("adres", nargs="?", help=h_("açılacak http/https adresi (tarayıcılar; --url ile aynı)"))
    s.add_argument("--url", dest="url", metavar="URL", help=h_("tarayıcıyı bu http/https adresiyle aç"))
    secenek(s, "--komut", dest="komut_satiri", help=h_("uygulama adı yerine bu komutu başlat"))
    secenek(s, "--onayli", action="store_true", help=h_("--komut yıkıcı bir kalıba uyuyorsa: kullanıcı AÇIKÇA onayladı"))
    s.add_argument("--site", action="append",
                   help=h_("(--arka) oturum kopyasına bu sitenin yerel deposunu da al; tekrarlanabilir"))
    secenek(s, "--sure", en="--timeout", type=float, default=30.0)
    s = komut("git", k_git, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("adres")
    secenek(s, "--onayli", action="store_true", help=h_("hassas sayfada Enter: kullanıcı AÇIKÇA onayladı"))
    s = komut("dosya-sec", k_dosya_sec, parents=[ortak]); s.add_argument("kimlik", help=h_("dosya seçici diyaloğu"))
    s.add_argument("yol", help=h_("seçilecek dosyanın tam yolu"))
    s = komut("akis", k_akis, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("dosya")
    secenek(s, "--sure", en="--timeout", type=float, help=h_("dosyadaki süreyi geçersiz kıl"))
    s = komut("erisim", k_erisim)
    s.add_argument("islem", nargs="?", default="durum", type=cevirici(ERISIM),
                   choices=secimler(ERISIM, ["ac", "kapat", "durum"]), metavar="{on,off,status}")
    s = komut("agac", k_agac, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("desen", nargs="?")
    secenek(s, "--rol", help=h_("yalnız bu rol (ör. 'push button', 'check box')"))
    secenek(s, "--hepsi", action="store_true", help=h_("etkileşimsiz ögeler dahil hepsi"))
    s = komut("web", k_web, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("desen", nargs="?")
    secenek(s, "--rol", help=h_("yalnız bu rol (ör. button, link, entry, 'check box', düğme, bağlantı)"))
    secenek(s, "--hepsi", action="store_true", help=h_("görünmeyenler dahil hepsi (sayfalama yok)"))
    secenek(s, "--sayfa", type=int, default=1, help=h_("sayfa numarası (her sayfada 60 öge)"))
    s = komut("ogeye-tikla", k_ogeye_tikla, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("ad")
    dugme(s); degistirici(s); secenek(s, "--rol")
    secenek(s, "--sira", type=int)
    secenek(s, "--onayli", action="store_true", help=h_("kullanıcı bu hassas tıklamayı AÇIKÇA onayladı"))
    secenek(s, "--eylem", nargs="?", const="", default=None, metavar="EYLEM",
            help=h_("fare/odak yerine ögenin AT-SPI eylemini çalıştır (EYLEM verilmezse birincil: click/press/"
                    "activate/toggle)"))
    s = komut("ogeye-yaz", k_ogeye_yaz, parents=[ortak]); s.add_argument("kimlik"); s.add_argument("ad")
    s.add_argument("metin", type=kacis_coz)
    secenek(s, "--rol"); secenek(s, "--sira", type=int)
    secenek(s, "--gizli", action="store_true", help=h_("günlüğe metni yazma"))
    secenek(s, "--onayli", action="store_true",
            help=h_("ödeme sayfasında Enter/Tab/boşluk içeren yazı: kullanıcı AÇIKÇA onayladı"))
    s = komut("mesgul", k_mesgul); s.add_argument("--json", action="store_true")
    s = komut("panel", k_panel, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("oturum", k_oturum, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("mcp", k_mcp); s.add_argument("--desktop", choices=["auto", "background"], default="auto")
    s.add_argument("--desktop-name", dest="desktop_name", default=None, metavar="AD",
                   help=h_("bu MCP oturumunu adlı görünmez masaüstüne sabitle (yoksa kendiliğinden seçilir)"))
    s = komut("masaustu", k_masaustu, add_help=False); s.add_argument("arg", nargs=argparse.REMAINDER)
    s = komut("karar", k_karar); s.add_argument("ozet", help=h_("görev özeti (bildirimde gösterilir)"))
    s.add_argument("--json", action="store_true")
    s = komut("doktor", k_doktor); s.add_argument("--json", action="store_true")
    komut("dur", k_dur)
    komut("devam", k_devam)
    komut("durum", k_durum)
    komut("yardım", k_yardim)
    return p


def varsayilan_foto_hedefi(au):
    """`screenshot` kimliksiz: görünmez masaüstünde tüm masaüstü; kullanıcının ekranında etkin pencere. Gerçek ekran
    kilidi (DESKHAND_GERCEK_EKRAN) açıkça denetlenir (17); etkin pencere belirlenemezse Dur(8)."""
    if au.ad == "sanal":
        return "ekran"
    hata.gercek_ekran_denetle(_("ekran görüntüsü"), okuma=True)
    ak = au.aktif()
    if not ak:
        raise Dur(8, _("etkin pencere belirlenemedi: kimlik ver (windows ile bul)"))
    return ak


# Komuttan önce gelebilen, DEĞER alan genel seçenekler (_masa_secenegi değerlerini atlar)
_DEGERLI_GENEL = frozenset({"-b", "--baslik", "--title", "-s", "--sinif", "--class"})
KAYDIR_ADIM = 3  # MCP scroll(amount) varsayılanıyla aynı


def _masa_secenegi(argv: list) -> list:
    """Komut adına kadar HER KONUMDAKİ genel `--desktop-name AD` (ya da `--desktop-name=AD`) → ortam
    DESKHAND_MASAUSTU: bu süreç ve başlattıkları o görünmez masaüstüne bağlanır (masalar.secili). Ör. `--background
    --desktop-name X windows`, `-b DESEN --desktop-name X click …`. Komuttan sonrakiler ayrıştırıcıda (`windows
    --desktop-name X`); kendi ayrıştırıcısı olan komutlar (desktop/sessions/panel) da önceki biçimi kullanır."""
    from . import masalar
    argv = list(argv)
    i = 0
    while i < len(argv):
        t = argv[i]
        if t == "--desktop-name" or t.startswith("--desktop-name="):
            if "=" in t:
                ad = t.split("=", 1)[1]
                del argv[i]
            else:
                if i + 1 >= len(argv):
                    raise Dur(1, _("--desktop-name bir ad ister"))
                ad = argv[i + 1]
                del argv[i:i + 2]
            os.environ[masalar.ORTAM] = masalar.dogrula(ad)
            continue
        if t in ("--no-title-lock", "--baslik-kilitsiz"):  # komuttan ÖNCE de kabul (argparse yalnız sonrasını tanır)
            os.environ[BASLIK_KILITSIZ_ORTAM] = "1"
            del argv[i]
            continue
        if t == "--" or not t.startswith("-"):
            break  # komut adı (ya da seçeneklerin sonu): sonrası komutun argümanları
        i += 2 if t in _DEGERLI_GENEL else 1
    return argv


# Kimlikle (başlık deseni değil) verilen bu girdi komutlarında -b yoksa şimdiki TAM başlığa kilit (^…$): komut sürerken
# sekme/sayfa değişirse girdi yanlış yere gitmez (Dur 4). YALNIZ tarayıcı pencerelerinde: editör (KWrite'ın "*"
# değişiklik işareti), uçbirim ve okunmamış sayaçlı başlıklar yazarken değişir; orada kilit yazmayı yarıda keserdi.
# dizi kapsam dışı (adımlar arasında sayfa değişimi olağan). --no-title-lock (komuttan önce ya da sonra) kapatır.
OTOMATIK_BASLIK_KOMUTLARI = {"yaz", "tus", "tikla", "kaydir"}
BASLIK_KILITSIZ_ORTAM = "DESKHAND_BASLIK_KILITSIZ"


def otomatik_baslik_kilidi(a, au) -> bool:
    """a.baslik yoksa ve pencere KİMLİKLE verildiyse (çözülmüş kimlik = verilen) şimdiki tam başlığa kilitle.
    → kilit kondu mu."""
    if a.komut not in OTOMATIK_BASLIK_KOMUTLARI or getattr(a, "baslik", None) or getattr(a, "baslik_kilitsiz", False) \
            or os.environ.get(BASLIK_KILITSIZ_ORTAM) == "1":
        return False
    k = getattr(a, "kimlik", None)
    if not k or k == EKRAN or getattr(a, "kimlik_ham", None) != k:
        return False
    from . import web
    try:
        if not web.tarayici_sinifi_mi(au.sinif(k) or ""):
            return False
    except Dur:
        pass  # DH-TUR2: sınıf okunamadı = tarayıcı olabilir → kilit (kapalı-başarısız; en kötü: Dur 4, yanlış sayfa değil)
    b = au.baslik(k)
    if not b:
        return False
    a.baslik = "^" + re.escape(b) + "$"
    return True

def _sayi_mi(t) -> bool:
    return bool(re.fullmatch(r"-?\d+", str(t)))


def _kaydir_bicimi(s) -> None:
    """scroll ayrıştırıcısı: `scroll KİMLİK X Y [yön] [ADIM]` → `scroll KİMLİK [yön] [ADIM] --point X,Y`; tek sayısal
    ikinci argüman (`scroll KİMLİK 300`) → yön/adım/nokta ipucuyla hata (çıkış 1)."""
    degerli = _DEGERLI_GENEL | {"--nokta", "--point", "--at"}
    asil = s.parse_known_args

    def parse_known_args(args=None, namespace=None):
        args = list(args or [])
        poz, i = [], 0
        while i < len(args):
            t = args[i]
            if t.startswith("-") and not _sayi_mi(t):
                i += 1 if "=" in t or t not in degerli else 2
                continue
            poz.append(i)
            i += 1
        if len(poz) >= 3 and _sayi_mi(args[poz[1]]) and _sayi_mi(args[poz[2]]):
            nokta = f"{args[poz[1]]},{args[poz[2]]}"
            args = [a for j, a in enumerate(args) if j not in (poz[1], poz[2])] + ["--point", nokta]
        elif len(poz) >= 2 and _sayi_mi(args[poz[1]]):
            s.error(_("ikinci argüman yön olmalı (down|up|left|right); nokta için: scroll KİMLİK X Y [yön] ya da "
                      "--point X,Y; adım için: scroll KİMLİK down {adim}").format(adim=args[poz[1]]))
        return asil(args, namespace)
    s.parse_known_args = parse_known_args


def main(argv=None):
    global _KOMUT_SATIRI
    _KOMUT_SATIRI = argv is None
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(komut_listesi())
        sys.exit(1)
    try:
        argv = _masa_secenegi(argv)
    except Dur as e:
        print(_("DURDURULDU ({kod}): {mesaj}").format(kod=e.kod, mesaj=e.mesaj), file=sys.stderr)
        sys.exit(e.kod)
    if not argv:
        print(komut_listesi())
        sys.exit(1)
    yollar.gecis()  # eski ekran klasörleri → deskhand (yalnız ilk açılışta, kopya)
    temizle()
    # Kendi ayrıştırıcısı olan komutlar: argümanları olduğu gibi devret. argparse REMAINDER, '--tepsi' gibi
    # seçenekle başlayan argümanı alt komuta bırakmıyordu ("unrecognized arguments: --tepsi").
    gecis = {"panel": k_panel, "oturum": k_oturum, "masaustu": k_masaustu}
    ilk = ic_ad(argv[0]) if argv else ""
    if ilk in gecis:
        gecis[ilk](argparse.Namespace(arg=argv[1:]))
    if argv[0] in ("secret", "sir"):  # key store commands (anahtar_deposu): no back end, own parser
        sys.exit(k_sir(argv[1:]))
    if argv[0] in ("wallet", "cuzdan"):  # open KDE Wallet at login (cuzdan_ac; the login unit runs `wallet open`)
        from .cuzdan_ac import main as cuzdan_main
        sys.exit(cuzdan_main([{"ac": "open", "durum": "status", "kaldir": "remove"}.get(x, x) for x in argv[1:]]))
    a = ayristirici().parse_args(argv)
    if getattr(a, "masa", None) is not None:  # komuttan sonra verilen --desktop-name (arka uç seçilmeden ÖNCE)
        from . import masalar
        try:
            os.environ[masalar.ORTAM] = masalar.dogrula(a.masa)
        except Dur as e:
            print(_("DURDURULDU ({kod}): {mesaj}").format(kod=e.kod, mesaj=e.mesaj), file=sys.stderr)
            sys.exit(e.kod)
    if a.arka or str(getattr(a, "kimlik", "") or "").startswith(ARKA_ONEK) or os.environ.get("DESKHAND_MASAUSTU"):
        # --desktop-name / DESKHAND_MASAUSTU da arka plan demek: adlı masaüstü yalnız görünmez masaüstünde vardır
        # (eskiden --background'sız `--desktop-name X windows` kullanıcının GERÇEK pencerelerini listeliyordu)
        os.environ["DESKHAND_HEDEF"] = "arka"  # bu süreç ve başlattıkları aynı arka ucu seçsin
    if a.ekranimda:
        os.environ["DESKHAND_EKRANIMDA"] = "1"  # kullanıcı açıkça izin verdi: oyun/film sırasında da ön plan
    if a.gozetimsiz:
        os.environ["DESKHAND_GOZETIMSIZ"] = "1"  # başında insan yok: onay diyaloğu açılmaz, hassas eylem reddedilir
    guvenlik.SINIF_DESEN = a.sinif
    onceki = au = None
    otomatik_kilit = False
    try:
        for alan in ("baslik", "sinif", "kimlik", "desen"):  # ajanın verdiği düzenli ifadeler: ReDoS sınırı (desen.py)
            if isinstance(getattr(a, alan, None), str):
                desen.denetle(getattr(a, alan))
        if a.komut in GIRDI_KOMUTLARI or a.komut == "ac":
            dur_denetle()  # DUR anahtarı açıkken hiçbir şeye başlama
        if a.komut not in KOMUTSUZ_ARKA_UC:
            au = arka_al()
            if au.ad != "sanal" and a.komut in ("bul", "erisim"):  # gerçek oturumun pencere/uygulama listesi = okuma
                hata.gercek_ekran_denetle(_("pencere/erişilebilirlik listesi"), okuma=True)
        if a.komut == "foto":
            if getattr(a, "cikti_dosya", None):
                if a.cikti:
                    raise Dur(1, _("çıktı yolu iki kez verildi (konumsal ve --out)"))
                a.cikti = a.cikti_dosya
            if a.kimlik is None:
                a.kimlik = varsayilan_foto_hedefi(au)
        if hasattr(a, "kimlik"):
            a.kimlik_ham = a.kimlik
            a.kimlik = au.pencere_coz(a.kimlik)
        if a.komut in GIRDI_KOMUTLARI:
            yasak_denetle(a.kimlik)  # yasak pencerede hiçbir şeye başlama
            otomatik_kilit = otomatik_baslik_kilidi(a, au)
        if a.komut in OKUMA_KOMUTLARI and not a.kal:
            onceki = au.aktif()
        a.f(a)
    except Dur as e:
        if e.kod == 4 and otomatik_kilit:
            e.mesaj += "\n" + _("başlık değişti (otomatik tam başlık kilidi): sayfa başlığı değişen akışlarda -b ile esnek "
                                "desen ver ya da --no-title-lock kullan")
        print(_("DURDURULDU: {mesaj}").format(mesaj=e.mesaj), file=sys.stderr)
        if a.komut in GIRDI_KOMUTLARI or a.komut == "ac":
            gunluk(f"DUR {e.kod} | {a.komut} {getattr(a, 'kimlik', '')} | {e.mesaj.splitlines()[0]}")
        sys.exit(e.kod)
    finally:
        # okuma bitti: hedef hâlâ öndeyse (kullanıcı başka yere geçmediyse) önceki pencereyi geri getir
        if au is not None and onceki and onceki != getattr(a, "kimlik", None) and \
                au.aktif() == getattr(a, "kimlik", None):
            etkinlestir = getattr(au, "etkinlestir", None)
            if etkinlestir:
                etkinlestir(onceki)
            else:
                try:
                    au.one_getir(onceki)
                except Dur:
                    pass
