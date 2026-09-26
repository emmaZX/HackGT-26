"""
Multi-agent internet discovery for Recall Me Maybe.

Five agents work together so we back product pages with real niche complaints —
not just FDA pages:

1. QueryGenerator  — writes hyper-specific search strings from product / FDA context
2. WebSearch       — runs those queries via Exa (or Brave / Gemini fallback)
3. PageFetch       — pulls readable page text from hit URLs
4. Triage          — semantic signal-vs-noise filter (keeps batch illness, drops taste gripes)
5. GeoCorrelate    — pulls coarse location clues from complaint text

Orchestrated by `run_agent_pipeline` in pipeline.py.
"""

from .pipeline import run_agent_pipeline

__all__ = ["run_agent_pipeline"]
