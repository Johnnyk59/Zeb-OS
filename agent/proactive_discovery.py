"""Proactively activate bundled skills the agent needs, without being asked.

ZebOS ships far more skills than any one install has enabled by default
(``skills/`` + ``optional-skills/``, most disabled out of the box). Today,
if the model needs a capability that lives in a disabled bundled skill, its
only options are to ask the user to run ``zeb skills`` or to fumble through
the task without it. This module closes that gap for the safe case: when
``tool_search`` comes up empty against the currently-loaded toolset, search
the disabled-but-already-bundled skill catalog for a match and enable it on
the spot.

Security boundary, deliberately narrow: this only ever flips the
``enabled`` bit on a skill that is *already on disk*, shipped and reviewed
as part of this repo/install (``skills/``, ``optional-skills/``). It never
fetches, downloads, or installs anything from a network source — that stays
an explicit, user-initiated action through ``tools/skills_hub.py``'s
GitHub/registry sources and the ``/skills`` command. Autonomy here is safe
specifically because there is no new code being introduced, only a config
flag on code that was already vetted and shipped.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Tuned empirically against tool_search's own BM25 scale (see
# tools/tool_search.py::search_catalog) — low enough to catch a decent
# single-keyword match ("docker" -> a docker-compose skill), high enough
# that unrelated skills sharing one common word don't get auto-enabled.
_MATCH_SCORE_THRESHOLD = 1.0


def _disabled_bundled_skills(config: dict[str, Any]) -> list[dict[str, Any]]:
    from zeb_cli.skills_config import _list_all_skills, get_disabled_skills

    disabled_names = get_disabled_skills(config)
    if not disabled_names:
        return []
    return [s for s in _list_all_skills() if s.get("name") in disabled_names]


def find_and_enable_matching_skill(
    query: str, config: Optional[dict[str, Any]] = None
) -> Optional[dict[str, Any]]:
    """Search disabled bundled skills for one matching ``query``; enable and return it.

    Returns ``None`` (and touches nothing) when there's no disabled skill,
    no confident match, or the config write fails — this is a best-effort
    convenience, never something a caller should depend on succeeding.
    """
    from tools.tool_search import _bm25_score, _tokenize

    if config is None:
        from zeb_cli.config import load_config

        config = load_config()

    candidates = _disabled_bundled_skills(config)
    if not candidates:
        return None

    query_tokens = _tokenize(query)
    if not query_tokens:
        return None

    docs = [
        _tokenize(f"{s.get('name', '')} {s.get('description', '')} {s.get('category', '')}")
        for s in candidates
    ]
    doc_lengths = [len(d) for d in docs]
    avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)
    doc_freq: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            doc_freq[t] = doc_freq.get(t, 0) + 1
    n_docs = len(docs)

    best_score = 0.0
    best_idx = -1
    for i, d in enumerate(docs):
        score = _bm25_score(query_tokens, d, doc_lengths, avg_dl, doc_freq, n_docs)
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx < 0 or best_score < _MATCH_SCORE_THRESHOLD:
        return None

    matched = candidates[best_idx]
    try:
        from zeb_cli.skills_config import get_disabled_skills, save_disabled_skills

        disabled = get_disabled_skills(config)
        disabled.discard(matched["name"])
        save_disabled_skills(config, disabled)
    except Exception:
        logger.warning(
            "Failed to auto-enable matched skill %r", matched.get("name"), exc_info=True
        )
        return None

    logger.info(
        "Proactively enabled bundled skill %r for query %r (score=%.2f)",
        matched["name"], query, best_score,
    )
    return matched
