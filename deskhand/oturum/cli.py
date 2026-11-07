"""Oturum köprüsü alt komutları: `main(argv)` (ana cli.py'ye koordinatör bağlar). İngilizce adlar birincil,
Türkçeleri takma ad (status/durum, prepare/hazirla, policy/politika, clear/sil; komutlar.OTURUM).

  durum [<uygulama>]        uygulama başına: kurulu mu, kullanıcıda açık mı, politika, kopya var mı
  hazirla <uygulama> [--site ALAN ...] [--json]   kararı + (kopya ise) argv'yi üret
  politika [<uygulama>]     çözülmüş politikayı yaz
  sil                       tüm oturum kopyalarını sil

Sır değerleri yazılmaz. `hazirla` kopya üretir (kaynak YAZILMAZ) ama uygulamayı BAŞLATMAZ.
"""
from __future__ import annotations

import argparse
import json
import os

from ..i18n import _, h_
from ..komutlar import OTURUM
from . import Hazirlik, hazirla, sil_hepsi
from . import chromium, kopya, politika, tespit


def _durum_satiri(ad: str, yap: dict) -> dict:
    pol = politika.coz(ad, yap)
    calisiyor, ayrinti = tespit.calisiyor_mu(pol.uygulama, pol.flatpak)
    kurulu = _kurulu_mu(pol)
    return {"uygulama": pol.uygulama, "kurulu": kurulu, "acik": calisiyor,
            "kapali_iken": pol.kapali_iken, "acik_iken": pol.acik_iken,
            "keyring": pol.keyring, "flatpak": pol.flatpak, "ayrinti": ayrinti}


def _kurulu_mu(pol) -> bool:
    if pol.flatpak:
        base = os.path.join(os.path.expanduser("~"), ".var", "app", pol.flatpak)
        if os.path.isdir(base):
            return True
    if pol.uygulama == "firefox":
        return tespit.firefox_profil_dizini() is not None
    if pol.uygulama in ("chromium", "vivaldi", "chrome", "brave"):
        return tespit.chromium_veri_dizini(pol.uygulama) is not None
    import shutil
    return shutil.which(pol.uygulama) is not None


def _kopya_var(ad: str) -> list[str]:
    kok = politika.kopya_dizini()
    if not os.path.isdir(kok):
        return []
    return [d for d in sorted(os.listdir(kok)) if d.startswith(ad + "-")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="deskhand sessions", description=h_("Oturum köprüsü"))
    alt = p.add_subparsers(dest="komut", required=True)
    en = {tr: en for en, tr in OTURUM.items()}

    def komut(tr, yardim):
        s = alt.add_parser(en[tr], aliases=[tr], help=yardim)
        s.set_defaults(komut=tr)  # içeride Türkçe ad
        return s

    pd = komut("durum", h_("uygulama durumları"))
    pd.add_argument("uygulama", nargs="?")
    pd.add_argument("--json", action="store_true")

    ph = komut("hazirla", h_("kararı + kopyayı üret (başlatmaz)"))
    ph.add_argument("uygulama")
    ph.add_argument("--site", nargs="*", default=None, help=h_("göreve özel izinli alan adları"))
    ph.add_argument("--json", action="store_true")

    pp = komut("politika", h_("çözülmüş politika"))
    pp.add_argument("uygulama", nargs="?")
    pp.add_argument("--json", action="store_true")

    komut("sil", h_("tüm oturum kopyalarını sil"))

    a = p.parse_args(argv)
    yap = politika.yukle()

    if a.komut == "durum":
        adlar = [a.uygulama] if a.uygulama else sorted(yap.get("uygulama", {}).keys() - {"_varsayilan"})
        satirlar = [_durum_satiri(ad, yap) for ad in adlar]
        for s in satirlar:
            s["kopyalar"] = _kopya_var(s["uygulama"])
        if a.json:
            print(json.dumps(satirlar, ensure_ascii=False, indent=2))
        else:
            for s in satirlar:
                k = _("kurulu") if s["kurulu"] else _("yok")
                ac = _("AÇIK") if s["acik"] else _("kapalı")
                print(_("{uygulama} {kurulu} {acik} kapalıyken={kapali_iken} açıkken={acik_iken} keyring={keyring} "
                        "kopya={kopya}").format(
                    uygulama=f"{s['uygulama']:12}", kurulu=f"{k:6}", acik=f"{ac:6}", kapali_iken=f"{s['kapali_iken']:6}",
                    acik_iken=f"{s['acik_iken']:6}", keyring="e" if s["keyring"] else "h", kopya=len(s["kopyalar"])))
        return 0

    if a.komut == "politika":
        adlar = [a.uygulama] if a.uygulama else sorted(yap.get("uygulama", {}).keys())
        cikti = {}
        for ad in adlar:
            pol = politika.coz(ad, yap)
            cikti[pol.uygulama] = {"kapali_iken": pol.kapali_iken, "acik_iken": pol.acik_iken,
                                   "keyring": pol.keyring, "flatpak": pol.flatpak,
                                   "disla": list(pol.disla), "not": pol.not_}
        print(json.dumps(cikti, ensure_ascii=False, indent=2) if a.json else
              "\n".join(f"{k}: {v['kapali_iken']}/{v['acik_iken']} keyring={v['keyring']}"
                        for k, v in cikti.items()))
        return 0

    if a.komut == "hazirla":
        h: Hazirlik = hazirla(a.uygulama, gorev_siteleri=a.site)
        cikti = {"karar": h.karar, "aciklama": h.aciklama, "kopya_yolu": h.kopya_yolu,
                 "gerekli_keyring": h.gerekli_keyring, "argv": h.argv, "env_ek": h.env_ek,
                 "ayrinti": h.ayrinti}
        if a.json:
            print(json.dumps(cikti, ensure_ascii=False, indent=2))
        else:
            print(_("karar: {karar}").format(karar=h.karar))
            if h.aciklama:
                print(_("açıklama: {aciklama}").format(aciklama=h.aciklama))
            if h.kopya_yolu:
                print(_("kopya: {yol}").format(yol=h.kopya_yolu))
            if h.argv:
                print("argv: " + " ".join(h.argv))
        return 0 if h.karar in ("kopya", "paylas") else 3

    if a.komut == "sil":
        n = sil_hepsi()
        print(_("{sayi} kopya silindi").format(sayi=n))
        return 0

    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
