/* Report interactions and charts.
 *
 * Everything data-driven reads from window.__AECB, a blob emitted by
 * aecb/render/js.py. No figures are hard-coded here: to wire a chart to the
 * payload, change what Python puts in the blob, not this file.
 *
 * Sections:
 *   1. helpers
 *   2. charts   (applications timeline, conduct heatmap)
 *   3. behaviour (tooltip, expanders, folds, spine nav, rail)
 *
 * The income and returns timelines and the facilities utilisation line are
 * inline SVG/HTML built in Python (aecb/render/sections/), not drawn here:
 * whether they can be drawn at all depends on which dates the payload
 * carries, and that decision belongs beside the data.
 */
(function () {
  "use strict";

  const A = window.__AECB || {};
  const T = A.tokens || {};

  /* ---------- 1. helpers ---------- */

  // Parse 'YYYY-MM-DD' as a LOCAL date. new Date('2023-10-26') would parse as
  // UTC and can land on the previous day west of Greenwich, shifting every
  // month label on the axis. Returns null for a missing date -- falling back
  // to "today" would stamp real month names onto a report whose date the
  // payload never stated.
  function d(iso) {
    if (!iso) return null;
    const p = String(iso).slice(0, 10).split("-");
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  function monthsBack(from, m) {
    return new Date(from.getFullYear(), from.getMonth() - m, 1);
  }

  function moLbl(from, m) {
    const x = monthsBack(from, m);
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

  function asSet(list) {
    if (!list) return null;
    const out = {};
    for (const item of list) out[item] = true;
    return out;
  }

  /* ---------- 2. charts ---------- */

  /* The applications timeline.

     The axis is SPLIT -- the last 90 days take most of the width, everything
     older is compressed into the rest -- and every position arrives already
     computed as a percentage from derive/applications.py. Percentages rather
     than an SVG viewBox on purpose: the row has to scale with the report column
     across two rail states and ten widths, and a viewBox would magnify the
     8.5px axis labels along with it. */
  const TIMELINE_BASE = 30;

  function timelineEvent(e, lanePitch) {
    const stem = TIMELINE_BASE + e.lane * lanePitch;
    /* Exceptions only: a delivered dispute rings the marker, a non-main-
       holder role letters the provider label. Both keys are absent on the
       default case and nothing extra is drawn. */
    return '<div class="tl-event" style="left:' + e.x + '%" data-info="' +
           esc(e.info) + '">' +
           '<div class="amt">' + esc(e.provider || "") +
           (e.role ? " · " + esc(e.role) : "") + "</div>" +
           '<div class="mk' + (e.taken ? " taken" : "") + (e.otherPhase ? " other" : "") +
           (e.focus ? " focus" : "") + (e.disp ? " disp" : "") + '">' +
           esc(e.glyph || "") + "</div>" +
           '<div class="stem" style="height:' + stem + 'px"></div></div>';
  }

  function applicationTimeline() {
    const cfg = A.applications;
    const node = el("enqTimeline");
    if (!cfg || !node) return;

    // split 0 = the focus window IS the whole axis; there is no break to draw.
    let h = "";
    if (cfg.split > 0) {
      h += '<div class="enq-focus" style="left:' + cfg.split + '%"></div>' +
           '<div class="enq-split" style="left:' + cfg.split + '%"></div>';
    }
    h += '<div class="tl-axis"></div>';
    for (const t of cfg.ticks || []) {
      h += '<div class="tl-mo' + (t.lead ? " lead" : "") + '" style="left:' +
           t.x + '%">' + esc(t.label) + "</div>";
    }
    for (const e of cfg.events || []) h += timelineEvent(e, cfg.lanePitch);
    node.innerHTML = h;
  }

  /* 36-month conduct heatmap, grouped by contract category.

     heatmapKit() gathers what every row builder needs -- the month count,
     the label and colour rules -- so the builders below stay small, flat
     functions of (kit, row). */
  function heatmapKit(cfg) {
    const now = d(cfg.reportDate);
    const statusCodes = cfg.statusCodes || {};      // code -> {label, rank}
    const dpdBuckets = cfg.dpdBuckets || [];
    const severeMax = cfg.severeMax, normalMin = cfg.normalMin;

    function meta(code) {
      // rank null = severity unknown -- painted as unknown, never as clean.
      return statusCodes[code] ||
        { label: "Not in the AECB status table — severity unknown", rank: null };
    }
    return {
      cfg: cfg,
      months: cfg.months,
      statusCodes: statusCodes,
      roles: cfg.roles || {},
      frequency: cfg.frequency || {},
      meta: meta,
      // Month label for a cell. Without a report date there is nothing to
      // anchor real month names to, so cells are labelled by their offset.
      lbl: function (m) { return now ? moLbl(now, m) : "m−" + m; },
      // Colour band follows the bureau's own severity ranking.
      stCls: function (code) {
        const r = meta(code).rank;
        if (r == null) return "su";
        if (r <= severeMax) return "ss";
        return r < normalMin ? "sa" : "sn";
      },
      bucket: function (days) {
        for (const b of dpdBuckets) {
          if (b.max === null || days <= b.max) return b;
        }
        return dpdBuckets[dpdBuckets.length - 1];
      },
      uCol: function (v) {
        if (v == null) return "var(--dpd-none)";
        return v > 100 ? T.red : T["green-mid"];
      }
    };
  }

  function statChip(label, value) {
    return value ? '<span class="stat">' + label + ' <b>' + esc(value) + "</b></span>" : "";
  }

  /* "Current" figures are as delivered at Current_ReferenceDate, which can lag
     the report date -- the hover says when "current" actually was. */
  function basicStats(c) {
    let s = statChip("Limit", c.limit);
    if (c.os) {
      s += '<span class="stat"' +
           (c.asAt ? ' data-info="Current balance as delivered by AECB, as at ' +
                     esc(c.asAt) + ' — this snapshot can lag the report date."' : "") +
           '>OS <b>' + esc(c.os) + "</b></span>";
    }
    s += statChip("Amount", c.amount) + statChip("Payment", c.payment) +
         statChip("Tenor", c.tenor);
    if (c.util != null) {
      s += '<span class="stat">Util <b style="color:' +
           (c.util > 100 ? "var(--red)" : "var(--green)") + '">' + esc(c.util) + "%</b></span>";
    }
    if (c.method) s += '<span class="stat">' + esc(c.method) + "</span>";
    if (c.secured != null) {
      s += '<span class="stat">Secured' + (c.secured ? " · " + esc(c.secured) : "") + "</span>";
    }
    if (c.maxdpd > 0) s += '<span class="stat dpd">Max DPD <b>' + esc(c.maxdpd) + "</b></span>";
    return s;
  }

  function dated(text, when) {
    return text + (when ? " (" + when + ")" : "");
  }

  /* The contract's dated LIFETIME worst -- it can predate the window, so a
     clean-looking strip must not hide it. Ships only when adverse. */
  function worstEverChip(kit, we) {
    if (!we) return "";
    const bits = [];
    const label = we.code ? (we.label || kit.meta(we.code).label) : "";
    if (we.code) bits.push(dated("worst status " + we.code + " — " + label, we.when));
    if (we.maxDays) bits.push(dated("deepest delay " + we.maxDays + " days", we.maxDaysWhen));
    if (we.maxOverdue) bits.push(dated("peak overdue AED " + we.maxOverdue, we.maxOverdueWhen));
    return '<span class="final-st we ' + (we.code ? kit.stCls(we.code) : "sa") +
           '" data-info="Lifetime worst, delivered on the contract row — it can predate ' +
           'the 36-month window: ' + esc(bits.join("; ")) + '.">Worst ever · ' +
           esc(we.code ? label : we.maxDays + "d late") + "</span>";
  }

  function warningChips(c) {
    let s = "";
    if (c.dispute) {
      s += '<span class="hm-warn" data-info="FlagOpenDispute is set on this contract — ' +
           'the row may change once the dispute resolves.">Open dispute</span>';
    }
    if (c.notLiable) {
      s += '<span class="hm-warn" data-info="HolderIsNotLiable is set — the conduct on ' +
           'this row may not be the subject&#39;s own liability.">Holder not liable</span>';
    }
    if (c.currency) {
      s += '<span class="hm-warn" data-info="Original currency ' + esc(c.currency) +
           ' — the page otherwise renders money as AED; this contract&#39;s figures are ' +
           'in its own currency.">' + esc(c.currency) + "</span>";
    }
    return s;
  }

  /* How much of the window this provider actually filed, against the months
     the facility was actually open -- "3/3" and "3/36" are different claims.
     A row with two reported months tells you almost nothing, however green it
     looks; a short facility fully reported is complete, not thin. */
  function coverageChip(kit, c) {
    if (c.monthsReported == null) return "";
    const poss = c.possible != null ? c.possible : kit.months;
    const thin = c.monthsReported < 6 && c.monthsReported < poss;
    return '<span class="stat cov' + (thin ? " thin" : "") + '" data-info="' +
           'The provider filed ' + c.monthsReported + ' monthly row(s) out of the ' + poss +
           ' month(s) this facility was open inside the window. Unreported months are ' +
           'grey and carry no conduct information.">' +
           'Reported <b>' + c.monthsReported + "/" + poss + "</b></span>";
  }

  function finalStatusChip(kit, code) {
    if (!code) {
      // No history row for the closing month (closures outside the window
      // included). The lifetime WorstStatus is NOT a stand-in for it.
      return '<span class="final-st na" data-info="AECB delivers no status ' +
             'row for this contract\'s closing month, so the closing ' +
             'status is not reported.">Final · not reported</span>';
    }
    const label = kit.meta(code).label;
    return '<span class="final-st ' + kit.stCls(code) + '" data-info="Final contract status ' +
           esc(code) + " — " + esc(label) +
           '. This is the status AECB carries for the contract\'s closing month.">Final · ' +
           esc(label) + "</span>";
  }

  function closureChips(kit, c) {
    let s = "";
    if (c.closedUndated) {
      s += '<span class="closed-on na" data-info="AECB reports this ' +
           'contract as closed but delivers no ClosedDate, so it cannot ' +
           'be placed in the ' + kit.cfg.closedWindow + '-month window and is listed ' +
           'with the older closures.">Closed · date not reported</span>';
    }
    if (c.closedOn) {
      s += '<span class="closed-on">Closed ' + esc(c.closedOn) + "</span>" +
           finalStatusChip(kit, c.finalStatus);
    }
    return s;
  }

  /* Frequency shows only when AECB delivers one: frequency is not part of the
     card and service schemas at all, so there is no gap to report there. */
  function frequencyChip(kit, c) {
    const f = c.freq ? kit.frequency[c.freq] : null;
    if (f) {
      return '<span class="freq" data-info="AECB payment frequency ' + esc(c.freq) + " — " +
             esc(f.long) + '">' + esc(f.short) + "</span>";
    }
    if (c.freqText) {
      return '<span class="freq" data-info="Payment frequency as delivered — not in ' +
             'the configured frequency list.">' + esc(c.freqText) + "</span>";
    }
    return "";
  }

  /* Role likewise shows only when it is NOT main holder: a co-holder or
     guarantor is the exception that changes who is liable. A delivered role
     the config cannot read is never assumed to be main holder. */
  function roleChip(kit, c) {
    const rl = kit.roles[c.role];
    if (rl && c.role && c.role !== "A") {
      return '<span class="role ' + esc(rl.css) + '">' + esc(rl.label) + "</span>";
    }
    if (c.roleText) {
      return '<span class="role unk" data-info="Role as delivered — not one of the ' +
             'configured roles (main holder, co-holder, guarantor).">' +
             esc(c.roleText) + "</span>";
    }
    return "";
  }

  function exposureChips(c) {
    let s = "";
    // util is a number from js.py. Left unescaped on purpose: a blob that
    // ships overLimit without util then shows "undefined", which the corpus
    // browser pass is built to catch -- escaping would hide the defect.
    if (c.overLimit) s += '<span class="ovl">OVER LIMIT ' + c.util + "%</span>";
    if (c.overdueNow) s += '<span class="ovl">Overdue now AED ' + esc(c.overdueNow) + "</span>";
    return s;
  }

  function rowStats(kit, c) {
    return basicStats(c) + worstEverChip(kit, c.worstEver) + warningChips(c) +
           coverageChip(kit, c) + closureChips(kit, c) + frequencyChip(kit, c) +
           roleChip(kit, c) + exposureChips(c);
  }

  /* The contract's own numbers ride on the name's hover; the provider name
     prints only when it says more than the code on the badge. */
  function rowLabel(c) {
    const ids = [];
    if (c.ids && c.ids.cb) ids.push("AECB contract " + c.ids.cb);
    if (c.ids && c.ids.lender) ids.push("lender contract no. " + c.ids.lender);
    const nameHtml = ids.length
      ? '<span class="hm-name" data-info="' + esc(ids.join(" · ")) + '">' + esc(c.name) + "</span>"
      : esc(c.name);
    const provName = (c.provider && c.provider !== c.code) ? " " + esc(c.provider) : "";
    return nameHtml + ' <span class="prov-badge ' + esc(c.badge) + '">' + esc(c.code) + "</span>" +
           provName;
  }

  /* One month's position relative to the facility: "before" it opened,
     "closed", "unreported" (the provider filed no row -- NOT current, and
     never painted green), or "reported". */
  function monthState(c, reported, m) {
    if (m > c.openMonths) return "before";
    if (c.closedAtMonth != null && m < c.closedAtMonth) return "closed";
    if (reported && !reported[m]) return "unreported";
    return "reported";
  }

  // Status strip -- one AECB status code per reported month.
  function statusCell(kit, c, reported, m) {
    const state = monthState(c, reported, m);
    if (state === "before") return '<div class="scell sx"></div>';
    if (state === "closed") {
      return '<div class="scell sc" data-info="' + kit.lbl(m) + " · contract closed " +
             esc(c.closedOn) + ' — no history reported"></div>';
    }
    if (state === "unreported") {
      return '<div class="scell sx" data-info="' + kit.lbl(m) +
             ' · no status reported for this month"></div>';
    }
    const k = (c.status || {})[m] || "?";
    return '<div class="scell ' + kit.stCls(k) + '" data-info="' + kit.lbl(m) + " · status " +
           esc(k) + " — " + esc(kit.meta(k).label) + '">' + esc(k) + "</div>";
  }

  /* The month's OWN balance/overdue for a cell tooltip -- never the row-level
     current balance, which is not a monthly figure. */
  function moneyBits(c, m) {
    let s = "";
    if (c.bal && c.bal[m] != null) s += " · balance AED " + esc(c.bal[m]);
    if (c.od && c.od[m] != null) s += " · overdue AED " + esc(c.od[m]);
    return s;
  }

  function reportedDpdCell(kit, c, noDpd, m) {
    /* A month with a status row but no delivered DaysPaymentDelay must not
       paint as 0 DPD -- that would be a zero the bureau never sent. */
    if (noDpd && noDpd[m]) {
      return '<div class="cell dn" data-info="' + kit.lbl(m) +
             ' · status reported, but DaysPaymentDelay was not delivered for ' +
             'this month — this is not a record of 0 DPD.' + moneyBits(c, m) + '"></div>';
    }
    const dl = (c.delays || {})[m];
    if (!dl) {
      return '<div class="cell d0" data-info="' + kit.lbl(m) +
             ' · current (0 DPD)' + moneyBits(c, m) + '"></div>';
    }
    const b = kit.bucket(dl.days);
    return '<div class="cell ' + b["class"] + '" data-info="' + kit.lbl(m) + " · " +
           esc(dl.days) + " days past due · status: " + esc(b.label) +
           moneyBits(c, m) + '">' + esc(dl.days) + "</div>";
  }

  // DPD strip.
  function dpdCell(kit, c, reported, noDpd, m) {
    const state = monthState(c, reported, m);
    if (state === "before") {
      return '<div class="cell dn" data-info="' + kit.lbl(m) +
             ' · before this facility opened"></div>';
    }
    if (state === "closed") {
      return '<div class="cell dc" data-info="' + kit.lbl(m) + " · contract closed " +
             esc(c.closedOn) + '"></div>';
    }
    if (state === "unreported") {
      return '<div class="cell dn" data-info="' + kit.lbl(m) +
             ' · NOT REPORTED — the provider filed no row for this month. ' +
             'This is not a record of on-time payment."></div>';
    }
    return reportedDpdCell(kit, c, noDpd, m);
  }

  // Utilisation sub-strip, cards and overdrafts only. Only a payload-fed
  // series draws -- nothing here synthesises one.
  function utilStrip(kit, c) {
    if (!c.u) return "";
    let h = '<div class="hm-ustrip">';
    for (let m = 0; m < kit.months; m++) {
      const v = c.u[m];
      if (v == null) {
        h += '<div class="ucell" style="background:var(--dpd-none)"></div>';
      } else {
        h += '<div class="ucell" style="background:' + kit.uCol(v) + '" data-info="' +
             kit.lbl(m) + " · utilisation " + esc(v) + "%" + (v > 100 ? " · OVER LIMIT" : "") +
             '"></div>';
      }
    }
    return h + "</div>";
  }

  function rowHtml(kit, c) {
    // Which months the bureau actually reported. Coverage is sparse in real
    // payloads, so unreported-vs-current carries real weight.
    const reported = asSet(c.reported);
    const noDpd = asSet(c.noDpd);
    let status = "", dpd = "";
    for (let m = 0; m < kit.months; m++) {
      status += statusCell(kit, c, reported, m);
      dpd += dpdCell(kit, c, reported, noDpd, m);
    }
    return '<div class="hm-row' + (c.closedAtMonth != null ? " isclosed" : "") + '">' +
           '<div class="hm-rl"><div class="hm-rl-t">' + rowLabel(c) +
           '</div><div class="hm-rl-s">' + rowStats(kit, c) + "</div></div>" +
           '<div class="hm-rcells"><div class="hm-sstrip">' + status +
           '</div><div class="hm-cells">' + dpd + "</div>" +
           utilStrip(kit, c) + "</div></div>";
  }

  /* Month axis. The label column keeps its width with no text in it: the
     month labels have to line up over the cells, and that alignment is what
     the empty .hm-axis-lab is holding. */
  function monthAxis(kit) {
    let html = '<div class="hm-axis"><div class="hm-axis-lab"></div><div class="hm-months">';
    for (let m = 0; m < kit.months; m++) {
      html += '<div class="hm-mo ' + (m % 6 === 0 ? "" : "tk") + '">' +
              (m % 6 === 0 ? kit.lbl(m) : "·") + "</div>";
    }
    return html + "</div></div>";
  }

  function noteStatuses(c, seen) {
    for (const k of Object.keys(c.status || {})) seen[c.status[k]] = true;
    if (c.finalStatus) seen[c.finalStatus] = true;
  }

  function groupHtml(kit, g, seen) {
    const rows = g.rows || [];
    let inner = '<div class="hm-grouphead"><span class="hm-gc ' + esc(g.cat) + '">' +
                esc(g.cat) + "</span>" + esc(g.label) +
                ' <span class="gh-n">(' + rows.length + ")</span></div>";
    for (const c of rows) {
      noteStatuses(c, seen);
      inner += rowHtml(kit, c);
    }
    return inner;
  }

  /* One block. What goes in which block is a payload decision -- closure
     dates, arrears -- so it is made in js.py and arrives already bucketed;
     this only draws what it is handed. */
  function blockHtml(kit, b, seen) {
    const fold = !!b.collapsed;
    let html = '<div class="hm-blockhead' + (fold ? " tog closed" : "") + '"' +
               (fold ? ' data-fold="' + esc(b.key) + '"' : "") + ">" +
               esc(b.label) + ' <span class="gh-n">(' + b.n + ")</span>" +
               (fold ? '<button class="sec-toggle" aria-expanded="false">▾</button>' : "") +
               "</div>";
    let inner = "";
    for (const g of b.groups || []) inner += groupHtml(kit, g, seen);
    html += fold
      ? '<div class="hm-fold closed" id="' + esc(b.key) + '">' + inner + "</div>"
      : inner;
    return html;
  }

  /* Toggle a folded container and keep its button's aria-expanded in step. */
  function toggleFold(container, cls, head) {
    const isClosed = container.classList.toggle(cls);
    const b = head.querySelector(".sec-toggle");
    if (b) b.setAttribute("aria-expanded", String(!isClosed));
    return isClosed;
  }

  function bindBlockFolds() {
    for (const gh of document.querySelectorAll(".hm-blockhead.tog")) {
      gh.addEventListener("click", function () {
        const f = el(gh.dataset.fold);
        if (!f) return;
        gh.classList.toggle("closed", toggleFold(f, "closed", gh));
      });
    }
  }

  // Status legend: codes present in this report first, full table behind the
  // expander. '?' is not a config code, so it joins the head chips only when
  // an unknown status actually occurred in this report.
  function statusLegend(kit, seen) {
    const head = el("stlHead"), grid = el("stlGrid"), all = el("stlAll");
    if (!head || !grid) return;
    const order = Object.keys(kit.statusCodes)
      .sort(function (a, b) { return kit.meta(a).rank - kit.meta(b).rank; });
    const chip = function (k) {
      return '<span class="stl"><i class="' + kit.stCls(k) + '">' + esc(k) + "</i>" +
             esc(kit.meta(k).label) + "</span>";
    };
    const present = order.filter(function (k) { return seen[k]; });
    if (seen["?"]) present.push("?");
    head.innerHTML = '<span class="stl-t">Monthly status</span>' +
      present.map(chip).join("") +
      '<button class="stl-more" id="stlMore">all status codes ▾</button>';
    grid.innerHTML = order.filter(function (k) { return !seen[k]; }).map(chip).join("");
    const more = el("stlMore");
    if (more && all) {
      more.addEventListener("click", function () {
        const open = all.classList.toggle("show");
        more.textContent = open ? "all status codes ▴" : "all status codes ▾";
      });
    }
  }

  function heatmap() {
    const cfg = A.heatmap;
    const node = el("heatmap");
    if (!cfg || !node) return;
    const kit = heatmapKit(cfg);
    const seen = {};
    let html = monthAxis(kit);
    for (const b of cfg.blocks || []) html += blockHtml(kit, b, seen);
    node.innerHTML = html;
    bindBlockFolds();
    statusLegend(kit, seen);
  }

  /* ---------- 3. behaviour ---------- */

  /* One shared tooltip for every [data-info] element. */
  function tooltips() {
    const tip = document.createElement("div");
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

    // Charts render after this runs, so the boot sequence re-binds once they
    // have added their nodes.
    return function bindTips() {
      for (const n of document.querySelectorAll("[data-info]:not([data-tipbound])")) {
        n.setAttribute("data-tipbound", "1");
        bind(n);
      }
    };
  }

  /* In-cell identity history expanders. */
  function expanders() {
    for (const ch of document.querySelectorAll(".chevron[data-exp]")) {
      ch.addEventListener("click", function () {
        const t = el(ch.dataset.exp);
        if (!t) return;
        const open = t.classList.toggle("show");
        ch.textContent = ch.textContent.replace(/[▾▴]/, open ? "▴" : "▾");
      });
    }
  }

  function secOpen(sec) {
    if (!sec || !sec.classList.contains("coll") || !sec.classList.contains("closed")) return;
    sec.classList.remove("closed");
    const b = sec.querySelector(".sec-toggle");
    if (b) b.setAttribute("aria-expanded", "true");
  }

  /* Open a section if it is folded, then scroll to it -- shared by the spine
     dots and the brief's "Verify at" links. */
  function bindOpenAndScroll(link) {
    link.addEventListener("click", function () {
      const t = el(link.dataset.to);
      if (!t) return;
      secOpen(t);
      t.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function collapsibles() {
    for (const sec of document.querySelectorAll(".sec.coll")) {
      const head = sec.querySelector(".sec-head");
      head.addEventListener("click", function () { toggleFold(sec, "closed", sec); });
    }
    for (const bar of document.querySelectorAll(".sub-bar")) {
      bar.addEventListener("click", function () {
        toggleFold(bar.parentElement, "sub-closed", bar);
      });
    }
  }

  function markActive(dots, index) {
    for (const x of dots) x.classList.remove("active");
    if (dots[index]) dots[index].classList.add("active");
  }

  function spineNav() {
    const dots = Array.prototype.slice.call(document.querySelectorAll(".spine-dot"));
    if (!dots.length) return;
    dots.forEach(bindOpenAndScroll);
    const secs = dots.map(function (dot) { return el(dot.dataset.to); });
    const obs = new IntersectionObserver(function (entries) {
      for (const e of entries) {
        if (e.isIntersecting) markActive(dots, secs.indexOf(e.target));
      }
    }, { rootMargin: "-45% 0px -50% 0px" });
    for (const s of secs) {
      if (s) obs.observe(s);
    }
  }

  function railToggle() {
    const x = el("railX"), btn = el("briefBtn");
    if (x) x.addEventListener("click", function () { document.body.classList.add("rail-off"); });
    if (btn) btn.addEventListener("click", function () { document.body.classList.toggle("rail-off"); });
  }

  /* Brief findings carry "Verify at" links; the brief is baked server-side,
     so binding once at boot is enough. */
  function briefLinks() {
    for (const link of document.querySelectorAll(".bf-go[data-to]")) bindOpenAndScroll(link);
  }

  /* ---------- boot ---------- */

  const bindTips = tooltips();
  bindTips();
  applicationTimeline();
  heatmap();
  bindTips();      // charts injected new [data-info] nodes
  expanders();
  collapsibles();
  spineNav();
  railToggle();
  briefLinks();
})();
