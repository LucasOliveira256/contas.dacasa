/* Gráficos locais em canvas; sem CDN ou requisições externas. */
(() => {
  const palette = ['#a3e635', '#fb7185', '#60a5fa', '#c084fc', '#fbbf24', '#2dd4bf', '#f472b6', '#a3a3a3', '#818cf8', '#34d399'];
  const money = cents => (Number(cents || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const shortMoney = cents => {
    const value = Math.abs(Number(cents || 0)) / 100;
    if (value >= 1000000) return `${(value / 1000000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mi`;
    if (value >= 1000) return `${(value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;
    return `${Math.round(value).toLocaleString('pt-BR')}`;
  };
  const colors = () => {
    const style = getComputedStyle(document.documentElement);
    return {
      text: style.getPropertyValue('--chart-text').trim() || '#91a0b7',
      grid: style.getPropertyValue('--chart-grid').trim() || '#293548',
      surface: style.getPropertyValue('--surface').trim() || '#151c27',
      ink: style.getPropertyValue('--ink').trim() || '#e9eef7',
      income: style.getPropertyValue('--chart-income').trim() || '#45d6a4',
      expense: style.getPropertyValue('--chart-expense').trim() || '#fb7185',
      accent: style.getPropertyValue('--chart-accent').trim() || '#a3e635',
    };
  };
  const shorten = (text, size = 12) => String(text ?? '').length > size ? String(text).slice(0, size - 1) + '…' : String(text ?? '');

  function setup(canvas) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(240, Math.floor(rect.width || 340));
    const height = Math.max(210, Math.floor(rect.height || 260));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d'); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const c = colors();
    ctx.font = '11px system-ui, sans-serif'; ctx.fillStyle = c.text; ctx.strokeStyle = c.grid;
    return { ctx, width, height, c };
  }

  function drawLegend(ctx, items, x, y, maxWidth, textColor) {
    let cx = x, cy = y;
    items.forEach(item => {
      const needed = 22 + Math.min(138, ctx.measureText(String(item.label || '')).width);
      if (cx + needed > x + maxWidth && cx !== x) { cx = x; cy += 18; }
      ctx.fillStyle = item.color; ctx.fillRect(cx, cy - 8, 9, 9);
      ctx.fillStyle = textColor; ctx.textAlign = 'left'; ctx.fillText(shorten(item.label, 21), cx + 14, cy);
      cx += needed + 8;
    });
  }

  function axes(ctx, width, plot, max, min, c) {
    ctx.strokeStyle = c.grid; ctx.fillStyle = c.text; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
    const range = max - min || 1;
    for (let i = 0; i <= 4; i++) {
      const y = plot.top + plot.height * i / 4;
      ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke();
      const value = max - range * i / 4;
      const prefix = value < -0.5 ? '−' : '';
      ctx.fillText(`${prefix}${shortMoney(value)}`, plot.left - 7, y + 3);
    }
  }

  function drawPie(canvas, payload) {
    const { ctx, width, height, c } = setup(canvas); const values = payload.data || []; const labels = payload.labels || [];
    const total = values.reduce((a, b) => a + Number(b), 0);
    if (!total) return false;
    const cx = width / 2, cy = height * 0.30, radius = Math.min(width * 0.30, height * 0.27);
    let angle = -Math.PI / 2;
    values.forEach((v, i) => {
      const next = angle + Math.PI * 2 * Number(v) / total;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, radius, angle, next); ctx.closePath();
      ctx.fillStyle = palette[i % palette.length]; ctx.fill(); angle = next;
    });
    ctx.beginPath(); ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2); ctx.fillStyle = c.surface; ctx.fill();
    ctx.textAlign = 'center'; ctx.fillStyle = c.ink; ctx.font = '700 13px system-ui'; ctx.fillText(shortMoney(total), cx, cy + 4);
    ctx.textAlign = 'left'; ctx.font = '10px system-ui';
    const legendItems = labels.map((label, i) => ({ label: `${label}: ${money(values[i])}`, color: palette[i % palette.length] }));
    const colWidth = width > 430 ? width / 2 - 14 : width - 22; const startY = height * 0.62;
    legendItems.slice(0, 8).forEach((item, i) => {
      const col = width > 430 ? i % 2 : 0; const row = width > 430 ? Math.floor(i / 2) : i;
      const y = startY + row * 16;
      ctx.fillStyle = item.color; ctx.fillRect(10 + col * (colWidth + 8), y - 8, 8, 8);
      ctx.fillStyle = c.text; ctx.fillText(shorten(item.label, width > 430 ? 35 : 31), 23 + col * (colWidth + 8), y);
    });
    return true;
  }

  function drawBars(canvas, labels, series, stacked = false) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 48, right: 10, top: 17, bottom: 43 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    let max = 0;
    labels.forEach((_, i) => { const vals = series.map(s => Number(s.data[i] || 0)); max = Math.max(max, stacked ? vals.reduce((a, b) => a + b, 0) : Math.max(0, ...vals)); });
    max = max || 100; axes(ctx, width, plot, max * 1.08, 0, c);
    const groupWidth = plot.width / labels.length; const inner = groupWidth * .72; const barWidth = Math.max(2, inner / (stacked ? 1 : Math.max(1, series.length)) - 3);
    labels.forEach((label, i) => {
      let stackedHeight = 0;
      series.forEach((s, j) => {
        const val = Number(s.data[i] || 0); const h = val / (max * 1.08) * plot.height;
        const x = plot.left + i * groupWidth + (groupWidth - inner) / 2 + (stacked ? 0 : j * (barWidth + 3));
        const y = plot.top + plot.height - (stacked ? stackedHeight + h : h);
        ctx.fillStyle = s.color || palette[j % palette.length]; ctx.beginPath();
        const radius = Math.min(4, barWidth / 2); ctx.roundRect(x, y, barWidth, Math.max(0, h), radius); ctx.fill();
        if (stacked) stackedHeight += h;
      });
      ctx.save(); ctx.translate(plot.left + i * groupWidth + groupWidth / 2, height - 22); ctx.rotate(labels.length > 8 ? -0.50 : 0);
      ctx.textAlign = labels.length > 8 ? 'right' : 'center'; ctx.fillStyle = c.text; ctx.fillText(shorten(label, 9), 0, 0); ctx.restore();
    });
    drawLegend(ctx, series.map((s, i) => ({ label: s.label, color: s.color || palette[i % palette.length] })), plot.left, height - 4, plot.width, c.text);
  }

  function drawLine(canvas, labels, values) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas); if (!labels || !labels.length || !values?.length) return;
    const plot = { left: 48, right: 12, top: 18, bottom: 36 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
    axes(ctx, width, plot, max, min, c);
    const point = (v, i) => ({ x: plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)), y: plot.top + (max - v) / range * plot.height });
    ctx.beginPath(); values.forEach((v, i) => { const p = point(v, i); i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); });
    ctx.strokeStyle = c.accent; ctx.lineWidth = 2.5; ctx.lineJoin = 'round'; ctx.stroke();
    values.forEach((v, i) => { const p = point(v, i); ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fillStyle = c.accent; ctx.fill(); });
    labels.forEach((label, i) => { const p = point(values[i], i); ctx.fillStyle = c.text; ctx.textAlign = 'center'; ctx.fillText(shorten(label, 9), p.x, height - 15); });
  }

  // Duas curvas compartilham a escala; quando entradas/saídas variam, as linhas cruzam visualmente.
  function drawCashflow(canvas, labels, incomes, expenses) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas);
    if (!labels?.length) return;
    const maxValue = Math.max(1, ...incomes.map(Number), ...expenses.map(Number));
    const plot = { left: 58, right: 18, top: 24, bottom: 42 };
    plot.width = Math.max(1, width - plot.left - plot.right); plot.height = Math.max(1, height - plot.top - plot.bottom);
    axes(ctx, width, plot, maxValue * 1.08, 0, c);
    const xAt = i => plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1));
    const yAt = value => plot.top + plot.height - (Number(value || 0) / (maxValue * 1.08)) * plot.height;
    const series = [
      { label: 'Entradas', data: incomes || [], color: c.income },
      { label: 'Saídas', data: expenses || [], color: c.expense },
    ];
    series.forEach(s => {
      const points = labels.map((_, i) => ({ x: xAt(i), y: yAt(s.data[i] || 0) }));
      if (!points.length) return;
      ctx.beginPath(); ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1], current = points[i], midX = (prev.x + current.x) / 2;
        ctx.bezierCurveTo(midX, prev.y, midX, current.y, current.x, current.y);
      }
      ctx.strokeStyle = s.color; ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
      points.forEach(point => { ctx.beginPath(); ctx.arc(point.x, point.y, 3, 0, Math.PI * 2); ctx.fillStyle = s.color; ctx.fill(); });
    });
    labels.forEach((label, i) => {
      ctx.fillStyle = c.text; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
      ctx.fillText(shorten(label, 8), xAt(i), height - 17);
    });
  }

  window.FamilyCharts = {
    render(payload) {
      const pie = document.getElementById('chart-pie');
      if (pie) { const ok = drawPie(pie, payload.pie || {}); const empty = document.getElementById('pie-empty'); if (empty) empty.hidden = ok; }
      const cashflow = document.getElementById('chart-cashflow');
      const lineData = payload.cashflow || payload.bars || {};
      if (cashflow) drawCashflow(cashflow, lineData.labels || [], lineData.income || [], lineData.expense || []);
      const bars = document.getElementById('chart-bars');
      if (bars) drawBars(bars, payload.bars?.labels || [], [
        { label: 'Entradas', data: payload.bars?.income || [], color: colors().income },
        { label: 'Saídas', data: payload.bars?.expense || [], color: colors().expense },
      ]);
      const line = document.getElementById('chart-line'); if (line) drawLine(line, payload.line?.labels || [], payload.line?.data || []);
      const cards = document.getElementById('chart-cards');
      if (cards) drawBars(cards, payload.cards?.labels || [], (payload.cards?.datasets || []).map((s, i) => ({ ...s, color: palette[i % palette.length] })), true);
    }
  };
})();
