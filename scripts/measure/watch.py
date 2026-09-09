"""Selector inventory, shared by the harness and the comparator."""

# Per-section families. A selector may appear in more than one list where the
# vocabulary is genuinely shared (.rec* by 03/04, .sub-wrap by 04/06/07,
# .prov-mark by almost everything).
SECTIONS = {
    "s1": [".id-name-h", ".id-name-lg", ".id-name-ttl", ".id-name-ar",
           ".id-traits", ".id-trait",
           ".id-dob", ".facts.id-grid", ".fact", ".fact.c2", ".fact .k",
           ".fact .v", ".fact .v .mono", ".v-sub", ".mob-list", ".mob .num",
           ".mob .when", ".facts.id-grid > .fact:last-child"],
    "s2": [".score-strip", ".ss-score", ".ss-val", ".ss-k", ".ss-bands",
           ".ss-band", ".ss-band em", ".ss-gauge", ".ss-bar", ".ss-marker",
           ".ss-ticks", ".ss-hist", ".ss-hv", ".ss-hu", ".ss-vint", ".ss-hs"],
    "s3": [".inc-latest", ".inc-latest-k", ".inc-latest-v", ".inc-latest-s",
           ".emp-name", ".emp-cur", ".emp-prov", ".other-inc", ".oi-line",
           ".inc-legend", ".inc-lg", ".inc-tray-k", ".inc-chip", ".inc-why",
           ".inc-note", ".attn"],
    "s4": [".ret-grp", ".rec-t", ".ret-amt", ".ret-date", ".rtype", ".sev",
           ".mk-lg", ".sub-wrap.slim .sub-bar-t"],
    # The .wsx-row* family went with the three-panel redesign (7 Aug 2026).
    # The pending 36-month panel renders an .empty-state inside a .wsx-panel,
    # which is scoped markup the bare .empty-state selector would resolve to
    # section 06's instead -- hence the scoped entries.
    "s5": [".wsx", ".wsx-panel", ".wsx-win", ".wsx-fig", ".wsx-worst",
           ".wsx-sub", ".wsx-sub .k", ".wsx-sub .v",
           "#s5 .empty-state", "#s5 .es-msg", "#s5 .es-detail"],
    # Rebuilt 7 Aug 2026. Gone with the donut and the folded utilisation chart:
    # .fac-count, .fac-note, .donut*, .overlimit-flag and the whole .cb-* family.
    # New: the role split (.fac-role / .fac-nil) and the utilisation line.
    "s6": [".fac-grid", ".fac", ".fac-h", ".fac-cat", ".fac-name",
           ".fac-block", ".fac-role", ".fac-nil", ".fac-big", ".fac-outcomes",
           ".fac-rows", ".fac-row", ".fac-row .k", ".fac-row .val",
           ".fac-util", ".fac-util-h .k", ".fac-util-h .v",
           ".fac-util-bar", ".fac-util-fill"],
    # Restructured 7 Aug 2026 into four buckets. .hm-blockhead is the bucket
    # heading (and carries the fold); .hm-grouphead is the AECB category inside
    # it. .role now renders only for a non-main holder and .freq only where AECB
    # delivers one, so neither is present on the reference payload -- they are
    # exercised by synthetic.py's guarantor-role case.
    "s7": [".hm-wrap", ".hm", ".hm-axis-lab", ".hm-mo", ".hm-blockhead",
           ".hm-grouphead", ".hm-gc", ".hm-rl", ".hm-rl-t", ".hm-rl-s",
           ".hm-cells", ".cell", ".scell", ".ucell", ".prov-badge",
           ".closed-on", ".final-st", ".we", ".hm-warn", ".freq", ".role",
           ".stl-t", ".stl",
           ".stl-more", ".lg", ".hm-note"],
    # Rewritten 7 Aug 2026 from counter tiles + a deferred table to one chart.
    # Gone: .ret-stats / .rs* / .enq-tbl* / .er-date / .enq-divider /
    # .inc-conflict / the .phase pill vocabulary. The .tl-* family is shared
    # with nothing else now, so it is watched here.
    "s8": [".enq-tl", ".enq-focus", ".enq-split", ".tl-axis", ".tl-mo",
           ".tl-event", ".tl-event .mk", ".tl-event .mk.disp",
           ".tl-event .amt", ".tl-event .stem",
           ".enq-key", ".ek", ".ek-mk", ".ek-mk.disp", ".ek-role", ".ek-note"],
    # Shared frame -- belongs to 03 and 04 jointly, and carries the Python
    # mirrors in sections/returns.py (_TILE_BASE/_TILE_ENTRY/_TILE_GAP/_COL_W).
    "shared34": [".inc-split", ".inc-detail", ".inc-vis", ".inc-svg",
                 ".rec", ".rec-h", ".rec-meta", ".rec-list", ".rec-item",
                 ".rec-none", ".trend-head", ".trend-title", ".prov-mark",
                 # Scoped to section 04. The bare selectors above resolve to
                 # section 03's, which LOADS COLLAPSED and therefore measures
                 # zero -- useless as a witness for the Python mirrors.
                 "#s4 .inc-vis", "#s4 .rec", "#s4 .rec-item", "#s4 .rec-list",
                 "#s4 .rec-t", "#s4 .ret-amt", "#s4 .rec-meta", "#s4 .inc-svg"],
    # Never changes: the top bar is locked, and the rail is chrome.
    "locked": [".topbar", ".brand-t", ".brand-mark", ".tb-valid", ".tb-scope",
               ".tv-k",
               ".tv-v", ".tv-meter", ".brief-btn", ".rail", ".rail-title",
               ".rail-sub", ".re-title", ".re-body p",
               ".sec", ".sec-title", ".sec-purpose", ".sec-no", ".sec-toggle",
               ".tag", ".hint", ".na", ".histflag", ".chevron", ".spine-dot",
               ".report", ".wrap", ".empty-state", ".es-msg", ".es-detail"],
}

ALL = []
for _k in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "shared34", "locked"):
    for _s in SECTIONS[_k]:
        if _s not in ALL:
            ALL.append(_s)


