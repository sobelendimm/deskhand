// Deskhand web okuma testleri: ortak tıklama günlüğü (tamamen sentetik sayfalar).
// Fare basışı (mousedown) en yakın [data-ad] ögesinin adını sayfa BAŞLIĞINA yazar: "TIK <ad> #<sıra>".
// Test, ögenin bildirilen merkezine gerçek tıklama gönderip pencere başlığından doğru ögeye düştüğünü doğrular.
// Çerçevenin (iframe) içindeki tıklama üst sayfaya postMessage ile iletilir (farklı köken de olabilir).
(function () {
  "use strict";
  var sayac = 0;
  window.__gunluk = [];
  function ad(el) {
    while (el && el !== document) {
      if (el.dataset && el.dataset.ad) return el.dataset.ad;
      el = el.parentNode;
    }
    return null;
  }
  function yaz(a) {
    sayac += 1;
    window.__gunluk.push(a);
    document.title = "TIK " + a + " #" + sayac;
  }
  window.__tikYaz = yaz;
  document.addEventListener("mousedown", function (e) {
    var a = ad(e.target);
    if (!a) return;
    if (window !== window.top) {
      window.top.postMessage({ deskhandTik: a }, "*");
    } else {
      yaz(a);
    }
  }, true);
  // yerel (#…) bağlantılar sayfayı kaydırmasın: koordinat ölçümü bozulmasın
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a[href^='#']") : null;
    if (a) e.preventDefault();
  }, true);
  if (window === window.top) {
    window.addEventListener("message", function (e) {
      if (e.data && typeof e.data.deskhandTik === "string") yaz(e.data.deskhandTik);
    });
    // sayfanın otomasyon işaretini gördüğü değer (uzaktan denetim protokolü açıkken true olur): küçük bir başlık
    // olarak sayfaya yazılır, erişilebilirlik ağacından da okunabilir
    document.addEventListener("DOMContentLoaded", function () {
      var h = document.createElement("h6");
      h.id = "otomasyon";
      h.textContent = "webdriver: " + String(navigator.webdriver);
      h.style.margin = "2px 0";
      document.body.appendChild(h);
    });
  }
})();
