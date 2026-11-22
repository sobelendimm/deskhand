# Değişiklik notları (Türkçe)

*Bu dosya İngilizce belgelerden bağımsız tutulan Türkçe özettir; İngilizce çeviri henüz yapılmadı.*

## 0.9.0 (22 Kasım 2026)

- **Düzeltme (kritik): görünmez masaüstünde (KWin) Firefox'a yazılan `#`, `$`, `€` sessizce kayboluyordu** ("a#b" →
  "ab", araç yine "yazıldı" diyordu). tr düzeninde bu karakterler X11'e iletilemeyen "inet" tuşlarında da durduğu için o
  tuşlar seçiliyordu; artık XWayland'in iletebildiği tuş (AltGr+3/4/E) seçilir, yalnız böyle bir tuştaki karakter
  panodan yapıştırılır. Yardımcı yeniden derlenmeli: `make -C deskhand/yardimci deskhand-eis`.
- **Güvenlik: güç/uyku/kilit tuşları onaysız gidiyordu.** Değiştiricisiz tek başına `power`, `sleep`, `wakeup`,
  `coffee`/ekran koruyucu, `suspend`, hazırda bekletme, oturum kapatma tuşları (dotool adları, `x:XF86PowerOff` gibi
  XF86 adları/kodları, `k:116/142/143/152/205`) ve KDE'nin onaysız kapatma kısayolları `ctrl+alt+shift+delete/pageup/
  pagedown` artık `tus`/`bas`/`press_key`'de insan onayı ister.
- **Güvenlik: yazıdaki denetim karakterleri tuş olarak gidiyordu.** `\n` ve `\t` dışındaki C0/C1 ve DEL karakterleri
  (`\x08` geri silme, `\x1b` Esc, `\x7f`…) yazıda (iki arka uç, yapıştırma yolu, erişilebilirlik değer yazma) hiçbir
  şey gönderilmeden 1 ile reddedilir; ileti `press_key`'e yönlendirir.
- **Güvenlik: `--secret` yazı sızıntıları kapatıldı.** Dizi/akış adımının gizli satırı stdout'a, günlüğe ve hata
  iletisine yazılmaz (yalnız komut adı + `***`); gizli yazıda düzende olmayan karakter değiştirilmez (Café → Cafe yok),
  yazmadan 1 ile durur ve ileti yalnız konum/uzunluk verir; dotool'un "impossible character" uyarısı merkez günlüğünde
  ve gizli gönderimin iletisinde maskelenir; günlükte parça uzunlukları (6, 6, 4) yerine yalnız toplam uzunluk kalır;
  gizli yapıştırmadan sonra eski pano geri yüklenemezse (ör. çok büyük) pano temizlenir.
- **Güvenlik: okunamayan tarayıcı sayfasında Enter kuralı yeniden tasarlandı.** Eskiden yalnız tek başına Boşluk/Enter
  ya da Tab'dan sonra gelen girdi reddediliyordu; `['a','enter']` ya da `abc\n` bilinmeyen odağa gidiyordu. Artık
  dizinin herhangi yerinde Enter/Boşluk varsa ucuz bir odak sorgusu yapılır: odak belge dışındaysa (adres çubuğu, dosya
  seçici gibi tarayıcı iletişim kutuları) ya da bir yazı alanındaysa izin, sayfadaki başka bir ögedeyse ya da
  bilinmiyorsa ret; ileti ne yapılacağını söyler (alana tıkla, `goto`, `ac --arka`). MCP `type_text` kapısı
  `submit=True`'nun Enter'ını da görür; `goto` adresi ve Enter'ı tek yazı eylemi olarak gönderir.
- **Güvenlik: gerçek ekran kilidi görünmez masaüstündeki ödeme sayfasını kilitliyordu.** `DESKHAND_GERCEK_EKRAN=kapali`
  iken başlığında "Ödeme" geçen sayfada her tıklama/Enter/`goto` reddediliyordu. Onayı panelde göstermek gerçek ekrana
  girdi değil: görünmez masaüstü hedefinde onay istenir, kullanıcının ekranında 17 aynen; ileti tetikleyen kalıbı söyler.
  `goto` ile çıkış, odak adres çubuğunda doğrulanırsa onaysız.
- **Güvenlik: web yolunda alan değerleri maskelenmiyordu.** Tarayıcı sayfası okunurken tek kullanımlık kod, kart
  numarası, CVC, PIN ve parola alanlarının değeri dönüyordu; artık masaüstü yoluyla aynı kural (ad, açıklama, `id`/
  `placeholder`/`text-input-type`) → `***`. Sınır: Firefox `autocomplete` belirtecini erişilebilirlik ağacına vermez.
- **Güvenlik: CLI okuma komutları yasak pencere listesine uyuyor.** `foto`, `metin`, `bekle`, `simge-bul`,
  `simge-kaydet`, `renk-bul`: hedef yasaksa 10, görüntüye düşen diğer yasak pencereler siyah (MCP ile aynı).
- **Yeni: CLI otomatik başlık kilidi.** `yaz`, `tus`, `tikla`, `dizi`, `kaydir` pencere KİMLİĞİYLE ve `-b` olmadan
  verilirse şimdiki tam başlığa kilitlenir; komut sürerken sekme/sayfa değişirse 4 ile durur (ileti: `-b` ile esnek desen
  ya da `--no-title-lock`).
- **MCP: sonuç sözleşmesi.** Beklenmeyen istisna da yapılandırılmış hata döner (`[9]`, `sent`, `next`; girdi gitmişse
  `maybe_partial`); `get_status`, `choose_desktop`, `manage_desktop`, `screenshot`, `read_text`, `listen`, `find` da
  yapılandırılmış hata döndürür; iletilerde CLI seçenekleri (`--region`) yerine MCP parametre adları (`region`).
- **Düzeltme: bazı uygulamalar tarayıcı sanılıyordu** (zenity, hedgewars, knowledge-base, citizen, operator,
  chromatic): tarayıcı adı artık sınıfın tam bir parçası olmalı.
- **Düzeltme: insan önceliği.** Kendi girdimizin pencere bitiminden sonraki 0,5 sn'de gelen tek ve kısa yansıması
  kullanıcı sayılmaz (gerçek tuş basışı iki olay üretir, yine keser); etkinlik yardımcısı kapanışta beklenir (zombi/fd
  sızıntısı yok); öncelik bekçisi kafesin geçici okunamamasını "boş" sanmaz.
- **Düzeltme: KDE.** Kapalı monitör ekran alanını büyütmez; klavye düzeni önbelleği kxkbrc değişince yenilenir;
  ext-idle-notify v1'e düşülürse klavye izleyicisi yok sayılır (yalnız fare izlenir).
- **Düzeltme: arka plan Firefox'unda indirilenler kayboluyordu.** Kopyanın kendi `XDG_CONFIG_HOME`'unda
  `user-dirs.dirs` yoktu: GTK "Masaüstü" var olmayan `~/Desktop`'u gösteriyor, İndirilenler çözülmüyor, Firefox ad
  alanındaki geçici `~/Downloads`'a indiriyordu (tarayıcı kapanınca siliniyordu). Artık kopyaya kullanıcının
  `user-dirs.dirs` / `user-dirs.locale` / `mimeapps.list` ve GTK/fontconfig görünümü (0600) alınır; user.js indirme
  klasörünü (`browser.download.dir`, `folderList=2`) XDG İndirilenler'e sabitler; görev kipinde görevin indirme
  klasörü. Flatpak Electron kopyasında da aynı.
- **Düzeltme: oturum çerezleri arka plan kopyasına gerçekten taşınıyor.** recovery.jsonlz4'ten eklenen çerezler
  `expiry=0` ile yazılıyordu (Firefox açılışta "süresi geçmiş" diye atıyordu) ve bölümlenmiş/kapsayıcı bağlamları
  (`partitionKey`, `userContextId`) kayboluyordu. Artık bitiş = şimdi + 1 gün (birim mevcut satırlardan), bağlam
  Firefox sonek biçiminde; çevrilemeyen bağlam (gizli pencere) atlanır.
- Kopya kapanış uyarısı yalnız kimlik sağlayıcılarını (Google/Microsoft/e-Devlet) gösterir ve "asıl profil
  değiştirilmedi" der; diğer sitelerin değişen çerezleri yalnız günlükte.
- **Masaüstü sahipliği komut satırında da.** `desktop start` ve `open --background`'ın kendiliğinden açtığı masaüstü,
  çağıranın ata zincirinde claude varsa o Claude oturumuna yazılır: başka Claude oturumları ona erişemez/kapatamaz
  (14); sahibi ölen adlı masaüstü kendiliğinden kapatılır (sızan masaüstleri 3'lük sınırı yemesin). MCP otomatik
  bağlanırken sahipsiz ama içinde uygulama çalışan varsayılan masaüstünü dolu sayar ve `oturum-N` açar.
  `desktop stop` adlı masaüstünün dizinini de siler.
- **`--desktop-name` her yerde.** Komuttan önce herhangi bir konumda (`--background --desktop-name X windows`,
  `-b DESEN --desktop-name X …`) ve komuttan sonra (`windows --desktop-name X`); `desktop … --desktop-name X`
  (`--name` takma adı). `--desktop-name` / `DESKHAND_MASAUSTU` artık kendiliğinden arka plan demek (`--background`
  olmadan kullanıcının gerçek pencereleri listeleniyordu). Kapalı/yanlış adlı masaüstü: "'X' adlı görünmez masaüstü
  açık değil (açık olanlar: …)". `DESKHAND_GERCEK_EKRAN=kapali` iken gerçek oturumun `windows` / `a11y` listesi 17.
- `desktop` kullanım hatasında çıkış kodu 1 (argparse'ın 2'si Deskhand'de "nokta pencere dışında" demek); açık
  masaüstü farklı ölçekle istenince çıkış 1 + JSON `olcek_uyusmaz`.
- `scroll KİMLİK X Y [yön] [ADIM]` biçimi ve `--at x,y` takma adı; tek sayısal ikinci argümanda ipuçlu hata.
  **Varsayılan kaydırma adımı 5 → 3** (MCP `scroll(amount)` ile aynı).
- Arka plan tarayıcı önbelleği 64 MB ile sınırlı (Firefox user.js, Chromium `--disk-cache-size`): kopyalar
  RUNTIME_DIR'ı (bellek) doldurmasın; canlı kopyalar sınırı aşınca uyarı. Kopya dosyaları 0600.
- Yarıda kalmış `insan-dogrulama.json.<pid>.tmp` dosyaları açılış temizliğinde silinir.

## 0.8.2 (22 Kasım 2026)

- **Yeni: 2× (HiDPI) görünmez masaüstü — keskin ekran görüntüsü.** Görünmez masaüstünden alınan görüntüler ürün
  görsellerinde küçültülünce/büyütülünce piksellere ayrılıyordu (1× masaüstünde yazı 11-12 px). Artık
  `deskhand desktop start --scale 2` (MCP: `manage_desktop(action="start", scale=2)`; `--desktop-name` ile de) aynı
  mantıksal düzeni (pencere yerleşimi, tıklama koordinatları) iki kat pikselle çizer: `deskhand screenshot --out`
  tam çözünürlüğü kaydeder (1280x800 masaüstünde 2560x1600), `--width` küçültür; MCP `screenshot` aynı boyutta
  (varsayılan `max_edge` 1280) ama tam kareden küçültüldüğü için daha keskin döner, `shot_id` tıklamaları doğru
  yere gider. Ölçülen: 14px metnin mürekkep yüksekliği 15 → 28 px; Firefox ve Chromium `devicePixelRatio` 2
  (GDK_SCALE / `--force-device-scale-factor`), Qt uygulamaları kendiliğinden 2×. `desktop status`/`desktop list`,
  `get_status` ve `manage_desktop` çıktısında `scale` görünür. Varsayılan ölçek 1 (davranış değişmedi). Yalnız KWin
  türü: Xvfb'de açık iletiyle reddedilir. Sınır: OCR ve `observe` mantıksal (2×'ten küçültülmüş) görüntüyü okur;
  ölçek değişikliği için masaüstü kapatılıp açılır; XWayland'deki GTK/Chromium dışı X11 uygulamaları küçük görünebilir.

## 0.8.1 (22 Kasım 2026)

- **Düzeltme: yazı, kullanıcı dokunmadığı hâlde "kullanıcı klavye/fare kullandı" ile kesiliyordu.** Ön planda
  (kullanıcının ekranı) `type_text` ikinci kelime sınırında (ör. "Satın alımdan vazgeçtim." → 12/24) duruyordu.
  Neden: her komut yeni bir etkinlik izleyicisi açar; girdi merkezi hazır olduğundan yazı 50 ms'lik boşta süresi
  dolmadan başlar ve harfler arası boşluk 50 ms'den kısa olduğundan "boşta" bildirimi hiç gelmez; bu durum 0,2 sn sonra
  koşulsuz insan sayılıyordu. Artık kesintisiz etkinlik, Deskhand'in kendi girdisiyle örtülüyorsa insan sayılmaz;
  kelime sınırında kısa bir yerleşme beklemesi (en çok 0,3 sn) kendi girdimizin gecikmeli yansımasını ayırır, kendi
  girdi payı 0,12 → 0,25 sn; ilk girdiden önce izleyicinin ilk "boşta" bildirimi beklenir (en çok ~0,2 sn). Kullanıcı
  gerçekten yazarsa (ya da yazmayı sürdürürse) yazı YİNE 12 ile kesilir.
- **Düzeltme: Steam istemcisinde (CEF/Chromium, XWayland) fare tekerleği kaydırması etkisizdi** (`scroll`:
  no_change). Tek olay olarak giden "wheel N" bu uygulamalarda tümüyle yutuluyordu; çentikler artık ayrı olaylar
  olarak gider (en çok ilk çentik kaybolur; tek çentikte End/PageDown tuşu daha güvenilir).
- **Düzeltme: kapanan arka plan tarayıcılarının oturum kopyaları geçici alanı (/run/user, tmpfs) dolduruyordu.**
  Kopya (225-514 MB) masaüstü kapanana dek kalıyordu; alan dolunca `key`/`type` OSError 28 ile çöküyordu. Artık her
  kopyanın sahibi (tarayıcı süreci + başlangıç zamanı) kaydedilir, tarayıcı bitince kopya bir bekçi tarafından silinir;
  yeni kopya açılırken, masaüstü başlarken ve `deskhand doctor`'da sahipsiz kopyalar süpürülür (canlı ya da başka
  masaüstünün kullandığı kopya ASLA silinmez); toplam 3 kopya / 1,5 GB aşılınca en eski sahipsizler silinir.
  `deskhand doctor` "Oturum kopyaları: N adet, X MB" satırını gösterir; geçici alan doluysa komutlar çökmek yerine
  "geçici alan dolu … deskhand doctor" ile durur (9).

## 0.8.0 (22 Kasım 2026)

- **Çoklu görünmez masaüstü (çekirdek).** Aynı anda birden çok görünmez masaüstü açılabilir (KWin türü; en çok
  `[masaustu] azami = 3`, 1..6): her Claude/MCP oturumu kendi masaüstüne kendiliğinden bağlanır (ilk oturum
  varsayılanı, sonrakiler `oturum-1`, `oturum-2`…; `deskhand mcp --desktop-name AD` ile sabitlenebilir) ve başka
  oturumun masaüstüne erişemez (Dur 14; aynı oturumun komut satırı erişir). CLI: genel `--desktop-name AD`,
  `deskhand desktop list`, `desktop start|stop|status --name AD`. Kendiliğinden açılan masaüstü oturum bitince
  (~2 dk sonra) kapanır; varsayılan ve adlı masaüstleri açık kalır. Varsayılan masaüstünün dosyaları eskisiyle aynı
  yerde (geçiş yok). Panel şimdilik yalnız varsayılan masaüstünü gösterir.
- **Düzeltme: bir masaüstünü durdurmak başkasının tarayıcı kopyalarını silmez.** Oturum kopyaları ve Flatpak
  örnek kaydı masaüstü başına ayrıldı; `dinle` (listen) yalnız bağlı olduğu masaüstünün sesini kaydeder.
- **Bekleyen onay yalnız kendi masaüstünü kilitler** (bir masaüstündeki CAPTCHA devri ötekini durdurmaz).
- **Kendi terminalinden çalışan sen her masaüstüne erişirsin.** Ata zincirinde Claude olmayan `deskhand`/`ekran
  --background` çağrısı (terminal, KDE kısayolu) panel gibi izinlidir; başka bir Claude oturumunun komutları başkasının
  masaüstüne erişemez (Dur 14). Bu ajanlar arası bir düzen kuralıdır, güvenlik sınırı değildir.
- **Görev kipi çoklu masaüstüyle uyumlu.** Panel görevi her zaman varsayılan masaüstünde yürütür (sohbetteki Claude
  varsayılanı tutuyor olsa bile); görev sürerken başka oturumlar ona erişemez, görev bitince eski sahibine döner.
- **Panel: başka masaüstündeki insan doğrulaması da çözülebilir.** Onay penceresi masaüstünün adını gösterir; "Devral"
  Arka plan sekmesini o masaüstüne çevirir, iş bitince varsayılana döner.
- Sağlamlaştırma: MCP sunucusu Claude oturumu kapanıp sahipsiz kalınca masaüstüne bağlanmaz; sahiplik kaydı PID ad
  alanını taşır (başka ad alanındaki kayıt "boş" sayılmaz); Flatpak örneği yalnız kesin PID eşleşmesiyle kaydedilir
  (iki masaüstü aynı Flatpak uygulamasını açınca biri ötekinin örneğini kapatmaz).

## 0.7.1 (22 Kasım 2026)

- **Devral klavyesi düzeltildi.** Panelde Devral ile yazarken Türkçe Q klavyede "i" harfi "ı" çıkıyordu (parola girişini bozuyordu); yazılan karakterler artık karakter olarak gider, her klavye düzeninde doğru çıkar (i, ı, İ, ş, ğ, @, nokta).

- **Hesap oturumları: görünmez masaüstünde girişli Microsoft / Google / e-Devlet (isteğe bağlı).** Firefox kopyası
  güvenlik için merkezi giriş (Microsoft, Google) ve devlet sitelerinin çerezlerini süzdüğünden Excel Online gibi
  sayfalar her seferinde şifre istiyordu. Panel → Ayarlar → **Hesap oturumları**'ndan tek ana anahtarla ("Giriş
  yaptığım hesaplar görünmez masaüstünde de açık olsun — banka ve ödeme siteleri hariç") ya da tek tek
  (Microsoft, Google, e-Devlet ve devlet siteleri) izin verilebilir: o hesabın çerezleri, kayıtlı girişleri (parolayı
  Firefox doldurur) ve deposu kopyaya girer. Varsayılan **kapalı**; açarken onay sorulur ve uyarı gösterilir
  ("arka plandaki tarayıcı bu hesabın e-postalarına ve dosyalarına erişebilir"). Yalnız panelden açılır: ayar
  dosyasına elle ya da ajanla yazılan değer geçmez, panel geri alır; CLI/MCP değeri yalnız panelden alır. Banka ve
  ödeme siteleri hiçbir ayarla açılmaz; görev kipinde izin hiç uygulanmaz. `deskhand doctor` ve `open` çıktısı
  hangi hesabın aktarıldığını ya da neden süzüldüğünü söyler ("kimlik oturumları: Microsoft aktarıldı (5 çerez,
  1 kayıtlı giriş)").
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
