# Export: Windows folder, .exe, Android

🌐 Русский: [Экспорт (RU)](ru/export.md)

The **"Export"** button on the project page opens the export window. Pick a
format, set the exe name if needed, and click "Export" — by default the build is
saved to the **Desktop**.

During the build you see two bars: the overall percentage and the current stage
(preparation → copying → engine → icon → build → finalization). Exporting again
to the same folder safely updates it, if the folder was created by the engine;
foreign folders are never overwritten.

## Windows folder

A self-contained folder: project + built-in engine + Play.bat + README. The
folder can be zipped and handed to anyone — the recipient doesn't need Python
installed.

## Windows .exe

- Set the **executable name** in Latin characters (for example, `StarCatcher`) —
  it becomes the name of the exe and of the window.
- The result is a single self-contained file with the project icon.
- `project.json` is placed next to the exe: the game can be tweaked without
  rebuilding.

## Android

1. Pick the **Android** format and read the built-in instructions.
2. Two build paths:
   - **Locally**: WSL2/Linux + buildozer (the engine prepares `buildozer.spec`);
   - **In the cloud**: the engine puts a ready GitHub Actions workflow into the
     folder — build the APK without installing anything.
3. Screen orientation is set in the project properties; the window size for
   Windows is chosen by the agent per task.

## After export

Test the build on a clean machine (or at a friend's). If something is wrong —
describe the problem to the AI agent right in the project and export again.
