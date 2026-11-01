# AI Agent: tasks, plan, progress

🌐 Русский: [ИИ-агент (RU)](ru/agent.md)

The "AI Agent" section is the agent's workspace. Here you give tasks, and the
agent shows what it is doing right now.

## How the agent works

1. **Studies the project**: the manifest, instructions, current plan, and files.
2. **Draws up a plan** of concrete tasks and shows it as a card in the chat.
3. **Executes step by step**: writes files, generates assets, configures the
   window, and adjusts the plan along the way.
4. **Checks itself**: after major milestones, the agent runs a structure check
   and a headless launch on its own and fixes whatever it finds.
5. **Reports back**: status, completion percentage, and the event feed update in
   real time — both in the agent section and in "Overview".

## Highlights

- **No step limit.** The agent doesn't stop at "step 60" — it works until there
  is a result. If the agent repeats the same action without progress, it will
  stop on its own and explain why.
- **History is saved.** Every task you give and every agent reply is stored in
  the project (`.reasonable/chat.json`). Close the editor, come back a week
  later — the whole conversation is there; the "Clear" button removes it.
- **Version snapshots.** Before starting work, the agent saves a snapshot of the
  project: if you don't like the result, roll everything back with one click
  ("Version history").

## Interface levels and agent skills

The project knows its interface levels, and the agent receives only the matching
skills: a tkinter utility gets plain-window skills, a game gets scene and
graphics skills. That way the agent won't drag a game renderer into a utility or
office forms into a game.

## External agent (Claude Code, Cursor, Codex CLI, Cline…)

If the project was created in the "External agent" mode:

1. Click **"Open project folder"** and open it in your agent.
2. Copy the ready-made prompt from the panel (the "Copy prompt" button) and paste
   it to the agent. Add your own task if you like.
3. Watch the progress in Reasonable Engine: the external agent updates the plan
   and percentage through the project CLI (`re.bat`), and the editor picks it up
   automatically.
4. The project already contains instructions: `AGENT_GUIDE.md`, skills in
   `skills/`, and pointers for specific agents (`AGENTS.md`, `CLAUDE.md`).

Don't run the built-in and the external agent over the same files at the same time.

## Launch console

The "Run" button shows the program's output in the console. The "Fix with AI"
button (on the agent page) sends the error text to the agent — it will find the
cause and fix the files.

## Common prompts

- "Continue working on the plan" — the agent will find the unfinished task itself.
- "Improve the visuals: background, sprites, animations" — the agent will
  generate assets and weave them into the project.
- "Check the project, fix the errors, and get it to launch" — a full cleanup.
