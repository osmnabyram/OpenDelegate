"use strict";
// Mesaj metinleri sunucuda süzülmüş HTML'dir (yalnızca b/i/u/s/code/pre/blockquote ve https bağlantı);
// bunun dışında sayfaya veri sadece textContent ile girer.
(function () {
  var EN = (navigator.language || "").toLowerCase().indexOf("en") === 0;
  var T = EN
    ? { parola: "Password", kod: "Verification code", girisYap: "Sign in", yaziyor: "typing...", cikis: "Sign out",
        gonder: "Send", yaz: "Write a message", hata: "Connection problem. Retrying...", dosya: "File", ses: "Voice",
        kayit: "Recording... tap Voice again to send", mikYok: "Microphone is not available (it needs https and permission).", yuklenemedi: "Could not upload." }
    : { parola: "Parola", kod: "Doğrulama kodu", girisYap: "Giriş yap", yaziyor: "yazıyor...", cikis: "Çıkış",
        gonder: "Gönder", yaz: "Bir mesaj yazın", hata: "Bağlantı sorunu. Tekrar deneniyor...", dosya: "Dosya", ses: "Ses",
        kayit: "Kaydediliyor... göndermek için Ses düğmesine tekrar dokunun", mikYok: "Mikrofon kullanılamıyor (https ve izin gerekir).", yuklenemedi: "Yüklenemedi." };
  document.documentElement.lang = EN ? "en" : "tr";
  document.querySelectorAll("[data-t]").forEach(function (e) { e.textContent = T[e.dataset.t]; });
  document.querySelectorAll("[data-p]").forEach(function (e) { e.placeholder = T[e.dataset.p]; });

  var $ = function (id) { return document.getElementById(id); };
  var akis = $("akis"), yaz = $("yaz"), son = 0, calisiyor = false, mesajlar = {};

  function api(yol, govde) {
    var secenek = { credentials: "same-origin", headers: { "X-OD": "1" } };
    if (govde !== undefined) {
      secenek.method = "POST";
      secenek.headers["Content-Type"] = "application/json";
      secenek.body = JSON.stringify(govde);
    }
    return fetch(yol, secenek);
  }

  function goster(giris) {
    $("giris").hidden = giris === false;
    $("sohbet").hidden = giris !== false;
    if (giris === false) { $("parola").focus(); } else { yaz.focus(); }
  }

  function altaKaydir() { akis.scrollTop = akis.scrollHeight; }

  function dugmeleriYaz(kutu, dugmeler) {
    var eski = kutu.querySelector(".dugmeler");
    if (eski) { eski.remove(); }
    if (!dugmeler || !dugmeler.length) { return; }
    dugmeler.forEach(function (satir) {
      var d = document.createElement("div");
      d.className = "dugmeler";
      satir.forEach(function (b) {
        var dg = document.createElement("button");
        dg.type = "button";
        dg.textContent = b.yazi;
        dg.addEventListener("click", function () {
          d.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
          api("/sohbet/dugme", { veri: b.veri });
        });
        d.appendChild(dg);
      });
      kutu.appendChild(d);
    });
  }

  function kutuYap(o, ben) {
    var k = document.createElement("div");
    k.className = "m" + (ben ? " ben" : "");
    var ic = document.createElement("div");
    ic.className = "ic";
    ic.innerHTML = o.metin || "";
    k.appendChild(ic);
    return k;
  }

  function olayIsle(o) {
    var k;
    if (o.tur === "kullanici" || o.tur === "mesaj") {
      k = kutuYap(o, o.tur === "kullanici");
      mesajlar[o.id] = k;
      akis.appendChild(k);
      dugmeleriYaz(k, o.dugmeler);
    } else if (o.tur === "duzenle" && mesajlar[o.hedef]) {
      k = mesajlar[o.hedef];
      k.querySelector(".ic").innerHTML = o.metin || "";
      dugmeleriYaz(k, o.dugmeler);
    } else if (o.tur === "sil" && mesajlar[o.hedef]) {
      mesajlar[o.hedef].remove();
      delete mesajlar[o.hedef];
    } else if (o.tur === "temizle") {
      akis.textContent = "";
      mesajlar = {};
    } else if (o.tur === "medya") {
      k = document.createElement("div");
      k.className = "m";
      var el;
      if (o.cins === "foto") { el = document.createElement("img"); el.src = o.url; el.alt = ""; }
      else if (o.cins === "ses") { el = document.createElement("audio"); el.controls = true; el.src = o.url; }
      else if (o.cins === "video") { el = document.createElement("video"); el.controls = true; el.src = o.url; }
      else { el = document.createElement("a"); el.href = o.url; el.textContent = o.ad || "dosya"; el.download = ""; }
      k.appendChild(el);
      if (o.altyazi) { var a = document.createElement("div"); a.innerHTML = o.altyazi; k.appendChild(a); }
      mesajlar[o.id] = k;
      akis.appendChild(k);
    }
  }

  async function dongu() {
    if (calisiyor) { return; }
    calisiyor = true;
    for (;;) {
      try {
        var r = await api("/sohbet/olaylar?son=" + son);
        if (r.status === 401) { calisiyor = false; goster(false); return; }
        var v = await r.json();
        var altta = akis.scrollHeight - akis.scrollTop - akis.clientHeight < 80;
        v.olaylar.forEach(olayIsle);
        son = v.son;
        $("yaziyor").hidden = !v.yaziyor;
        if (v.olaylar.length && altta) { altaKaydir(); }
      } catch (e) {
        await new Promise(function (t) { setTimeout(t, 3000); });
      }
    }
  }

  $("girisForm").addEventListener("submit", async function (e) {
    e.preventDefault();
    $("hata").textContent = "";
    try {
      var r = await api("/sohbet/giris", { parola: $("parola").value, kod: $("kod").value });
      var v = await r.json();
      if (r.ok) { $("parola").value = ""; $("kod").value = ""; goster(true); dongu(); }
      else { $("hata").textContent = v.hata || ""; }
    } catch (x) { $("hata").textContent = T.hata; }
  });

  $("yazForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var metin = yaz.value.trim();
    if (!metin) { return; }
    yaz.value = "";
    yaz.style.height = "";
    api("/sohbet/mesaj", { metin: metin });
  });
  yaz.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("yazForm").requestSubmit(); }
  });
  yaz.addEventListener("input", function () {
    yaz.style.height = "auto";
    yaz.style.height = Math.min(yaz.scrollHeight, 160) + "px";
  });

  function sistemNotu(metin) {
    var k = document.createElement("div");
    k.className = "m sistem";
    k.textContent = metin;
    akis.appendChild(k);
    altaKaydir();
    setTimeout(function () { k.remove(); }, 6000);
  }

  async function yukle(govde, ad, tur, tip) {
    var baslik = { "X-OD": "1", "Content-Type": tip || "application/octet-stream", "X-Dosya-Adi": encodeURIComponent(ad),
      "X-Tur": tur, "X-Not": encodeURIComponent(yaz.value.trim()) };
    try {
      var r = await fetch("/sohbet/yukle", { method: "POST", credentials: "same-origin", headers: baslik, body: govde });
      if (!r.ok) { var v = await r.json().catch(function () { return {}; }); sistemNotu(v.hata || T.yuklenemedi); return; }
      yaz.value = "";
      yaz.style.height = "";
    } catch (e) { sistemNotu(T.yuklenemedi); }
  }

  $("ekle").addEventListener("click", function () { $("dosya").click(); });
  $("dosya").addEventListener("change", function () {
    var f = this.files[0];
    this.value = "";
    if (f) { yukle(f, f.name, "dosya", f.type); }
  });

  var kayit = null;
  $("mikrofon").addEventListener("click", async function () {
    var dugme = this;
    if (kayit) { kayit.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { sistemNotu(T.mikYok); return; }
    try {
      var akim = await navigator.mediaDevices.getUserMedia({ audio: true });
      var parcalar = [];
      kayit = new MediaRecorder(akim);
      kayit.ondataavailable = function (e) { if (e.data.size) { parcalar.push(e.data); } };
      kayit.onstop = function () {
        akim.getTracks().forEach(function (t) { t.stop(); });
        var tip = kayit.mimeType || "audio/webm";
        kayit = null;
        dugme.classList.remove("kayit");
        var blob = new Blob(parcalar, { type: tip });
        if (blob.size) { yukle(blob, tip.indexOf("ogg") >= 0 ? "ses.ogg" : tip.indexOf("mp4") >= 0 ? "ses.m4a" : "ses.webm", "ses", tip); }
      };
      kayit.start();
      dugme.classList.add("kayit");
      sistemNotu(T.kayit);
    } catch (e) { kayit = null; sistemNotu(T.mikYok); }
  });

  $("cikis").addEventListener("click", async function () {
    await api("/sohbet/cikis", {});
    location.reload();
  });

  api("/sohbet/ben").then(function (r) { return r.json(); }).then(function (v) {
    $("kodSatir").hidden = !v.totp;
    if (v.giris) { goster(true); dongu(); } else { goster(false); }
  }).catch(function () { goster(false); });
})();
