(() => {
  const root = document.documentElement;
  const body = document.body;
  const themeButton = document.getElementById('theme-toggle');
  const themeText = themeButton?.querySelector('.theme-text');
  const themeIcon = themeButton?.querySelector('.theme-icon');
  const sidebar = document.getElementById('app-sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebarOverlay = document.getElementById('sidebar-overlay');

  function applyTheme(theme) {
    const next = theme === 'light' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('casa-theme', next); } catch (_) { /* Tema continua funcionando sem armazenamento local. */ }
    if (themeText) themeText.textContent = next === 'dark' ? 'Material Light' : 'Tema escuro';
    if (themeIcon) {
      themeIcon.innerHTML = next === 'dark'
        ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>'
        : '<path d="M20.5 15.5A8.5 8.5 0 0 1 8.5 3.5 8.5 8.5 0 1 0 20.5 15.5Z"/>';
    }
    themeButton?.setAttribute('aria-label', next === 'dark' ? 'Mudar para Material Light' : 'Mudar para tema Dark');
    // Aguarda o CSS trocar as cores antes de redesenhar os gráficos em canvas.
    window.setTimeout(renderCharts, 30);
  }

  themeButton?.addEventListener('click', () => applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  function mobileMenu() { return window.matchMedia('(max-width: 760px)').matches; }
  function setSidebarOpen(open) {
    root.classList.toggle('sidebar-open', open && mobileMenu());
    if (sidebarToggle) {
      sidebarToggle.setAttribute('aria-expanded', String(open));
      sidebarToggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    }
    if (sidebarOverlay) sidebarOverlay.tabIndex = open && mobileMenu() ? 0 : -1;
  }
  sidebarToggle?.addEventListener('click', () => {
    if (mobileMenu()) setSidebarOpen(!root.classList.contains('sidebar-open'));
    else {
      const pinned = root.classList.toggle('sidebar-pinned');
      try { localStorage.setItem('casa-sidebar-pinned', pinned ? '1' : '0'); } catch (_) { /* Preferência opcional. */ }
      sidebarToggle.setAttribute('aria-expanded', String(pinned));
      sidebarToggle.setAttribute('aria-label', pinned ? 'Recolher menu' : 'Fixar menu expandido');
    }
  });
  sidebarOverlay?.addEventListener('click', () => setSidebarOpen(false));
  sidebar?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setSidebarOpen(false)));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setSidebarOpen(false); });
  try {
    if (localStorage.getItem('casa-sidebar-pinned') === '1' && !mobileMenu()) root.classList.add('sidebar-pinned');
  } catch (_) { /* Preferência opcional. */ }
  window.addEventListener('resize', () => { if (!mobileMenu()) setSidebarOpen(false); });

  function renderCharts() {
    const dataNode = document.getElementById('chart-data');
    if (!dataNode || !window.FamilyCharts) return;
    try { window.FamilyCharts.render(JSON.parse(dataNode.textContent)); }
    catch (error) { console.error('Não foi possível renderizar os gráficos locais.', error); }
  }
  document.addEventListener('DOMContentLoaded', renderCharts);
  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(renderCharts, 140);
  });
  applyTheme(root.dataset.theme || 'dark');
})();
