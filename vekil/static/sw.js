"use strict";
// Servis çalışanı: yalnızca bildirim gösterir ve tıklanınca sohbeti açar. Çevrimdışı önbellek yok.
self.addEventListener("push", function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = {}; }
  e.waitUntil(self.registration.showNotification(d.baslik || "OpenDelegate", {
    body: d.govde || "Yeni mesaj", icon: "/sohbet/dosya/ikon-192.png", tag: "opendelegate"
  }));
});
self.addEventListener("notificationclick", function (e) {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window" }).then(function (liste) {
    for (var i = 0; i < liste.length; i++) {
      if (liste[i].url.indexOf("/sohbet") >= 0 && "focus" in liste[i]) { return liste[i].focus(); }
    }
    return self.clients.openWindow("/sohbet");
  }));
});
