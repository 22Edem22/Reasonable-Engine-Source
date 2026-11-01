# Reasonable Engine Changelog

🌐 English · [Русский](CHANGELOG.ru.md)

Version format: **RE-<generation>.<release>** — for example RE-1.01, RE-1.02.
The generation changes only on a major engine overhaul (Reasonable Engine 1 → 2).
The first release of a generation is always .01; versions like "RE-2.00" do not exist.

## [RE-1.01] — 2026-11-01

The first public release of Reasonable Engine 1.

### Added
- **Interface levels** when creating a project: Simple (tkinter), Standard
  (engine widgets), Advanced (scenes and graphics). Multi-select; the project
  receives only the matching template, assets, and agent skills — nothing extra.
- **Chat history** with the AI agent is saved per project and restored on reopen
  (`.reasonable/chat.json`).
- **Unlimited agent operation**: the 60-step limit has been removed; the agent
  works until there is a result. Anti-loop protection added: six identical
  actions in a row stop the agent with a clear message.
- **Live progress without zeros**: the completion percentage is automatically
  derived from the completed plan tasks when the agent doesn't report it itself;
  a single percentage across all editor panels.
- **Export with detailed progress**: two bars — the overall build percentage and
  the current stage (preparation → copying → engine → icon → exe build →
  finalization). Export is saved to the **Desktop** by default.
- **The .exe name is set at export time** (Latin characters) with live validation.
- **English project name** at creation (used for the folder and files).
- **Project conversion** (Windows ↔ Android) with interface-level selection.
- The **Export** button has been moved to the first row of project buttons.
- The project overview has become a **read-only panel**: the plan and percentage
  are shown, but cannot be edited from "Overview" (that is the agent's job).

### Fixed
- Crash of generated programs: `pygame.event.Event has no attribute 'pos'`
  — mouse wheel scrolling in lists no longer causes a crash.
- Crash of any button without an explicit height in engine-widget applications
  (the one that looked like "the program doesn't work, tasks aren't added").
- One bad event in a project no longer kills the entire application: the error
  is logged, and the program keeps running.
- Export to .exe no longer opens a second broken "Reasonable Engine" window:
  the editor and Qt are excluded from the build, and the project manifest is
  placed next to the exe.
- Export hanging at the "Copying project and engine…" stage — every stage now
  reports its progress.
- The window and its size are no longer configured anywhere in the UI — the
  AI agent chooses them per task; exported exes correctly read the window settings.

### Changed
- **The Reasonable Engine splash screen** has been redesigned in a minimalist
  style (Unity/Godot): dark background, logo, a quiet caption, ~1.8 seconds. The
  splash is now part of the engine: users cannot disable or skip it.
- The external AI agent panel has been cut down to three steps: open the folder →
  paste the prompt → watch the progress. The "Progress commands" and "Created
  instructions" cards have been removed.
- Agent instructions and skills have been rewritten: a project receives only the
  skills it needs (based on its type and interface levels).

[RE-1.01]: ../../releases/tag/RE-1.01
