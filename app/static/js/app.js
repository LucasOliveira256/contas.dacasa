(() => {
  function renderCharts() {
    const dataNode = document.getElementById("chart-data");
    if (!dataNode || !window.FamilyCharts) return;
    try { window.FamilyCharts.render(JSON.parse(dataNode.textContent)); }
    catch (error) { console.error("Não foi possível renderizar os gráficos locais.", error); }
  }
  document.addEventListener("DOMContentLoaded", renderCharts);
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderCharts, 140);
  });
})();
