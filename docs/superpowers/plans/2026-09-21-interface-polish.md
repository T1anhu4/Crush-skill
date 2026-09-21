# Interface polish implementation plan

**Goal:** Improve everyday readability, responsive layout and motion across the existing CLI, web preview and host-rendered Skill, without changing conversation engines.

**Architecture:** Preserve Python and React/CSS. CLI rendering gets a cell-aware presentation layer; web keeps its warm-paper/sage identity and uses bounded transform/opacity motion. Skill retains JSON tool output and gains concise host presentation guidance. Work in the existing development checkout to preserve the already-tested security fixes.

**Design decisions:** Prefer a targeted system polish over a color-only refresh or framework rewrite. No fake thinking/token animation, typing delays, forced scroll hijacking, remote fonts or new UI dependencies. No private-data tests or paid model calls. User has delegated design decisions and requested implementation through verified publication.

## CLI

- [x] Add tests in `tests/test_cli_layout.py` for 24/40/80-column panels, CJK/combining characters, untrusted ANSI, plain output and reduced motion.
- [x] Implement `crush_cli/presentation.py`; adapt banner, panels, selector and reply display in `crush_cli/app.py`, preserve all security edits and `crush v3` JSON output.
- [x] Keep the single-line activity pulse. Avoid full-screen erasure during selection; use static choices where terminal capabilities or reduced motion require it.
- [x] Run targeted tests and a real disposable PTY check; spec review then independent quality review.

## Web

- [x] Add a focused `web/src/polish.css`: legible typography, larger targets, aligned bounded conversation/composer, small-height and mobile safe-area layouts, dark contrast, focus states.
- [x] Add a tested motion policy helper: historical messages do not replay entry animations, new messages animate once; scrolling respects reduced motion. Use transform/opacity, 140–220 ms for controls.
- [x] Preserve drafts edited while sending; keep stale session responses from replacing the active view. Add deterministic state helper tests before implementation.
- [x] Add accessible navigation/mode semantics and modal labeling, preserve existing functionality.
- [x] Verify real local preview with synthetic fixtures at desktop/mobile/narrow heights, dark mode and keyboard; verify reduced motion with policy tests and CSS inspection. Do not start the user's private server.

## Skill and publication

- [x] Specify compact host-rendered chat/status/review output in `Crush.skill/SKILL.md`; no fabricated animation or raw JSON in ordinary chat, no altered machine contract.
- [x] Add a brief README increment without removing images or opening/closing copy.
- [x] Run full pytest, frontend tests/build, smoke tests and packaging. Review diff and private-file exclusions.
- [x] Commit author and committer `T1anhu4`, linked noreply email; fast-forward push development and main only after remote refs are verified and review passes. Never force push.
