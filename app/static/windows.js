(function () {
  'use strict';

  var inFrame = window.parent !== window;
  function isMobile() { return window.matchMedia('(max-width: 767px)').matches; }

  /* Links that should open floating windows (works in the desktop and inside windows) */
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button > 0) return;
    var t = e.target.closest ? e.target.closest('a[data-win], [data-app]') : null;
    if (!t) return;
    var host = inFrame ? window.parent : window;
    var wm = host.WM;
    if (!wm || wm.isMobile()) return;
    e.preventDefault();
    if (t.dataset.app) { wm.openApp(t.dataset.app); }
    else { wm.open(t.dataset.win, t.dataset.title || t.textContent.trim(), t.getAttribute('href')); }
  });

  if (inFrame) return;

  var layer = document.getElementById('winlayer');
  var dockDyn = document.getElementById('dock-dyn');
  var main = document.getElementById('win-main');
  var hint = document.getElementById('desktop-hint');
  if (!layer || !main) return;

  var wins = {};
  var zTop = 100;
  var APPS = {
    dashboard: { title: 'Dashboard' },
    attention: { title: 'Needs attention', url: '/manager/attention', w: 620, h: 520 },
    rules: { title: 'Rules', url: '/manager/rules', w: 460, h: 540 }
  };
  var JOB_ICON = '<svg class="ico" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>';

  function dockEl(id) {
    if (APPS[id]) return document.querySelector('[data-app="' + id + '"].dock-item');
    return wins[id] && wins[id].dockEl;
  }
  function setState(id) {
    var d = dockEl(id), w = wins[id];
    if (!d) return;
    d.classList.toggle('is-open', !!w);
    d.classList.toggle('is-min', !!(w && w.min));
  }
  function focus(id) {
    var w = wins[id];
    if (!w) return;
    Object.keys(wins).forEach(function (k) { wins[k].el.classList.toggle('active', k === id); });
    w.el.style.zIndex = ++zTop;
  }
  function changed(id) {
    if (window.refreshDashboard) window.refreshDashboard();
    if (id && id.indexOf('issue-') === 0 && wins.attention) {
      try { wins.attention.frame.contentWindow.location.reload(); } catch (e) {}
    }
  }

  function makeDraggable(el, id) {
    var bar = el.querySelector('.titlebar');
    var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    bar.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.dot') || el.classList.contains('max')) return;
      dragging = true; sx = e.clientX; sy = e.clientY; ox = el.offsetLeft; oy = el.offsetTop;
      bar.setPointerCapture(e.pointerId);
      layer.classList.add('dragging');
    });
    bar.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      var nx = ox + e.clientX - sx, ny = oy + e.clientY - sy;
      nx = Math.min(Math.max(nx, 80 - el.offsetWidth), window.innerWidth - 80);
      ny = Math.min(Math.max(ny, 32), window.innerHeight - 70);
      el.style.left = nx + 'px';
      el.style.top = ny + 'px';
    });
    function end(e) {
      if (!dragging) return;
      dragging = false;
      layer.classList.remove('dragging');
      try { bar.releasePointerCapture(e.pointerId); } catch (err) {}
    }
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
    bar.addEventListener('dblclick', function (e) {
      if (!e.target.closest('.dot')) toggleMax(id);
    });
  }

  function open(id, title, url, opts) {
    opts = opts || {};
    if (isMobile()) { location.href = url; return; }
    if (wins[id]) { restore(id); return; }

    var n = Object.keys(wins).length;
    var w = Math.min(opts.w || 760, window.innerWidth - 40);
    var h = Math.min(opts.h || 600, window.innerHeight - 130);
    var left = Math.max(16, Math.round((window.innerWidth - w) / 2) + (n % 6) * 30 - 60);
    var top = Math.max(48, 64 + (n % 6) * 30);

    var el = document.createElement('div');
    el.className = 'window fwin';
    el.style.cssText = 'left:' + left + 'px;top:' + top + 'px;width:' + w + 'px;height:' + h + 'px;z-index:' + (++zTop);
    el.innerHTML =
      '<div class="titlebar">' +
        '<span class="tl-group">' +
          '<button class="dot r" data-act="close" aria-label="Close"></button>' +
          '<button class="dot y" data-act="min" aria-label="Minimize"></button>' +
          '<button class="dot g" data-act="max" aria-label="Zoom"></button>' +
        '</span>' +
        '<div class="wtitle"></div>' +
      '</div>' +
      '<div class="wbody"><iframe title=""></iframe><div class="shield"></div></div>';
    el.querySelector('.wtitle').textContent = 'Mendly \u2014 ' + title;

    var frame = el.querySelector('iframe');
    frame.title = title;
    frame.src = url + (url.indexOf('?') > -1 ? '&' : '?') + 'embed=1';
    var loads = 0;
    frame.addEventListener('load', function () { loads++; if (loads > 1) changed(id); });

    el.addEventListener('pointerdown', function () {
      if (!el.classList.contains('active')) focus(id);
    }, true);
    el.querySelector('.tl-group').addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]');
      if (!b) return;
      if (b.dataset.act === 'close') close(id);
      else if (b.dataset.act === 'min') minimize(id);
      else toggleMax(id);
    });
    makeDraggable(el, id);

    layer.appendChild(el);
    wins[id] = { el: el, frame: frame, min: false, dockEl: null };

    if (!APPS[id]) {
      var d = document.createElement('button');
      d.type = 'button';
      d.className = 'dock-item t-job';
      d.innerHTML = JOB_ICON + '<span class="dock-lbl"></span><i class="run"></i>';
      d.querySelector('.dock-lbl').textContent = title;
      d.addEventListener('click', function () { restore(id); });
      dockDyn.appendChild(d);
      wins[id].dockEl = d;
    }
    setState(id);
    focus(id);
  }

  function restore(id) {
    var w = wins[id];
    if (!w) return;
    w.min = false;
    w.el.classList.remove('minimized');
    setState(id);
    focus(id);
  }
  function minimize(id) {
    var w = wins[id];
    if (!w) return;
    w.min = true;
    w.el.classList.add('minimized');
    w.el.classList.remove('active');
    setState(id);
  }
  function toggleMax(id) {
    var w = wins[id];
    if (w) w.el.classList.toggle('max');
  }
  function close(id) {
    var w = wins[id];
    if (!w) return;
    w.el.remove();
    if (w.dockEl) w.dockEl.remove();
    delete wins[id];
    setState(id);
    changed(id);
  }

  /* main Dashboard window */
  function minimizeMain() {
    main.classList.add('main-min');
    if (hint) hint.classList.remove('is-hidden');
    var d = dockEl('dashboard');
    if (d) d.classList.add('is-min');
  }
  function restoreMain() {
    main.classList.remove('main-min');
    if (hint) hint.classList.add('is-hidden');
    var d = dockEl('dashboard');
    if (d) d.classList.remove('is-min');
  }
  main.querySelector('.tl-group').addEventListener('click', function (e) {
    var b = e.target.closest('[data-main]');
    if (!b) return;
    if (b.dataset.main === 'full') main.classList.toggle('main-full');
    else minimizeMain();
  });
  main.querySelector('.titlebar').addEventListener('dblclick', function (e) {
    if (!e.target.closest('.dot')) main.classList.toggle('main-full');
  });

  function openApp(app) {
    if (app === 'dashboard') { restoreMain(); return; }
    var a = APPS[app];
    if (a) open(app, a.title, a.url, a);
  }

  /* clicking the desktop deactivates floating windows */
  document.addEventListener('pointerdown', function (e) {
    if (e.target.closest('.fwin') || e.target.closest('#dock')) return;
    Object.keys(wins).forEach(function (k) { wins[k].el.classList.remove('active'); });
  });

  var dashDock = dockEl('dashboard');
  if (dashDock) dashDock.classList.add('is-open');

  window.WM = { open: open, openApp: openApp, isMobile: isMobile };
})();