"""The AI Analysis's one failure type, shared by the pipeline and every
provider.

Its own module so the provider modules (ollama.py, core42.py) can raise it
without importing the package __init__, which imports them.
"""

from __future__ import annotations


class BriefUnavailable(Exception):
    """The model service could not produce a block. The reason is for the
    server log and the sidebar -- the analysis view shows the block as not
    generated rather than carrying an error about infrastructure."""
