#!/usr/bin/env python3
"""Bir UX dalını hedef worktree'ye tek komutla birleştirir (UX-A…F birleştirmelerinde elle yapılan adımlar).

    python3 tools/ux_birlestir.py <dal> [--hedef DIR] [--yama P] [--testler a,b] [--kuru] [--trailer T …]

Adımlar:
  1. Hedef temiz (izlenen dosyada değişiklik yok) ve dal var mı → `git merge --no-commit --no-ff <dal>`.
  2. Çakışma yalnız deskhand/i18n/en.json, kaynak.json ya da türetilmiş dosyalardaysa (tests/gorsel_taban/**,
     atspi_bilinen.json, tasarim_bilinen.json; bunlar 4. adımda zorunlu yeniden üretilir) çözülür. en.json her zaman ÜÇ YOLLU birleşir
     (taban = merge-base): bir tarafın sildiği ve öbürünün değiştirmediği anahtar silinir; iki taraf aynı anahtarı
     tabandan ve birbirinden farklı değiştirdiyse (ya da biri silip öbürü değiştirdiyse) DEĞER ÇAKIŞMASI → çıkış 3.
     Sıra: ours sırası + theirs'in yeni anahtarları; biçim (girinti, ensure_ascii, sondaki satır sonu) ours'tan.
     kaynak.json `tools/i18n_cikar.py` ile yeniden üretilir. Başka dosyada çakışma → abort, çıkış 3.
  3. --yama verilirse `git apply --3way` (başarısızsa abort, çıkış 3).
  4. deskhand/gui/** değiştiyse ya da türetilmiş dosya çakıştıysa görsel taban, AT-SPI bilinen ve tasarım bilinen yeniden yazılır. Yeniden yazılan
     bilinen listelerinde İKİ ebeveynde de olmayan kayıt = YENİ İHLAL → abort, çıkış 4 (sessizce "bilinen" olmaz).
  5. Testler (--testler ya da VARSAYILAN_TESTLER + değişen modüllerin test dosyaları, eşleme: test_takimlari())
     `<kafes> env HOME=<geçici> XDG_*=<geçici> python3 tools/test_kos.py …` ile; kalan varsa abort, çıkış 5.
  6. Commit: `merge: <dal> (<dalın son commit konusu>) into <hedef>` + en.json özeti, yeniden üretilenler, test.
  --kuru: 1-5 yapılır, sonda `git merge --abort` (yeni izlenmeyen dosyalar da silinir) → depo değişmez.

Çıkış: 0 tamam (ya da zaten güncel) · 2 ön koşul/kullanım · 3 çakışma ya da yama · 4 yeni bilinen kayıt ·
5 türetilmiş dosya üretilemedi ya da test kaldı · 6 commit başarısız.
Çıktının ilk satırı `UX-BIRLESTIR: TAMAM` ya da `UX-BIRLESTIR: DUR <neden>` (protokol sözcükleri çevrilmez).
Stdlib-only; uygulama paketini içe aktarmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import site
import subprocess
import sys
import tempfile

EN = "deskhand/i18n/en.json"
KAYNAK = "deskhand/i18n/kaynak.json"
ATSPI = "tests/atspi_bilinen.json"
TASARIM = "tests/tasarim_bilinen.json"
GORSEL = "tests/gorsel_taban"
GUI = "deskhand/gui/"
VARSAYILAN_TESTLER = ["test_gui", "test_tema", "test_tasarim_kapi", "test_gorsel_taban", "test_atspi_kural",
                      "test_i18n"]
VARSAYILAN_KAFES = "agir-is -m 4G"
YOK = object()


# --- dil --------------------------------------------------------------------------------------------------------------

def _dil(env=None) -> str:
    """deskhand.i18n.sistem_dili ile aynı kural (DESKHAND_DIL önce): tr ya da en."""
    env = os.environ if env is None else env
    zorla = (env.get("DESKHAND_DIL") or "").strip().lower()[:2]
    if zorla in ("tr", "en"):
        return zorla
    loc = next(((env.get(v) or "").strip() for v in ("LC_ALL", "LC_MESSAGES", "LANG") if (env.get(v) or "").strip()), "")
    if not loc or loc in ("C", "POSIX") or loc.startswith(("C.", "POSIX.")):
        return "en"
    for oge in (env.get("LANGUAGE") or "").split(":"):
        if oge.strip()[:2].lower() in ("tr", "en"):
            return oge.strip()[:2].lower()
    return "tr" if loc[:2].lower() == "tr" else "en"


DIL = _dil()


def t(tr: str, en: str) -> str:
    return tr if DIL == "tr" else en


# --- saf yardımcılar --------------------------------------------------------------------------------------------------

def uc_yollu(b: dict, o: dict, th: dict) -> tuple[dict, list]:
    """Üç yollu sözlük birleşimi → (birleşik, değer çakışan anahtarlar). Sıra: o sırası + th'nin yeni anahtarları."""
    sira = list(o) + [k for k in th if k not in o]
    birlesik, cakisma = {}, []
    for k in sira:
        bv, ov, tv = b.get(k, YOK), o.get(k, YOK), th.get(k, YOK)
        if k in b and (ov is YOK or tv is YOK):        # bir taraf sildi
            kalan = tv if ov is YOK else ov
            if kalan is not YOK and kalan != bv:       # öbürü değiştirdi → silme/değiştirme çakışması
                cakisma.append(k)
            continue
        if ov is not YOK and tv is not YOK and ov != tv and ov != bv and tv != bv:
            cakisma.append(k)
            continue
        birlesik[k] = tv if tv is not YOK and (ov is YOK or tv != bv) else ov
    return birlesik, cakisma


def json_bicimle(d: dict, ornek: str) -> str:
    """d'yi ornek metnin biçimiyle yazar: girinti, ensure_ascii, sondaki satır sonu."""
    satirlar = ornek.splitlines()
    girinti = 1
    if len(satirlar) > 1 and satirlar[1].strip():
        girinti = len(satirlar[1]) - len(satirlar[1].lstrip(" ")) or 1
    ascii_ = "\\u" in ornek and ornek.isascii()
    return json.dumps(d, ensure_ascii=ascii_, indent=girinti) + ("\n" if ornek.endswith("\n") else "")


def kayitlar(metin: str | None) -> set:
    """Bilinen listesi kayıtları: {"ihlaller": {...}} → anahtarlar; liste → ögeler; sözlük → anahtarlar."""
    if not metin:
        return set()
    try:
        veri = json.loads(metin)
    except ValueError:
        return set()
    if isinstance(veri, dict) and isinstance(veri.get("ihlaller"), dict):
        return set(veri["ihlaller"])
    if isinstance(veri, list):
        return {json.dumps(x, sort_keys=True) if not isinstance(x, str) else x for x in veri}
    return set(veri) if isinstance(veri, dict) else set()


def test_takimlari(degisen: list[str], kok: str, secili: list[str] | None = None) -> list[str]:
    """Koşulacak takımlar (eşleme kuralı TEK yer): seçili ya da varsayılan UX listesi + değişen deskhand/**/x.py için
    tests/test_x.py + değişen tests/test_*.py. Yalnız hedefte var olanlar."""
    liste = list(secili) if secili else list(VARSAYILAN_TESTLER)
    if not secili:
        for d in degisen:
            ad = os.path.splitext(os.path.basename(d))[0]
            if d.startswith("deskhand/") and d.endswith(".py"):
                liste.append(f"test_{ad}")
            elif d.startswith("tests/test_") and d.endswith(".py"):
                liste.append(ad)
    sonuc = []
    for ad in liste:
        if ad not in sonuc and (secili or os.path.exists(os.path.join(kok, "tests", ad + ".py"))):
            sonuc.append(ad)
    return sonuc


# --- git / süreç ------------------------------------------------------------------------------------------------------

class Dur(Exception):
    def __init__(self, kod: int, neden: str, ayrinti: list[str] | None = None):
        super().__init__(neden)
        self.kod, self.neden, self.ayrinti = kod, neden, ayrinti or []


class Birlestirici:
    def __init__(self, g: argparse.Namespace):
        self.g = g
        self.kok = ""
        self.satirlar: list[str] = []
        self.merge_basladi = False
        self.izsiz_once: set = set()
        self.gecici = tempfile.TemporaryDirectory(prefix="ux-birlestir-")

    def git(self, *args, check=True, girdi=None) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_MERGE_AUTOEDIT="no")
        p = subprocess.run(["git", "-C", self.kok, *args], capture_output=True, text=True, input=girdi, env=env,
                           timeout=600)
        if check and p.returncode:
            raise Dur(2, f"git {' '.join(args[:2])}: {p.stderr.strip()[:300]}")
        return p

    def goster(self, rev: str, yol: str) -> str | None:
        p = self.git("show", f"{rev}:{yol}", check=False)
        return p.stdout if p.returncode == 0 else None

    def izsiz(self) -> set:
        return set(self.git("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")) - {""}

    def ilerleme(self, s: str) -> None:
        print("… " + s, file=sys.stderr, flush=True)

    def gecici_ortam(self) -> list[str]:
        ev = self.gecici.name
        degisken = {"HOME": ev, "XDG_CONFIG_HOME": f"{ev}/config", "XDG_DATA_HOME": f"{ev}/data",
                    "XDG_STATE_HOME": f"{ev}/state", "XDG_CACHE_HOME": f"{ev}/cache",
                    "PYTHONUSERBASE": os.environ.get("PYTHONUSERBASE") or site.getuserbase()}
        return ["env", *(f"{k}={v}" for k, v in degisken.items())]

    def calistir(self, komut: list[str], ek_env: dict | None = None) -> subprocess.CompletedProcess:
        """Kafes (agir-is) gerçek ortamla, çocuk süreç geçici HOME/XDG ile koşar."""
        ekler = [f"{k}={v}" for k, v in (ek_env or {}).items()]
        tam = shlex.split(self.g.kafes) + self.gecici_ortam() + ekler + komut
        try:
            return subprocess.run(tam, cwd=self.kok, capture_output=True, text=True, timeout=self.g.zaman)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(tam, 124, "", t(f"ZAMAN AŞIMI ({self.g.zaman} sn)",
                                                                f"TIMEOUT ({self.g.zaman} s)"))

    def geri_al(self) -> None:
        if self.merge_var():
            # Ön koşulda izlenen dosyalar temizdi: bütün izlenen değişiklik bizim. Dizine alınmamış değişikliği
            # `git merge --abort` (reset --merge) korur; önce dizine alınır ki abort hepsini geri alsın.
            self.git("add", "-u", check=False)
            self.git("merge", "--abort", check=False)
        for yol in sorted(self.izsiz() - self.izsiz_once, reverse=True):
            tam = os.path.join(self.kok, yol)
            try:
                os.remove(tam)
                d = os.path.dirname(tam)
                while d.startswith(self.kok + os.sep) and not os.listdir(d):
                    os.rmdir(d)
                    d = os.path.dirname(d)
            except OSError:
                pass

    def merge_var(self) -> bool:
        yol = self.git("rev-parse", "--git-path", "MERGE_HEAD").stdout.strip()
        return os.path.exists(yol if os.path.isabs(yol) else os.path.join(self.kok, yol))

    # --- adımlar ------------------------------------------------------------------------------------------------------

    def kos(self) -> int:
        g = self.g
        p = subprocess.run(["git", "-C", g.hedef or os.getcwd(), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=60)
        if p.returncode:
            raise Dur(2, t("hedef bir git worktree'si değil", "target is not a git worktree"))
        self.kok = p.stdout.strip()
        if self.git("rev-parse", "--verify", "--quiet", f"{g.dal}^{{commit}}", check=False).returncode:
            raise Dur(2, t(f"dal yok: {g.dal}", f"no such branch: {g.dal}"))
        if self.merge_var():
            raise Dur(2, t("hedefte süren bir birleştirme var", "a merge is already in progress in the target"))
        kirli = self.git("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if kirli:
            raise Dur(2, t("hedef worktree temiz değil", "target worktree is not clean"), kirli.splitlines()[:20])
        if g.yama and not os.path.isfile(g.yama):
            raise Dur(2, t(f"yama yok: {g.yama}", f"patch not found: {g.yama}"))
        hedef_ad = self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if hedef_ad == "HEAD":
            hedef_ad = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        konu = self.git("log", "-1", "--format=%s", g.dal).stdout.strip()
        bas = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.satirlar.append(f"{t('dal', 'branch')}: {g.dal} → {hedef_ad} ({bas})"
                             + (t(" [kuru deneme]", " [dry run]") if g.kuru else ""))
        self.izsiz_once = self.izsiz()

        # 1. birleştir
        self.ilerleme(f"git merge --no-commit --no-ff {g.dal}")
        p = self.git("merge", "--no-commit", "--no-ff", g.dal, check=False)
        if not self.merge_var():
            if p.returncode == 0:
                self.satirlar.append(t("zaten güncel: birleştirilecek bir şey yok", "already up to date: nothing to merge"))
                return 0
            raise Dur(3, t("git merge başarısız", "git merge failed"), (p.stdout + p.stderr).strip().splitlines()[:20])
        self.merge_basladi = True

        # 2. çakışmalar + en.json üç yollu
        cakisan = self.git("diff", "--name-only", "--diff-filter=U").stdout.split()
        turetilmis = [d for d in cakisan if d.startswith(GORSEL + "/") or d in (ATSPI, TASARIM)]
        disari = [d for d in cakisan if d not in (EN, KAYNAK) and d not in turetilmis]
        if disari:
            raise Dur(3, t("i18n dışı dosyada çakışma", "conflict outside i18n files"), disari)
        for yol in turetilmis:  # türetilmiş: geçici olarak bir taraf alınır, 4. adım üreticiyle yeniden yazar
            asamalar = {s.split()[2] for s in self.git("ls-files", "-u", "--", yol).stdout.splitlines()}
            if "2" in asamalar or "3" in asamalar:
                self.git("checkout", "--ours" if "2" in asamalar else "--theirs", "--", yol)
                self.git("add", "--", yol)
            else:
                self.git("rm", "-q", "--cached", "--", yol)
        taban = self.git("merge-base", "HEAD", "MERGE_HEAD").stdout.strip()
        metinler = {r: self.goster(r, EN) for r in (taban, "HEAD", "MERGE_HEAD")}
        self.en_ozet = None
        if all(m is not None for m in metinler.values()):
            try:
                b, o, th = (json.loads(metinler[r] or "") for r in (taban, "HEAD", "MERGE_HEAD"))
            except ValueError as e:
                raise Dur(3, t("en.json okunamadı", "en.json is not valid JSON"), [str(e)]) from None
            birlesik, cakisma = uc_yollu(b, o, th)
            if cakisma:
                raise Dur(3, t(f"en.json değer çakışması ({len(cakisma)})", f"en.json value conflict ({len(cakisma)})"),
                          [f'"{k}"' for k in cakisma[:50]])
            with open(os.path.join(self.kok, EN), "w", encoding="utf-8") as f:
                f.write(json_bicimle(birlesik, metinler["HEAD"] or ""))
            self.git("add", "--", EN)
            self.en_ozet = (sum(k not in o for k in birlesik), sum(k not in birlesik for k in o),
                            sum(k in o and o[k] != v for k, v in birlesik.items()))
            self.satirlar.append(f"en.json: +{self.en_ozet[0]} -{self.en_ozet[1]} ~{self.en_ozet[2]}, "
                                 + t("değer çakışması 0", "value conflicts 0"))
        elif EN in cakisan:
            raise Dur(3, t("en.json bir tarafta yok (silme çakışması)", "en.json missing on one side (delete conflict)"),
                      [EN])
        yeniden = []
        if os.path.exists(os.path.join(self.kok, "tools/i18n_cikar.py")):
            self.ilerleme("tools/i18n_cikar.py")
            p = self.calistir([sys.executable, "tools/i18n_cikar.py"])
            if p.returncode:
                raise Dur(5, t("kaynak.json üretilemedi", "kaynak.json could not be regenerated"),
                          (p.stdout + p.stderr).strip().splitlines()[-10:])
            if KAYNAK in cakisan or self.git("diff", "--quiet", "--", KAYNAK, check=False).returncode:
                yeniden.append(KAYNAK)
            self.git("add", "--", KAYNAK)
        elif KAYNAK in cakisan:
            raise Dur(3, t("kaynak.json çakıştı ama tools/i18n_cikar.py yok", "kaynak.json conflicted, no i18n_cikar.py"))
        kalan = self.git("diff", "--name-only", "--diff-filter=U").stdout.split()
        if kalan:
            raise Dur(3, t("çözülemeyen çakışma", "unresolved conflict"), kalan)

        # 3. yama
        if g.yama:
            self.ilerleme(f"git apply --3way {g.yama}")
            p = self.git("apply", "--3way", os.path.abspath(g.yama), check=False)
            if p.returncode:
                raise Dur(3, t("yama uygulanamadı", "patch did not apply"), (p.stdout + p.stderr).strip().splitlines()[:20])

        # 4. türetilmiş dosyalar + yeni kayıt denetimi
        degisen = self.git("diff", "--name-only", "HEAD").stdout.split()
        gorsel_degisen = []
        if turetilmis or any(d.startswith(GUI) for d in degisen):
            uretici = [("tests/test_gorsel_taban.py", [], {"GORSEL_GUNCELLE": "1"}),
                       ("tests/test_atspi_kural.py", [], {"ATSPI_BILINEN_YAZ": "1"}),
                       ("tools/tasarim_kapi.py", ["--bilinen-yaz"], {})]
            for betik, arg, env in uretici:
                if not os.path.exists(os.path.join(self.kok, betik)):
                    continue
                self.ilerleme(betik)
                p = self.calistir([sys.executable, betik, *arg], env)
                if p.returncode:
                    raise Dur(5, t(f"üretici başarısız: {betik}", f"generator failed: {betik}"),
                              (p.stdout + p.stderr).strip().splitlines()[-10:])
            for yol in (ATSPI, TASARIM):
                tam = os.path.join(self.kok, yol)
                if not os.path.exists(tam):
                    continue
                with open(tam, encoding="utf-8") as f:
                    simdi = kayitlar(f.read())
                yeni = sorted(simdi - kayitlar(self.goster("HEAD", yol)) - kayitlar(self.goster("MERGE_HEAD", yol)))
                if yeni:
                    raise Dur(4, t(f"yeni bilinen kayıt: {yol} ({len(yeni)})", f"new known entry: {yol} ({len(yeni)})"),
                              yeni[:50])
            gorsel_degisen = sorted(set(self.git("diff", "--name-only", "--", GORSEL).stdout.split())
                                    | {d for d in self.izsiz() - self.izsiz_once if d.startswith(GORSEL + "/")})
            for yol in (ATSPI, TASARIM):
                if self.git("diff", "--quiet", "--", yol, check=False).returncode:
                    yeniden.append(yol)
            if gorsel_degisen:
                yeniden.append(f"{GORSEL} ({len(gorsel_degisen)} PNG)")
            var = [y for y in (GORSEL, ATSPI, TASARIM) if os.path.exists(os.path.join(self.kok, y))]
            if var:
                self.git("add", "-A", "--", *var)

        # 5. testler
        secili = [s.strip() for s in g.testler.split(",") if s.strip()] if g.testler else None
        takimlar = test_takimlari(degisen, self.kok, secili)
        if not os.path.exists(os.path.join(self.kok, "tools/test_kos.py")):
            raise Dur(5, t("tools/test_kos.py yok", "tools/test_kos.py not found"))
        self.ilerleme("tools/test_kos.py " + " ".join(takimlar))
        p = self.calistir([sys.executable, "tools/test_kos.py", *takimlar])
        cikti = (p.stdout + p.stderr).strip().splitlines()
        test_son = next((s for s in reversed(cikti) if s.strip()), "")
        if p.returncode:
            raise Dur(5, t("test kaldı", "tests failed"), [" ".join(takimlar), *cikti[-15:]])

        # özet
        self.satirlar.append(t("yeniden üretilen: ", "regenerated: ") + (", ".join(yeniden) or "-"))
        if gorsel_degisen:
            self.satirlar.append(t("görsel taban değişti (gözle denetle):", "visual baseline changed (check by eye):"))
            self.satirlar += [f"  {os.path.join(self.kok, d)}" for d in gorsel_degisen]
        self.satirlar.append(t("testler: ", "tests: ") + " ".join(takimlar) + f" → {test_son}")

        # 6. commit ya da kuru geri alma
        if g.kuru:
            self.geri_al()
            self.satirlar.append(t("kuru deneme: git merge --abort, depo değişmedi",
                                   "dry run: git merge --abort, repository unchanged"))
            return 0
        govde = []
        if self.en_ozet:
            govde.append(f"en.json merged three-way: +{self.en_ozet[0]} added, -{self.en_ozet[1]} removed, "
                         f"~{self.en_ozet[2]} changed, value conflicts 0")
        govde.append("regenerated: " + (", ".join(yeniden) or "none") + " (no new known entries)")
        govde.append(f"tests: {' '.join(takimlar)} -> {test_son}")
        mesaj = f"merge: {g.dal} ({konu}) into {hedef_ad}\n\n" + "\n".join(govde) + "\n"
        if g.trailer:
            mesaj += "\n" + "\n".join(g.trailer) + "\n"
        p = self.git("commit", "-q", "-F", "-", check=False, girdi=mesaj)
        if p.returncode:
            raise Dur(6, t("commit başarısız", "commit failed"), (p.stdout + p.stderr).strip().splitlines()[-10:])
        self.merge_basladi = False
        kirli = self.git("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if kirli:
            self.satirlar.append(t("uyarı: commit dışında kalan değişiklik:", "warning: changes left outside the commit:"))
            self.satirlar += ["  " + s for s in kirli.splitlines()[:20]]
        self.satirlar.append(f"commit: {self.git('rev-parse', '--short', 'HEAD').stdout.strip()}")
        return 0


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("dal", help=t("birleştirilecek dal", "branch to merge"))
    a.add_argument("--hedef", help=t("hedef worktree (varsayılan: bulunduğun)", "target worktree (default: cwd)"))
    a.add_argument("--yama", help=t("git apply --3way ile uygulanacak yama", "patch applied with git apply --3way"))
    a.add_argument("--testler", help=t("virgüllü takım listesi", "comma-separated suite list"))
    a.add_argument("--kuru", action="store_true", help=t("1-5 sonra merge --abort", "steps 1-5 then merge --abort"))
    a.add_argument("--kafes", default=VARSAYILAN_KAFES, help=t("komut öneki (boş = yok)", "command prefix (empty = none)"))
    a.add_argument("--zaman", type=int, default=1800, help=t("alt komut zaman aşımı (sn)", "subcommand timeout (s)"))
    a.add_argument("--trailer", action="append", default=[], help=t("commit mesajı sonuna satır", "commit trailer line"))
    g = a.parse_args(argv)
    b = Birlestirici(g)
    try:
        kod = b.kos()
        print("UX-BIRLESTIR: TAMAM")
        print("\n".join(b.satirlar))
        return kod
    except Dur as d:
        if b.merge_basladi:
            b.geri_al()
            b.satirlar.append(t("git merge --abort: depo eski haline döndü", "git merge --abort: repository restored"))
        print(f"UX-BIRLESTIR: DUR {d.neden}")
        print("\n".join(b.satirlar + ["  " + s for s in d.ayrinti]))
        return d.kod
    finally:
        b.gecici.cleanup()


if __name__ == "__main__":
    sys.exit(main())
