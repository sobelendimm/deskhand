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
DEVRAL_ACIK = N_("Kontrol sizde: arka plan masaüstünü siz kullanıyorsunuz")

# ---- tepsi menüsü
M_DUR = N_("DUR — tüm girdileri durdur")
M_DEVAM = N_("Devam et (DUR'u kaldır)")
M_GOREV = N_("Görev ver…")
M_PANEL = N_("Paneli aç")
M_ARKA = N_("Arka plan ekranını göster")
M_CIK = N_("Çık")
P_BEKLENMEYEN_HATA = N_("Panelde beklenmeyen bir hata oluştu ({hata}); panel çalışmaya devam ediyor. Ayrıntı günlükte.")

# ---- başlık şeridi
DUR_DUGME = N_("DUR")
DEVAM_DUGME = N_("Devam et")
DUR_IPUCU = N_("Ajanın tüm girdilerini hemen durdurur (basılı tuşlar bırakılır).")
DEVAM_IPUCU = N_("DUR'u kaldırır; ajan yeniden girdi gönderebilir.")
DEVAM_CLI_NOT = N_("DUR'u ajan koydu; buradan kaldırabilirsiniz.")
DEVAM_SORU = N_("DUR kaldırılsın mı? Ajan yeniden girdi gönderebilir.")
DEVAM_VAZGEC = N_("DUR açık kalsın")

# ---- sekmeler
S_GOREV = N_("Görev")
S_ETKINLIK = N_("Etkinlik")
S_ARKA = N_("Arka plan ekranı")
S_ONAY = N_("Onaylar")
S_ONAY_SAYI = N_("Onaylar ({n})")
S_AYAR = N_("Ayarlar")
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
A_BASLAT_YOK = N_("bu kurulumda arka plan masaüstü başlatılamıyor")
A_BASLAT = N_("Başlat")
A_DURDUR = N_("Durdur")
A_BASLATILIYOR = N_("Başlatılıyor…")
A_DURDURULUYOR = N_("Durduruluyor…")
A_DEVRAL = N_("Devral")
A_BIRAK = N_("Bırak")
A_DEVRAL_IPUCU = N_("Fare ve klavyeniz önizleme üzerinden arka plan masaüstüne gider; bu sırada ajan bekler. "
                    "DUR açıkken girdi gönderilmez.")
A_DEVRAL_NOT = N_("Kontrol sizde: önizlemeye tıklayın, yazın. Bitince «Geri ver»e basın.")
A_DEVRAL_HATA = N_("Devral açılamadı: {hata}")
A_ONIZLEME_YOK = N_("Önizleme yok")
A_ONIZLEME_HATA = N_("Önizleme yok: {hata}")
A_GIRDI_HATA = N_("Girdi gönderilemedi: {hata}")
A_TEKERLEK_YOK = N_("Kontrol sizdeyken kaydırma bu arka plan masaüstü sürümünde desteklenmiyor")

# ---- onaylar
O_BEKLEYEN = N_("Bekleyen istekler")
O_GECMIS = N_("Geçmiş")
O_BEKLEYEN_SUTUNLAR = (N_("Zaman"), N_("Eylem"), N_("Hedef"), N_("Masaüstü"), N_("Kalan"))
O_SUTUNLAR = (N_("Zaman"), N_("Eylem"), N_("Hedef"), N_("Masaüstü"), N_("Durum"))
O_BOS = N_("Bekleyen onay yok")
O_AC = N_("Diyaloğu aç")
O_KARAR = {"izin": N_("izin verildi"), "red": N_("reddedildi"), "sure": N_("süre doldu"),
           "panel-yok": N_("panel kapalıydı"), "panel-kapandi": N_("panel kapandı"), "dur": N_("DUR nedeniyle red"),
           "gozetimsiz": N_("gözetimsiz kip: red"), "hata": N_("hata"), "bekliyor": N_("bekliyor"), "geri": N_("istek geri çekildi"),
           # insan doğrulaması devri (request_human): "izin" değil, iş kullanıcıya devredildi
           "devir-tamam": N_("devir tamam"), "devir-kosul": N_("devir tamam (sınama kalktı)"),
           "devir-red": N_("devir: vazgeçildi"), "devir-sure": N_("devir: süre doldu"),
           "devir-panel-yok": N_("devir: panel kapalıydı"), "devir-panel-kapandi": N_("devir: panel kapandı"),
           "devir-dur": N_("devir: DUR"), "devir-gozetimsiz": N_("devir: gözetimsiz kip"),
           "devir-hata": N_("devir: hata"), "devir-kanal": N_("devir: kanal doğrulanamadı")}
MASAUSTU = {"ekran": N_("Ekranınız"), "arka": N_("Arka plan (görünmez masaüstü)")}

# ---- onay diyaloğu
D_SORU = N_("Claude bir işlem için izninizi istiyor")
D_EYLEM = N_("Eylem")
D_HEDEF = N_("Hedef")
D_MASAUSTU = N_("Masaüstü")
D_AYRINTI = N_("Ayrıntı")
D_ISTEYEN = N_("İsteyen süreç")
D_KALAN = N_("Kalan süre: {s} — yanıt vermezseniz reddedilir")
D_KALAN_DEVIR = N_("Kalan süre: {s} — gelmezseniz devir iptal olur; hiçbir girdi gönderilmez")
D_IZIN = N_("Bir kez izin ver")
D_RED = N_("Reddet")
D_NOT = N_("İzin yalnız bu tek işlem içindir. Emin değilseniz reddedin.")
# insan doğrulaması devri (request_human): CAPTCHA çözülmez, kullanıcıya devredilir
D_DEVIR_SORU = N_("Claude sizi bekliyor: insan doğrulaması gerekiyor")
D_DEVIR_BITTI = N_("Bitti")
D_DEVIR_VAZGEC = N_("Çözemiyorum / Vazgeç")
D_DEVIR_DEVRAL = N_("Kontrolü al")
D_DEVIR_NOT = N_("Sınamayı kendiniz çözün (Claude çözmez). Arka plan masaüstündeyse «Kontrolü al»a basın; bitince Bitti. "
                 "Sınama sayfadan kalkınca da devam edilir.")
D_IZIN_IPUCU = N_("Kazara izne karşı: birkaç saniye sonra ve fareyi bu pencerenin üzerinde gezdirince etkinleşir.")

# ---- ayarlar
Y_MESGUL = N_("Meşgulken davranış")
Y_MESGUL_YOK = N_("Meşgulken davranış ayarları bu kurulumda kullanılamıyor. Deskhand'i yeniden kurmayı deneyin.")
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
Y_YASAK_LISTE_NOT = N_("Bu uygulamaların pencerelerine Deskhand hiçbir girdi göndermez ve bu uygulamaları başlatmaz.")
Y_SEVIYE_LISTE_NOT = N_("Deskhand'in bir uygulamada ne yapabileceğini sınırlar. Yalnız göster: bakar, tıklamaz ve "
                        "yazmaz. Yalnız fare: tıklar ama yazmaz. Tam: kısıt yok. Listede olmayan uygulamalar "
                        "kısıtsızdır.")
Y_SEVIYE_AD = {"goruntule": N_("Yalnız göster"), "tikla": N_("Yalnız fare"), "tam": N_("Tam")}
Y_UYGULAMA = N_("Uygulama")
Y_SEVIYE_SUTUN = N_("Seviye")
Y_UYGULAMA_EKLE = N_("Uygulama ekle…")
Y_KALDIR = N_("Kaldır")
Y_METIN_KIPI = N_("Metin olarak düzenle (ileri düzey)")
Y_PENCERE_SEC_BASLIK = N_("Uygulama ekle")
Y_PENCERE_SEC = N_("Açık pencerelerden bir uygulama seçin:")
Y_PENCERE_YOK = N_("Eklenebilecek açık pencere yok. Uygulamayı açıp yeniden deneyin.")
Y_TEMEL = N_("Temel")
Y_GELISMIS = N_("Gelişmiş")
Y_UYGULA = N_("Uygula")
Y_SIFIRLA = N_("Sıfırla")
Y_DEGISIKLIK_VAR = N_("Kaydedilmemiş değişiklikler var")
Y_KAYDEDILDI_TIK = N_("Kaydedildi ✓")
Y_UYGULA_HATA = N_("⚠ {bolum} kaydedilemedi. {hata} Kayıtlı değer geri yüklendi.")
Y_UYGULA_GECERSIZ = N_("⚠ {bolum}: düzeltip yeniden Uygula'ya basın.")
Y_UYGULA_RED = N_("{bolum}: izin vermediniz; bu değişiklik uygulanmadı.")
Y_CIKIS_BASLIK = N_("Kaydedilmemiş değişiklikler")
Y_CIKIS_SORU = N_("Ayarlar'da uygulanmamış değişiklikler var. Uygulansın mı?")
Y_CIKIS_AT = N_("Değişiklikleri at")
Y_IPTAL = N_("İptal")
Y_IZINLER = N_("İzinler")
Y_IZINLER_YAKINDA = N_("Uygulama başına ayrıntılı izinler yakında burada olacak.")
Y_YASAK_ACIKLAMA = N_("Bu desenlere (regex, büyük/küçük harf duyarsız) uyan pencere başlığı ya da sınıfına hiçbir "
                      "girdi gönderilmez ve bu uygulamalar başlatılmaz. # ile başlayan satırlar açıklamadır.")
Y_SEVIYE = N_("Uygulama erişim seviyeleri")
Y_SEVIYE_ACIKLAMA = N_("Her satır: DESEN = goruntule | tikla | tam. DESEN pencere başlığı ya da sınıfı için regex'tir "
                       "(büyük/küçük harf duyarsız). goruntule: hiçbir girdi gönderilmez (okuma ve ekran görüntüsü "
                       "serbest); tikla: fare serbest, klavye (yaz/tuş) yok; tam: kısıt yok. Birden çok satır uyarsa "
                       "en kısıtlayıcı olan geçerlidir. Varsayılan: boş (hiçbir kısıt yok).")
Y_SEVIYE_HATA = N_("{no}. satır geçerli değil: {hata}")
Y_KAYDET = N_("Kaydet")
Y_GERI_AL = N_("Geri al")
Y_KAYDEDILDI = N_("Kaydedildi.")
Y_DESEN_HATA = N_("{no}. satır geçerli bir desen değil: {hata}")
Y_ONAY = N_("Onay soruları")
Y_ONAY_SORULARI = N_("Onay soruları")
Y_ONAY_SECENEK = {"hepsi": N_("Hepsi"), "kart": N_("Yalnız kartla ödeme")}
Y_ONAY_NOT = N_("Hepsi: bugünkü davranış; tüm riskli eylemler (uçbirimde Enter, pano, riskli tuş, sistem istemleri…) "
                "sorar. Yalnız kartla ödeme: yalnızca satın alma/ödeme düğmeleri (ve ödeme sayfasında Enter) ile "
                "kart bilgisi yazma sorar; diğerleri sormadan yapılır (günlüğe yazılır). Yasaklar, erişim "
                "seviyeleri ve DUR bundan etkilenmez.")
Y_HESAP = N_("Hesap oturumları")
Y_HESAP_HEPSI = N_("Giriş yaptığım hesaplar görünmez masaüstünde de açık olsun (banka ve ödeme siteleri hariç)")
Y_HESAP_SECENEK = {
    "microsoft": N_("Microsoft hesabım (Outlook/Hotmail, OneDrive, Office) görünmez masaüstünde oturum açık "
                    "kullanılabilir"),
    "google": N_("Google hesabım (Gmail, Drive, Dokümanlar) görünmez masaüstünde oturum açık kullanılabilir"),
    "edevlet": N_("e-Devlet ve devlet siteleri (turkiye.gov.tr, gib.gov.tr, sgk.gov.tr…) görünmez masaüstünde oturum "
                  "açık kullanılabilir"),
}
Y_HESAP_AD = {"microsoft": N_("Microsoft hesabı"), "google": N_("Google hesabı"),
              "edevlet": N_("e-Devlet ve devlet siteleri"), "hepsi": N_("Microsoft, Google ve e-Devlet oturumları")}
Y_HESAP_UYARI = N_("Açarsanız arka plandaki tarayıcı bu hesabın e-postalarına ve dosyalarına erişebilir; güvenilmeyen "
                   "bir sayfa ajanı kandırabilir. Hesabın kendi ödeme sayfaları (Google Pay, Microsoft faturalama) da bu "
                   "oturumla açılır; ödeme düğmeleri yine onayınıza gelir. İzni kapatınca o an açık arka plan "
                   "tarayıcısı kapanana kadar oturum sürer.")
Y_HESAP_NOT = N_("Kapalıyken (varsayılan) bu hesapların giriş çerezleri ve kayıtlı parolaları görünmez masaüstündeki "
                 "Firefox kopyasına alınmaz; her seferinde şifre gerekir. Açıkken kayıtlı parolayı Firefox kendisi "
                 "doldurur (ajan parolayı görmez). Görev kipinde (Görev sekmesi) bu izin hiç uygulanmaz. Banka ve "
                 "ödeme siteleri hiçbir ayarla açılmaz. Yalnız bu panelden açılabilir; ayar dosyasına elle yazılan "
                 "değer geçmez.")
Y_HESAP_SORU_BASLIK = N_("{hesap}: oturum izni açılsın mı?")
Y_HESAP_SORU = N_("{hesap} görünmez masaüstündeki tarayıcıda oturum açık kullanılabilecek.\n\n"
                  "Arka plandaki tarayıcı bu hesabın e-postalarına ve dosyalarına erişebilir; güvenilmeyen bir sayfa "
                  "ajanı kandırabilir. Yalnız gerektiğinde açın, işiniz bitince kapatın.\n\nAçılsın mı?")
Y_DIL = N_("Dil")
Y_TEMA = N_("Görünüm")
Y_TEMA_SECENEK = {"koyu": N_("Koyu tema"), "acik": N_("Açık tema"), "sistem": N_("Sistem teması")}
Y_DIL_OTOMATIK = N_("Otomatik (sistem dili: {dil})")
Y_DIL_NOT = N_("Arayüzün dili. Panel ve tepsi menüsü hemen değişir; komut satırı ve ajanın (MCP) iletileri yeni "
               "başlatılan süreçlerde geçerli olur. Etkinlik günlüğü Türkçe kaydedilir.")
Y_DIL_NOT_UYGULA = N_("Arayüzün dili. Uygula'ya basınca panel ve tepsi menüsü hemen değişir; komut satırı ve ajanın "
                      "(MCP) iletileri yeni başlatılan süreçlerde geçerli olur.")
Y_DIL_ZORLA =N_("DESKHAND_DIL ortam değişkeni bu süreçte dili zorluyor ({dil}); seçim kaydedildi, sonraki "
                 "açılışta geçerli olur.")
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
I_BOS = N_("Kayıtlı simge yok. Ajan yazısı olmayan düğmeleri (yalnız simgesi olanları) kaydettiğinde burada görünür.")
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
H_UYARI = N_("uyarı")
H_TUR = {"ek": N_("kurulum/oturum durumu"), "arac": N_("araç"), "dil": N_("OCR dili"), "modul": N_("Python modülü")}

# ---- genel
EVET = N_("Evet")
HAYIR = N_("Hayır")
KAPAT = N_("Kapat")

# ---- görev sekmesi
G_KUTU_IPUCU = N_("Ne yapılmasını istiyorsunuz? Örn: «Trendyol'da şu kasayı sepete ekle», «İndirilenler'i düzenle»")
G_BASLAT = N_("Başlat")
G_BASLAT_IPUCU = N_("Görevi Claude'a verir (Ctrl+Enter). Claude görünmez masaüstünde çalışır; ekranınıza dokunmaz.")
G_DEVRAL = N_("Kontrolü al")
G_BIRAK = N_("Geri ver")
G_DEVRAL_IPUCU = N_("Görünmez masaüstünü siz kullanın (Arka plan ekranı sekmesi): giriş, CAPTCHA, doğrulama kodu…")
G_MODEL = N_("Model")
G_MODEL_AD = {"sonnet": N_("Dengeli · Sonnet"), "opus": N_("Güçlü, daha yavaş · Opus"),
              "haiku": N_("Hızlı, basit işler · Haiku")}
G_MODEL_IPUCU = N_("Görevi yapan Claude modeli (Claude Code aboneliğiniz kullanılır).")
G_ADIMLAR = N_("Adımlar")
G_SONUC = N_("Sonuç")
G_GECMIS = N_("Geçmiş görevler (çift tıkla: metni kutuya al)")
G_HAZIR = N_("Hazır. Görevi yazıp Başlat'a basın.")
G_CALISIYOR = N_("Çalışıyor… ({n} adım)")
G_ONAY = N_("Onay bekleniyor ({n}): onay penceresine bakın — Claude sizin kararınızı bekliyor.")
G_BITTI = {"tamam": N_("Bitti."), "hata": N_("Görev tamamlanamadı."), "durduruldu": N_("Durduruldu."),
           "zaman_asimi": N_("Süre doldu, durduruldu."), "devam": N_("Yarım kaldı.")}
G_DURDURULUYOR = N_("Durduruluyor…")
G_SANAL_YOK = N_("Görünmez masaüstü henüz açık değil. Claude açınca burada canlı görünür.")
G_ONIZLEME_BOS = N_("Görev çalışırken görünmez masaüstü burada canlı görünür.")
G_ONIZLEME_HATA = N_("Görüntü alınamadı: {hata}")
G_DUSUNUYOR = N_("Düşünüyor…")
G_HATA_SATIRI = N_("Hata: {ozet}")
G_GECMIS_SATIRI = N_("{zaman} · {durum} · {metin}")
G_ARAC = {
    "open_app": N_("{app} açılıyor"),
    "click": N_("‘{hedef}’ tıklanıyor"),
    "click_genel": N_("Bir öğe tıklanıyor"),
    "type_text": N_("Metin yazılıyor"),
    "press_key": N_("Tuşa basılıyor: {keys}"),
    "scroll": N_("Sayfa kaydırılıyor"),
    "drag": N_("Öğe sürükleniyor"),
    "observe": N_("Pencere inceleniyor"),
    "screenshot": N_("Ekran görüntüsü alınıyor"),
    "read_text": N_("Ekrandaki metin okunuyor"),
    "find": N_("Simge/renk aranıyor"),
    "wait_for": N_("Bekleniyor: {value}"),
    "wait_for_genel": N_("Ekranın oturması bekleniyor"),
    "get_status": N_("Durum kontrol ediliyor"),
    "choose_desktop": N_("Masaüstü seçiliyor"),
    "manage_desktop_start": N_("Görünmez masaüstü açılıyor"),
    "manage_desktop_stop": N_("Görünmez masaüstü kapatılıyor"),
    "manage_desktop_status": N_("Görünmez masaüstü inceleniyor"),
    "manage_window": N_("Pencere düzenleniyor"),
    "clipboard": N_("Pano kullanılıyor"),
    "listen": N_("Ses dinleniyor"),
    "run_flow": N_("Kayıtlı akış çalıştırılıyor"),
    "batch": N_("Adım dizisi çalıştırılıyor"),
}
G_ARAC_BILINMEYEN = N_("Araç çalışıyor: {arac}")
G_SITELER = N_("Oturumla girilebilecek siteler:")
G_SITELER_IPUCU = N_("github.com, ornek.com — boşsa çerezsiz temiz profil")
G_SITELER_ACIKLAMA = N_("Yalnız bu sitelerin çerezleri (girişleri) görev tarayıcısına kopyalanır; boşsa tarayıcı hiçbir "
                        "oturum olmadan açılır. Kayıtlı parolalar HİÇ kopyalanmaz. Bu sitelerde ajan sizin adınıza "
                        "işlem yapabilir (ayar değiştirme, gönderi, silme); güvenilmeyen sayfa içeriği ajanı "
                        "kandırabilir.")
G_SITE_RET = N_("Görev başlatılmadı; site listesinde düzeltilmesi gerekenler var:\n{nedenler}")
G_MASAUSTU_ACIK_BASLIK = N_("Görünmez masaüstü açık")
G_MASAUSTU_ACIK_METIN = N_("Görünmez masaüstü başka bir iş için açık; kapatıp başlatılsın mı?\n\nGörev kendi temiz "
                           "masaüstünde çalışır: açık masaüstündeki pencereler (başka oturumların açtıkları dahil) "
                           "kapatılır.")
G_MASAUSTU_KAPAT_BASLAT = N_("Kapat ve başlat")
G_PAROLA_UYARI = N_("Görev metnine parola ya da kart numarası yazmayın.")
G_ONAY_BASLIK = N_("Görevi başlat")
G_ONAY_METIN = N_("Görev: {metin}\n\nOturumla girilebilecek siteler: {siteler}\n\nYalnız tarayıcı açılabilir; yerel "
                  "dosyalar ve kayıtlı parolalar görev ajanına kapalı.\n\nBu sitelerde ajan sizin adınıza işlem "
                  "yapabilir (ayar değiştirme, gönderi, silme); güvenilmeyen sayfa içeriği ajanı kandırabilir.")
G_ONAY_SITE_YOK = N_("yok — çerezsiz")
G_INDIRILENLER = N_("İndirilen dosyalar: {dosyalar} (klasör: {klasor})")

# ---------------------------------------------------------------- 0.9.1 (Faz A): bekleyen istek bildirimi, iptal edilen devir
TB_DEVIR_BASLIK = N_("Deskhand: insan doğrulaması sizi bekliyor")
TB_ONAY_BASLIK = N_("Deskhand: onay bekliyor")
TB_ONAY_GOVDE = N_("{neden}\nAçmak için tıklayın; Bitti / Vazgeç panel penceresinde.")
O_KARAR.update({"iptal": N_("isteyen vazgeçti"), "devir-iptal": N_("devir: çağrı iptal edildi")})
# ---- Arka plan ekranı: masaüstü seçici + "ajan şu an ne yapıyor" (çoklu görünmez masaüstü)
A_MASA_SUTUNLAR = (N_("Masaüstü"), N_("Açık"), N_("Son etkinlik"))
A_MASA_VARSAYILAN = N_("varsayılan")
A_MASA_YOK = N_("Çalışan arka plan masaüstü yok. Bir ajan masaüstü açınca burada görünür; varsayılan masaüstünü "
                "Başlat ile açabilirsiniz.")
A_MASA_IPUCU = N_("Bir masaüstü seçin: önizleme onu gösterir (yalnız izleme).")
A_SURE_SN = N_("{n} sn")
A_SURE_DK = N_("{n} dk")
A_SURE_SA = N_("{s} sa {d} dk")
A_ONCE = N_("{sure} önce")
A_SON_YOK = N_("—")
A_EYLEM = N_("Ajan şu an: {eylem} · [{pencere}] · {once}")
A_EYLEM_YOK = N_("Ajan şu an: bu masaüstünde henüz bir eylem yok")
A_EYLEM_GIZLI = N_("gizli alana yazı (içerik gösterilmez)")
A_DEVRAL_ADLI = N_("Bu, bir ajanın kendi masaüstü: burada yalnız izlersiniz. «Kontrolü al» varsayılan masaüstünde ya da "
                   "bir onay devrinde açılır.")
A_MASKE_HATA = N_("Önizleme gizlendi: yasak pencereler denetlenemedi ({hata})")

# ---------------------------------------------------------------- UX-F (O4–O9): iki katmanlı hata, Sağlık özeti, Görev
# Hata iletisi iki katman: üstte sade cümle + ne yapılacak (hata_ozeti), ham istisna yalnız katlı "Ayrıntı" altında.
D_AYRINTI_DUGME = N_("Ayrıntı")
HATA_CARE = {
    "izin": N_("Ayar dosyası yazılamıyor. Klasör izinlerini kontrol edin."),
    "disk": N_("Disk dolu: kaydedilemedi. Biraz yer açıp yeniden deneyin."),
    "salt": N_("Ayar klasörü salt okunur: kaydedilemedi. Klasörün yazılabilir olduğunu kontrol edin."),
    "yok": N_("Gerekli bir dosya ya da klasör bulunamadı. Deskhand'i yeniden başlatıp yeniden deneyin."),
    "dosya": N_("Ayar dosyası yazılamıyor. Disk dolu mu? Klasör izinlerini kontrol edin."),
    "genel": N_("Beklenmeyen bir sorun oldu. Yeniden deneyin; sürerse Sağlık sekmesine bakın."),
}


def hata_turu(e: BaseException | None) -> str:
    """İstisna → HATA_CARE anahtarı (Qt'siz; ham metin kullanıcıya gösterilmez)."""
    import errno
    if isinstance(e, PermissionError) or getattr(e, "errno", None) in (errno.EACCES, errno.EPERM):
        return "izin"
    if getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
        return "disk"
    if getattr(e, "errno", None) == errno.EROFS:
        return "salt"
    if isinstance(e, FileNotFoundError):
        return "yok"
    if isinstance(e, OSError):
        return "dosya"
    return "genel"


def hata_ozeti(e: BaseException | None) -> str:
    """Sade cümle + ne yapılacak (etkin dilde)."""
    from ..i18n import _
    return _(HATA_CARE[hata_turu(e)])


def hata_ayrinti(e: BaseException | object) -> str:
    """Katlı ayrıntı: ham istisna metni (tür adı yalnız metin boşsa)."""
    m = str(getattr(e, "mesaj", None) or e) if e is not None else ""
    return m or type(e).__name__


Y_PENCERE_OKUNAMADI = N_("Açık pencereler okunamadı. Biraz sonra yeniden deneyin.")
Y_GOREV = N_("Görev")
Y_GOREV_ONAY = N_("Görev başlatmadan önce onay sor")
Y_GOREV_ONAY_NOT = N_("Kapalıyken Görev sekmesindeki Başlat onay penceresi göstermeden çalışır. Görev penceresinde "
                      "«Bir daha sorma» dediyseniz buradan yeniden açabilirsiniz.")
Y_ACIKLAMA = N_("Açıklama")
Y_SIMGELER = N_("Kayıtlı simgeler")
Y_SIMGELER_NOT = N_("Ajanın tanıdığı yazısız düğmeler. Silerseniz ajan o düğmeyi yeniden öğrenmek zorunda kalır.")
G_BASLATMA_HATA_SADE = N_("Görev başlatılamadı. {care}")
G_BASLATMA_CARE = N_("Claude Code'un kurulu ve oturumunuzun açık olduğunu kontrol edip yeniden deneyin.")
G_ADIMLAR_BOS = N_("görev başlayınca adımlar burada görünür")
G_SONUC_BOS = N_("Görev bitince sonuç burada görünür.")
G_GECMIS_BOS = N_("henüz görev yok")
H_HEPSI_TAMAM = N_("Her şey hazır ✓")
H_SORUN_VAR = N_("{n} sorun var")
H_SORUN_TEK = N_("1 sorun var")
H_SORUN_NOT = N_("Aşağıdaki bileşenler eksik. Komutu kopyalayıp bir uçbirimde çalıştırın, sonra «Yeniden denetle».")
H_KOPYALA = N_("Kopyala")
H_KOPYALA_IPUCU = N_("Kurulum komutunu panoya kopyalar: {komut}")
H_KOPYALANDI = N_("Kopyalandı: {komut}")
H_TUMU = N_("Tüm bileşenler")
