// Menggambar garis panah dari langkah n ke langkah n+1 pada slide alur (flow). Hanya dekorasi: urutan tetap
// terbaca dari nomor langkah. Tanpa JavaScript, panah kecil bawaan (CSS) tetap tampil.
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var seq = 0;

  function el(name, attrs) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) { e.setAttribute(k, attrs[k]); }
    return e;
  }

  function draw(flow) {
    var old = flow.querySelector('svg.flow-lines');
    if (old) { old.remove(); }
    var steps = [].slice.call(flow.querySelectorAll('.step[data-n]'));
    if (steps.length < 2) { return; }
    var fr = flow.getBoundingClientRect();
    var gap = parseFloat(getComputedStyle(flow).rowGap) || 10;
    var info = {};
    steps.forEach(function (s) {
      var r = s.getBoundingClientRect();
      var l = s.closest('.lane').getBoundingClientRect();
      info[s.getAttribute('data-n')] = {
        l: r.left - fr.left, r: r.right - fr.left, t: r.top - fr.top, b: r.bottom - fr.top,
        cx: (r.left + r.right) / 2 - fr.left, cy: (r.top + r.bottom) / 2 - fr.top,
        laneTop: l.top - fr.top, laneBottom: l.bottom - fr.top
      };
    });

    var id = 'flow-head-' + (seq++);
    var svg = el('svg', { 'class': 'flow-lines', 'aria-hidden': 'true', width: fr.width, height: fr.height });
    var defs = el('defs', {});
    var marker = el('marker', { id: id, markerWidth: 9, markerHeight: 9, refX: 7, refY: 4.5, orient: 'auto', markerUnits: 'userSpaceOnUse' });
    marker.appendChild(el('path', { d: 'M0,0 L9,4.5 L0,9 z', 'class': 'head' }));
    defs.appendChild(marker);
    svg.appendChild(defs);

    // Titik keluar di 30% lebar kartu, titik masuk di 70%, supaya garis masuk dan keluar tidak bertumpuk.
    for (var n = 1; n < steps.length; n++) {
      var a = info[n], b = info[n + 1], d;
      if (!a || !b) { continue; }
      var down = b.laneTop > a.laneTop;
      var ox = a.l + (a.r - a.l) * 0.3, ix = b.l + (b.r - b.l) * 0.7;
      var y1 = down ? a.b : a.t, y2 = down ? b.t : b.b;
      if (a.laneTop === b.laneTop) {                         // jalur yang sama: garis mendatar sisi ke sisi
        d = b.l > a.l ? 'M' + a.r + ',' + a.cy + ' H' + b.l : 'M' + a.l + ',' + a.cy + ' H' + b.r;
      } else if (Math.abs(a.cx - b.cx) < 4) {                // kolom yang sama: garis lurus vertikal
        d = 'M' + a.cx + ',' + y1 + ' V' + y2;
      } else {                                               // beda jalur dan kolom: lewat celah antar jalur
        var off = (((n - 1) % 3) - 1) * 7;                   // tiap garis memakai jalur celah sendiri
        var gy = (down ? a.laneBottom + gap / 2 : a.laneTop - gap / 2) + off;
        d = 'M' + ox + ',' + y1 + ' V' + gy + ' H' + ix + ' V' + y2;
      }
      svg.appendChild(el('path', { d: d, 'class': 'ln', 'marker-end': 'url(#' + id + ')' }));
    }
    flow.appendChild(svg);
    flow.classList.add('has-lines');
  }

  function init() {
    var flows = [].slice.call(document.querySelectorAll('.flow'));
    if (!flows.length) { return; }
    var run = function () { flows.forEach(draw); };
    run();
    var timer;
    window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(run, 120); });
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(run); }
    window.addEventListener('load', run);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
