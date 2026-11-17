// Fills in the deployment's short name (ARMY HQ or POLICE HQ) on the About and Privacy pages. On any failure the built-in text stays.
fetch("/api/v1/profile/").then(function (r) { return r.ok ? r.json() : null; }).then(function (p) {
  if (!p || !p.short_name) return;
  document.querySelectorAll("[data-app-name]").forEach(function (el) { el.textContent = p.short_name; });
}).catch(function () {});
