# Frequently Asked Questions (FAQ)

🌐 Русский: [Частые вопросы (RU)](ru/faq.md)

## Installation and updates

**Does the installer ask to install anything else?**
No. The editor ships with a portable Python and all dependencies.

**Will my projects survive an update?**
Yes, the `Projects` folder is not touched by the installer. Still, keep backups
of important projects — it's copying a folder.

**Where are projects stored?**
Inside the installation: `...\Reasonable Engine\Projects\<project name>`. Inside:
`project.json` (the manifest), `main.py`, assets, the progress plan, and the chat
history.

## Splash screen

**Can the splash screen before games be removed?**
No. The Reasonable Engine splash screen is a signature part of the engine, like
in Unity or Godot, and cannot be disabled. It plays for ~2 seconds and closes by
itself.

**Is the splash screen stuck?**
It lasts a couple of seconds and closes by itself. If the window hasn't closed —
just wait a little longer; force-closing does not harm the project.

## AI agent

**Is the internet required?**
For cloud models (Anthropic, OpenAI, OpenRouter, DeepSeek…) — yes. Local models
(Ollama, LM Studio) and procedural asset generation work offline.

**Where is my API key?**
Only on your computer, in the Reasonable Engine settings. We never receive or
store it.

**The agent stopped, but the task isn't finished?**
Write to it: "Continue". The agent works without a step limit; if it stopped, it
explained the reason in the chat (for example, it kept repeating the same
action). Describe exactly what didn't work.

**The agent messed everything up — how do I roll back?**
"Version history" on the project page — snapshots taken before the agent's work.
Restore the one you need with a single click.

**Why doesn't the agent let me set the window size?**
The window size is chosen by the agent per task — these settings are absent from
the editor UI on purpose.

## Export

**Where is the build saved?**
To the Desktop by default. The path can be changed with the "Change…" button.

**Does a second "Reasonable Engine" window open from the exe?**
It shouldn't. Make sure you export with release RE-1.01 or newer — the extra
window is excluded there.

**Who can I hand my built games to?**
Anyone — they are your projects. The engine/installer itself may only be shared
as a link to the official download page (see LICENSE.txt).

## Versions

**What does RE-1.01 mean?**
Generation 1, release 01. Releases go in order (RE-1.02, RE-1.03…); versions
like "RE-2.00" don't exist — a new generation starts with RE-2.01. Details: the
"Versioning System" section in the [README](../README.md#-versioning-system).

**Where can I see my version?**
The "About" window in the editor or `python -m reasonable --version` in the
installation folder.
