# Contributing to Reasonable Engine

🌐 English · [Русский](CONTRIBUTING.ru.md)

Reasonable Engine is a closed project: the source code is not published, so
regular pull requests to the code are not accepted. But users largely drive the
engine's development — bug reports, ideas, and usage scenarios.

## How to help the project

### 1. Report a bug
1. Open [Issues](../../issues) and check whether the problem has already been
   reported (including closed issues).
2. If not — create a new issue using the **Bug report** template.
3. Fill in the fields: what you did, what you expected, what happened, and the
   engine version (the "About" window or `python -m reasonable --version`).
4. Attach the details: the error text from the console, a screenshot, and
   reproduction steps. The more precise the steps, the faster the fix.

### 2. Suggest an improvement
1. Create an issue using the **Feature request** template.
2. Describe the task you are solving right now and what you are missing. A
   concrete scenario is worth more than an abstract "add a button".
3. We tag suggestions: `accepted` (taken into work), `planned`
   (scheduled for a release), `question` (needs clarification), `wontfix`.

### 3. Join the discussions
- Usage questions go to [Discussions](../../discussions) or via the Questions link.
- Answering other users in Discussions is also a contribution: the experience of
  project owners is invaluable.

## Rules for a good report

- **One issue — one problem.** Don't mix several bugs in one.
- State the **release version** (RE-2.01, RE-2.02…), the OS, and, if the bug is
  in a generated program, the project type and interface level.
- Attach logs: the editor writes them next to its settings, and project launch
  errors are visible in the project console ("Overview" section → launch console).
- Don't attach API keys or personal data — everything you post is visible to everyone.

## What is NOT accepted

- Attempts to obtain or discuss the engine's source code (it is closed; see LICENSE.txt).
- Bypassing the splash screen and branding elements — they are part of the engine.
- Requests for "cracks", piracy, or license circumvention.

## How the release cycle works

- Releases are numbered RE-2.01, RE-2.02, …; the global generation is Reasonable
  Engine 1, 2, etc. Details: the "Versioning System" section in [README.md](README.md).
- Fixes and accepted suggestions land in the next release; [CHANGELOG.md](CHANGELOG.md)
  notes exactly what was included.
- Significant suggestions may land in a pre-release — keep an eye on Discussions.

Thank you for making Reasonable Engine better!
