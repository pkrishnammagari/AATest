"""Background lens: curated macro context from config/macro_context.json.

This is the ONLY time-sensitive knowledge the model receives: its own
training knowledge is cutoff-frozen and must not supply current conditions,
so currency comes from a human-curated file under MRM change control, each
entry stamped with the file's as-of date, and the model contributes only the
connection to this payload.
"""

from __future__ import annotations

from ...context import load_optional_config
from ._common import BACKGROUND


def macro_facts(facts):
    """config/macro_context.json entries as citable facts, as-of stamped.

    The file is OPTIONAL and, unlike every other config, absence degrades
    silently -- the brief works without macro context. A malformed file is
    still a loud failure.
    """
    macro = load_optional_config("macro_context.json")
    if macro is None:
        return
    as_of = str(macro.get("as_of") or "undated").strip()
    for entry in macro.get("facts") or []:
        text = str(entry.get("text") or "").strip()
        if text:
            facts.add(BACKGROUND,
                      "[curated context, as of %s] %s" % (as_of, text),
                      ["config/macro_context.json"],
                      None)
