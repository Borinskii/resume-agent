# CV-Job Match Agent

Evidence-first dashboard that scores a CV against real ATS vacancies, surfaces
honest skill gaps, and (optionally) rewrites individual resume bullets using a
**local Ollama model** or hosted Fireworks — without inventing experience.

- Live vacancies from approved Greenhouse and Lever boards.
- Bring-your-own LLM: `LLM_PROVIDER=auto` prefers local Ollama, falls back to
  Fireworks if a key is set, gracefully degrades to deterministic-only output
  otherwise.
- CV stored encrypted at rest (Fernet), per-session isolation, hard delete.
- Manual-only apply queue. Auto-apply, LinkedIn scraping, and stealth automation
  are disabled by policy.
- 28 unit tests + 39 end-to-end "click → verify response → verify DB" checks.

Run it: see [Quickstart](#quickstart).