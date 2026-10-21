/* Adaptador mínimo para os atributos hx-get/hx-trigger/hx-swap usados neste projeto. */
(() => {
  async function loadElement(element) {
    const url = element.getAttribute("hx-get");
    if (!url) return;
    try {
      const response = await fetch(url, { headers: { "HX-Request": "true" } });
      if (!response.ok) throw new Error("Falha ao carregar conteúdo");
      const html = await response.text();
      if ((element.getAttribute("hx-swap") || "innerHTML") === "innerHTML") element.innerHTML = html;
    } catch (_) { element.innerHTML = '<p class="muted">Não foi possível carregar esta seção.</p>'; }
  }
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[hx-get]").forEach(element => {
      const trigger = element.getAttribute("hx-trigger") || "load";
      if (trigger.split(" ").includes("load")) loadElement(element);
    });
  });
  window.htmx = { ajax: (_method, url, options = {}) => fetch(url).then(r => r.text()).then(html => { if (options.target) document.querySelector(options.target).innerHTML = html; }) };
})();
