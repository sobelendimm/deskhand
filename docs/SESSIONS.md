# Deskhand — Oturum köprüsü (oturum aktarımı araştırması)

> **English summary.** Research notes behind Deskhand's "session bridge": how apps running on the invisible second
> desktop (Xvfb + openbox, same Linux user, same `$HOME`, private D-Bus session) can reuse the user's existing
> account sessions without logging in again. It covers per-app session storage and single-instance behaviour,
> Chromium/Electron cookie encryption, safe snapshotting of Firefox profiles, refresh-token rotation risks, how to
> detect that an app is running in the user's session, and the default per-app policy
> (`deskhand/data/oturum.toml`). Source code refers to sections by number (§2, §3, §3.2, §4, §6, §8). The text is in
> Turkish, like the project's code comments.

Kapsam: görünmez ikinci masaüstünde (Xvfb + openbox, aynı Linux kullanıcısı, aynı `$HOME`, ÖZEL D-Bus oturumu)
çalışan uygulamaların kullanıcının mevcut hesap oturumlarını yeniden giriş yapmadan kullanabilmesi.

Yöntem notu: Araştırmada gerçek profillerde yalnız dosya/dizin ADLARI listelendi; çerez/parola/jeton içeriği
okunmadı. `busctl --user tree/list` yalnız nesne yollarını gösterir (içerik yok). Kaynak kodu okuma, `curl`/WebFetch
ile yapıldı. Doğrulanamayan her şey **DOĞRULANMADI** diye işaretli. Belirli bir uygulamanın yolları genel bilgidir;
kurulum ve sürüme göre değişebilir.

---

## 0. Ortam notu

Bulgular Arch/CachyOS + KDE Plasma 6 üzerinde doğrulandı. Başka dağıtımlarda ya da masaüstü ortamlarında
dosya yolları, anahtarlık hizmeti (KWallet / GNOME Keyring) ve Flatpak izinleri farklı olabilir.

Kısa genel hatırlatmalar:
- Profil dizinleri sembolik bağ olabilir (ör. `profile-sync-daemon` ile tmpfs'e taşınmış profiller); Deskhand
  `realpath` çözmeli ve diskteki bayat yedek klasörlerini (`*-backup` vb.) kaynak olarak KULLANMAMALI.
- Firefox profil konumu `~/.mozilla/firefox` ya da (XDG düzeninde) `~/.config/mozilla/firefox` olabilir; iki konum
  da taranmalı. Firefox 147 XDG dizinlerini destekledi ([OMG Ubuntu](https://www.omgubuntu.co.uk/2026/01/firefox-147-released),
  [Phoronix](https://phoronix.com/news/Firefox-147-Beta)); kaynaklar "yeni kurulumlar" diyor, eski profillerin
  taşınıp taşınmadığı resmi notlarda **DOĞRULANMADI**
  (<https://www.firefox.com/en-US/firefox/147.0/releasenotes/>).
- `profiles.ini` tuzağı: gerçek varsayılan profil `[Install*]` bölümündeki `Default=` anahtarıdır; `[Profile*]`
  bölümündeki `Default=1` başka bir profile işaret edebilir.
- Firefox profilinde `signedInUser.json` (Firefox Hesabı/Sync oturumu) olabilir; kopyada kalırsa arka plan Firefox'u
  AYNI Sync cihazı gibi davranır (bkz. §3.6). Profilde `logins.json` ile birlikte `logins.db` de görülebilir;
  `logins.db`'nin rolü **DOĞRULANMADI** → ikisini de (site süzgecinden geçirerek) kopyala.
- Flatpak Electron uygulamalarının çoğunda (Discord, Spotify, Ferdium) `org.freedesktop.secrets` / `kwalletd`
  `talk` izni yoktur → bunlar anahtarlığı doğrudan kullanamaz ve oturumları anahtarlık köprüsü OLMADAN
  kopyalanabilir (tam şifreleme modu **DOĞRULANMADI**: portal Secret mi, basic mi — çalıştırınca
  `safeStorage.getSelectedStorageBackend()` ile görülür). VS Code Flatpak'ında bu izinler vardır.
- KDE cüzdan topolojisi (Plasma 6, kwallet 6.x): `org.freedesktop.secrets`, `org.kde.ksecretd`,
  `org.kde.secretservicecompat` ve `org.freedesktop.impl.portal.desktop.kwallet` adlarını tek süreç **ksecretd**
  tutar; `org.kde.kwalletd6` yalnız "activatable"dır. KWallet deposunun resmi README'si: "kwalletd exposes the KWallet
  API and proxies it to Secret Service"; "ksecretd exposes the Secret Service DBus API"
  ([README](https://invent.kde.org/frameworks/kwallet/-/blob/master/README.md)). kwalletd'nin `main.cpp`'si: "A KWallet
  compatibility service, wrapping upon Secret Service"
  ([kaynak](https://invent.kde.org/frameworks/kwallet/-/raw/master/src/runtime/kwalletd/main.cpp)). Yani eski
  `org.kde.kwalletd6` API'si D-Bus ile etkinleştirilen ayrı bir sarmalayıcı süreçtir; asıl depo Secret Service
  tarafındadır.
- Plasma ortamı: `XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6` (Chromium'un otomatik arka uç seçimi buna bağlı, §2).

---

## 1. Uygulama tablosu

Politika sözlüğü: **paylas** = uygulama kullanıcı oturumunda KAPALIYKEN doğrudan aynı dosyalarla (kilit/koruma
altında) · **kopya** = anlık, tutarlı, tek yönlü kopya ile eşzamanlı · **bekle** = eşzamanlı ASLA; kullanıcı
kapatana dek bekle / ön plana sor · **kapali** = hiç çalıştırma.

### 1.1 Özet tablo

| Uygulama | Oturum nerede | Tek örnek mekanizması | Eşzamanlı kopya güvenli mi | Öneri (açıkken) |
|---|---|---|---|---|
| Firefox | Profil: `cookies.sqlite`, `key4.db`+`logins.json`(+`logins.db`), `cert9.db`, `permissions.sqlite`, `storage/default/<origin>`; oturum çerezleri yalnız `sessionstore-backups/recovery.jsonlz4`'te. Anahtarlık YOK (birincil parola yoksa) | profil kilidi (`.parentlock` fcntl + `lock` symlink `ip:+pid`) + uzaktan-komut (D-Bus/X11) | Evet, kopya + `--no-remote --new-instance`; Sync kimliği ve jeton döndürme riski | **kopya** |
| Chromium / Chrome / Vivaldi / Brave | `Default/Cookies` (+journal), `Login Data`, `Local Storage`, `IndexedDB`, `Local State`; çerez/parola şifresi v10/v11 → anahtar KWallet/Secret Service'te | `SingletonLock` (symlink `host-pid`), `SingletonSocket` (/tmp altına symlink), `SingletonCookie` | Kopya dizinde evet (anahtarlık köprüsü şart); AYNI dizinde asla: 2. örnek kilidi çalar / birincisini SIGKILL'ler | **on** (köprü yok, §5) |
| Discord (resmi Flatpak / yerel) + Vesktop | Electron userData: `Local Storage`, `Cookies`; Flatpak: `~/.var/app/com.discordapp.Discord/config/discord` | Electron `requestSingleInstanceLock` | Evet (çoklu oturum normal); sesli kanala girme yasak | **kopya** |
| Slack | Electron userData `~/.config/Slack` (yol DOĞRULANMADI) | Electron single-instance | Evet (çoklu istemci normal); anahtarlık gerekir | **on** (anahtarlık köprüsü yok) |
| VS Code | `User/globalStorage/state.vscdb` (gizliler safeStorage ile), `Cookies`; Flatpak: `~/.var/app/com.visualstudio.code/config/Code` | Electron + `--user-data-dir` | Evet; anahtarlık köprüsü gerekir | **on** (köprü yok) |
| Spotify | Flatpak `~/.var/app/com.spotify.Client/config/spotify` (`prefs`, `Users/`) | D-Bus `org.mpris.MediaPlayer2.spotify` (own) | Teknik evet, AMA 2. istemcinin çalması birincisini duraklatır | **kopya** (çalma yasak) |
| Obsidian | Kasa = düz dosya (`filesystem=home`); Sync jetonu Electron localStorage'da | Electron | Kasa dosyaları paylaşılabilir ama arka plan örneği gerçek kasaya yazar; Sync çift istemci riskli | **on** (yalnız ön plan) |
| Element Desktop | Matrix `access_token`+`device_id`+E2EE anahtarları IndexedDB'de; anahtarlık | Electron | **HAYIR**: aynı device_id iki istemci → OTK çakışması / çözülemeyen mesajlar | **bekle** |
| Signal Desktop | `~/.config/Signal`: `config.json` (`encryptedKey`+`safeStorageBackend`), `sql/db.sqlite` | Electron | **HAYIR**: sunucu eski bağlantıyı düşürür (4409), Desktop yeniden bağlanmaz | **bekle** |
| Telegram Desktop | `~/.local/share/TelegramDesktop/tdata` (auth key) | Qt `QLocalServer` SOYUT soket `md5(workdir)-TelegramDesktop` + `QLockFile` /tmp | **HAYIR**: AUTH_KEY_DUPLICATED → oturum sunucuda ölür; ayrıca soyut soket yüzünden 2. örnek kullanıcı penceresini açar | **bekle** |
| WhatsApp sarmalayıcıları (ZapZap, whatsapp-for-linux, Ferdium hizmeti) | WhatsApp Web bağlı cihaz = tarayıcı deposu (IndexedDB) | Uygulamaya göre | Aynı bağlı cihaz kimliği iki yerde: davranış **DOĞRULANMADI**, ihtiyatlı | **bekle** |
| Steam | `~/.local/share/Steam/config/{loginusers.vdf,config.vdf}` | `~/.steam/steam.pid` + `steam.pipe` | Tek oturum kuralı belirsiz/çelişkili; çevrimiçi oynama tek makine | **bekle** |
| Thunderbird | Firefox ile aynı: `logins.json`+`key4.db`, OAuth jetonları `logins.json`'da; posta kutusu büyük | profil kilidi (Firefox ile aynı) | Posta deposu paylaşılamaz; OAuth döndürme riski | **bekle** (isteğe bağlı hafif kopya) |
| Heroic | `~/.config/heroic/{legendaryConfig/legendary/user.json,gog_store,nile_store}` + Electron `Partitions` | Electron `requestSingleInstanceLock` (kaynak: main.ts:298) | Epic/GOG/Amazon jeton yenileme: **DOĞRULANMADI** | **bekle** |
| Lutris | `~/.local/share/lutris/pga.db`, `~/.config/lutris`; site jetonu `~/.cache/lutris` (**DOĞRULANMADI**) | GtkApplication `net.lutris.Lutris` (D-Bus) | Özel D-Bus'ta ayrı örnek açılır (aynı pga.db üzerinde) | **bekle** / kapalıyken paylas |
| Dolphin | `dolphinrc`, `~/.local/share/dolphin`; SFTP/SMB parolaları KIO→KWallet | KDE D-Bus | Hesap yok; yapılandırma yarışı zararsız | **paylas** |
| KMail / Akonadi | `~/.local/share/akonadi` (MySQL veri dizini) + `$XDG_RUNTIME_DIR/akonadi` soketleri; parolalar KWallet  | `org.freedesktop.Akonadi.Control` (D-Bus) | **HAYIR**: özel veri yolunda 2. Akonadi → aynı MySQL veri dizini | **kapali** |
| Nextcloud istemcisi | `~/.config/Nextcloud/nextcloud.cfg`; jeton QtKeychain→Secret Service/KWallet  | `KDSingleApplication` (kaynak: application.cpp:433) | İki istemci aynı eşitleme klasörü → çakışma | **kapali** |
| Ferdium | Electron `Partitions/service-*`: WhatsApp/Telegram/Discord hizmetleri içinde | Electron | İçindeki hizmetlerin en kötüsü kadar riskli | **bekle** |

Bu tablo araştırma bulgularının özetidir; Deskhand'in fiilen uyguladığı varsayılan politika §8'dedir (anahtarlık köprüsü bu sürümde olmadığından anahtarlık isteyen uygulamalar `on`, yani yalnız ön plandır). Tarayıcılarda bile kapalıyken **kopya** esastır (§1.2).

### 1.2 Ayrıntılar ve kanıtlar

**Genel ilke 1 — tarayıcıları kapalıyken bile kopyala.** Chromium'un `process_singleton_posix.cc` kaynağı: ikinci süreç
profil dizinindeki soketten birinciye komut satırını yollar, birinci süreç 20 sn içinde ACK vermezse **birincisini
SIGKILL ile öldürür** ve devralır; kilit başka bir hostname'e aitse "profil kullanımda" hatası verir
([process_singleton_posix.cc, tag 139.0.7258.138](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/chrome/browser/process_singleton_posix.cc)).
Kilit sahibinin PID'si başka PID ad alanında (Flatpak) çözülemezse "öksüz kilit" sayılıp silinir → iki süreç
aynı profili yazar. Ayrıca kullanıcı arka plan paylaşımı sürerken simgeye tıklarsa kendi örneği `/tmp` soketi
üzerinden ARKA PLAN örneğine bağlanır ve pencere görünmez masaüstünde açılır. Bu yüzden Chromium ailesi ve
Electron uygulamalarında hiç `paylas` kullanma, `--user-data-dir=KOPYA` kullan.

**Genel ilke 2 — soyut Unix soketleri ve `$XDG_RUNTIME_DIR` D-Bus'tan bağımsızdır.** Özel D-Bus yalnız D-Bus tabanlı
tek-örnek mekanizmalarını (Lutris/GApplication, KDE/KDBusService, Firefox uzaktan komutu) izole eder. Telegram
Desktop `QLocalServer::AbstractNamespaceOption` kullanıyor (adı `md5(çalışma dizini)-TelegramDesktop`) ve kilit
dosyası `QDir::tempPath()` altında ([sandbox.cpp](https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/Telegram/SourceFiles/core/sandbox.cpp)).
Soyut soket ağ ad alanı genelidir → Xvfb'deki 2. Telegram aynı `tdata` ile açılırsa kullanıcının Telegram'ına
bağlanır (pencere kullanıcı ekranında). Çözüm: `bekle`; ayrıca arka plan oturumuna ayrı `XDG_RUNTIME_DIR`
(ses/pipewire soketlerini symlink ile ekleyerek) vermek yol-tabanlı soketleri ayırır, soyut soketleri ayırmaz
(**DOĞRULANMADI**: `unshare --net` uygulanabilirliği, ağ gerektirdiğinden değerlendirilmedi).

**Firefox** — bkz. §3. Kilit: `nsProfileLock.cpp` önce `.parentlock` üzerinde `fcntl(F_SETLK)` dener, olmazsa
`lock` symlink'ine (`ip:+pid`) döner
([nsProfileLock.cpp](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/profile/nsProfileLock.cpp)).
Oturum anahtarlıkta DEĞİL; birincil parola kullanılıyorsa `key4.db` korumalıdır (**DOĞRULANMADI**: kullanıcının
birincil parolası olup olmadığı bilinemez).

**Chromium ailesi** — bkz. §2. Çerez DB'sinin yolu sürüme göre `Default/Cookies` ya da `Default/Network/Cookies` olabilir; Deskhand ikisini de
denemeli. Çerez DB'si `Cookies-journal` (geri-alma günlüğü) kullanıyor, WAL değil. Chromium çerez deposu kaynağında
`enable_exclusive_access` ve `restore_old_session_cookies` parametreleri var; `restore_old_session_cookies` kapalıyken
açılışta oturum çerezleri DB'den **silinir** (`DeleteSessionCookiesOnStartup`)
([sqlite_persistent_cookie_store.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/net/extras/sqlite/sqlite_persistent_cookie_store.cc))
→ kopyalanan oturum çerezleri arka plan Chromium'unda "son oturumu geri yükle" ayarı yoksa kaybolur (bu bayrağın
hangi kullanıcı ayarına bağlandığı **DOĞRULANMADI**).
- Kopya DAHİL: `Local State`, `Default/{Cookies,Cookies-journal,Login Data,Login Data For Account,Web Data,Preferences,Secure Preferences,Local Storage,IndexedDB,Session Storage,Sessions*,Service Worker (isteğe bağlı)}`, kullanılan uzantılar (`Extensions`).
- HARİÇ: `Singleton*`, `Cache`, `Code Cache`, `GPUCache`, `DawnGraphiteCache`, `Crash Reports`, `Safe Browsing`, `component_crx_cache`, `OptimizationHints`, `WidevineCdm`, `BrowserMetrics*`, `LOCK`, `*-journal` DIŞINDA kalan kilit/`LOCK` dosyaları.
- Senkron: Chrome'da hesap senkronu kopyada çalışmasın (`--disable-sync`); Vivaldi/Brave'in kendi senkron zincirleri için de kapat (**DOĞRULANMADI** ayrıntı).
- Vivaldi: yt-dlp, Linux'ta Vivaldi'nin anahtarlık adını `Chrome` (yani "Chrome Safe Storage") olarak eşliyor
  ([cookies.py](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/cookies.py), "D-Bus dinleyerek belirlendi" yorumu) — Vivaldi'nin güncel sürümleri için **DOĞRULANMADI**.

**Discord (resmi + Vesktop).** Oturum, uygulamanın Electron kullanıcı veri dizinindeki `Local Storage` ve `Cookies`
içinde. Flatpak'ta: `~/.var/app/com.discordapp.Discord/config/discord` (büyük kısmı `Cache`, `logs`, `Dictionaries` ve
önbellek dizinleridir). Vesktop yapılandırması XDG config altında
`vesktop/` ([Home Manager seçenekleri](https://mynixos.com/home-manager/option/programs.vesktop.settings); iç yapı
`settings/settings.json` iddiası **DOĞRULANMADI**). Flatpak Discord'un keyring izni olmadığından anahtarlık köprüsü gerekmez.
Birden çok eşzamanlı Discord oturumunun hesap kilidine yol açmadığı: bu rapor için resmi bir Discord belgesi
**bulunamadı → DOĞRULANMADI** (uygulama pratiği olarak yaygın; kopya aynı jetonla ve aynı cihaz parmak iziyle
çalışacağından yeni cihaz girişi tetiklenmez). KOPYA hariç: `Cache`, `Code Cache`, `GPUCache`, `GPUPersistentCache`,
`DawnGraphiteCache`, `DawnWebGPUCache`, `logs`, `discord_asset_cache`, `Crashpad`, `blob_storage`, `Dictionaries`;
sürümlü modül dizini (ör. `1.0.x/`) kopyalanmazsa uygulama modülleri yeniden indirir. Kural: Deskhand sesli kanala katılmaz
(kullanıcı adına "çevrimiçi/seste" görünür).

**VS Code.** `code --verbose --vmodule="*/components/os_crypt/*=1"` ile hangi anahtarlığın seçildiği görülür;
çalışma zamanı bayrağı `argv.json` içinde `"password-store"` (`kwallet5`, `gnome-libsecret`, `kwallet`, `basic`; belgede
`kwallet6` listelenmiyor) ([resmi belge](https://code.visualstudio.com/docs/configure/settings-sync)).
Gizliler (`secret://…`) `state.vscdb`'de safeStorage ile şifreli (**DOĞRULANMADI**: iç biçim okunmadı, yalnız
bilinen mimari). Kopya: `User/globalStorage/state.vscdb`(+wal), `Cookies`, `Local State`, `User/settings.json`;
HARİÇ `Cache*`, `CachedData`, `logs`, `User/workspaceStorage` (büyük). Uzantı dizinini kopyalamak yerine
`--extensions-dir` ile salt-okur paylaşmak **DOĞRULANMADI** (VS Code uzantı dizinine yazar).

**Slack.** Electron. `d` çerezi uzun ömürlü oturum çerezi olarak bilinir ama bu rapor için resmi kaynak
bulunmadı → yol (`~/.config/Slack`) ve çerez davranışı **DOĞRULANMADI**. Slack çoklu istemciyi desteklediğinden
kopya mantıklı; jeton döndürme riski §4.

**Spotify.** Flatpak `~/.var/app/com.spotify.Client/config/spotify` (`prefs`, `Users/`). Manifest `org.mpris.MediaPlayer2.spotify=own`:
özel D-Bus'ta ad çakışması olmaz. Asıl risk: aynı hesapta yalnız bir cihaz çalabilir; ikinci istemcide çalma
başlatmak birincisini duraklatır (Spotify topluluğu yanıtları:
[örnek 1](https://community.spotify.com/t5/Accounts/Listening-on-two-devices-simultaneously/m-p/4992140),
[örnek 2](https://community.spotify.com/t5/Desktop-Windows/Music-keeps-pausing-when-Spotify-is-open-on-two-devices/m-p/6479920/highlight/true);
resmi destek makalesi bulunamadı → kural forum kaynaklı). Kopya dosyalarının iç yapısı **DOĞRULANMADI**.

**Obsidian.** Kasa düz dosya; `filesystem=home` ile Flatpak'tan erişilir; yapılandırma
`~/.var/app/md.obsidian.Obsidian/config/obsidian`. Hesap yalnız Sync/Publish için. Arka plan örneği kasayı okuyabilir;
yazma-yarışı (son yazan kazanır) ve Sync çift-istemci davranışı **DOĞRULANMADI** → Sync kapalı, kasa paylaşımlı.

**Element Desktop.** Matrix'te cihaz kimliği (`device_id`) ve Olm/Megolm anahtarları istemciye özgü. İki canlı istemci
aynı `device_id` ile çalışırsa tek-kullanımlık anahtar (OTK) yüklemesi çakışır ve "One time key … already exists"
hatası / çözülemeyen mesajlar (UTD) oluşur
([matrix-rust-sdk #1415](https://github.com/matrix-org/matrix-rust-sdk/issues/1415): "two OlmMachine created … same
deviceId but different keys"). Bu kopya senaryosuyla birebir çakışıyor. → `bekle`; alternatif olarak
ayrı bir Element Web oturumu (yeni cihaz) gerekir ki bu "yeniden giriş" demek.

**Signal Desktop.** `config.json` içinde `encryptedKey` ve `safeStorageBackend` alanları: veritabanı anahtarı Electron
safeStorage ile korunuyor; GNOME↔KDE geçişi "Database Error" verir, çözüm `--password-store="kwallet6"`
([yingtongli.me](https://www.yingtongli.me/blog/2025/08/13/signal-secrets.html),
[Signal-Desktop commit](https://ayakael.net/mirrors/signal-desktop/commit/405ecfdcf8eb491e1684530b13948da758c906bd)).
Sunucu davranışı (kaynak): libsignal `ConnectedElsewhere` → WebSocket kapanış kodu **4409**; Desktop'un
`SocketManager`'ı 4409'da `log.error('got 4409, connected on another device'); return;` yapar ve **yeniden bağlanmaz**
([WebsocketResources.preload.ts](https://raw.githubusercontent.com/signalapp/Signal-Desktop/main/ts/textsecure/WebsocketResources.preload.ts),
[SocketManager.preload.ts, satır 391-394](https://raw.githubusercontent.com/signalapp/Signal-Desktop/main/ts/textsecure/SocketManager.preload.ts)).
Yani arka plan kopyası bağlanırsa kullanıcının Signal'i düşer ve yeniden başlatılana dek bağlanmaz; ayrıca iki
kopyada Double Ratchet durumu ayrışır (bu ikincisi mimari çıkarım, **DOĞRULANMADI**). Signal-Server'ın
`ClientPresenceManager` kaynağı okunamadı (404) → sunucu tarafı "eski bağlantıyı düşür" davranışı yalnız istemci
kaynağından çıkarım. → `bekle`.

**Telegram Desktop.** Resmi belge: `AUTH_KEY_DUPLICATED` (406) — "yalnız bir medya olmayan DC, yetkili bir oturumun
paralel TCP bağlantılarında istek yolladığını görünce"; hata alınmışsa oturum sunucuda zaten geçersiz kılınmıştır ve
"kullanıcı yeni auth key üretip yeniden giriş yapmalı" ([core.telegram.org/api/errors](https://core.telegram.org/api/errors)).
→ tdata kopyası ile eşzamanlı çalıştırmak kullanıcının ASIL oturumunu öldürebilir (kopya/orijinal fark etmez, auth key aynı).
Sıralı kullanım (biri kapalıyken) için aynı belge sorun görmüyor ama "kapalıyken kullan ve geri bırak" desteği
tdesktop kaynağında özel olarak doğrulanmadı (**DOĞRULANMADI**). `-many -workdir` bayrağı ayrı hesap içindir,
aynı tdata'yı ikinci kez açmak için değil. → `bekle`; kapalıyken `paylas` mümkün.

**WhatsApp sarmalayıcıları.** ZapZap: PyQt6 + PyQt6-WebEngine
([github.com/zapzap-linux/zapzap](https://github.com/zapzap-linux/zapzap)); oturum dizini **DOĞRULANMADI**.
whatsapp-for-linux: `$HOME/.config/whatsapp-for-linux/settings.conf` ve `web.css`
([wiki](https://github.com/eneshecan/whatsapp-for-linux/wiki)); WebKit oturum dizini **DOĞRULANMADI**. WhatsApp Web
"bağlı cihaz" olarak tarayıcı IndexedDB'sinde anahtar tutar; aynı depoyu iki istemcinin kullanması durumunda sunucu
davranışı (çıkış yaptırma, "başka pencerede açık") hakkında araştırmada kaynak **bulunamadı → DOĞRULANMADI**;
Element/Signal ile aynı mantık (aynı cihaz kimliği iki yerde) nedeniyle ihtiyatlı → `bekle`.

**Steam.** `loginusers.vdf` ve `config.vdf` oturum dosyalarıdır (içerik okunmadı). Resmî Steam Destek SSS'si tek hesabın
birden çok kişi tarafından aynı anda kullanılamayacağını söylüyor ama ikinci girişin birincisini atıp atmadığını
söylemiyor ([destek](https://help.steampowered.com/en/faqs/view/71EA-CDCE-FB5C-82B3)); forum raporları çelişkili:
bazıları "diğeri çıkış yapıyor", bazıları "oturum açık kalır, oyun oturumu çakışır" diyor, "çevrimiçi kütüphane tek makine" ortak
([topluluk iş parçacıkları](https://steamcommunity.com/discussions/forum/0/3874842132571689460)). Resmi kural belirsiz →
ihtiyatlı `bekle`. Tek örnek: `~/.steam/steam.pid` / `steam.pipe` (bilinen mimari; bu raporda kaynak okunmadı → **DOĞRULANMADI**).

**Thunderbird.** Firefox ile aynı profil/kilit mimarisi; OAuth jetonları `logins.json`'da (bilinen
mimari, **DOĞRULANMADI**). Posta deposu (mbox/Maildir, `global-messages-db.sqlite`) iki süreç arasında paylaşılamaz;
IMAP-yalnız hesaplar için hafif kopya (`prefs.js`, `logins.json`, `key4.db`, `cert9.db`, `abook.sqlite`, posta DIŞINDA)
mümkün ama ilk açılışta başlıkları yeniden indirir. Microsoft OAuth jetonunda eski jeton iptal edilmediği için döndürme
riski düşük (§4).

**Heroic.** `requestSingleInstanceLock` kullanıyor ([main.ts:298](https://raw.githubusercontent.com/Heroic-Games-Launcher/HeroicGamesLauncher/main/src/backend/main.ts)).
Dizinler: `legendaryConfig/legendary/user.json` (Epic oturumu), `gog_store`, `nile_store`,
`gogdlConfig`, `Partitions`, `Cache`, `tools`. Heroic, Legendary'nin yapılandırmasını kendi
`legendaryConfig` dizinine taşıdığını söylüyor
([PR #2803 özeti](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/pull/2803)). Epic yenileme jetonunun
döndürülüp döndürülmediği **DOĞRULANMADI**. Otomasyonun ihtiyacı çok az → `bekle`.

**Lutris.** `Gtk.Application(application_id="net.lutris.Lutris", flags=HANDLES_COMMAND_LINE)`
([application.py](https://raw.githubusercontent.com/lutris/lutris/master/lutris/gui/application.py)): D-Bus tabanlı
tek örnek → özel D-Bus'ta ikinci, bağımsız örnek açılır ve aynı `pga.db`'yi kullanır. → açıkken `bekle`.

**KDE uygulamaları.** Dolphin hesap tutmuyor; SFTP/SMB parolaları KIO üzerinden cüzdana gider, bunun için köprü
gerekir. Akonadi/KMail: arama sonuçları Akonadi'nin MySQL veri dizinini
`~/.local/share/akonadi` altında ve soketleri `$XDG_RUNTIME_DIR/akonadi` altında tuttuğunu, aynı veri dosyalarını
kullanan ikinci mysqld'nin `InnoDB: Unable to lock ./ibdata1, error: 11` verdiğini gösteriyor
([KDE forum](https://forum.kde.org/viewtopic.php%3Ff=309&t=161559.html); "kullanıcı başına tek örnek" kuralı açıkça
yazılı değil → **DOĞRULANMADI**). Özel D-Bus'ta Akonadi D-Bus etkinleştirmesi ikinci sunucu başlatır → `kapali`.

**Nextcloud istemcisi.** Kimlik bilgileri QtKeychain ile GNOME Keyring / KWallet / libsecret'e yazılır
([QtKeychain README alıntısı](https://help.nextcloud.com/t/kwallet-in-3-14-0-package/205341)); tek örnek
`KDSingleApplication` ([application.cpp:433](https://raw.githubusercontent.com/nextcloud/desktop/master/src/gui/application.cpp)).
İki istemci aynı klasörü eşitler → `kapali`.

---

## 2. Chromium ailesi ve Electron çerez/parola şifrelemesi (Linux)

### 2.1 Biçim ve anahtar

Kaynak: `components/os_crypt/sync/os_crypt_linux.cc` (tag 139.0.7258.138)
([kaynak](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/os_crypt_linux.cc)):

- Önek `v10` = sabit parola `"peanuts"`; `v11` = sistem anahtar deposundan gelen parola. Türetme:
  PBKDF2-HMAC-SHA1, tuz `"saltysalt"`, **1 yineleme**, 16 bayt anahtar; AES-128-CBC, IV = 16 boşluk;
  PKCS7 dolgu. Kaynak yorumu: "V11 will not be used if such a library is not available." Çözmede başarısız olursa
  boş parolayla (`kEmptyKey`) yeniden dener. `v11` verisi için anahtar alınamazsa çözme **başarısız** olur
  (çerez sessizce düşer). Aynı türetme üçüncü taraf kodda da görülür (yt-dlp `derive_key`: salt `saltysalt`, 1 yineleme, 16 bayt).
- Anahtar yoksa YENİ veri `v10` ile yazılır.
- Anahtar depolama: `KeyStorageLinux` — Chromium (markasız): klasör **"Chromium Keys"**, kayıt **"Chromium Safe Storage"**;
  Google Chrome markalı yapıda **"Chrome Keys" / "Chrome Safe Storage"**
  ([key_storage_linux.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_linux.cc)).
- libsecret kolu: şema `chrome_libsecret_os_crypt_password_v2`, tek öznitelik `application` (`chromium` veya `chrome`;
  Electron'da çalışma zamanında uygulama adı). Kayıt BULUNAMAZSA **yeni rastgele 16 bayt parola üretip yazar**
  ([key_storage_libsecret.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_libsecret.cc)).
- KWallet kolu: `org.kde.KWallet` arayüzü; klasör/anahtar adları yukarıdaki sabitler; `HasEntry` yoksa, tür parola değilse
  (`RemoveEntry` çağırıp) veya parola boşsa **yeni parola üretip yazar**
  ([key_storage_kwallet.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_kwallet.cc)).
  Cüzdan adı: `networkWallet` yanıtı (genelde `kdewallet`) (yt-dlp: `dbus-send … org.kde.KWallet.networkWallet`).
- yt-dlp'nin D-Bus dinlemesiyle bulduğu adlar (Linux): chrome→`Chrome`, chromium→`Chromium`, brave→`Brave`,
  edge→`Chromium`, opera→`Chromium`, vivaldi→`Chrome`; KWallet çağrısı `kwallet-query --read-password "<Ad> Safe Storage" --folder "<Ad> Keys" <cüzdan>`;
  KWallet hizmetleri: `org.kde.kwalletd` (`/modules/kwalletd`), `…kwalletd5` (`/modules/kwalletd5`), `…kwalletd6` (`/modules/kwalletd6`)
  ([cookies.py](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/cookies.py)).

### 2.2 Arka uç seçimi (özel oturumda kritik)

- `--password-store=gnome-libsecret|kwallet|kwallet5|kwallet6|basic|detect`; istenen/otomatik seçilen arka uç yoksa
  `basic`'e düşer ([password_storage.md](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/password_storage.md)).
- Otomatik seçim `XDG_CURRENT_DESKTOP`/`DESKTOP_SESSION` ortam değişkenlerinden: KDE4→KWALLET, KDE5→KWALLET5, **KDE6→KWALLET6**;
  GNOME/Cinnamon/XFCE/COSMIC→libsecret; LXQt/diğer→**basic**
  ([key_storage_util_linux.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_util_linux.cc)).
  yt-dlp de `XDG_CURRENT_DESKTOP`+`KDE_SESSION_VERSION` bakıyor.
- **Sonuç / tuzak:** Xvfb+openbox oturumunda bu değişkenler yoksa Chromium `basic`'e düşer → `v11` çerezler çözülemez
  (düşer) ve yeni çerezler `v10` yazılır. Deskhand arka plan oturumuna **`XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6`**
  verip ayrıca açıkça `--password-store=kwallet6` (Chromium/Vivaldi) ya da kullanıcının gerçek arka ucu neyse onu
  geçirmeli. Gerçek arka ucu tespit için kopyadaki çerez DB'sinde `encrypted_value`'ın ilk 3 baytı (`v10`/`v11`)
  yalnız sayılabilir (değer okunmaz).

### 2.3 Özel D-Bus'taki kopya anahtara nasıl erişir

Kopya, anahtarı aynı yoldan ister: libsecret (`org.freedesktop.secrets`, öznitelik `application`) veya KWallet
(`org.kde.kwalletd6`, `/modules/kwalletd6`). Özel veri yolunda bu adlar yok → **köprü şart**; bu sürümde köprü olmadığından bu uygulamalar yalnız ön planda çalışır (§5). Köprü yoksa:
(a) `basic`'e düşer, çerezler kaybolur; (b) kullanıcının cüzdanı ERİŞİLEMEZ durumda "yeni parola üret ve yaz"
yoluna girebilirse (yanlış/boş depo) kullanıcının GERÇEK `Chromium Safe Storage` kaydı üzerine yazılabilir ve
asıl Chromium'un `v11` verisi çözülemez olur. Bu yüzden köprü **salt-okunur** olmalı: Secret Service `CreateItem`,
`Item.Delete`, `SetSecret`, `CreateCollection`; KWallet `writePassword`, `writeEntry`, `removeEntry`, `removeFolder`,
`createFolder`, `changePassword`, `closeAllWallets`, `deleteWallet` engellenmeli.

Yedek yol (köprüsüz): Deskhand, kopya DB'deki `v11` değerleri yalnız kendi sürecinde kullanıcının anahtarıyla çözüp `v10`'a
(sabit anahtar) yeniden şifreler. Bedeli: kopyada çerezler yalnızca gizlilik-olmayan (obfuscation) düzeyinde durur;
kopya 0700 + tmpfs + oturum sonunda silinmeli. Bu yöntem denenmedi (**DOĞRULANMADI**).

### 2.4 Electron `safeStorage` aynı mı?

Kısmen. Electron ana kaynağı (`shell/browser/browser_process_impl.cc`): `--password-store` değerleri Chromium ile aynı
(`kwallet`, `kwallet5`, `kwallet6`, `gnome-libsecret`, `basic`), seçilmezse masaüstü ortamından
(KDE6→kwallet6). **Yeni asenkron yol** (Electron'un `safeStorage`'ı): `FreedesktopSecretKeyProvider` için
`kwallet_folder = "<uygulama adı> Keys"`, `key_name = "<uygulama adı> Safe Storage"`; öncesinde isteğe bağlı bir
**Secret Portal** sağlayıcısı (`org.freedesktop.portal.Secret.RetrieveSecret`, anahtarı bir boru/FD üzerinden verir,
`Local State`'te `token` tutar) daha yüksek öncelikle denenir; hepsi başarısızsa sabit-parola (`PosixKeyProvider`)
([browser_process_impl.cc](https://raw.githubusercontent.com/electron/electron/main/shell/browser/browser_process_impl.cc),
[secret_portal_key_provider.cc](https://chromium.googlesource.com/chromium/src/+/main/components/os_crypt/async/browser/secret_portal_key_provider.cc),
[freedesktop_secret_key_provider.cc](https://chromium.googlesource.com/chromium/src/+/main/components/os_crypt/async/browser/freedesktop_secret_key_provider.cc)).
Bu yeni sağlayıcı Secret Service'e `OpenSession` için **"plain"** algoritma kullanıyor, önek `v11`.
Electron belgeleri: `isEncryptionAvailable`, `getSelectedStorageBackend()` (`basic_text` ise "korumasız"), desteklenen
arka uçlar `kwallet`, `kwallet5`, `kwallet6`, `gnome-libsecret`
([safe-storage](https://www.electronjs.org/docs/latest/api/safe-storage)).
Notlar:
- KDE hata kaydı 510038, `Chromium Keys` klasöründe `Chromium Safe Storage` kaydının Chromium tabanlı uygulamalarca
  paylaşıldığını ve bazen iki kez göründüğünü gösteriyor ([KDE #510038](https://bugs.kde.org/show_bug.cgi?id=510038));
  eski eşzamanlı OSCrypt yolu (çerez/yerel depo için) uygulama adını `application` özniteliği olarak
  kullanıyor, klasör/anahtar adları sabit "Chromium …". Hangi Electron sürümünün hangi yolu hangi veri için kullandığı
  **DOĞRULANMADI** → Deskhand adları sabit kodlamasın, köprü adı-bağımsız aktarsın.
- Portal sağlayıcısı etkinse (varsayılan durumu **DOĞRULANMADI**; kod `features::kDbusSecretPortal` ve
  `kSecretPortalKeyProviderUseForEncryption` bayraklarına bakıyor) anahtar `org.freedesktop.portal.Desktop` üzerinden
  gelir. Özel D-Bus'ta portal yok → sağlayıcı "kNoService" ile düşer; bu anahtarla şifrelenmiş veri çözülemez.
  Portal, istemciyi `/proc/<pid>` ile tanır; röle üzerinden gelen çağrı rölenin kimliğiyle görünür → uygulamaya özel
  portal sırrı alınamaz (**DOĞRULANMADI**, mimari çıkarım). Köprü şimdilik portalı KAPSAMAMALI; bu durumda ilgili
  uygulamaya `--password-store=kwallet6` (ya da `gnome-libsecret`) ile eski yolu zorlamak ve `Local State` içindeki
  portal belirtecini kopyadan temizlemek gerekir (**DOĞRULANMADI**).
- Flatpak Electron uygulamaları (Discord, Spotify, Ferdium) keyring'e `talk` izni olmadığından köprüden yararlanamaz;
  bunlar için §0'daki notlar geçerli.

---

## 3. Firefox anlık kopyası — iyi uygulamalar

### 3.1 Oturum için gereken dosyalar (profil kökü)

| Dosya / dizin | Ne için | Not |
|---|---|---|
| `cookies.sqlite` + `cookies.sqlite-wal` | KALICI çerezler | Oturum çerezleri (`expiry` yok) burada DEĞİL |
| `storage/default/<origin>/` (`ls/data.sqlite`=localStorage, `idb/*.sqlite`, `cache/`) | site depoları | Dizin adı `https+++github.com`; kap/bölüm: `^userContextId=N`, `^partitionKey=…`. `storage/` yüzlerce origin ve çok yer tutabilir → YALNIZ gereken origin'ler |
| `storage/permanent`, `storage.sqlite`, `storage/ls-archive.sqlite` | kota/arşiv meta | Kopyaladığın origin'lerin `.metadata-v2` dosyası da gelmeli (dizin içinde) |
| `key4.db` + `logins.json` (+ `logins.db`, `logins-backup.json`) | kayıtlı parolalar | Oturum çerezi için gerekmez; otomatik doldurma için gerekir. Bu dosya adları gerçek profillerde görüldü |
| `cert9.db`, `pkcs11.txt` | istemci sertifikaları / güvenlik modülleri | |
| `permissions.sqlite` | site izinleri (çerez istisnaları dahil) | |
| `containers.json` | Multi-Account Containers eşlemesi | `userContextId` ile çerezlerin kapsayıcısını bağlar |
| `sessionstore-backups/recovery.jsonlz4` | **oturum çerezleri** + açık sekmeler | bkz. §3.4 |
| `prefs.js` / `user.js` | ayarlar | Kopyada Sync kapatılmalı (§3.6) |
| `extensions/`, `extensions.json`, `addonStartup.json.lz4` | uzantılar (reklam engelleyici vb.) | |
| `SiteSecurityServiceState.bin`, `AlternateServices.bin` | HSTS / alt-svc | gerekmez |

HARİÇ: `lock`, `.parentlock`, `parent.lock`, `signedInUser.json`, `weave/`, `synced-tabs.db*`, `places.sqlite*` (geçmiş —
gerekmez), `formhistory.sqlite`, `datareporting/`, `crashes/`, `minidumps/`, `saved-telemetry-pings/`,
`Telemetry.FailedProfileLocks.txt`, `sessionstore-logs/`, `bounce-tracking-protection.sqlite` (gerekirse).
Önbellek zaten `~/.cache/mozilla` altında (profilde değil).

### 3.2 Kilitli SQLite'ı çalışırken güvenle kopyalama

- Firefox bağlantıları varsayılan olarak "exclusive" VFS ile açar: `Connection::initialize` içinde
  `bool exclusive = StaticPrefs::storage_sqlite_exclusiveLock_enabled() && !mOpenNotExclusive;` ve SQLITE_BUSY/LOCKED
  alırsa **açarken** dışlayıcı olmayan VFS'e düşer
  ([mozStorageConnection.cpp](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/storage/mozStorageConnection.cpp);
  pref'in varsayılan değeri kaynakta görünmedi → **DOĞRULANMADI**; bkz. [Bug 1650201](https://bugzilla.mozilla.org/show_bug.cgi?id=1650201)).
  Çerez DB'sinin dışarıdan okunamaması eski bir sorun: [Bug 449987](https://bugzilla.mozilla.org/show_bug.cgi?id=449987),
  [pycookiecheat #48](https://github.com/n8henrie/pycookiecheat/issues/48) çözümü "dosyayı (ve WAL'ını) geçici yere kopyala,
  kopyadan oku".
- Bu yüzden: **ham kopya + kopyadan SQLite yedek API'si** (deneyle çalıştığı doğrulandı).
- Tutarlılık için (mühendislik yorumu, kaynaklı değil): (1) `.sqlite`, `-wal` için `stat`(mtime_ns, size) al; (2) ana dosya ve
  `-wal`'ı arka arkaya hızlı kopyala; (3) `-shm` KOPYALAMA (yeniden oluşturulur); (4) tekrar `stat`: değiştiyse baştan; (5) kopyayı
  normal (yazılabilir) açıp `PRAGMA integrity_check` + `.backup`/`VACUUM INTO` ile temiz tek dosya üret. Neden: WAL
  kontrol noktası (checkpoint) iki kopya arasına denk gelirse ana dosya yeni, WAL eski olabilir.
- `immutable=1` URI'si WAL'ı yok sayar → son işlemler kaybolur; kullanma.
- `storage/default/<origin>/ls/data.sqlite` ve `idb/*.sqlite` için aynı döngü; IndexedDB için `.files/` blob dizinini de al.

### 3.3 Hangi profil, hangi konum

`profiles.ini` içinde `[Install*] Default=` anahtarı esas (`[Profile*]` bölümündeki `Default=1` başka profile işaret edebilir, §0).
Profil dizini symlink olabilir (ör. tmpfs'e taşınmış profil) → `realpath`. Çalışıp çalışmadığı: `lock` symlink'i `ip:+pid` ve `.parentlock`
(fcntl) — bkz. §6.

### 3.4 Oturum çerezleri

- Çerez DB'sine yalnız kalıcı çerezler yazılır; oturum çerezleri sessionstore'a (`recovery.jsonlz4`, kökte `cookies` dizisi)
  yazılır ve "oturumu geri yükle"de yeniden eklenir. Kaynak: `SessionCookies.sys.mjs` yalnız `cookie.isSession`
  olanları toplar; `restore()` onları `Services.cookies.add(... isSession=true ...)` ile ekler ve
  `browser.sessionstore.privacy_level`'a bağlıdır
  ([SessionCookies.sys.mjs](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/browser/components/sessionstore/SessionCookies.sys.mjs)).
  `recovery.jsonlz4` oturum sırasında sürekli güncellenir, kapanışta `sessionstore.jsonlz4`'e dönüşür
  ([Mozilla destek](https://support.mozilla.org/en-US/questions/1189759)).
- Pratik yol: kopyaya `recovery.jsonlz4`'ü `sessionstore.jsonlz4` olarak koy + kopya `user.js`'e
  `browser.startup.page = 3` ("önceki oturumu aç"). **Yan etki:** kullanıcının TÜM sekmeleri arka planda açılır (ağır,
  bildirim/ses). Daha iyi: Deskhand `.jsonlz4`'ü (`mozLz40\0` + LZ4) açıp `windows[*].tabs`'i tek boş sekmeye indirir, `cookies`'i
  korur. `restore()`'un pencere geri yüklenmeden çağrılıp çağrılmadığı **DOĞRULANMADI** → deneysel doğrulama gerekir.
  `sessionstore-backups/` altında `recovery.jsonlz4`, `recovery.baklz4`, `previous.jsonlz4` ve `upgrade.jsonlz4-*`
  dosyaları bulunabilir.
- Hangi sitelerin yalnız oturum çerezi kullandığını önceden bilmek zor; bu yüzden "bu site girişli kalsın" listesi
  (`oturum.toml`) kullanıcı tarafından, ya da denemeyle belirlenmeli.

### 3.5 Firefox 140+ değişiklikleri

- 147: XDG Base Directory desteği (§0). `MOZ_LEGACY_HOME=1` ile eski düzen (tek kaynak, issoh.co.jp/desdelinux haberleri,
  **DOĞRULANMADI**).
- Yeni Firefox sürümlerinde `logins.db` görülüyor (§0). Araştırmada bu dosyayı açıklayan resmi kaynak **bulunamadı**.
- Çerez/depolama biçiminde 140-159 arası kırıcı değişiklik raporu **bulunamadı** (arama sonuç vermedi) → **DOĞRULANMADI**;
  önlem olarak kopyayı AYNI Firefox ikilisiyle aç (sürüm uyumsuzluğu: Mozilla topluluğu başka sürümde yazılmış
  `recovery.jsonlz4`'ün eski sürümde geri yüklenemediğini bildiriyor).
- Yeni profil yöneticisi ("seçilebilir profiller"): `profiles.ini`'de `StoreID=` anahtarı profil gruplarının
  kullanıldığını gösterir (`Profile Groups/` yapısı **DOĞRULANMADI**).

### 3.6 Sync / Firefox Hesabı riski

Kopyalanmış profil, aynı cihaz kimliğini taşır; Mozilla topluluğu "iki makine tek cihaz gibi görünür, Send Tab / aygıt
yöneticisi karışır, eşitleme birbirini ezer", çözüm olarak `signedInUser.json`'ı silmeyi öneriyor
([destek 1202057](https://support.mozilla.org/bm/questions/1202057), [Bug 1234181](https://bugzilla.mozilla.org/show_bug.cgi?id=1234181)).
`signedInUser.json` Sync açık profilde bulunur. Yani: `signedInUser.json`'ı kopyalama; ek olarak kopya `user.js`'e
`identity.fxaccounts.enabled = false` (etkisi **DOĞRULANMADI**, deneyle teyit et) ve `weave/` dizinini dışarıda bırak.

### 3.7 Başlatma bayrakları

`firefox --profile KOPYA --no-remote --new-instance` (deneyle çalıştığı doğrulandı). Wayland/X11 uzaktan komut ve D-Bus
`org.mozilla.firefox.*` adı özel oturumda olduğundan kullanıcının Firefox'u etkilenmez.

---

## 4. Jeton döndürme (refresh token rotation) riski

Genel hüküm: **Kopya, kaynakla paylaştığı bir TÜKETİLEBİLİR sırrı (yenileme jetonu / dönen oturum çerezi) kullanıp
yeniler ise, asıl tarayıcının elindeki eski kopya geçersizleşebilir.** Risk, sitenin tasarımına bağlı:

| Hizmet / sınıf | Kanıt | Kopya yenilerse asıl oturum? |
|---|---|---|
| OAuth 2.x, genel istemci, döndürme + yeniden-kullanım tespiti | RFC 9700 §2.2.2: "Refresh tokens for public clients MUST be sender-constrained or use refresh token rotation"; §4.14.2: yeniden kullanılan eski jeton görülürse sunucu "revoke the active refresh token" ([RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)) | **EVET, düşer**: bayat sahibi kimliği ayırt edilemez, aktif jeton iptal edilir |
| Auth0 (döndürme açıksa) | yeniden kullanım → "invalidates the refresh token family, including refresh token 2", yeniden kimlik doğrulama gerekir ([Auth0](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)) | **EVET**, aile iptali |
| Okta (döndürme açıksa) | önceki jeton `leeway` süresince (varsayılan 30 sn, 0-60) geçerli; sonra eski jeton iptal ([Okta](https://developer.okta.com/docs/guides/refresh-tokens/refresh-token-rotation/)) | Pencere sonrası **düşebilir**; aile iptali **DOĞRULANMADI** |
| GitHub App kullanıcı jetonları (süreli) | "Once you use a refresh token, that refresh token and the old user access token will no longer work"; 6 ay ([GitHub](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)) | **EVET** (tek kullanımlık) |
| Microsoft kimlik platformu | "Refresh tokens replace themselves with a fresh token upon every use. The Microsoft identity platform doesn't revoke old refresh tokens"; SPA için 24 saat, diğerleri 90 gün ([Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)) | Düşük risk (eski jeton geçerli kalır); şifre değişimi/oturum kapatma ayrı |
| Google hesap çerezleri (YouTube dahil) | yt-dlp: "YouTube rotates account cookies frequently on open YouTube browser tabs as a security measure" → dışarı aktarılan çerezler çalışmaz hale gelir; önerilen: özel pencerede giriş, dışa aktar, pencereyi kapat ([yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors)) | Döndürme GERÇEK. Kopya yenilerse asıl tarayıcının çerezi bayatlayıp oturum düşebilir mi: **DOĞRULANMADI** (belge yok; yt-dlp kanıtı kopyanın bayatladığını gösteriyor, simetrik durum çıkarım) |
| Discord / Slack / Telegram (kullanıcı jetonu) | döndürme belgesi **bulunamadı** | Jeton döndürme **DOĞRULANMADI**; Telegram için ayrıca §1 (anahtar çiftleme) |
| Bankalar / ödeme | kaynak yok | **DOĞRULANMADI**; yaygın uygulama: tek eşzamanlı oturum, cihaz/IP bağlama, işlem başına OTP → ASLA kopyalama |
| Cihaza bağlı oturum çerezi (DBSC) | Google: Chrome 146 ile Windows'ta genel kullanıma, macOS'a genişleyecek; Linux'tan söz edilmiyor ([Google blog](https://blog.google/security/protecting-cookies-with-device-bound-session-credentials/)) | Linux'ta şimdilik uygulanmıyor (kaynaklar tutarsız: başka ikincil kaynaklar Linux'u "aşamalı" diye sayıyor, **DOĞRULANMADI**); ileride kopya kırılabilir |

Riski azaltma önerileri:
1. **Site izin/ret listesi:** `deny` varsayılanı: bankalar, ödeme/finans, e-devlet, sağlık, `accounts.google.com` / `login.microsoftonline.com`
   gibi merkezi kimlik sağlayıcılar. `allow`: yalnız görevin ihtiyaç duyduğu siteler; kopya YALNIZ bu origin'leri taşır
   (Firefox: `storage/default/<origin>` ve `cookies.sqlite` satırları süzülür).
2. **Salt okunur kip:** gezinti ve okuma serbest; oturum jetonu yenileyen isteklere (`/oauth/token`, `/token`, `/api/auth/refresh`,
   `securetoken.googleapis.com` gibi) izin verme. Tarayıcı içinde engelleme için Firefox `WebsiteFilter` politikası /
   Chromium `URLBlocklist` düşünülebilir; ancak bu politikaların XHR/fetch alt isteklerini kapsayıp kapsamadığı
   **DOĞRULANMADI**.
3. **Kısa ömür + tek yön:** kopya görev bitince hemen silinir; asıl profile ASLA geri yazılmaz (zaten planda).
4. **Değişim tespiti:** oturum sonunda kopyadaki kimlik doğrulama çerezlerinin/depolarının özetini (hash) başlangıçla
   karşılaştır; değişenleri "bu sitede jeton yenilendi, ana oturumunuz bir kez yeniden giriş isteyebilir" diye kullanıcıya bildir.
5. Dönen jetonlu SPA'lar (Auth0 vb.) için mümkünse yalnız çerez tabanlı sunucu oturumlarına güven (GitHub web `user_session` gibi;
   deneyle doğrulandı) — jeton `localStorage`/IndexedDB'de duruyorsa o origin'in deposunu kopyalama.

---

## 5. Secret Service / KWallet köprüsü

**Bu sürümde yapılmadı; şifre deposu isteyen uygulamalar yalnız ön planda çalışır.** Chromium ailesi, VS Code,
Slack gibi anahtarlık (Secret Service / KWallet) gerektiren uygulamalar için politika `on`'dur (§8): Deskhand bunları
arka plan masaüstünde açmaz, yalnız kullanıcının kendi ekranında (ön planda) açar (çıkış kodu 16).

Gerekçe, kısaca: özel D-Bus oturumunda `org.freedesktop.secrets` / `org.kde.kwalletd6` adları yoktur; köprü olmadan
Chromium `basic` arka uca düşer ve `v11` çerezleri çözülemez (§2.2). Köprü yazılsaydı zorunlu ilkeleri şunlar olurdu:
salt-okunur olması (Chromium kaynağı kayıt yoksa "yeni parola üret ve yaz" yoluna girer, bu da kullanıcının gerçek
kaydını ezebilirdi, §2.1, §2.3), kilitli cüzdanda kullanıcının ekranında parola penceresi açmaması ve özel
`dbus-daemon`'un standart etkinleştirme dizinlerini kullanmaması (ikinci bir `ksecretd` aynı cüzdan dosyasını
açabilir). Ayrıca hazır bir "tek ad rölesi" aracı bulunamadı; `xdg-dbus-proxy` her dinleme soketi için tek yukarı akış
veri yolu bağlayabildiğinden bu işi tek başına yapamaz ([man](https://man.archlinux.org/man/xdg-dbus-proxy.1)).
Bu maliyet ve risk nedeniyle röle tasarımı ertelenmiştir.

---

## 6. Uygulamanın kullanıcı oturumunda çalışıp çalışmadığını saptama

Tek bir sinyal güvenilir değil; **herhangi biri pozitifse "çalışıyor" say** ve Deskhand'ye ait süreçleri hariç tut.

1. **Süreç taraması** (`/proc/<pid>`, kendi `uid`): `comm`/`exe`/`cmdline` eşleşmesi; Flatpak için `flatpak ps --columns=application,pid,instance`
   (örnek dizinleri `$XDG_RUNTIME_DIR/.flatpak/<instance>/info`, [flatpak-ps](https://raw.githubusercontent.com/flatpak/flatpak/main/doc/flatpak-ps.xml));
   Deskhand'nin başlattıklarını ortamlarındaki `DBUS_SESSION_BUS_ADDRESS` (özel yol) ya da `deskhand-app-*.scope` cgroup'u ile ayıkla.
2. **Profil kilidi:**
   - Firefox/Thunderbird: `.parentlock` üzerinde `fcntl(F_GETLK)` ile kilit SORGULA (kilit ALMADAN); yedek: `lock` symlink'i
     `ip:+pid` → `kill(pid,0)` (`nsProfileLock.cpp` aynısını yapıyor).
   - Chromium/Electron: `SingletonLock` symlink'i `hostname-pid` → `/proc/pid` var mı ve `exe` eşleşiyor mu (Chromium'un kendi
     `IsChromeProcess` mantığı). Flatpak içinde PID başka ad alanında → bu kontrol yanlış-negatif verir, `flatpak ps` kullan.
   - Telegram: `/proc/net/unix` içinde soyut ad `@<md5>-TelegramDesktop` (kaynak: sandbox.cpp) ve `QLockFile` /tmp.
   - Steam: `~/.steam/steam.pid` + `steam.pipe` (**DOĞRULANMADI**).
3. **D-Bus adları (gerçek veri yolu):** `NameHasOwner`/`ListNames`: `net.lutris.Lutris`, `org.mozilla.firefox.*`,
   `org.mpris.MediaPlayer2.<uygulama>` (Spotify manifestte `own`), `org.freedesktop.Akonadi.Control`, `org.kde.StatusNotifierItem-<pid>-N`;
   sahibin PID'si `GetConnectionUnixProcessID` ile alınır. Flatpak uygulamaları xdg-dbus-proxy arkasında olduğundan PID
   vekilin PID'sidir → cgroup/`flatpak ps` ile uygulamayı bul.
4. **systemd kullanıcı birimleri:** Plasma uygulamaları `app-*.scope|service` birimlerinde başlatır
   (<https://systemd.io/DESKTOP_ENVIRONMENTS/>, bu raporda okunmadı → adlandırmanın geçerliliği **DOĞRULANMADI**);
   `systemctl --user list-units 'app-*'` ek kanıt.
5. **KWin pencere listesi** (`resourceClass`): tepsiye küçültülmüş ama çalışan uygulamayı görmenin tek yolu olabilir.

Eşzamanlılık: kontrol ile başlatma arasında yarış var (TOCTOU) → kopya alındıktan SONRA ve başlatmadan hemen önce tekrar sorgula;
`paylas` modunda ayrıca Deskhand'nin kendi "kullanımda" kilidi (ör. `$XDG_RUNTIME_DIR/deskhand/kilit/<uygulama>`) ve kullanıcı o uygulamayı
açmaya kalkarsa Deskhand'nin uyarması gerekir (kullanıcı örneğinin kilitleri bu şemayı bilmez).

---

## 7. Arka plan oturum ortamı için kontrol listesi (özet)

- `DBUS_SESSION_BUS_ADDRESS=unix:path=…/deskhand/bus`; `DISPLAY=:77`; `WAYLAND_DISPLAY` ve `XDG_SESSION_TYPE` kaldır/`x11`;
  `XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6`.
- Özel `dbus-daemon`: yalnız Deskhand servis dizini; standart oturum etkinleştirme dizinleri KAPALI (aksi halde ikinci bir `ksecretd` aynı cüzdan dosyasını açabilir).
- Anahtarlık köprüsü bu sürümde yok (§5): anahtarlık gerektiren uygulamalar arka planda açılmaz.
- Electron (Flatpak Discord/Spotify): `--user-data-dir=KOPYA` (Flatpak'ta kopya `~/.var/app/<id>/…` altında olmalı ki sanal alandan görünsün);
  Firefox: `--profile KOPYA --no-remote --new-instance`.
- Sync kapalı (Firefox Hesabı, Chrome/Vivaldi/Brave senkronu).
- Kopya 0700, tmpfs (`$XDG_RUNTIME_DIR`), `deskhand oturum sil` ile sıfırlanır; bayat profil yedekleri (`*-backup` vb.) kaynak olarak kullanılmaz.
- Ses: sessiz çıkış (`deskhand-sessiz`); Spotify/Discord/WhatsApp çağrısı gibi canlı ses/çalma yasak.

---

## 8. Varsayılan `oturum.toml` politikası

Kaynak: `deskhand/data/oturum.toml`. Kullanıcı `CONFIG_DIR/oturum.toml` ile geçersiz kılabilir (yalnız verdiği
anahtarlar birleştirilir). Politika, çağıranın yazdığı ham addan değil ÇÖZÜLMÜŞ uygulamadan hesaplanır: `.desktop` kimliği,
`Exec`'teki ikili adı (gerçek yolu da), Flatpak kimliği ve verilen ad. Bir uygulama birden çok bölüme uyarsa EN
KISITLAYICI karar kazanır: `kapali` > `on` > `bekle` > `kopya` > `paylas`.

Karar değerleri:
- `kopya` — tutarlı, tek yönlü anlık kopya ile arka planda aç (kaynağa asla yazılmaz).
- `paylas` — kullanıcının dosyalarıyla doğrudan (yalnız uygulama kullanıcı oturumunda KAPALIYKEN).
- `bekle` — aynı anda iki istemci oturumu bozar; kullanıcı kapatana dek bekle.
- `on` — yalnız kullanıcının ekranında (ön planda); arka planda açılamaz (şifre deposu gerektiren uygulamalar;
  kasası gerçek dosyaya yazan Obsidian). Çıkış kodu 16.
- `kapali` — hiç çalıştırma.

`kapali_iken`: uygulama kullanıcı oturumunda ÇALIŞMIYORKEN; `acik_iken`: çalışırken. `keyring`: uygulama anahtarlık
gerektirir mi (bu sürümde köprü yok, §5).

| Anahtar | kapali_iken | acik_iken | keyring | Not |
|---|---|---|---|---|
| `firefox` | kopya | kopya | hayır | `lock*`, `signedInUser.json`, `weave/`, `places*`, `sessionstore.jsonlz4`, `formhistory.sqlite` hariç; yalnız izinli `storage/default/<origin>`; Sync kapalı |
| `discord` (Flatpak) | kopya | kopya | hayır | Önbellekler hariç |
| `spotify` (Flatpak) | kopya | kopya | hayır | çalma yasak (aynı hesapta ikinci cihaz çalınca birincisi duraklar) |
| `chromium`, `vivaldi`, `chrome`, `brave`, `edge`, `opera` | on | on | evet | yalnız ön plan |
| `vscode` | on | on | evet | yalnız ön plan |
| `slack` | on | on | evet | yalnız ön plan |
| `obsidian` | on | on | hayır | kasa gerçek dosyaya yazar; arka plan örneği onu bozar → yalnız ön plan |
| `telegram` (+ türevleri), `signal`, `element`, `whatsapp` (sarmalayıcılar) | bekle | bekle | hayır | ikinci istemci kullanıcının asıl oturumunu düşürür |
| `steam`, `heroic`, `lutris`, `thunderbird` | bekle | bekle | hayır | tek oturum / ortak veri |
| `ferdium` | bekle | bekle | hayır | içindeki hizmetlerin en riskli olanı kadar riskli |
| `keepassxc`, `bitwarden` | kapali | kapali | — | parola yöneticisi: tek örnek kilidi kasayı kullanıcının ekranına getirir |
| `kmail`, `akonadi` | kapali | kapali | evet | tek MySQL veri dizini |
| `nextcloud` | kapali | kapali | evet | iki eşitleme istemcisi |
| `_varsayilan` (bilinmeyen uygulama) | paylas | bekle | hayır | aşağıya bakın |

**Bilinmeyen uygulama.** Uygulama kullanıcının oturumunda KESİNLİKLE çalışmıyorsa (`Exec` ikilisi `/proc`'ta yok,
Flatpak örneği yok) normal açılış (`paylas`: kendi verisiyle, kullanıcı açmış gibi). Çalışıyorsa YA DA bilinemiyorsa
(ikili bulunamadı, başlatıcı kabuk betiği, AppImage, `/proc` okunamadı) `bekle`: tek örnek kilidi pencereyi
kullanıcının ekranına devredebilir.

**Site ret listesi** (`[site].reddet`): bu alan adlarının çerezi/deposu kopyaya ALINMAZ; düz alan adı alt alanlarını
da kapsar. Kayıtlı parolalar (`logins.json` / `logins.db`) aynı listeyle süzülür. Liste şunları içerir:
- genel desenler: `*bank*`, `*banka*`, `*odeme*`, `*payment*`, `*checkout*`, `*paypal*`, `*stripe*`, `*e-devlet*`, `*edevlet*`;
- Türk bankaları ve ödeme kuruluşları (ör. İş Bankası, Garanti BBVA, Yapı Kredi, Akbank, Ziraat, Halkbank, Vakıfbank,
  QNB, DenizBank, ING, TEB, Kuveyt Türk, Enpara, Papara, ininal, Param, iyzico, PayTR);
- uluslararası ödeme: PayPal, Stripe, Wise/TransferWise, Revolut;
- devlet: `turkiye.gov.tr`, `gib.gov.tr`, `sgk.gov.tr`, `*.gov.tr`, `*.gov`;
- merkezi kimlik: `accounts.google.com`, `login.microsoftonline.com`, `login.live.com`, `securetoken.googleapis.com`.

Örnek geçersiz kılma:

```toml
[genel]
kopya_dizini = "$XDG_RUNTIME_DIR/deskhand/oturum"   # 0700, tmpfs
origin_boyut_siniri_mb = 50                         # storage/default/<origin> başına üst sınır

[site]
reddet = ["*bank*", "*odeme*", "*paypal*", "accounts.google.com", "login.microsoftonline.com", "*.gov.tr"]
izin = []                                           # görev bazında doldurulur

[uygulama.firefox]
kapali_iken = "kopya"
acik_iken   = "kopya"
senkron     = false
disla       = ["signedInUser.json", "weave", "lock", ".parentlock", "places.sqlite"]

[uygulama.telegram]
kapali_iken = "bekle"
acik_iken   = "bekle"
```

---

## 9. DOĞRULANMADI özeti (deneyle kapatılması gerekenler)

1. Chromium/Vivaldi'nin gerçek arka ucu (`kwallet6` / libsecret / basic) kurulumdan kuruluma değişir; Vivaldi'nin
   anahtarlık adı sürüme göre doğrulanmalı.
2. Electron'un hangi sürümü hangi veri için eski/yeni anahtar yolunu ve Secret Portal'ı kullanıyor (`kDbusSecretPortal` varsayılanı).
3. Firefox: `recovery.jsonlz4`'ten yalnız çerezleri geri yükleme, `identity.fxaccounts.enabled=false` etkisi, `logins.db` rolü,
   `storage.sqlite.exclusiveLock.enabled` varsayılanı, 140-159 arası biçim değişiklikleri.
4. Google'da kopyanın çerez döndürmesinin ASIL tarayıcıyı düşürüp düşürmediği; Discord/Slack/Telegram jeton döndürmesi; bankalar.
5. Steam eşzamanlı giriş davranışı; WhatsApp Web'de aynı depodan iki istemci; Signal çift ratchet bozulması; Heroic/Epic jeton döndürmesi.
6. Plasma'da `app-*.scope` adlandırması ve `systemd.io/DESKTOP_ENVIRONMENTS` içeriği.

## 10. Pratik sonuç

- **Çalışır ve düşük riskli:** Firefox (kopya) ve Flatpak Electron uygulamaları (Discord, Spotify; anahtarlık gerekmez).
- **Yalnız ön plan:** anahtarlık gerektiren uygulamalar (Chromium ailesi, VS Code, Slack) ve kasası gerçek dosyaya
  yazan Obsidian. Arka plana açılmak istenirse çıkış kodu 16.
- **Eşzamanlı ASLA:** Telegram, Signal, Element, WhatsApp sarmalayıcıları, Steam, Akonadi, Nextcloud, Ferdium. Bunlarda yanlış
  yapmanın bedeli kullanıcının asıl oturumunun ölmesi (Telegram AUTH_KEY_DUPLICATED, Signal 4409, Element UTD).
- **En büyük gizli risk:** jeton döndürme (Auth0/GitHub App/RFC 9700 tarzı) ve Google çerez döndürmesi: kopya yenilerse
  asıl oturum düşebilir. Site ret listesi + kısa ömür + değişim tespiti şart.
