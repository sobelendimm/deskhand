# Değişiklik notları (Türkçe)

*Bu dosya İngilizce belgelerden bağımsız tutulan Türkçe özettir; İngilizce çeviri henüz yapılmadı.*

## Yayımlanmamış

- **CLI sürtünmeleri giderildi.** Görünmez masaüstünde gerçek işte (Firefox ile bir web sayfasına gitme) çıkan altı engel:
  - `deskhand --background open firefox` masaüstü kapalıysa artık kendiliğinden başlatır ("görünmez masaüstü başlatıldı"),
    MCP `open_app` ile aynı kafes/kilit/görev kipi kapılarından geçer; oturum kopyası hazırlanmadan ÖNCE denetlenir.
  - `deskhand open firefox https://…` / `--url ADRES`: oturum kopyalı tarayıcıyı adresle açar (yalnız http/https; Chromium
    ailesi dahil; `file:`, `about:`, `javascript:`, `data:` reddedilir). Görev kipi kuralları CLI'de de geçerlidir.
  - `deskhand screenshot` kimliksiz çalışır (`--background`: tüm görünmez masaüstü, değilse etkin pencere; gerçek ekran
    kilitliyse 17) ve `--out DOSYA` alır (klasör yoksa oluşturulur); `--width N` küçültülmüş görüntü verir.
  - `deskhand windows` desensiz tüm pencereleri listeler.
  - Yeni `deskhand goto KİMLİK ADRES`: tarayıcıda adres çubuğuyla (ctrl+l → adres → Return) adrese gider; başlık kilidi,
    hassas sayfa onayı ve insan doğrulaması kapısı mevcut `key`/`type` yollarından aynen geçer; yalnız http/https.
  - `deskhand --help` alt komutları ve kısa açıklamalarını tablo olarak listeler.

## 0.7.0 (22 Kasım 2026)

- **Panelde "Görev" sekmesi: görev ver, o yapsın.** Yazdığınız işi (ör. "şu sitede şunu bul, bana özetle") panel kendi
  ajanına (`claude -p`) görünmez masaüstünde yaptırır; adımlar canlı akar, bitince sonuç ve indirilen dosyalar gösterilir.
  Ajan yalnız Deskhand'in arka plan araçlarını kullanır, sizin ekranınıza dokunmaz.
- **Güvenlik: görev kipi.** Görev ajanı güvenilmeyen web içeriği okuduğu için kısıtlıdır: yalnız tarayıcı açabilir
  (uçbirim, dosya yöneticisi, düzenleyici açamaz); Belgeler/Masaüstü gibi klasörleri görmez, indirmeler göreve özel
  klasöre iner; Firefox'ta `file://`, `about:logins`/`about:config` ilkeyle kapalı, indirilen dosya dış uygulamayla
  açılamaz; kayıtlı parolalar ve uzantılar kopyalanmaz, çerezler yalnız izin verdiğiniz siteler için gelir; tarayıcı
  dışında beliren pencere kapatılır. Görünmez masaüstü başka bir iş için açıksa görev ona dokunmaz: kapatıp başlatmak
  için onayınızı ister; görev sürerken başka istemciler görev masaüstüne bağlanamaz. İzinli sitelerde ajanın sizin
  adınıza işlem yapabileceği başlatmadan önce açıkça gösterilir.
- **İnsan doğrulaması (CAPTCHA) devri.** CAPTCHA çözülmez ve atlatılmaz: algılanınca ajanın girdisi reddedilir (kod 18)
  ve `request_human` ile size bildirim + panel diyaloğu gelir (Devral / Bitti / Vazgeç); siz çözünce ajan devam eder.
  Sayfa okunamıyorsa (erişilebilirlik kapalı) tek başına Enter/Boşluk reddedilir ve ileti "CAPTCHA olmayabilir,
  tarayıcıyı yeniden başlatın" der.
- **Testler 4 kat hızlı.** `tools/test_kos.py` takımları paralel koşar (tam koşu ~13 dk → ~3 dk); gerçek sistemi
  ölçen takımlar sonda tek başına koşar.

- **Güvenlik: arka plan uygulamaları ev dizininde yalnız beyaz listeyi görür.** Görünmez masaüstünde açılan
  uygulamanın ev dizini artık boştur; gerçek evden yalnız görünüm ayarları (KDE/GTK/Qt teması, renkler, yazı tipleri,
  simgeler, imleç, XDG klasör adları, dosya ilişkilendirmeleri, kullanıcı `.desktop` ve Flatpak kurulumu) salt okunur
  görünür. Eskiden ev dizini geçici katmanla okunur durumdaydı ve yalnız bilinen sır yolları (kara liste) örtülüyordu:
  listede olmayan bir uygulamanın jetonu (ör. `~/.config/<uygulama>/token`) okunabiliyordu. Belgeler, İndirilenler gibi
  veri klasörleri eskisi gibi yazılabilir ve kalıcıdır; ev köküne yazılanlar oturumla atılır. Bir uygulamanın kendi
  ayarı gerekiyorsa `oturum.toml`'da uygulama başına `ev = [...]` (varsayılan yok). Ölçüm: KWrite, Dolphin, Konsole,
  Gwenview, Firefox, Chromium, zenity, Meld ve Electron açılıyor; tema ve OCR doğruluğu değişmedi.
- **Güvenlik: ev beyaz listesi sertleştirildi (bağımsız inceleme).** Sembolik bağ olan beyaz liste/`ev` girdisinin
  kaynağı bir XDG veri klasörüne, ev dışında `/tmp`, `/run/user/UID` ya da RUNTIME_DIR'e giderse reddedilir; beyaz liste
  bağları ev içinde yalnız beyaz listedeki bir girdiye çıkabilir; ikinci hat (sır örtüleri) kaynak→hedef eşlemesiyle de
  örter; kaynak `O_PATH` fd'siyle açılıp bwrap `--ro-bind-fd` ile bağlanır (yol yarışı kapandı). Politika `ev`
  girdisinde glob, kısa gizli girdi ve `.config`/`.local`/`.cache`… merkezleri reddedilir. Flatpak `overrides` ve GTK
  yer imleri/sunucuları örtülür. Paket bağları veri klasörlerinden sonra gelir, `.git` kökü reddedilir. Ad alanındaki
  `/tmp` ve ev tmpfs'i min(2 GiB, kafes/4) ile sınırlı. Ev altında görünmeyen bir program başlatılırsa zaman aşımı
  beklenmeden `oturum.toml` `ev = [...]` ipuçlu anlaşılır hata verilir.

## 0.6.1 (22 Kasım 2026)

- **Chromium ailesi görünmez masaüstünde açılıyor.** profile-sync-daemon kullanan sistemlerde Chromium/Vivaldi/Electron
  arka planda açılışta çöküyordu; boşta kalan profil bağı artık ad alanına özel boş bir dizine çıkıyor (gerçek profil
  yine görünmez). İndirmeler gerçek indirme klasörü kuralına uyar.
- **Güvenlik: tarayıcı profil yedekleri gizlendi.** profile-sync-daemon'un Chromium/Brave disk kopyaları
  (`*-back-ovfs`, `*-backup`) görünmez masaüstündeki uygulamalardan gizlenir (0.5.4'ten beri açıktı).
- **Hassas alan değerleri maskelenir.** `observe`/`read_text` giriş alanlarının değerini döndürürken parola, PIN,
  tek kullanımlık kod, doğrulama kodu, kart alanları `***` olarak gelir.
- **`type_text` aynı adlı ögelerde** `role`/`nth` alır; ad tam eşleşip tek yazılabilir alan varsa onu seçer.
- **KWrite/Kate metni ağaçtan okunur** (`read_text(source="tree")`).
- **Gerçek ekran kilidi.** `DESKHAND_GERCEK_EKRAN=kapali` (testler bunu kendiliğinden ayarlar) iken kullanıcının
  gerçek ekranına giden her yan etki en alt katmanda reddedilir (çıkış kodu 17); `salt-okuma` değeri yalnız yan
  etkileri kapatır.
- `doctor` ekransız ortamda çökme kaydı bırakmaz; panel soket yolu çok uzunsa açık ileti verir.


- **`listen` aracı (dinleme).** Görünmez masaüstündeki uygulamaların SESİ yerel Whisper ile yazıya dökülür (video, sesli mesaj). Her masaüstü isterse kendi özel, donanımsız ses sunucusunu alır (`manage_desktop(start, audio=true)` ya da ilk `listen`); uygulamalar yalnız onu görür, ses kullanıcının hoparlörüne gitmez, mikrofon yoktur. Kayıt bellekte tutulur, metin günlüğe yazılmaz, kullanıcının kendi ekran sesi dinlenmez. `doctor` "Dinleme" satırı eklendi; ayarlar `[dinleme]`.
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
