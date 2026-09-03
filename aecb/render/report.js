/* Report interactions and charts.
 *
 * Everything data-driven reads from window.__AECB, a blob emitted by
 * aecb/render/js.py. No figures are hard-coded here: to wire a chart to the
 * payload, change what Python puts in the blob, not this file.
 *
 * Sections:
 *   1. helpers
 *   2. charts   (enquiries, heatmap)
 *   3. behaviour (tooltip, expanders, folds, spine nav, rail)
 */
(function () {
  "use strict";

  var A = window.__AECB || {};
  var T = A.tokens || {};

  /* ---------- 1. helpers ---------- */

  // Parse 'YYYY-MM-DD' as a LOCAL date. new Date('2023-10-26') would parse as
  // UTC and can land on the previous day west of Greenwich, shifting every
  // month label on the axis. Returns null for a missing date -- falling back
  // to "today" would stamp real month names onto a report whose date the
  // payload never stated.
  function d(iso) {
    if (!iso) return null;
    var p = String(iso).slice(0, 10).split("-");
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  function monthsBack(from, m) {
    return new Date(from.getFullYear(), from.getMonth() - m, 1);
  }

  function moLbl(from, m) {
    var x = monthsBack(from, m);
    return x.toLocaleString("en", { month: "short" }) + " '" + String(x.getFullYear()).slice(2);
  }

  function el(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* ---------- 2. charts ---------- */

  /* Section 04's timeline is inline SVG built in Python, not drawn here: the
     decision of whether a chart can be drawn at all depends on which dates the
     payload carries, and that decision belongs beside the data it is made from.
     See aecb/render/sections/income.py. */

  /* Section 06's utilisation line is built in Python, not here. It reads one
     delivered field (contractsTotalSummary.CreditUtilizationRate) and draws a
     div, so there was nothing left for JavaScript to do once the donut and the
     average-vs-peak trend chart went with the 7 Aug 2026 rebuild. */

  /* Section 05's returns timeline is inline SVG built in Python, like section
     04's -- see aecb/render/sections/returns.py. */

  /* Section 08's application timeline.

     The axis is SPLIT -- the last 90 days take most of the width, everything
     older is compressed into the rest -- and every position arrives already
     computed as a percentage from derive/applications.py. Percentages rather
     than an SVG viewBox on purpose: the row has to scale with the report column
     across two rail states and ten widths, and a viewBox would magnify the
     8.5px axis labels along with it. */
  function applicationTimeline() {
    var cfg = A.applications;
    var node = el("enqTimeline");
    if (!cfg || !node) return;

    var LANE = cfg.lanePitch, BASE = 30;
    // split 0 = the focus window IS the whole axis; there is no break to draw.
    var h = (cfg.split > 0
              ? '<div class="enq-focus" style="left:' + cfg.split + '%"></div>' +
                '<div class="enq-split" style="left:' + cfg.split + '%"></div>'
              : "") +
            '<div class="tl-axis"></div>';

    (cfg.ticks || []).forEach(function (t) {
      h += '<div class="tl-mo' + (t.lead ? " lead" : "") + '" style="left:' +
           t.x + '%">' + esc(t.label) + "</div>";
    });

    (cfg.events || []).forEach(function (e) {
      var stem = BASE + e.lane * LANE;
      h += '<div class="tl-event" style="left:' + e.x + '%" data-info="' +
           esc(e.info) + '">' +
           '<div class="amt">' + esc(e.provider || "") + "</div>" +
           '<div class="mk' + (e.taken ? " taken" : "") +
           (e.focus ? " focus" : "") + '">' + esc(e.glyph || "") + "</div>" +
           '<div class="stem" style="height:' + stem + 'px"></div></div>';
    });

    node.innerHTML = h;
  }

  /* 36-month conduct heatmap, grouped by contract category. */
  function heatmap() {
    var cfg = A.heatmap;
    var node = el("heatmap");
    if (!cfg || !node) return;

    var M = cfg.months, now = d(cfg.reportDate);
    var ST = cfg.statusCodes || {};      // code -> {label, rank}
    var ROLE = cfg.roles || {};
    var FREQ = cfg.frequency || {};
    var DPD = cfg.dpdBuckets || [];

    // Month label for a cell. Without a report date there is nothing to anchor
    // real month names to, so cells are labelled by their offset instead.
    function lbl(m) {
      return now ? moLbl(now, m) : "m−" + m;
    }
    function meta(code) {
      // rank null = severity unknown -- painted as unknown, never as clean.
      return ST[code] || { label: "Not in the AECB status table — severity unknown", rank: null };
    }
    // Colour band follows the bureau's own severity ranking.
    function stCls(code) {
      var r = meta(code).rank;
      return r == null ? "su" : r <= 60 ? "ss" : r < 100 ? "sa" : "sn";
    }
    function bucket(days) {
      for (var i = 0; i < DPD.length; i++) {
        if (DPD[i].max === null || days <= DPD[i].max) return DPD[i];
      }
      return DPD[DPD.length - 1];
    }
    function uCol(v) {
      return v == null ? "var(--dpd-none)" : (v > 100 ? T.red : T["green-mid"]);
    }

    function rowHtml(c) {
      var stats = "";
      if (c.limit) stats += '<span class="stat">Limit <b>' + esc(c.limit) + "</b></span>";
      if (c.os) stats += '<span class="stat">OS <b>' + esc(c.os) + "</b></span>";
      if (c.payment) stats += '<span class="stat">Payment <b>' + esc(c.payment) + "</b></span>";
      if (c.tenor) stats += '<span class="stat">Tenor <b>' + esc(c.tenor) + "</b></span>";
      if (c.util != null) {
        stats += '<span class="stat">Util <b style="color:' +
                 (c.util > 100 ? "var(--red)" : "var(--green)") + '">' + esc(c.util) + "%</b></span>";
      }
      if (c.maxdpd > 0) stats += '<span class="stat dpd">Max DPD <b>' + esc(c.maxdpd) + "</b></span>";
      // How much of the window this provider actually filed. A row with two
      // reported months tells you almost nothing, however green it looks.
      if (c.monthsReported != null) {
        var thin = c.monthsReported < 6;
        stats += '<span class="stat cov' + (thin ? " thin" : "") + '" data-info="' +
                 'The provider filed ' + c.monthsReported + ' monthly rows out of ' + M +
                 '. Unreported months are grey and carry no conduct information.">' +
                 'Reported <b>' + c.monthsReported + "/" + M + "</b></span>";
      }
      if (c.closedUndated) {
        stats += '<span class="closed-on na" data-info="AECB reports this ' +
                 'contract as closed but delivers no ClosedDate, so it cannot ' +
                 'be placed in the 6-month window and is listed with the older ' +
                 'closures.">Closed · date not reported</span>';
      }
      if (c.closedOn) {
        stats += '<span class="closed-on">Closed ' + esc(c.closedOn) + "</span>";
        if (c.finalStatus) {
          stats += '<span class="final-st ' + stCls(c.finalStatus) + '" data-info="Final contract status ' +
                   esc(c.finalStatus) + " — " + esc(meta(c.finalStatus).label) +
                   '. This is the status AECB carries for the contract\'s closing month.">Final · ' +
                   esc(meta(c.finalStatus).label) + "</span>";
        } else {
          // No history row for the closing month (closures outside the window
          // included). The lifetime WorstStatus is NOT a stand-in for it.
          stats += '<span class="final-st na" data-info="AECB delivers no status ' +
                   'row for this contract\'s closing month, so the closing ' +
                   'status is not reported.">Final · not reported</span>';
        }
      }
      /* Frequency shows only when AECB delivers one. The old "Frequency n/a"
         chip appeared on every card and service row, and it was not stating a
         missing value: frequency is not part of those schemas at all, so there
         is no gap to report. An absence the bureau could never have filled is
         not the kind this page exists to surface. */
      if (c.freq && FREQ[c.freq]) {
        stats += '<span class="freq" data-info="AECB payment frequency ' + esc(c.freq) + " — " +
                 esc(FREQ[c.freq].long) + '">' + esc(FREQ[c.freq].short) + "</span>";
      }
      /* Role likewise shows only when it is NOT main holder. Main holder is the
         default across the book; a co-holder or guarantor is the exception that
         changes who is liable, and marking every row "Main holder" buried it. */
      var rl = ROLE[c.role];
      if (rl && c.role && c.role !== "A") {
        stats += '<span class="role ' + rl.css + '">' + esc(rl.label) + "</span>";
      }
      if (c.overLimit) stats += '<span class="ovl">OVER LIMIT ' + c.util + "%</span>";
      if (c.overdueNow) stats += '<span class="ovl">Overdue now AED ' + esc(c.overdueNow) + "</span>";

      var h = '<div class="hm-row' + (c.closedAtMonth != null ? " isclosed" : "") + '">' +
              '<div class="hm-rl"><div class="hm-rl-t">' + esc(c.name) +
              ' <span class="prov-badge ' + esc(c.badge) + '">' + esc(c.code) + "</span> " +
              esc(c.provider) + '</div><div class="hm-rl-s">' + stats + "</div></div>" +
              '<div class="hm-rcells"><div class="hm-sstrip">';

      var st = c.status || {}, delays = c.delays || {}, m;

      /* Which months the bureau actually reported. A month outside this set is
         NOT current -- it is unknown, and must never be painted green. Coverage
         is sparse in real payloads, so this distinction carries real weight. */
      var reported = null;
      if (c.reported) {
        reported = {};
        for (var i = 0; i < c.reported.length; i++) reported[c.reported[i]] = true;
      }
      var wasReported = function (mo) { return reported ? !!reported[mo] : true; };

      // status strip -- one AECB status code per reported month
      for (m = 0; m < M; m++) {
        if (m > c.openMonths) { h += '<div class="scell sx"></div>'; continue; }
        if (c.closedAtMonth != null && m < c.closedAtMonth) {
          h += '<div class="scell sc" data-info="' + lbl(m) + " · contract closed " +
               esc(c.closedOn) + ' — no history reported"></div>';
          continue;
        }
        if (!wasReported(m)) {
          h += '<div class="scell sx" data-info="' + lbl(m) +
               ' · no status reported for this month"></div>';
          continue;
        }
        var k = st[m] || "U";
        h += '<div class="scell ' + stCls(k) + '" data-info="' + lbl(m) + " · status " +
             esc(k) + " — " + esc(meta(k).label) + '">' + esc(k) + "</div>";
      }
      h += '</div><div class="hm-cells">';

      // DPD strip
      for (m = 0; m < M; m++) {
        if (m > c.openMonths) {
          h += '<div class="cell dn" data-info="' + lbl(m) +
               ' · before this facility opened"></div>';
          continue;
        }
        if (c.closedAtMonth != null && m < c.closedAtMonth) {
          h += '<div class="cell dc" data-info="' + lbl(m) + " · contract closed " +
               esc(c.closedOn) + '"></div>';
          continue;
        }
        if (!wasReported(m)) {
          h += '<div class="cell dn" data-info="' + lbl(m) +
               ' · NOT REPORTED — the provider filed no row for this month. ' +
               'This is not a record of on-time payment."></div>';
          continue;
        }
        var dl = delays[m];
        if (dl) {
          var b = bucket(dl.days);
          h += '<div class="cell ' + b["class"] + '" data-info="' + lbl(m) + " · " +
               esc(dl.days) + " days past due · status: " + esc(b.label) + " · balance AED " +
               esc(c.os) + '">' + esc(dl.days) + "</div>";
        } else {
          h += '<div class="cell d0" data-info="' + lbl(m) +
               ' · current (0 DPD) · balance AED ' + esc(c.os) + '"></div>';
        }
      }
      h += "</div>";

      // utilisation sub-strip, cards and overdrafts only. Only a payload-fed
      // series draws -- nothing here synthesises one.
      var us = c.u;
      if (us) {
        h += '<div class="hm-ustrip">';
        for (m = 0; m < M; m++) {
          var v = us[m];
          if (v == null) {
            h += '<div class="ucell" style="background:var(--dpd-none)"></div>';
          } else {
            h += '<div class="ucell" style="background:' + uCol(v) + '" data-info="' +
                 lbl(m) + " · utilisation " + esc(v) + "%" + (v > 100 ? " · OVER LIMIT" : "") +
                 '"></div>';
          }
        }
        h += "</div>";
      }
      return h + "</div></div>";
    }

    // month axis
    /* The label column keeps its width with no text in it: the month labels
       have to line up over the cells, and that alignment is what the empty
       .hm-axis-lab is holding. */
    var html = '<div class="hm-axis"><div class="hm-axis-lab"></div><div class="hm-months">';
    for (var m = 0; m < M; m++) {
      html += '<div class="hm-mo ' + (m % 6 === 0 ? "" : "tk") + '">' +
              (m % 6 === 0 ? lbl(m) : "·") + "</div>";
    }
    html += "</div></div>";

    var seen = { U: true };
    function note(c) {
      Object.keys(c.status || {}).forEach(function (k) { seen[c.status[k]] = true; });
      if (c.finalStatus) seen[c.finalStatus] = true;
    }

    /* Four blocks, each grouped by category. What goes in which block is a
       payload decision -- closure dates, arrears -- so it is made in js.py and
       arrives already bucketed; this only draws what it is handed. */
    (cfg.blocks || []).forEach(function (b) {
      var fold = !!b.collapsed;
      html += '<div class="hm-blockhead' + (fold ? " tog closed" : "") + '"' +
              (fold ? ' data-fold="' + esc(b.key) + '"' : "") + ">" +
              esc(b.label) + ' <span class="gh-n">(' + b.n + ")</span>" +
              (fold ? '<button class="sec-toggle" aria-expanded="false">\u25be</button>' : "") +
              "</div>";

      var inner = "";
      (b.groups || []).forEach(function (g) {
        var rows = g.rows || [];
        inner += '<div class="hm-grouphead"><span class="hm-gc ' + esc(g.cat) + '">' +
                 esc(g.cat) + "</span>" + esc(g.label) +
                 ' <span class="gh-n">(' + rows.length + ")</span></div>";
        rows.forEach(function (c) { note(c); inner += rowHtml(c); });
      });

      html += fold
        ? '<div class="hm-fold closed" id="' + esc(b.key) + '">' + inner + "</div>"
        : inner;
    });

    node.innerHTML = html;

    // group folds
    document.querySelectorAll(".hm-blockhead.tog").forEach(function (gh) {
      gh.addEventListener("click", function () {
        var f = el(gh.dataset.fold);
        if (!f) return;
        var isClosed = f.classList.toggle("closed");
        gh.classList.toggle("closed", isClosed);
        var b = gh.querySelector(".sec-toggle");
        if (b) b.setAttribute("aria-expanded", String(!isClosed));
      });
    });

    // status legend: codes present in this report first, full table behind the expander
    var order = Object.keys(ST).sort(function (a, b) { return meta(a).rank - meta(b).rank; });
    var chip = function (k) {
      return '<span class="stl"><i class="' + stCls(k) + '">' + esc(k) + "</i>" +
             esc(meta(k).label) + "</span>";
    };
    // '?' is not a config code, so it joins the head chips only when an
    // unknown status actually occurred in this report.
    var present = order.filter(function (k) { return seen[k]; });
    if (seen["?"]) present.push("?");
    var head = el("stlHead"), grid = el("stlGrid"), all = el("stlAll");
    if (head && grid) {
      head.innerHTML = '<span class="stl-t">Monthly status</span>' +
        present.map(chip).join("") +
        '<button class="stl-more" id="stlMore">all status codes ▾</button>';
      grid.innerHTML = order.filter(function (k) { return !seen[k]; }).map(chip).join("");
      var more = el("stlMore");
      if (more && all) {
        more.addEventListener("click", function () {
          var open = all.classList.toggle("show");
          more.textContent = open ? "all status codes ▴" : "all status codes ▾";
        });
      }
    }
  }

  /* ---------- 3. behaviour ---------- */

  /* One shared tooltip for every [data-info] element. */
  function tooltips() {
    var tip = document.createElement("div");
    // Text colour has no token: it is the tooltip's own light-on-ink pairing.
    tip.style.cssText =
      "position:fixed;z-index:100;background:" + (T.ink || "#141E2C") + ";color:#EAF0F5;" +
      'font-family:"IBM Plex Mono",monospace;font-size:10px;padding:6px 9px;border-radius:6px;' +
      "pointer-events:none;opacity:0;transition:opacity .1s;" +
      "box-shadow:0 8px 30px rgba(20,30,44,.35);max-width:230px;line-height:1.45";
    document.body.appendChild(tip);

    function bind(node) {
      node.addEventListener("mouseenter", function () {
        tip.textContent = node.dataset.info;
        tip.style.opacity = 1;
      });
      node.addEventListener("mousemove", function (e) {
        tip.style.left = Math.min(e.clientX + 12, window.innerWidth - 242) + "px";
        tip.style.top = (e.clientY - 40) + "px";
      });
      node.addEventListener("mouseleave", function () { tip.style.opacity = 0; });
    }

    // Charts render after this runs, so expose a rebind for newly added nodes.
    window.__bindTips = function () {
      document.querySelectorAll("[data-info]:not([data-tipbound])").forEach(function (n) {
        n.setAttribute("data-tipbound", "1");
        bind(n);
      });
    };
    window.__bindTips();
  }

  /* In-cell identity history expanders. */
  function expanders() {
    document.querySelectorAll(".chevron[data-exp]").forEach(function (ch) {
      ch.addEventListener("click", function () {
        var t = el(ch.dataset.exp);
        if (!t) return;
        var open = t.classList.toggle("show");
        ch.textContent = ch.textContent.replace(/[▾▴]/, open ? "▴" : "▾");
      });
    });
  }

  function secOpen(sec) {
    if (!sec || !sec.classList.contains("coll") || !sec.classList.contains("closed")) return;
    sec.classList.remove("closed");
    var b = sec.querySelector(".sec-toggle");
    if (b) b.setAttribute("aria-expanded", "true");
  }

  function collapsibles() {
    document.querySelectorAll(".sec.coll").forEach(function (sec) {
      sec.querySelector(".sec-head").addEventListener("click", function () {
        var isClosed = sec.classList.toggle("closed");
        var b = sec.querySelector(".sec-toggle");
        if (b) b.setAttribute("aria-expanded", String(!isClosed));
      });
    });
    document.querySelectorAll(".sub-bar").forEach(function (bar) {
      bar.addEventListener("click", function () {
        var w = bar.parentElement;
        var isClosed = w.classList.toggle("sub-closed");
        var b = bar.querySelector(".sec-toggle");
        if (b) b.setAttribute("aria-expanded", String(!isClosed));
      });
    });
  }

  function spineNav() {
    var dots = [].slice.call(document.querySelectorAll(".spine-dot"));
    if (!dots.length) return;
    dots.forEach(function (dot) {
      dot.addEventListener("click", function () {
        var t = el(dot.dataset.to);
        if (!t) return;
        secOpen(t);
        t.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    var secs = dots.map(function (dot) { return el(dot.dataset.to); });
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var i = secs.indexOf(e.target);
        dots.forEach(function (x) { x.classList.remove("active"); });
        if (dots[i]) dots[i].classList.add("active");
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    secs.forEach(function (s) { if (s) obs.observe(s); });
  }

  function railToggle() {
    var x = el("railX"), btn = el("briefBtn");
    if (x) x.addEventListener("click", function () { document.body.classList.add("rail-off"); });
    if (btn) btn.addEventListener("click", function () { document.body.classList.toggle("rail-off"); });
  }

  /* ---------- boot ---------- */

  tooltips();
  applicationTimeline();
  heatmap();
  window.__bindTips();      // charts injected new [data-info] nodes
  expanders();
  collapsibles();
  spineNav();
  railToggle();
})();
