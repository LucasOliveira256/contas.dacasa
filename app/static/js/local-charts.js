/* Renderizador local de canvas para gráficos offline. Interface limitada ao uso desta aplicação. */
(() => {
  const palette = ["#236b56", "#e2a348", "#547bba", "#ba6d58", "#8d7ab8", "#63a6a1", "#d477a8", "#8a9b65", "#7b8794", "#c4a75b"];
  const money = cents => {
    const value = (Number(cents || 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
    return value;
  };
  function setup(canvas) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(280, Math.floor(rect.width || 340));
    const height = Math.max(220, Math.floor(rect.height || 260));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = "#69756f"; ctx.strokeStyle = "#e4e9e5";
    return { ctx, width, height };
  }
  const shorten = (text, size = 12) => String(text).length > size ? String(text).slice(0, size - 1) + "…" : String(text);
  function legend(ctx, items, x, y, maxWidth) {
    let cx = x, cy = y;
    items.forEach((item, index) => {
      const label = String(item.label || ""); const needed = 20 + Math.min(124, ctx.measureText(label).width);
      if (cx + needed > x + maxWidth && cx !== x) { cx = x; cy += 18; }
      ctx.fillStyle = item.color || palette[index % palette.length]; ctx.fillRect(cx, cy - 8, 9, 9);
      ctx.fillStyle = "#4f5e56"; ctx.fillText(shorten(label, 22), cx + 13, cy);
      cx += needed + 8;
    });
  }
  function drawPie(canvas, payload) {
    const { ctx, width, height } = setup(canvas); const values = payload.data || []; const labels = payload.labels || [];
    const total = values.reduce((a, b) => a + Number(b), 0);
    if (!total) return false;
    const cx = width / 2, cy = height * 0.30, radius = Math.min(width * 0.30, height * 0.27);
    let angle = -Math.PI / 2;
    values.forEach((v, i) => {
      const next = angle + Math.PI * 2 * Number(v) / total;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, radius, angle, next); ctx.closePath();
      ctx.fillStyle = palette[i % palette.length]; ctx.fill(); angle = next;
    });
    ctx.beginPath(); ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2); ctx.fillStyle = "#fff"; ctx.fill();
    ctx.textAlign = "center"; ctx.fillStyle = "#1e3c31"; ctx.font = "700 14px system-ui"; ctx.fillText(money(total), cx, cy + 4);
    ctx.textAlign = "left"; ctx.font = "11px system-ui";
    const legendItems = labels.map((label, i) => ({ label: `${label}: ${money(values[i])}`, color: palette[i % palette.length] }));
    const colWidth = width > 400 ? width / 2 - 14 : width - 22; let y = height * 0.62;
    legendItems.slice(0, 7).forEach((item, i) => {
      const col = width > 400 ? i % 2 : 0; const row = width > 400 ? Math.floor(i / 2) : i;
      ctx.fillStyle = item.color; ctx.fillRect(10 + col * (colWidth + 8), y + row * 16 - 8, 8, 8);
      ctx.fillStyle = "#53635b"; ctx.fillText(shorten(item.label, width > 400 ? 36 : 34), 23 + col * (colWidth + 8), y + row * 16);
    });
    return true;
  }
  function axes(ctx, width, height, plot, max) {
    ctx.strokeStyle = "#e5eae6"; ctx.fillStyle = "#78837d"; ctx.font = "10px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = plot.top + (plot.height * i / 4); ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke();
      const value = max * (1 - i / 4); ctx.fillText(value === 0 ? "0" : (Math.abs(value) >= 100000 ? `${Math.round(value / 100000) / 10} mi` : `${Math.round(value / 1000)} mil`), plot.left - 7, y + 3);
    }
  }
  function drawBars(canvas, labels, series, stacked = false) {
    const { ctx, width, height } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 44, right: 8, top: 15, bottom: 40 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    let max = 0;
    labels.forEach((_, i) => { const vals = series.map(s => Number(s.data[i] || 0)); max = Math.max(max, stacked ? vals.reduce((a, b) => a + b, 0) : Math.max(...vals)); });
    max = max || 100; axes(ctx, width, height, plot, max * 1.08);
    const groupWidth = plot.width / labels.length; const inner = groupWidth * .72; const barWidth = Math.max(2, inner / (stacked ? 1 : series.length) - 3);
    labels.forEach((label, i) => {
      let stackedHeight = 0;
      series.forEach((s, j) => {
        const val = Number(s.data[i] || 0); const h = val / (max * 1.08) * plot.height;
        const x = plot.left + i * groupWidth + (groupWidth - inner) / 2 + (stacked ? 0 : j * (barWidth + 3));
        const y = plot.top + plot.height - (stacked ? stackedHeight + h : h);
        ctx.fillStyle = s.color || palette[j % palette.length]; ctx.fillRect(x, y, barWidth, h);
        if (stacked) stackedHeight += h;
      });
      ctx.save(); ctx.translate(plot.left + i * groupWidth + groupWidth / 2, height - 22); ctx.rotate(labels.length > 8 ? -0.55 : 0);
      ctx.textAlign = labels.length > 8 ? "right" : "center"; ctx.fillStyle = "#69756f"; ctx.fillText(shorten(label, 9), 0, 0); ctx.restore();
    });
    legend(ctx, series.map((s, i) => ({ label: s.label, color: s.color || palette[i % palette.length] })), plot.left, height - 4, plot.width);
  }
  function drawLine(canvas, labels, values) {
    const { ctx, width, height } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 45, right: 10, top: 17, bottom: 40 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
    ctx.strokeStyle = "#e5eae6"; ctx.fillStyle = "#78837d"; ctx.font = "10px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) { const y = plot.top + plot.height * i / 4; ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke(); const val = max - (range * i / 4); ctx.fillText(`${Math.round(val / 1000)} mil`, plot.left - 7, y + 3); }
    ctx.beginPath(); values.forEach((v, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); const y = plot.top + (max - v) / range * plot.height; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = "#236b56"; ctx.lineWidth = 2.5; ctx.stroke();
    values.forEach((v, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); const y = plot.top + (max - v) / range * plot.height; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = "#236b56"; ctx.fill(); });
    labels.forEach((label, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); ctx.fillStyle = "#69756f"; ctx.textAlign = "center"; ctx.fillText(shorten(label, 9), x, height - 21); });
  }
  window.FamilyCharts = {
    render(payload) {
      const pie = document.getElementById("chart-pie");
      if (pie) { const ok = drawPie(pie, payload.pie || {}); const empty = document.getElementById("pie-empty"); if (empty) empty.hidden = ok; }
      const bars = document.getElementById("chart-bars");
      if (bars) drawBars(bars, payload.bars.labels, [
        { label: "Receitas", data: payload.bars.income, color: "#236b56" },
        { label: "Despesas", data: payload.bars.expense, color: "#e2a348" }
      ]);
      const line = document.getElementById("chart-line"); if (line) drawLine(line, payload.line.labels, payload.line.data);
      const cards = document.getElementById("chart-cards");
      if (cards) drawBars(cards, payload.cards.labels, (payload.cards.datasets || []).map((s, i) => ({ ...s, color: palette[i % palette.length] })), true);
    }
  };
})();
