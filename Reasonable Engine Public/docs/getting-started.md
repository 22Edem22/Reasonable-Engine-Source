# Getting Started

🌐 Русский: [Начало работы (RU)](ru/getting-started.md)

## Installation

1. Download `ReasonableEngine-Setup-RE-1.01.exe` from the
   [Releases](../../releases/latest) page.
2. Run the installer. It will install the editor, a portable Python, and the
   runtime itself — there is nothing extra to install.
3. Launch **Reasonable Engine** from the Start menu or the desktop shortcut.

Your projects live in the `Projects` folder inside the installation. They are
preserved when the engine is updated, but keep backups of important projects —
just copy the project folder to a safe place.

## Your first project

1. On the welcome screen, click **"Create project"**.
2. Describe the idea in your own words: for example, "A space cat collects stars
   and runs away from slugs".
3. Choose who works on the project:
   - **Built-in AI agent** — writes code right in the editor (requires a provider
     key or a local model);
   - **External agent** — you open the project folder in Claude Code, Cursor,
     Codex CLI, or another tool, and the editor shows the progress.
4. Choose the **interface levels** (several are allowed):
   - **Simple (tkinter)** — plain Windows windows: utilities, forms, lists;
   - **Standard (engine)** — ready-made widgets: panels, lists, scrolling;
   - **Advanced (scenes)** — custom graphics, camera, particles: for games.
5. Set the **project name in Latin characters** — it will become the name of the
   folder and files (for example, `Star Catcher`).
6. Click **"Create"** — the project will be generated in a few seconds:
   template, icon, agent instructions, and a progress plan.

## Your first launch

- On the project page, click **"Run"** (or `run.bat` in the project folder).
- The Reasonable Engine splash screen will play before the program (~2 seconds) —
  it is part of the engine.
- The game/app opens in a separate window. Launch errors appear in the console
  on the project page.

## Your first agent task

1. Open the **"AI Agent"** section.
2. Write the task in plain words: "Assemble a working vertical slice: player,
   stars, score, and game over" — or pick one of the ready-made hints.
3. The agent will study the project, draw up a plan, and start working: the plan,
   percentage, and file changes are visible in real time.
4. After the agent finishes, click **"Run"** and look at the result. Something is
   off — describe it to the agent: it will fix it.

## Setting up an AI provider

1. **File → Settings → Provider**.
2. Choose the provider and model, paste the API key (it is stored only on your
   computer).
3. Without a key and without the internet, local models (Ollama, LM Studio) and
   procedural asset generation are available.

## What's next

- [AI Agent: tasks, plan, progress, external agent](agent.md)
- [Export: Windows folder, .exe, Android](export.md)
- [Frequently asked questions](faq.md)
