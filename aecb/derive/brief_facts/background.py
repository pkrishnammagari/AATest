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


CONFIG = "macro_context.json"


def load():
    """The register, validated, or None when the file is absent.

    A file that carries a `sectors` vocabulary (the risk block's inference
    enum) must name its owner and review cadence: an unowned register is a
    model input nobody reviews. Malformed shapes raise, like every config.
    """
    macro = load_optional_config(CONFIG)
    if macro is None:
        return None
    sectors = macro.get("sectors")
    if sectors is not None:
        if not isinstance(sectors, dict) or not sectors or not all(
                isinstance(k, str) and k and isinstance(v, str) and v
                for k, v in sectors.items()):
            raise ValueError("%s: 'sectors' must map sector keys to labels" % CONFIG)
        for field in ("owner", "review_cadence"):
            if not str(macro.get(field) or "").strip():
                raise ValueError("%s: '%s' is required with 'sectors'" % (CONFIG, field))
    for entry in macro.get("register") or []:
        if not isinstance(entry, dict) or not str(entry.get("text") or "").strip():
            raise ValueError("%s: every 'register' entry needs a text" % CONFIG)
    return macro


def sector_vocabulary() -> dict:
    """{sector key: label} from the register, or {} without one."""
    macro = load()
    return dict((macro or {}).get("sectors") or {})


def macro_facts(facts):
    """config/macro_context.json register entries as citable facts, as-of
    stamped.

    The file is OPTIONAL and, unlike every other config, absence degrades
    silently -- the analysis works without macro context. A malformed file is
    still a loud failure. The `register` entries (dated, topic-tagged) are
    the only channel.
    """
    macro = load()
    if macro is None:
        return
    as_of = str(macro.get("as_of") or "undated").strip()
    for entry in macro.get("register") or []:
        topic = str(entry.get("topic") or "register").strip().replace("_", " ")
        sectors = entry.get("sectors") or []
        suffix = (" (sectors: %s)" % ", ".join(str(s) for s in sectors)) if sectors else ""
        facts.add(BACKGROUND,
                  "[register: %s, as of %s] %s%s"
                  % (topic, as_of, str(entry["text"]).strip(), suffix),
                  ["config/macro_context.json"],
                  None)
