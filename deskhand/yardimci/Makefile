# deskhand-etkinlik: Wayland klavye/fare etkinliği yardımcısı (insan önceliği). Yetki gerekmez.
# Derleme:  make -C deskhand/yardimci            (gereken: gcc, pkg-config, wayland istemci kitaplığı)
#           → deskhand/yardimci/deskhand-etkinlik (yollar.etkinlik_bin() burada da arar)
# Protokol dosyalarını yeniden üret:  make -C deskhand/yardimci protokol   (wayland-scanner + wayland-protocols)
# Kurulum (isteğe bağlı): make -C deskhand/yardimci kur  → $(DATA_DIR)/etkinlik/deskhand-etkinlik
CC ?= gcc
CFLAGS ?= -O2 -Wall
DATA_DIR ?= $(or $(DESKHAND_DATA_DIR),$(HOME)/.local/share/deskhand)
PROTOKOL_XML ?= $(shell pkg-config --variable=pkgdatadir wayland-protocols 2>/dev/null)/staging/ext-idle-notify/ext-idle-notify-v1.xml

deskhand-etkinlik: deskhand-etkinlik.c ext-idle-notify-v1-protocol.c ext-idle-notify-v1-client-protocol.h
	$(CC) $(CFLAGS) -o $@ deskhand-etkinlik.c ext-idle-notify-v1-protocol.c $$(pkg-config --cflags --libs wayland-client)

protokol:
	wayland-scanner client-header $(PROTOKOL_XML) ext-idle-notify-v1-client-protocol.h
	wayland-scanner private-code $(PROTOKOL_XML) ext-idle-notify-v1-protocol.c

kur: deskhand-etkinlik
	install -Dm755 deskhand-etkinlik $(DATA_DIR)/etkinlik/deskhand-etkinlik

temizle:
	$(RM) deskhand-etkinlik

.PHONY: protokol kur temizle
