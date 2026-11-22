# Değişiklik notları (Türkçe)

*Bu dosya İngilizce belgelerden bağımsız tutulan Türkçe özettir; İngilizce çeviri henüz yapılmadı.*

## Yayımlanmamış (Tur 3: dinleme)

- **`listen` aracı.** Görünmez masaüstündeki uygulamaların SESİ yerel Whisper ile yazıya dökülür (video, sesli mesaj). Her masaüstü isterse kendi özel, donanımsız ses sunucusunu alır (`manage_desktop(start, audio=true)` ya da ilk `listen`); uygulamalar yalnız onu görür, ses kullanıcının hoparlörüne gitmez, mikrofon yoktur. Kayıt bellekte tutulur, metin günlüğe yazılmaz, kullanıcının kendi ekran sesi dinlenmez. `doctor` "Dinleme" satırı eklendi; ayarlar `[dinleme]`.
- **Dinleme güvenlik düzeltmeleri (bağımsız inceleme).** Uygulamalar özel ses sunucusuna yalnız pulse soketinden ulaşır ve modül YÜKLETEMEZ (`load-module` kapalı: tünel ile gerçek mikrofona/hoparlöre bağlanma, LADSPA ile keyfi kod, pipe ile dosya yazma, TCP soketi açma engellendi). PipeWire'ın tam yetkili soketi uygulamaya hiç bağlanmaz. Üç ses süreci de kendi bwrap ad alanında çalışır: ağ yok, ses donanımı/GPU yok, kullanıcının gerçek oturum soketleri ve ev dizini görünmez, yalnız `ses/` yazılabilir, düşük öncelik. Konuşma tanıma masaüstünün bellek kafesinde düşük öncelikle çalışır; kullanıcı oyundayken CPU'da en çok 4 iş parçacığı kullanır.

## 0.6.0 (0.5.4'ten sonra)

### Öne çıkanlar

- **Gözlem, ref ve toplu eylem.**
  - `observe` tek çağrıda bir pencerenin ögelerini listeler (erişilebilirlik ağacı, gerekirse OCR). Her öge bir numara (`ref`) alır.
  - `click`, `type_text`, `scroll` ve `drag` artık koordinat yerine `ref` ile çalışır. Ekran değişmişse (pencere kapandı, öge kayboldu, adı ya da yeri değişti) eylem hiçbir girdi gönderilmeden reddedilir; aynı adlı başka düğmeye tıklanmaz.
  - `observe` için `since` ile yalnız değişenler, `query` ile süzme, `include_screenshot` ile numaralı görüntü alınabilir.
  - `batch` en çok 20 adımı tek çağrıda yürütür. Önce hepsi doğrulanır, ilk hatada durur, her adım arasında DUR, bekleyen onay ve insan önceliği yeniden denetlenir.
  - `wait_for` metin, öge, pencere, kaybolma ya da ekranın durulması için bekler.
  - Girdi araçlarının sonucu artık ne olduğunu söyler: `confirmed`, `changed`, `no_change`, `unverifiable`, `refused`. Hata iletileri bir sonraki adımı ve girdinin gidip gitmediğini (`sent`) bildirir.
- **Web sayfası ögeleri.** Tarayıcıdaki sayfanın bağlantı, düğme, alan ve kutuları erişilebilirlik ağacından okunur (`read_text` `source="web"`, CLI `web`, `click` ile `element`). Tarayıcıya uzaktan denetim kapısı açılmaz, sayfa otomasyon görmez. Öge konumu doğrulanamazsa tıklama reddedilir.
- **Yalıtık, ekran kartı hızlandırmalı görünmez masaüstü.** Arka plan masaüstü artık yalıtık bir KWin oturumu olarak açılır (ekran kartı hızlandırmalı, ayrı D-Bus ve Wayland soketi, düşük öncelik). Gerekli bileşenler yoksa eskisi gibi Xvfb + openbox ile açılır. Türü `deskhand desktop` durumundan görebilirsiniz.
- **Onay kapsamı: "Yalnız kartla ödeme".**
  - Panelde Ayarlar → "Onay soruları" içinde seçilir. Varsayılan **hepsi** (hiçbir şey değişmez).
  - **kart** seçilirse yalnızca iki durumda onay sorulur: para düğmeleri / ödeme sayfasında tıklama ve Enter, ve kart bilgisi yazma. Para düğmeleri Türkçe ve İngilizce okunur (satın al, öde, siparişi onayla, buy now, place order gibi).
  - Bu ayar yalnız panelden açılır; ayar dosyasını elle `kart` yapmak işe yaramaz.
  - Onay isteğinde kart numarasının yalnız son 4 hanesi görünür, günlüğe tam numara yazılmaz.
  - Terminal komutları, parola alanları, sistem parola istemleri, riskli tuşlar gibi diğer koruma ve reddetmeler olduğu gibi kalır.
- **Türkçe OCR.** Yazıya tıklama ve gözlemdeki OCR Türkçe ve İngilizce verisiyle çalışmaya devam eder; ödeme düğmesi tespiti de Türkçe ifadeleri tanır.

### Güvenlik

- **MCP `open_app(args)` ile onaysız komut çalıştırma açığı kapatıldı (0.5.4'te vardı).** `open_app` artık yalnız kurulu masaüstü girdilerini açar; kabuk, yorumlayıcı ve uçbirim başlatılamaz, çalıştırılabilir belge türleri reddedilir. Kök sahipli sistem girdileri onaysız çalışır; kullanıcının yazabildiği girdiler panel onayı ister ve özel bir kopyadan, kopyanın özeti yeniden denetlenerek başlatılır. Kod barındırma uygulamaları onay ister.
- **Ajanın kendi uçbirimine girdi yasağı.** Ajan kendi çalıştığı uçbirime girdi gönderemez. Gömülü uçbirimler süreç ağacıyla bulunur; uçbirime her Enter onay ister, yapıştırma tuşları ve menüden yapıştırma onaya bağlıdır.
- **Onay kanalı.** Onay kararı yalnız doğrulanmış panel soketinden kabul edilir. Dosya yazabilen bir süreç sahte izin üretemez; yanıt dosyaları ret sayılır. Onaydan sonra hedef (pencere, başlık, geometri, görüntü) yeniden doğrulanır; bekleyen onay varken girdi araçları reddedilir.
- **bwrap yalıtımı.** Arka plandaki uygulamalar `bubblewrap` içinde çalışır: salt okunur kök, ayrı PID/kullanıcı alanı, boş `/tmp`, geçici HOME, yalnız uygulamanın kendi oturum kopyası. Gizli yollar (ssh/gpg anahtarları, anahtarlıklar, gerçek tarayıcı profilleri, bulut ve ajan kimlik bilgileri, Deskhand yapılandırması) maskelenir; ses sunucusuna erişim yoktur.
- **Erişilebilirlik soketi koruması.** Deskhand, uygulamalardan önce erişilebilirlik dizinini kendisi oluşturur; bağlama kapalı başarısız olur (fail-closed), dizin kimliği denetlenir. Başka bir sürecin araya girmesi engellenir.
- **Sistem parola istemleri.** polkit, KWallet, askpass ve portal pencerelerinde her tıklama türü insan onayı ister; gözetimsiz kipte ret. Parola alanının değeri hiçbir yolda okunmaz.
- **Ödeme sayfası.** Ödeme/sipariş sayfasında para düğmesi (ya da okunamayan hedef) tıklaması ile Enter/boşluk onay ister; sayfa tespiti pencere başlığına ek olarak belge başlığından da yapılır.
- **Kart numarası tespiti.** Kart alanına (ad, etiket, `cc-number`, cvc/cvv, son kullanma vb.) ya da 13-19 haneli, Luhn denetiminden geçen numaraya yazmak (yazı, yapıştırma, değer yazma) onay ister; ayırıcılı numaralar da yakalanır.
- Ayrıca: yasak/erişim seviyesi listeleri panel tarafından korunur, çalışma dizini 0700 yaratılır, pano sahibi için süre ve boyut sınırları, kabuğa duyarlı riskli komut denetimi, ajanın kendi istemcisine karşı koruma.

### Davranış değişiklikleri

- **Panel kapalıyken yasak listesi ve seviye listeleri elle düzenlenirse komutlar durur.** Dosya panelin işaretiyle uyuşmuyorsa komutlar güvenli tarafta reddedilir; paneli açıp listeyi oradan düzenleyin.
- **Onay kapsamı panelde yetkilidir.** Panel kapalıysa ya da doğrulanamıyorsa kapsam **hepsi** sayılır.
- **`ref` başlık kuralı yalnız OCR ref'lerinde.** Ağaç ve web ref'leri kimlikleriyle yeniden doğrulandığı için başlığı sürekli değişen sayfalar artık çalışır; OCR ref'inde pencere başlığı değişmişse reddedilir.
- **KWin türünde Firefox ve Chromium/Electron XWayland ile açılır.** Gecko tarayıcıları yalnız oturumda XWayland varsa bu şekilde başlatılır; GTK4 ögeleri etkin sayılır. Pencere sorguları KWin'in geçici liste hatalarına dayanıklıdır.
- Girdi araçlarının sonuç biçimi değişti (`effect`, `sent`, `next` alanları); `observe` ve `batch` yalnız kısa metin döndürür.
- `wait_for` ön planda pencereyi öne getirmez.

### Kurulum

- Yeni gerekli bağımlılıklar: **`bubblewrap`** (arka plan uygulama yalıtımı; yoksa arka planda uygulama açılmaz), **`libei`** ve **`libxkbcommon`** (GPU'lu KWin arka plan masaüstünün girdi yardımcısı; yoksa Xvfb'ye düşülür).
- `make` artık **üç yardımcı** derler: klavye etkinliği (`deskhand-etkinlik`), ekran görüntüsü (`deskhand-goruntu`) ve KWin girdi (`deskhand-eis`). C derleyicisi, `make`, `pkg-config` gerekir.
- `install.sh` yeni bağımlılıkları denetler, eksikse paket komutunu yazar, yardımcıları adlarıyla derler ve eksiklikleri uyarı olarak bildirir.
- Önerilen: `sudo pacman -S --needed bubblewrap libei libxkbcommon`
- CI (GitHub Actions) eklendi; KWin gerektiren testler uygun olmayan ortamda atlanır.

### Bilinen sınırlar

- Kart numarası tek tek tuşla ya da ayrı alanlara parça parça yazılırsa, ya da panodan yapıştırılıp kart alanı olarak işaretlenmemiş bir alana girilirse yakalanamaz.
- Panel kapalıyken ayar dosyası ile panelin işareti dosyası birlikte (tutarlı biçimde) sahtelenirse, panelin bir sonraki açılışında "yalnız kartla ödeme" kapsamı geçirilebilir.
- İngilizce çeviri eksik: bu değişiklik notları ve `README.tr.md`'deki yeni bölüm yalnız Türkçedir.
- Yalnız KDE Plasma (Wayland) desteklenir.
- Kabuğu olan bir ajan için sandbox değildir: aynı kullanıcıyla keyfi kod çalıştırabilen bir süreç paneli öldürüp yerine geçebilir (bkz. tehdit modeli).
- Web ögelerinde başka ögenin üstünü örten öge (modal, yapışkan başlık) ağaçtan ayırt edilemez; gerçek Wayland ekranında koordinat çerçevesi doğrulaması elle denenmelidir.
