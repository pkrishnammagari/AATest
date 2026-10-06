"""The analysis blocks, one module each, sharing one protocol:

    generate(ctx, analysis, provider) -> dict

`analysis` is the dict aecb.brief.new_analysis built (facts, packets,
provenance, the other blocks' validated output); the returned dict is the
block's validated payload and is stored under analysis["blocks"][name] with
its status and provenance by aecb.brief.generate_block. A block raises
BriefUnavailable (or anything -- the orchestrator converts) when it cannot
produce output; it never returns a partial or unvalidated result.

Block order on the page is fixed by aecb.brief.BLOCKS. MODULES maps each
block name to its module.
"""

from __future__ import annotations

from . import checklist, lens, memo, risk

MODULES = {
    "lens": lens,
    "risk": risk,
    "checklist": checklist,
    "memo": memo,
}
