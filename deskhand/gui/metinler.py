"""Panelin TÜM kullanıcıya görünen metinleri, tek yerde. Her metin bir msgid'dir (kaynak dil Türkçe):
burada yalnız ``N_()`` ile işaretlenir, KULLANILDIĞI yerde ``_()`` ile çevrilir (``_(T.S_AYAR)``,
``_(T.E_SATIR).format(n=3)``). Böylece dil Ayarlar'dan değişince (i18n.yeniden_yukle) aynı sabit yeni dilde
okunur; modül yeniden içe aktarılmaz. Yer tutucular adlıdır ({n}, {ekran}); çeviride korunmalı.

Çevrilmeyenler: uygulama adı (Deskhand), pencere başlıkları (onay.PANEL_BASLIK / ONAY_BASLIK: yasak pencere
listesi ve testler sabit başlığa güvenir) ve günlük satırlarının içeriği (Türkçe kalır, panel ayrıştırır; yalnız
GUNLUK_ESLEME'deki sabit satırlar görüntülenirken çevrilir).
"""
from __future__ import annotations

from ..i18n import N_

UYGULAMA = "Deskhand"  # marka adı: çevrilmez
ALT_BASLIK = N_("Claude izleme ve yönetme paneli")

# ---- durum adları (tepsi + başlık)
DURUM = {
    "bos": N_("Boşta"),
    "ekran": N_("Ekranınızda çalışıyor"),
    "arka": N_("Arka planda çalışıyor"),
    "dur": N_("DUR açık"),
}
DUR_KAYNAK = {"kullanici": N_("siz durdurdunuz"), "cli": N_("ajan/komut satırı durdurdu")}
ONAY_BEKLIYOR = N_("{n} onay bekliyor")
SANAL_ACIK = N_("Arka plan masaüstü açık ({ekran})")
SANAL_KAPALI = N_("Arka plan masaüstü kapalı")
DEVRAL_ACIK = N_("Arka plan masaüstünü siz kullanıyorsunuz (Devral)")

# ---- tepsi menüsü
M_DUR = N_("DUR — tüm girdileri durdur")
M_DEVAM = N_("Devam et (DUR'u kaldır)")
M_PANEL = N_("Paneli aç")
M_ARKA = N_("Arka plan ekranını göster")
M_CIK = N_("Çık")

# ---- başlık şeridi
DUR_DUGME = N_("DUR")
DEVAM_DUGME = N_("Devam et")
DUR_IPUCU = N_("Ajanın tüm girdilerini hemen durdurur (basılı tuşlar bırakılır).")
DEVAM_IPUCU = N_("DUR'u kaldırır; ajan yeniden girdi gönderebilir.")
DEVAM_CLI_NOT = N_("DUR'u ajan koydu; buradan kaldırabilirsiniz.")
DEVAM_SORU = N_("DUR kaldırılsın mı? Ajan yeniden girdi gönderebilir.")
DEVAM_VAZGEC = N_("DUR açık kalsın")

# ---- sekmeler
S_ETKINLIK = N_("Etkinlik")
S_ARKA = N_("Arka plan ekranı")
S_ONAY = N_("Onaylar")
S_ONAY_SAYI = N_("Onaylar ({n})")
S_AYAR = N_("Ayarlar")
S_SIMGE = N_("Simgeler")
S_SAGLIK = N_("Sağlık")

# ---- etkinlik
E_SUTUNLAR = (N_("Zaman"), N_("Masaüstü"), N_("Pencere"), N_("Eylem"))
E_ARKA_AD = {"ekran": N_("ekran"), "arka": N_("arka plan"), "": ""}
E_FILTRE_IPUCU = N_("Süz: pencere, eylem, metin…")
E_TUR = (("hepsi", N_("Hepsi")), ("dur", N_("Yalnız DUR")), ("ekran", N_("Ekran")), ("arka", N_("Arka plan")),
         ("onay", N_("Onaylar")))
E_BOS = N_("Henüz günlük satırı yok. Ajan bir şey yaptığında burada görünür.")
E_KAYDIR = N_("Otomatik kaydır")
E_SATIR = N_("{n} satır")
# Günlükte sık geçen SABİT satırlar (Eylem sütunu) → görüntüleme metni. Günlük dosyası Türkçe kalır; süzgeç ham
# satırda arar. Anahtar = gunluk_okur.ayristir'ın "eylem" alanı.
GUNLUK_ESLEME = {
    "DUR anahtarı açıldı": N_("DUR anahtarı açıldı"),
    "DUR anahtarı kaldırıldı": N_("DUR anahtarı kaldırıldı"),
    "DUR anahtarı açıldı (panel)": N_("DUR anahtarı açıldı (panel)"),
    "DUR anahtarı kaldırıldı (panel)": N_("DUR anahtarı kaldırıldı (panel)"),
}
E_ONAY_SATIRI = N_("onay ({karar}): {eylem}")  # "onay izin: tıkla 'Öde'" → onay (izin verildi): tıkla 'Öde'

# ---- arka plan ekranı
A_ACIK = N_("Açık: {ekran} · {g}×{y}")
A_KAPALI = N_("Arka plan masaüstü kapalı.")
A_YOK = N_("Sanal masaüstü modülü yüklenemedi: {hata}")
A_BASLAT_YOK = N_("masaustu_baslat işlevi yok")
A_BASLAT = N_("Başlat")
A_DURDUR = N_("Durdur")
A_BASLATILIYOR = N_("Başlatılıyor…")
A_DURDURULUYOR = N_("Durduruluyor…")
A_DEVRAL = N_("Devral")
A_BIRAK = N_("Bırak")
A_DEVRAL_IPUCU = N_("Fare ve klavyeniz önizleme üzerinden arka plan masaüstüne gider; bu sırada ajan bekler. "
                    "DUR açıkken girdi gönderilmez.")
A_DEVRAL_NOT = N_("Devraldınız: önizlemeye tıklayın, yazın. Bitince Bırak.")
A_ONIZLEME_YOK = N_("Önizleme yok")
A_ONIZLEME_HATA = N_("Önizleme yok: {hata}")
A_GIRDI_HATA = N_("Girdi gönderilemedi: {hata}")
A_TEKERLEK_YOK = N_("Kaydırma bu sanal arka uç sürümünde Devral sırasında desteklenmiyor")

# ---- onaylar
O_BEKLEYEN = N_("Bekleyen istekler")
O_GECMIS = N_("Geçmiş")
O_BEKLEYEN_SUTUNLAR = (N_("Zaman"), N_("Eylem"), N_("Hedef"), N_("Masaüstü"), N_("Kalan"))
O_SUTUNLAR = (N_("Zaman"), N_("Eylem"), N_("Hedef"), N_("Masaüstü"), N_("Durum"))
O_BOS = N_("Bekleyen onay isteği yok.")
O_AC = N_("Diyaloğu aç")
O_KARAR = {"izin": N_("izin verildi"), "red": N_("reddedildi"), "sure": N_("süre doldu"),
           "panel-yok": N_("panel kapalıydı"), "panel-kapandi": N_("panel kapandı"), "dur": N_("DUR nedeniyle red"),
           "hata": N_("hata"), "bekliyor": N_("bekliyor"), "geri": N_("istek geri çekildi")}
MASAUSTU = {"ekran": N_("Ekranınız"), "arka": N_("Arka plan (görünmez masaüstü)")}

# ---- onay diyaloğu
D_SORU = N_("Claude bir işlem için izninizi istiyor")
D_EYLEM = N_("Eylem")
D_HEDEF = N_("Hedef")
D_MASAUSTU = N_("Masaüstü")
D_AYRINTI = N_("Ayrıntı")
D_ISTEYEN = N_("İsteyen süreç")
D_KALAN = N_("Kalan süre: {s} — yanıt vermezseniz reddedilir")
D_IZIN = N_("Bir kez izin ver")
D_RED = N_("Reddet")
D_NOT = N_("İzin yalnız bu tek işlem içindir. Emin değilseniz reddedin.")
D_IZIN_IPUCU = N_("Kazara izne karşı: birkaç saniye sonra ve fareyi bu pencerenin üzerinde gezdirince etkinleşir.")

# ---- ayarlar
Y_MESGUL = N_("Meşgulken davranış")
Y_MESGUL_YOK = N_("Meşgul algılama ayarları bu kurulumda bulunamadı (deskhand.ayarlar yüklenemedi).")
Y_MESGULKEN = N_("Meşgulken")
Y_MESGUL_SECENEK = {"sor": N_("Sor (Arka planda / Ekranımda / Sonra)"), "arka": N_("Hep arka planda yap"),
                    "hep-arka": N_("Hep arka planda yap"), "bekle": N_("Bitmesini bekle")}
Y_SOR_SURE = N_("Soru süresi")
Y_SN = N_("sn")  # saniye kısaltması (sayı kutusu soneki)
Y_CEVAPSIZ = N_("Yanıt yoksa")
Y_CEVAPSIZ_SECENEK = {"sonra": N_("Sonraya bırak"), "arka": N_("Arka planda yap"), "bekle": N_("Bekle"),
                      "iptal": N_("İptal")}
Y_TAM_EKRAN = N_("Tam ekranda da sor")
Y_TAM_EKRAN_NOT = N_("Kapalıysa film/oyun sırasında bildirim gösterilmez, 'Yanıt yoksa' seçeneği uygulanır.")
Y_YASAK = N_("Yasak pencereler")
Y_YASAK_ACIKLAMA = N_("Bu desenlere (regex, büyük/küçük harf duyarsız) uyan pencere başlığı ya da sınıfına hiçbir "
                      "girdi gönderilmez ve bu uygulamalar başlatılmaz. # ile başlayan satırlar açıklamadır.")
Y_KAYDET = N_("Kaydet")
Y_GERI_AL = N_("Geri al")
Y_KAYDEDILDI = N_("Kaydedildi.")
Y_DESEN_HATA = N_("{no}. satır geçerli bir desen değil: {hata}")
Y_DIL = N_("Dil")
Y_DIL_OTOMATIK = N_("Otomatik (sistem dili: {dil})")
Y_DIL_NOT = N_("Arayüzün dili. Panel ve tepsi menüsü hemen değişir; komut satırı ve ajanın (MCP) iletileri yeni "
               "başlatılan süreçlerde geçerli olur. Etkinlik günlüğü Türkçe kaydedilir.")
Y_DIL_ZORLA = N_("DESKHAND_DIL ortam değişkeni bu süreçte dili zorluyor ({dil}); seçim kaydedildi, sonraki "
                 "açılışta geçerli olur.")
Y_DIL_HATA = N_("Dil kaydedilemedi: {hata}")
Y_KISAYOL = N_("Genel kısayol")
Y_KISAYOL_AC = N_("Klavye kısayoluyla DUR (KDE genel kısayolu)")
Y_KISAYOL_TUS = N_("Tuş")
Y_KISAYOL_NOT = N_("Varsayılan kapalıdır. Açınca kısayol KDE'ye bu uygulama adına kaydedilir; kapatınca kaydı "
                   "silinir. Çalışmazsa tepsi simgesindeki DUR yeterlidir.")
Y_KISAYOL_CAKISMA = N_("Çakışma: {tus} şu an «{eylem}» ({bilesen}) için kullanılıyor.")
Y_KISAYOL_BOS = N_("{tus} boşta görünüyor.")
Y_KISAYOL_HATA = N_("Kısayol kaydedilemedi: {hata}")
Y_KISAYOL_TAMAM = N_("Kısayol etkin: {tus}")

# ---- simgeler
I_BOS = N_("Kayıtlı simge yok. Ajan `simge-kaydet` ile yazısız düğmeleri kaydettiğinde burada görünür.")
I_SIL = N_("Sil")
I_YENILE = N_("Yenile")
I_SIL_SORU = N_("«{ad}» simgesi silinsin mi? Bu simgeyi kullanan akışlar artık onu bulamaz.")
I_SIL_BASLIK = N_("Simgeyi sil")
I_BILGI = N_("{ad} · {g}×{y}")

# ---- sağlık
H_YENILE = N_("Yeniden denetle")
H_SUTUNLAR = (N_("Bileşen"), N_("Durum"), N_("Not"))
H_VAR = N_("var")
H_YOK = N_("yok")
H_OZET = N_("{ok}/{n} bileşen hazır")
H_TUR = {"arac": N_("araç"), "dil": N_("OCR dili"), "modul": N_("Python modülü")}

# ---- genel
EVET = N_("Evet")
HAYIR = N_("Hayır")
KAPAT = N_("Kapat")
