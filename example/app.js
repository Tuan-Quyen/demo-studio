(function () {
  "use strict";
  var D = window.DEMO_DATA;
  var $ = function (id) { return document.getElementById(id); };
  var NS = "http://www.w3.org/2000/svg";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var DUR = reduce ? 0 : 260;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function genreLabel(slug) {
    return D.genres.filter(function (g) { return g.slug === slug; })[0].label;
  }
  // Deterministic generative thumbnail (no randomness)
  function thumb(v, prefix) {
    var h1 = v.hues[0], h2 = v.hues[1], n = parseInt(v.id.slice(1), 10);
    var s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 320 180");
    s.setAttribute("preserveAspectRatio", "xMidYMid slice");
    s.setAttribute("aria-hidden", "true");
    var gid = prefix + v.id;
    s.innerHTML =
      '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" stop-color="hsl(' + h1 + ',80%,55%)"/><stop offset="1" stop-color="hsl(' + h2 + ',80%,30%)"/></linearGradient></defs>' +
      '<rect width="320" height="180" fill="url(#' + gid + ')"/>' +
      '<circle cx="' + (60 + n * 28) + '" cy="' + (50 + (n % 3) * 30) + '" r="' + (40 + n * 4) + '" fill="hsla(' + h2 + ',90%,70%,.35)"/>' +
      '<circle cx="' + (280 - n * 20) + '" cy="150" r="' + (30 + n * 3) + '" fill="hsla(' + h1 + ',90%,75%,.3)"/>' +
      '<path d="M0 ' + (140 - n * 3) + ' Q80 ' + (100 + n * 4) + ' 160 130 T320 ' + (120 - n * 2) + ' V180 H0Z" fill="rgba(0,0,0,.3)"/>' +
      '<circle cx="160" cy="90" r="22" fill="rgba(255,255,255,.85)"/><path d="M153 78 L174 90 L153 102Z" fill="rgba(20,20,30,.9)"/>';
    return s;
  }

  // sensitive (fake) fields
  $("user-email").textContent = D.user.email;
  $("api-key").textContent = D.user.apiKey;

  // chips
  var active = "all";
  D.genres.forEach(function (g) {
    var b = el("button", "chip", g.label);
    b.type = "button";
    b.setAttribute("data-testid", "chip-" + g.slug);
    b.setAttribute("data-slug", g.slug);
    b.setAttribute("aria-pressed", g.slug === "all" ? "true" : "false");
    b.addEventListener("click", function () { setFilter(g.slug); });
    $("chips").appendChild(b);
  });

  // cards
  var cards = {};
  D.videos.forEach(function (v) {
    var c = el("button", "card");
    c.type = "button";
    c.setAttribute("data-testid", "card-" + v.id);
    c.setAttribute("data-genre", v.genre);
    var t = el("div", "thumb"); t.appendChild(thumb(v, "g"));
    t.appendChild(el("span", "tag", v.tool));
    var body = el("div", "card-body");
    body.appendChild(el("h3", null, v.title));
    body.appendChild(el("p", "creator", v.creator));
    var row = el("div", "stats");
    row.appendChild(el("span", null, v.views + " views"));
    row.appendChild(el("span", "up", "▲ " + v.growth + "%"));
    body.appendChild(row);
    c.appendChild(t); c.appendChild(body);
    c.addEventListener("click", function () { openModal(v, c); });
    $("grid").appendChild(c);
    cards[v.id] = c;
  });

  function updateCount() {
    var n = D.videos.filter(function (v) { return active === "all" || v.genre === active; }).length;
    $("count").textContent = n + (n === 1 ? " video" : " videos") + " · " + genreLabel(active);
  }
  function setFilter(slug) {
    active = slug;
    Array.prototype.forEach.call($("chips").children, function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-slug") === slug ? "true" : "false");
    });
    D.videos.forEach(function (v) {
      var c = cards[v.id], show = slug === "all" || v.genre === slug;
      clearTimeout(c._t);
      if (show) {
        c.hidden = false;
        void c.offsetWidth;
        c.classList.remove("is-out");
      } else {
        c.classList.add("is-out");
        c._t = setTimeout(function () { c.hidden = true; }, DUR);
      }
    });
    updateCount();
  }
  updateCount();

  // trends
  D.trends.forEach(function (t) {
    var c = el("article", "trend");
    c.setAttribute("data-testid", "trend-" + t.id);
    c.appendChild(el("div", "stat", t.stat));
    c.appendChild(el("h3", null, t.title));
    c.appendChild(el("p", "muted", t.text));
    $("trend-cards").appendChild(c);
  });

  // inline SVG bar chart
  (function () {
    var svg = $("chart"), max = 80, left = 150, w = 400, rowH = 38, y0 = 10;
    D.chart.forEach(function (d, i) {
      var y = y0 + i * rowH, bw = Math.round(w * d.growth / max);
      var lab = document.createElementNS(NS, "text");
      lab.setAttribute("x", left - 10); lab.setAttribute("y", y + 19);
      lab.setAttribute("text-anchor", "end"); lab.setAttribute("class", "c-label");
      lab.textContent = d.genre;
      var r = document.createElementNS(NS, "rect");
      r.setAttribute("x", left); r.setAttribute("y", y); r.setAttribute("height", 26);
      r.setAttribute("width", bw); r.setAttribute("rx", 6); r.setAttribute("class", "c-bar");
      var val = document.createElementNS(NS, "text");
      val.setAttribute("x", left + bw + 8); val.setAttribute("y", y + 19); val.setAttribute("class", "c-val");
      val.textContent = "+" + d.growth + "%";
      svg.appendChild(lab); svg.appendChild(r); svg.appendChild(val);
    });
  })();

  // ranked genres
  D.promising.forEach(function (p) {
    var li = el("li", "rank-item");
    li.setAttribute("data-testid", "rank-" + p.rank);
    li.appendChild(el("span", "rank-n", String(p.rank)));
    var d = el("div");
    d.appendChild(el("h3", null, p.genre));
    d.appendChild(el("p", "muted", p.why));
    li.appendChild(d);
    $("rank").appendChild(li);
  });

  // modal
  var lastFocus = null;
  function openModal(v, trigger) {
    lastFocus = trigger;
    var mt = $("m-thumb"); mt.textContent = ""; mt.appendChild(thumb(v, "m"));
    $("m-title").textContent = v.title;
    $("m-meta").textContent = v.creator + " · " + genreLabel(v.genre) + " · " + v.views + " views · ▲ " + v.growth + "%";
    $("m-desc").textContent = v.description;
    $("m-prompt").textContent = v.prompt;
    $("m-tool").textContent = v.tool;
    $("m-why").textContent = v.why;
    $("modal").hidden = false;
    document.body.classList.add("lock");
    $("modal-close").focus();
  }
  function closeModal() {
    $("modal").hidden = true;
    document.body.classList.remove("lock");
    if (lastFocus) lastFocus.focus();
  }
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", function (e) { if (e.target === $("modal")) closeModal(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("modal").hidden) closeModal(); });
})();
