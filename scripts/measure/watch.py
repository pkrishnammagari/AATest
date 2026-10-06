"""Selector inventory, shared by the harness and the comparator."""

# Per-section families. A selector may appear in more than one list where the
# vocabulary is genuinely shared (.rec* by 04/05, .sub-wrap by 05/06/07,
# .prov-mark by almost everything).
SECTIONS = {
    "s1": [".id-name-h", ".id-name-lg", ".id-name-ttl", ".id-name-ar",
           ".id-traits", ".id-trait",
           ".id-dob", ".facts.id-grid", ".fact", ".fact.c2", ".fact .k",
           ".fact .v", ".fact .v .mono", ".v-sub", ".mob-list", ".mob .num",
           ".mob .when", ".facts.id-grid > .fact:last-child"],
    # A half-width card with a dial, paired with s3 in a .sec-pair row.
    "s2": [".sec-pair", ".sp", ".sp-dial", ".sp-svg", ".sp-side", ".ss-bands",
           ".ss-band", ".ss-band em", ".ss-hist", ".ss-hline", ".ss-hv",
           ".ss-hu", ".ss-vint", ".ss-hs"],
    "s4": [".inc-latest", ".inc-latest-k", ".inc-latest-v", ".inc-latest-s",
           ".emp-name", ".emp-cur", ".emp-prov", ".other-inc", ".oi-line",
           ".inc-legend", ".inc-lg", ".inc-tray-k", ".inc-chip", ".inc-why",
           ".inc-note", ".attn"],
    "s5": [".ret-grp", ".rec-t", ".ret-amt", ".ret-date", ".rtype", ".sev",
           ".mk-lg", ".sub-wrap.slim .sub-bar-t"],
    # A panel stating an absence renders an .empty-state inside a .wsx-panel,
    # which the bare .empty-state selector would resolve to another section's
    # instead -- hence the scoped entries.
    "s3": [".wsx", ".wsx-panel", ".wsx-win", ".wsx-fig", ".wsx-worst",
           ".wsx-sub", ".wsx-sub .k", ".wsx-sub .v",
           "#s3 .empty-state", "#s3 .es-msg", "#s3 .es-detail"],
    # Facility cards, with the role split (.fac-role / .fac-nil) and the
    # utilisation line.
    "s6": [".fac-grid", ".fac", ".fac-h", ".fac-cat", ".fac-name",
           ".fac-block", ".fac-role", ".fac-nil", ".fac-big", ".fac-outcomes",
           ".fac-rows", ".fac-row", ".fac-row .k", ".fac-row .val",
           ".fac-util", ".fac-util-h .k", ".fac-util-h .v",
           ".fac-util-bar", ".fac-util-fill"],
    # Four buckets. .hm-blockhead is the bucket heading (and carries the
    # fold); .hm-grouphead is the AECB category inside it. .role renders only
    # for a non-main holder and .freq only where AECB delivers one, so neither
    # is present on the reference payload -- they are exercised by
    # synthetic.py's guarantor-role case.
    "s7": [".hm-wrap", ".hm", ".hm-axis-lab", ".hm-mo", ".hm-blockhead",
           ".hm-grouphead", ".hm-gc", ".hm-rl", ".hm-rl-t", ".hm-rl-s",
           ".hm-cells", ".cell", ".scell", ".ucell", ".prov-badge",
           ".closed-on", ".final-st", ".we", ".hm-warn", ".freq", ".role",
           ".stl-t", ".stl",
           ".stl-more", ".lg", ".hm-note"],
    # One timeline chart. The .tl-* family is shared with nothing else, so it
    # is watched here.
    "s8": [".enq-tl", ".enq-focus", ".enq-split", ".tl-axis", ".tl-mo",
           ".tl-event", ".tl-event .mk", ".tl-event .mk.disp",
           ".tl-event .amt", ".tl-event .stem",
           ".enq-key", ".ek", ".ek-mk", ".ek-mk.disp", ".ek-role", ".ek-note"],
    # Shared frame -- belongs to income (s4) and returns (s5) jointly, and
    # carries the Python mirrors in sections/returns.py
    # (_TILE_BASE/_TILE_ENTRY/_TILE_GAP/_COL_W).
    "shared34": [".inc-split", ".inc-detail", ".inc-vis", ".inc-svg",
                 ".rec", ".rec-h", ".rec-meta", ".rec-list", ".rec-item",
                 ".rec-none", ".trend-head", ".trend-title", ".prov-mark",
                 # Scoped to returns (s5). The bare selectors above resolve to
                 # income's (s4), which LOADS COLLAPSED and therefore measures
                 # zero -- useless as a witness for the Python mirrors.
                 "#s5 .inc-vis", "#s5 .rec", "#s5 .rec-item", "#s5 .rec-list",
                 "#s5 .rec-t", "#s5 .ret-amt", "#s5 .rec-meta", "#s5 .inc-svg"],
    # Never changes: the top bar is locked.
    "locked": [".topbar", ".brand-t", ".brand-mark", ".tb-valid", ".tb-scope",
               ".tv-k",
               ".tv-v", ".tv-meter", ".brief-btn",
               ".sec", ".sec-title", ".sec-purpose", ".sec-no", ".sec-toggle",
               ".tag", ".hint", ".na", ".histflag", ".chevron", ".spine-dot",
               ".report", ".wrap", ".empty-state", ".es-msg", ".es-detail"],
}

ALL = []
for _k in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "shared34", "locked"):
    for _s in SECTIONS[_k]:
        if _s not in ALL:
            ALL.append(_s)


