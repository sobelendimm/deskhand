# deskhand-etkinlik: Wayland klavye/fare etkinliği yardımcısı (insan önceliği). Yetki gerekmez.
# Derleme:  make -C deskhand/yardimci            (gereken: gcc, pkg-config, wayland istemci kitaplığı)
#           → deskhand/yardimci/deskhand-etkinlik (yollar.etkinlik_bin() burada da arar)
# Protokol dosyalarını yeniden üret:  make -C deskhand/yardimci protokol   (wayland-scanner + wayland-protocols)
# Kurulum (isteğe bağlı): make -C deskhand/yardimci kur  → $(DATA_DIR)/etkinlik/deskhand-etkinlik
# deskhand-goruntu: KWin ScreenShot2 ile ekran görüntüsü (spectacle'sız, hızlı). Ayrı hedef, çünkü libsystemd
# (sd-bus) ister:  make -C deskhand/yardimci deskhand-goruntu
# deskhand-eis: KWin EIS (libei) ile girdi gönderen kalıcı yardımcı (dotool satır dilini okur). libei + libxkbcommon +
# libsystemd ister; yoksa bu hedef atlanır (diğerleri etkilenmez):  make -C deskhand/yardimci deskhand-eis
# Tuş adı tablosunu yeniden üret:  make -C deskhand/yardimci tuslar   (linux/input-event-codes.h)
CC ?= gcc
CFLAGS ?= -O2 -Wall
DATA_DIR ?= $(or $(DESKHAND_DATA_DIR),$(HOME)/.local/share/deskhand)
PROTOKOL_XML ?= $(shell pkg-config --variable=pkgdatadir wayland-protocols 2>/dev/null)/staging/ext-idle-notify/ext-idle-notify-v1.xml

deskhand-etkinlik: deskhand-etkinlik.c ext-idle-notify-v1-protocol.c ext-idle-notify-v1-client-protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ deskhand-etkinlik.c ext-idle-notify-v1-protocol.c $$(pkg-config --cflags --libs wayland-client)

deskhand-goruntu: deskhand-goruntu.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ deskhand-goruntu.c $$(pkg-config --cflags --libs libsystemd)

EIS_PAKETLER = libei-1.0 xkbcommon libsystemd

# libei/xkbcommon/libsystemd geliştirme dosyaları yoksa açık bir iletiyle atlanır (çıkış 0: `make` diğer hedefleri
# derlemeye devam eder; deskhand-eis yokken arka plan KWin oturumu kurulamaz, Xvfb kalır)
deskhand-eis: deskhand-eis.c deskhand-eis-tuslar.h
	@if pkg-config --exists $(EIS_PAKETLER) 2>/dev/null; then \
	  $(CC) $(CPPFLAGS) $(CFLAGS) -Wextra $(LDFLAGS) -o $@ deskhand-eis.c $$(pkg-config --cflags --libs $(EIS_PAKETLER)) -lm \
	  || exit 1; \
	else \
	  echo "deskhand-eis ATLANDI: libei / libxkbcommon / libsystemd geliştirme dosyaları yok (pkg-config $(EIS_PAKETLER))" >&2; \
	fi

tuslar:
	{ echo '/* deskhand-eis: dotool tuş adı -> evdev kodu (linux/input-event-codes.h den üretildi: make tuslar) */'; \
	  LC_ALL=C awk '/^#define[ \t]+KEY_[A-Z0-9_]+[ \t]/ { n=substr($$2,5); if (n!="MAX" && n!="CNT" && n!="MIN_INTERESTING") \
	  printf "    {\"%s\", KEY_%s},\n", tolower(n), n }' /usr/include/linux/input-event-codes.h; } > deskhand-eis-tuslar.h

protokol:
	wayland-scanner client-header $(PROTOKOL_XML) ext-idle-notify-v1-client-protocol.h
	wayland-scanner private-code $(PROTOKOL_XML) ext-idle-notify-v1-protocol.c

kur: deskhand-etkinlik
	install -Dm755 deskhand-etkinlik $(DATA_DIR)/etkinlik/deskhand-etkinlik

temizle:
	$(RM) deskhand-etkinlik deskhand-goruntu deskhand-eis

.PHONY: protokol tuslar kur temizle
