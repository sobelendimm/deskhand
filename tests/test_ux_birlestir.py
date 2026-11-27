"""tools/ux_birlestir.py testleri — yalnız tmp_path'teki geçici git depolarında (gerçek depoya, ekrana dokunmaz).

Geçici depoda türetilmiş dosya üreticileri (i18n_cikar, tasarim_kapi, test_atspi_kural, test_gorsel_taban, test_kos)
küçük sahte betiklerdir; araç hedef deponun kendi betiklerini çağırdığı için gerçek akış aynen sınanır.

Çalıştır:  python3 -m pytest -x -q tests/test_ux_birlestir.py   (ya da python3 tests/test_ux_birlestir.py)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap

import pytest

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARAC = os.path.join(KOK, "tools", "ux_birlestir.py")

_spec = importlib.util.spec_from_file_location("ux_birlestir", ARAC)
assert _spec and _spec.loader
ub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ub)

SAHTE = {
    "tools/i18n_cikar.py": """
        import json
        en = json.load(open("deskhand/i18n/en.json", encoding="utf-8"))
        with open("deskhand/i18n/kaynak.json", "w", encoding="utf-8") as f:
            json.dump({k: ["x.py:1"] for k in sorted(en)}, f, ensure_ascii=False, indent=1)
            f.write("\\n")
        """,
    "tools/tasarim_kapi.py": """
        import json, sys
        assert "--bilinen-yaz" in sys.argv
        satir = [s for s in open("tests/_ihlal_tasarim.txt", encoding="utf-8").read().splitlines() if s]
        with open("tests/tasarim_bilinen.json", "w", encoding="utf-8") as f:
            json.dump(sorted(satir), f, ensure_ascii=False, indent=1)
            f.write("\\n")
        """,
    "tests/test_atspi_kural.py": """
        import json, os
        if os.environ.get("ATSPI_BILINEN_YAZ") == "1":
            satir = [s for s in open("tests/_ihlal_atspi.txt", encoding="utf-8").read().splitlines() if s]
            with open("tests/atspi_bilinen.json", "w", encoding="utf-8") as f:
                json.dump({"aciklama": "x", "ihlaller": {s: 1 for s in satir}}, f, ensure_ascii=False, indent=1)
                f.write("\\n")
        """,
    "tests/test_gorsel_taban.py": """
        import os
        if os.environ.get("GORSEL_GUNCELLE") == "1":
            os.makedirs("tests/gorsel_taban", exist_ok=True)
            renk = open("deskhand/gui/renk.txt", encoding="utf-8").read()
            with open("tests/gorsel_taban/panel.png", "w", encoding="utf-8") as f:
                f.write(renk)
            if "yeni-ekran" in renk:
                with open("tests/gorsel_taban/yeni.png", "w", encoding="utf-8") as f:
                    f.write("yeni")
        """,
    "tools/test_kos.py": """
        import os, sys
        print("ARGS", " ".join(sys.argv[1:]))
        print("HOME", os.environ.get("HOME"))
        rc = int(open("tests/_test_sonuc").read().strip() or 0)
        print(f"{1 - (rc != 0)}/1 takım geçti")
        sys.exit(rc)
        """,
}

TABAN_EN = {"a": "A", "b": "B", "c": "C", "d": "D", "e": "Ç"}


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def yaz(repo, yol, icerik):
    p = os.path.join(str(repo), yol)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(icerik)


def en_yaz(repo, d):
    yaz(repo, "deskhand/i18n/en.json", json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def en_oku(repo):
    with open(os.path.join(str(repo), "deskhand/i18n/en.json"), encoding="utf-8") as f:
        return f.read()


def commit(repo, mesaj):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", mesaj)


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    ev = tmp_path / "ev"
    ev.mkdir()
    for k, v in {"HOME": str(ev), "XDG_CONFIG_HOME": str(ev / ".config"), "XDG_STATE_HOME": str(ev / ".state"),
                 "XDG_DATA_HOME": str(ev / ".data"), "XDG_CACHE_HOME": str(ev / ".cache"),
                 "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "LANG": "C.UTF-8"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    repo = tmp_path / "depo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "ana")
    for yol, kod in SAHTE.items():
        yaz(repo, yol, textwrap.dedent(kod).lstrip())
    en_yaz(repo, TABAN_EN)
    yaz(repo, "deskhand/i18n/kaynak.json", "{}\n")
    yaz(repo, "deskhand/gui/renk.txt", "mavi\n")
    yaz(repo, "deskhand/gui/panel.py", "x = 1\n")
    yaz(repo, "tests/_ihlal_tasarim.txt", "T1\n")
    yaz(repo, "tests/_ihlal_atspi.txt", "A1\n")
    yaz(repo, "tests/_test_sonuc", "0\n")
    yaz(repo, "tests/tasarim_bilinen.json", '[\n "T1"\n]\n')
    yaz(repo, "tests/atspi_bilinen.json", '{\n "aciklama": "x",\n "ihlaller": {\n  "A1": 1\n }\n}\n')
    yaz(repo, "tests/gorsel_taban/panel.png", "mavi\n")
    yaz(repo, "README.md", "satir1\nsatir2\nsatir3\n")
    commit(repo, "taban")
    return repo


def dal(repo, ad, degistir, mesaj, tabandan="ana"):
    git(repo, "checkout", "-q", "-b", ad, tabandan)
    degistir(repo)
    commit(repo, mesaj)
    git(repo, "checkout", "-q", "ana")


def kos(repo, *args):
    return subprocess.run([sys.executable, ARAC, *args, "--hedef", str(repo), "--kafes", ""],
                          capture_output=True, text=True, timeout=60)


def temiz_mi(repo, bas):
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") == bas
    assert not os.path.exists(os.path.join(str(repo), ".git", "MERGE_HEAD"))


# --- saf üç yollu birleşim ------------------------------------------------------------------------------------------

def test_uc_yollu_ekleme_silme_ayni_deger():
    b = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    o = {"a": 1, "d": 40, "c": 3, "x": 9, "e": 50}          # b sildi, d ve e değiştirdi, x ekledi
    t = {"a": 1, "d": 40, "e": 5, "y": 8}           # b ve c sildi (b iki taraflı), d aynı değer, y ekledi
    birlesik, cakisma = ub.uc_yollu(b, o, t)
    assert cakisma == []
    assert list(birlesik.items()) == [("a", 1), ("d", 40), ("x", 9), ("e", 50), ("y", 8)]


def test_uc_yollu_deger_cakismasi():
    b = {"a": 1, "k": 0}
    birlesik, cakisma = ub.uc_yollu(b, {"a": 2, "k": 0, "n": 1}, {"a": 3, "k": 0, "n": 2})
    assert cakisma == ["a", "n"]


def test_uc_yollu_silme_ve_degistirme_cakismadir():
    _, cakisma = ub.uc_yollu({"a": 1}, {}, {"a": 2})
    assert cakisma == ["a"]


def test_json_bicim_korunur():
    metin = '{\n "a": "Ç"\n}\n'
    assert ub.json_bicimle({"a": "Ç", "b": "x"}, metin) == '{\n "a": "Ç",\n "b": "x"\n}\n'
    metin2 = '{\n  "a": "\\u00c7"\n}'
    assert ub.json_bicimle({"a": "Ç"}, metin2) == '{\n  "a": "\\u00c7"\n}'


# --- uçtan uca (geçici git deposu) ----------------------------------------------------------------------------------

def test_basarili_birlesim_en_json_uc_yollu_ve_commit(ortam):
    repo = ortam

    def ours(r):
        en_yaz(r, {"a": "A2", "c": "C", "d": "D2", "e": "Ç", "x": "X"})      # b sildi, d aynı yeni değer
    def theirs(r):
        en_yaz(r, {"a": "A", "d": "D2", "e": "Ç", "y": "Y"})                # b ve c sildi, y ekledi
        yaz(r, "deskhand/gui/renk.txt", "kirmizi yeni-ekran\n")
    dal(repo, "ux-z", theirs, "feat(ui): red panel")
    ours(repo)
    commit(repo, "ana ilerledi")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.splitlines()[0].startswith("UX-BIRLESTIR: TAMAM")
    assert git(repo, "status", "--porcelain") == ""
    ebeveyn = git(repo, "rev-list", "--parents", "-n1", "HEAD").split()
    assert ebeveyn[1] == bas and len(ebeveyn) == 3
    en = json.loads(en_oku(repo))
    assert list(en.items()) == [("a", "A2"), ("d", "D2"), ("e", "Ç"), ("x", "X"), ("y", "Y")]
    assert en_oku(repo).endswith("}\n") and "Ç" in en_oku(repo)
    kaynak = json.load(open(os.path.join(str(repo), "deskhand/i18n/kaynak.json"), encoding="utf-8"))
    assert sorted(kaynak) == sorted(en)
    mesaj = git(repo, "log", "-1", "--format=%B")
    assert mesaj.splitlines()[0] == "merge: ux-z (feat(ui): red panel) into ana"
    assert "en.json" in mesaj and "+1" in mesaj and "value conflicts 0" in mesaj
    assert "tests/gorsel_taban/yeni.png" in p.stdout     # değişen görsel taban gözle denetim için listelenir
    assert os.path.exists(os.path.join(str(repo), "tests/gorsel_taban/yeni.png"))


def test_deger_cakismasi_cikis_3_depo_temiz(ortam):
    repo = ortam
    dal(repo, "ux-z", lambda r: en_yaz(r, {**TABAN_EN, "a": "THEIRS"}), "t")
    en_yaz(repo, {**TABAN_EN, "a": "OURS"})
    commit(repo, "o")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z")
    assert p.returncode == 3, p.stdout + p.stderr
    assert p.stdout.splitlines()[0].startswith("UX-BIRLESTIR: DUR")
    assert '"a"' in p.stdout or " a" in p.stdout
    temiz_mi(repo, bas)


def test_i18n_disi_cakisma_cikis_3_depo_temiz(ortam):
    repo = ortam
    dal(repo, "ux-z", lambda r: yaz(r, "README.md", "satir1\nTHEIRS\nsatir3\n"), "t")
    yaz(repo, "README.md", "satir1\nOURS\nsatir3\n")
    commit(repo, "o")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "README.md" in p.stdout
    temiz_mi(repo, bas)


def test_turetilmis_dosya_cakismasi_yeniden_uretilir(ortam):
    """Görsel taban PNG'si iki tarafta da değişti (ux-f yeniden oynatmasında görülen durum): çakışma türetilmiş
    dosyada → taraf seçilip üretici yeniden yazar; sonuç üreticinin çıktısıdır."""
    repo = ortam

    def theirs(r):
        yaz(r, "deskhand/gui/renk.txt", "yesil\n")
        yaz(r, "tests/gorsel_taban/panel.png", "yesil-eski\n")
    dal(repo, "ux-z", theirs, "t")
    yaz(repo, "deskhand/gui/panel.py", "x = 9\n")
    yaz(repo, "tests/gorsel_taban/panel.png", "mor\n")
    commit(repo, "o")
    p = kos(repo, "ux-z")
    assert p.returncode == 0, p.stdout + p.stderr
    assert open(os.path.join(str(repo), "tests/gorsel_taban/panel.png")).read() == "yesil\n"
    assert git(repo, "status", "--porcelain") == ""


def test_turetilmis_cakisma_gui_degismese_de_yeniden_uretilir(ortam):
    repo = ortam
    dal(repo, "ux-z", lambda r: yaz(r, "tests/gorsel_taban/panel.png", "a\n"), "t")
    yaz(repo, "tests/gorsel_taban/panel.png", "b\n")
    commit(repo, "o")
    p = kos(repo, "ux-z")
    assert p.returncode == 0, p.stdout + p.stderr
    assert open(os.path.join(str(repo), "tests/gorsel_taban/panel.png")).read() == "mavi\n"


def test_yeni_bilinen_kayit_cikis_4_depo_temiz(ortam):
    repo = ortam

    def theirs(r):
        yaz(r, "deskhand/gui/panel.py", "x = 2\n")
        yaz(r, "tests/_ihlal_tasarim.txt", "T1\nT_YENI\n")           # yeni ihlal, bilinen listesine girmemiş
    dal(repo, "ux-z", theirs, "t")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z")
    assert p.returncode == 4, p.stdout + p.stderr
    assert "T_YENI" in p.stdout
    temiz_mi(repo, bas)


def test_dalda_bilinen_kayit_varsa_gecer(ortam):
    repo = ortam

    def theirs(r):
        yaz(r, "deskhand/gui/panel.py", "x = 2\n")
        yaz(r, "tests/_ihlal_atspi.txt", "A1\nA2\n")
        yaz(r, "tests/atspi_bilinen.json", '{\n "aciklama": "x",\n "ihlaller": {\n  "A1": 1,\n  "A2": 1\n }\n}\n')
    dal(repo, "ux-z", theirs, "t")
    p = kos(repo, "ux-z")
    assert p.returncode == 0, p.stdout + p.stderr


def test_kuru_depo_degismez(ortam):
    repo = ortam

    def theirs(r):
        en_yaz(r, {**TABAN_EN, "y": "Y"})
        yaz(r, "deskhand/gui/renk.txt", "kirmizi yeni-ekran\n")
    dal(repo, "ux-z", theirs, "t")
    en_yaz(repo, {**TABAN_EN, "x": "X"})
    commit(repo, "o")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z", "--kuru")
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.splitlines()[0].startswith("UX-BIRLESTIR: TAMAM")
    assert "+1" in p.stdout
    temiz_mi(repo, bas)
    assert not os.path.exists(os.path.join(str(repo), "tests/gorsel_taban/yeni.png"))


def test_zaten_guncel_cikis_0(ortam):
    repo = ortam
    dal(repo, "ux-z", lambda r: yaz(r, "README.md", "z\n"), "t")
    git(repo, "merge", "-q", "--no-edit", "ux-z")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z", "--kuru")
    assert p.returncode == 0, p.stdout + p.stderr
    temiz_mi(repo, bas)


def test_kirli_hedef_cikis_2(ortam):
    repo = ortam
    dal(repo, "ux-z", lambda r: yaz(r, "README.md", "z\n"), "t")
    yaz(repo, "README.md", "kirli\n")
    p = kos(repo, "ux-z")
    assert p.returncode == 2
    assert kos(repo, "yok-boyle-dal").returncode == 2


def test_test_kalirsa_cikis_5_ve_test_listesi(ortam):
    repo = ortam

    def theirs(r):
        yaz(r, "deskhand/gui/panel.py", "x = 3\n")
        yaz(r, "tests/test_panel.py", "")
        yaz(r, "tests/_test_sonuc", "1\n")
    dal(repo, "ux-z", theirs, "t")
    bas = git(repo, "rev-parse", "HEAD")
    p = kos(repo, "ux-z")
    assert p.returncode == 5, p.stdout + p.stderr
    assert "test_panel" in p.stdout                    # değişen modülün test dosyası listeye girdi
    assert "HOME " + os.environ["HOME"] not in p.stdout  # testler geçici HOME ile
    temiz_mi(repo, bas)


def test_yama_uygulanir_ve_bozuk_yama_cikis_3(ortam, tmp_path):
    repo = ortam
    dal(repo, "ux-z", lambda r: yaz(r, "notlar.txt", "bir\n"), "t")
    iyi = tmp_path / "iyi.patch"
    iyi.write_text("--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n satir1\n-satir2\n+YAMA\n satir3\n")
    bas = git(repo, "rev-parse", "HEAD")
    bozuk = tmp_path / "bozuk.patch"
    bozuk.write_text("--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n yok1\n-yok2\n+YAMA\n yok3\n")
    p = kos(repo, "ux-z", "--yama", str(bozuk))
    assert p.returncode == 3, p.stdout + p.stderr
    temiz_mi(repo, bas)
    p = kos(repo, "ux-z", "--yama", str(iyi), "--testler", "test_a")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "YAMA" in open(os.path.join(str(repo), "README.md")).read()
    assert "tests: test_a →" in p.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "-q"]))
