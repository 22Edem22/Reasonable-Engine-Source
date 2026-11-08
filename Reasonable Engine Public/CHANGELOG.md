# Reasonable Engine Changelog

🌐 English · [Русский](CHANGELOG.ru.md)

Version format: **RE-<generation>.<release>** — for example RE-2.01, RE-2.02.
The generation changes only on a major engine overhaul (Reasonable Engine 1 → 2).
The first release of a generation is always .01; versions like "RE-2.00" do not exist.

## [RE-2.02] — 2026-11-06

### Added
- **Older context is compressed instead of discarded**: when history no longer
  fits, the agent summarizes older steps into a short note and continues from it.
  The context budget is measured in tokens and calibrated from the chosen model's
  real usage; compression can be disabled in the agent settings.
- **Prompt caching is used and visible in the chat**: the stable system prompt and
  tools are not rebuilt unnecessarily, Anthropic gets explicit cache blocks, and
  OpenCode/DeepSeek/OpenAI cache the stable prefix. The usage tooltip shows how
  many sent tokens were read from cache.

### Fixed
- **The agent no longer loses the task in a long run**: the original request stays
  in context on every step, and history is trimmed in complete call/result groups
  with a size budget. Previously, after about 18 steps the model kept working
  without remembering what was asked and repeated the same calls forever.
- **The agent no longer stops with a false “no progress” error**: reading
  different parts of the same file, checks and runs now count as progress, and
  when the project already passes verification the agent is asked to finish
  instead of being failed. The hard `stall_steps` threshold is off by default;
  repeated identical actions are still detected separately.
- **Questions about the project work again**: when a task needs no edits, the agent
  answers and finishes after an independent check of the answer instead of forcing
  itself to edit files, run checks and repeat them in a loop.
- **Truncated replies and broken tool arguments are not executed**: if the provider
  cuts the reply at the output limit, the agent asks for a smaller step and stops
  after the second cut. The default output limit is now 16k tokens, and a 400 error
  no longer disables tool calling entirely.
- **Specialists no longer take over the global plan**: in parallel mode a role can
  no longer call tools owned by the lead (plan, progress, validation, finish).
  Verification-only tasks and tasks that depend on another task's files are merged
  instead of running at the same time.
- **The token/time counter no longer freezes in parallel mode**: specialist usage
  and messages now reach the chat. Previously a long parallel run stayed silent
  while the counter showed only a few service requests from the master.
- **The agent no longer gets stuck repeating its own “thoughts”**: if the model
  returns the same fragment instead of work, the agent discards it, retries at a
  lower temperature and stops after the second attempt with a clear message. The
  chat and history are no longer flooded with repetitions.

### Changed
- **The agent is more focused by default**: the temperature is lowered from 0.65
  to 0.3 for more stable tool calls; a saved 0.65 setting is migrated
  automatically.

## [RE-2.01] — 2026-11-04

The first release of **Reasonable Engine 2**. The main change: the agent draws
assets itself instead of substituting one template for unrelated objects.

### Added
- **The `draw_sprite` tool**: the agent describes the image itself — as a pixel
  grid with a palette or as a list of primitives (ellipses, polygons, lines,
  arcs, rounded rectangles, gradients). The engine only renders that description
  with supersampling, trims empty margins and saves a PNG.
- **Result inspection**: after drawing, the agent calls `inspect_image` to see
  size, transparency, bounds and dominant colors, and can immediately redraw an
  object that does not read well.
- **Project context in external-model prompts**: the request now includes the
  project's purpose, the chosen style and the exact target size, so the model
  draws a specific game asset rather than a generic picture.
- **Lifetime token and generation-time counter**: the built-in agent chat shows
  cumulative tokens and total generation time for the whole project. The totals
  are stored in the project and survive restarts, new agent runs and chat
  clearing.
- **Continue after a server error**: if the agent stops because the AI server
  failed, the chat offers a “Continue” button that sends the same word to the
  model. Automatic continuation can also be allowed for selected error types;
  the list is managed in the agent settings.
- **Multiple AI chats**: every project can now keep any number of separate
  conversations with the agent. The chat switcher sits in the panel header,
  next to the create and delete buttons; each conversation has its own history.
- **The “Improve” button**: creates a new chat and runs a hidden read-only
  review of the whole project. The agent studies the code, returns a list of
  concrete improvements and asks what to implement, while the service prompt
  stays invisible in the chat.
- **Visual scene editor**: projects now have a “Scene” workspace — a grid canvas,
  an object list and an inspector. Rectangles, circles, text and images from
  assets are added from the toolbar, dragged with the mouse, resized by handles,
  zoomed with the wheel and snapped to the grid.
- **Multiple scenes, Unity/Godot style**: scene tabs, creating an empty scene, a
  level, a menu or an app screen, duplicating, renaming, deleting, and scene
  size/background/grid settings. A new game immediately gets a ready
  `scenes/main.json` with a backdrop and spawn markers for the player, stars and
  slimes — edits in the editor really change the game instead of staying a
  picture. Apps no longer start with an empty scene: they get a ready screen
  layout with a sidebar, task cards and an assistant panel.
- **Drag-to-create objects**: pick a rectangle, circle, text or panel and drag
  out the shape like in Unity/Godot. Right-click opens creation, duplicate,
  layer order and reset view; the toolbar gained zoom in/out buttons and a panel
  tool.
- **Scenes are available to the game**: the same objects can be loaded in a
  running project with one `add_scene_objects` call — coordinates no longer have
  to be copied into code by hand.
- **Real interface icons**: emoji are replaced with neat vector icons drawn in the
  editor's own style.
- **Interactive first-launch tutorial**: six hands-on steps ask you to choose a
  project type, write a task and see the plan, visit the workspaces in order,
  run the project, undo changes and pick an export format. The next step unlocks
  only after the current action, so the tour cannot be skipped ahead. It can be
  closed and replayed later from Help → Quick start (F1), the settings dialog,
  or the Tutorial button on the start screen.
- **Complete examples**: the game gained a title menu, a how-to-play screen,
  enemy waves, combos, a dash, power-ups, procedural sound and a saved high
  score; the app became a genuine planner with priorities, tags, search,
  sorting, weekly statistics, a day streak and undo-delete.
- **OpenCode Go provider**: settings now include a ready preset with the correct
  Base URL, model list and automatic `User-Agent` and `x-opencode-session`
  headers. A Console key (Go / Go Plus / Go Teams) connects without the
  `MissingSessionID` error; the session is stable per chat, so prompt caching
  works.
- **Independent task completion check**: before the final answer a separate pass
  compares the user's exact request with the changed files, validation, run
  result and scenes. If anything is missing, the agent receives a concrete list
  and keeps working. The check can be disabled in the agent settings.
- **Parallel development with multiple agents**: the master agent no longer
  writes code itself — it studies the project, splits the task into independent
  items and assigns them to code and asset specialists. They work at the same
  time in disjoint files, then the master verifies the launch, runs an
  independent audit, dispatches focused repairs and only then answers the user.
  Any orchestration failure automatically falls back to the regular sequential
  mode, so quality and reliability are preserved. The specialist count and
  repair rounds are configurable.
- **The starter example no longer misleads the AI agent**: the system prompt now
  states explicitly that the ready-made game/app is a base, not the brief. The
  agent sees scenes and markers, must follow the user's task, and cannot call the
  work done just because the example already looks complete.
- **The agent thinks and answers in the UI language**: with Russian selected in
  settings it plans, comments and replies in Russian even for an English task —
  and vice versa. Only tool names, code and identifiers stay English.
- **Tool calls are collapsed by default**: the chat shows one compact group
  header; details expand on click instead of filling the screen during a run.
- **External-agent live progress no longer stacks stages**: every refresh fully
  removes the previous plan rows, so task statuses are not painted on top of
  each other.
- **The `pkg_resources is deprecated` warning is gone**: the engine, editor and
  player filter only that exact pygame warning without hiding other errors.
- **The Reasonable Engine splash can no longer be disabled from a project**:
  `splash=False` is ignored, the developer token is gone, and the editor, player,
  CLI and `run.bat` play the intro before project code. Even if the AI rewrites
  `main.py`, the branding stays. The only exception is headless no-window runs
  used by tests and agent validation.
- **The splash shows the correct version**: the hard-coded “Reasonable Engine 1”
  is replaced with the current engine generation — currently **Reasonable
  Engine 2**.

### Fixed
- **AI answers no longer disappear from the chat history**: after reopening a
  project both the user's messages and the agent's answers, errors and service
  notices are still there. The task is stored the moment it is sent, and every
  answer as it appears, so even an interrupted run keeps the conversation.
- **Long model names no longer break the assistant panel**: in engine-built apps
  the model id is shortened with an ellipsis, and the settings controls stay in
  place.
- **The start screen no longer clips its heading and description**: both lines of
  “Make a game from a single idea” and the full intro fit even in the minimum
  window size; in a narrow window the projects path is shortened instead of
  running off the edge.
- **The shield and damage ring stay on the player**: after F11 or a window
  resize the camera keeps the scene centred, and effects plus floating score
  popups are drawn exactly around the character.
- **Unlimited auto-continue**: after a run of errors the agent keeps retrying
  until the server recovers. The interval grows up to 8 seconds to avoid
  hammering the provider, but the old stop after two errors is gone.
- **The agent no longer gives up with “Work is not finished”**: if the model
  stops without changing anything, the agent runs validation and a smoke run
  itself, feeds the concrete errors back and keeps working. The old three-nudge
  limit is gone; repeated tool calls switch it to a recovery plan instead of
  ending the run with an error.
- **The editor no longer freezes on large projects**: the file list and event
  feed refresh much more cheaply, the progress journal is read from its tail
  only, and service folders (`_engine`, `build`, `.venv`) are no longer walked in
  full. On a project with thousands of files the refresh became about 30 times
  faster.
- **Stopping a project no longer freezes the window**: terminating the process
  tree no longer blocks the interface for several seconds.
- **Engine apps hold 60 FPS again**: text, button shadows and backdrop glows are
  cached instead of being redrawn every frame. On a typical screen a frame became
  about seven times lighter.

### Changed
- **`generate_sprite` no longer substitutes templates**: without a configured
  external model the tool says so honestly and points to `draw_sprite`. There is
  no silent "default character" fallback.
- **One consistent set**: the `draw_sprite` description gives the agent rules —
  one palette per project, one outline color and one cell/detail size. These are
  instructions for the model, not ready-made images.
- **A wider built-in agent chat**: the editor opens in a larger window, with a
  narrower sidebar and tighter margins, so long messages and plans are easier
  to read.
- **Compact, collapsible tool calls in the chat**: every call is one line with a
  readable name and the file/command it targets, and the result expands on
  click. Consecutive calls share one header that can be collapsed as a whole.
- **Enter sends, Ctrl+Enter inserts a line**: the familiar chat flow without an
  extra click; explicit newlines stay on the modifier shortcut.
- **Stopping a project really stops the game**: the “Stop” button now terminates
  the whole child-process tree instead of only the launcher, so no game keeps
  running in the background.
- **The procedural sprite provider is gone** from image settings. Only the
  external image model remains; without it the agent draws by itself.
- The sample game's starter assets (hero, star, slime) are now drawn from
  separate descriptions instead of one universal silhouette.
- **A new look for the editor**: a dense grid, a neutral palette, compact panels
  with hairline borders, consistent typography and flat controls — the window now
  reads as a working tool rather than a landing page.

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

[RE-2.02]: ../../releases/tag/RE-2.02
[RE-2.01]: ../../releases/tag/RE-2.01
[RE-1.01]: ../../releases/tag/RE-1.01
