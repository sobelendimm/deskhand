"""Deskhand paneli (PyQt6): Claude'u izleme/yönetme arayüzü. İnsan için otomasyon düzenleyici DEĞİLDİR:
işi ajan yapar, panel gösterir, durdurur (DUR), onaylar, ayarlar.

  python3 -m deskhand.gui [--tepsi] [--arka]

Modüller: panel (denetleyici, tek örnek), izleyici (dosya izleme → sinyaller), tepsi, pencere (sekmeler),
onay_diyalog, onizleme (arka plan önizlemesi + Devral), kisayol (KGlobalAccel), saglik, ayar, metinler (tüm
metinler, i18n için tek yer), gunluk_okur + durum (Qt'siz, test edilebilir).
"""
