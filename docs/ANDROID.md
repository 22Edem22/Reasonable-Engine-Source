# Android: сборка APK из Reasonable Engine

Reasonable Engine экспортирует **готовый проект для buildozer / python-for-android**. Это не мгновенный APK: сборка выполняется на Linux или в WSL2, потому что buildozer использует Android SDK, NDK и инструменты, которых нет в Windows-сборке Python.

Экспорт честно показывает это в интерфейсе и создаёт ZIP со всем необходимым:

```text
Мой проект-android.zip
└─ Мой-проект-android/
   ├─ main.py
   ├─ buildozer.spec
   ├─ assets/
   │  ├─ icon.png
   │  ├─ presplash.png
   │  ├─ sprites/
   │  └─ backgrounds/
   ├─ _engine/reasonable/
   ├─ progress/
   ├─ README_ANDROID.md
   └─ .github/workflows/android.yml
```

---

## Из Windows-проекта в Android

Если игра или приложение уже созданы как Windows-проект, не меняйте их на месте: **Проект → Конвертировать в новый проект…** (или кнопка **«Конвертировать…»** в боковой панели) создаёт отдельную Android-копию.

Что происходит:

- копируются код, `assets/`, `README` и заметки, но **не** `_engine/`, `dist/`, `build/`, кеши, `.git`, `.env`, `data.json` и `ai_config.json`;
- в `project.json` записывается `platform: android`, выбранная ориентация и Android-пакет;
- `_engine/` встраивается заново из установленного Reasonable Engine;
- пересобирается пакет агента (`AGENT_GUIDE.md`, `skills/` и указатели);
- появляется `CONVERSION.md` с источником и списком изменений;
- прогресс сохраняется либо сбрасывается — по вашему выбору.

В диалоге можно сразу поменять имя, ориентацию, режим агента, режим окна, resizable и базовое разрешение. Портретная ориентация без явного размера меняет стороны местами: 1280×720 → 720×1280.

Исходный Windows-проект остаётся нетронутым. Дальше работайте в новой папке: `re.bat validate`, `re.bat run --headless`, затем `re.bat export android` и buildozer.

То же из CLI:

```bat
re.bat convert --to android --name "Кот на телефоне" --orientation portrait
```

### Что конвертация не делает

- **Не адаптирует вёрстку и управление автоматически.** Код копируется как есть. После конвертации попросите агента проверить касания, размеры элементов, safe margins, узкие экраны и производительность.
- **Не заменяет шаблон игры на приложение** и наоборот.
- **Не импортирует проекты других движков.**
- **Не собирает APK.** Android-пакет по-прежнему собирается buildozer на Linux/WSL2.

### Как параметры влияют на Android

| Поле | Действие |
|---|---|
| `platform` | Помечает проект как Android и задаёт контекст агенту и редактору |
| `orientation` / `android.orientation` | Ориентация в `buildozer.spec`; при конфликте приоритет у `android.orientation` |
| `android.package` | Имя пакета; при смене имени стандартный пакет пересчитывается |
| `window.width` / `window.height` | Базовая логическая поверхность; runtime масштабирует её под экран |
| `window.mode` | На Android приложение всегда разворачивается на весь экран |
| `window.resizable` | Не влияет на Android, сохраняется для Windows-копии |

---

## Требования

| Компонент | Версия / примечание |
|---|---|
| Windows | 10/11 с поддержкой WSL2 |
| WSL2 | Ubuntu 22.04 или новее |
| Python | 3.10–3.12 внутри Linux (3.11 рекомендуется) |
| JDK | OpenJDK 17 |
| buildozer | последняя версия |
| Cython | устанавливается вместе с buildozer |
| Android SDK/NDK | скачиваются buildozer автоматически при первой сборке |
| Свободное место | 10–20 ГБ на первую сборку |

Для сборки не нужен Android Studio. Для установки APK на телефон — `adb` или передача файла вручную.

---

## Быстрый старт в WSL2

### 1. Установите WSL2

В PowerShell от администратора:

```powershell
wsl --install
```

Перезагрузите компьютер, задайте логин и пароль Ubuntu.

Проверка:

```powershell
wsl -l -v
```

### 2. Установите зависимости

В терминале Ubuntu:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
  libtinfo6 cmake libffi-dev libssl-dev
```

Проверьте Java:

```bash
java -version
```

Должна быть строка `openjdk version "17..."`.

### 3. Установите buildozer

Рекомендуется отдельное окружение или `pipx`:

```bash
python3 -m pip install --user --upgrade buildozer cython
export PATH="$HOME/.local/bin:$PATH"
```

Проверка:

```bash
buildozer --version
```

Добавьте `export PATH="$HOME/.local/bin:$PATH"` в `~/.bashrc`, чтобы команда была доступна в новых терминалах.

### 4. Распакуйте ZIP

Экспорт из редактора создаёт архив. Скопируйте его в Linux-файловую систему, а не оставляйте в `/mnt/c/...` — сборка там заметно медленнее.

```bash
mkdir -p ~/android
cd ~/android
unzip /mnt/c/Users/<вы>/Downloads/Мой-проект-android.zip
cd Мой-проект-android
```

### 5. Соберите debug APK

```bash
buildozer -v android debug
```

Первый запуск:

- скачивает Android SDK, NDK и python-for-android;
- занимает **15–40 минут** и несколько гигабайт;
- может потребовать принять лицензии — в `buildozer.spec` уже стоит `android.accept_sdk_license = True`.

Готовый файл:

```text
bin/<package>-<version>-arm64-v8a_armeabi-v7a-debug.apk
```

### 6. Установите на устройство

По USB с включённой отладкой:

```bash
adb devices
adb install -r bin/*.apk
```

Или скопируйте APK на телефон и откройте файл. Для установки может потребоваться разрешение «Установка из неизвестных источников».

---

## Что внутри `buildozer.spec`

Ключевые параметры:

```ini
title = Мой проект
package.name = moi_proekt
package.domain = org.reasonable

source.dir = .
source.include_exts = py,png,jpg,jpeg,webp,ogg,wav,mp3,ttf,otf,json,txt,md,csv
source.exclude_dirs = dist,build,.git,__pycache__,.github,.reasonable,tests

version = 1.0.0
requirements = python3,pygame
orientation = landscape
fullscreen = 1
android.wakelock = True
android.archs = arm64-v8a, armeabi-v7a
android.api = 34
android.minapi = 24
android.ndk_api = 24
android.permissions = VIBRATE
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #080C14
```

### Изменить имя пакета

Имя пакета задаётся в `project.json`:

```json
"android": {
  "package": "com.example.mygame",
  "version": "1.0.0",
  "orientation": "landscape"
}
```

или через **Настройки проекта** в редакторе. После изменения экспортируйте ZIP заново. Для Google Play идентификатор пакета должен быть уникальным и постоянным.

### Ориентация

- `landscape` — альбомная, по умолчанию для игр.
- `portrait` — портретная, для приложений и вертикальных игр.

Ориентация берётся из `android.orientation`, затем из `orientation` проекта. Меняется в настройках проекта или при конвертации. После изменения экспортируйте ZIP заново.

### Архитектуры

По умолчанию собираются `arm64-v8a` и `armeabi-v7a`. Для Google Play достаточно 64-битной:

```ini
android.archs = arm64-v8a
```

Это ускоряет сборку и уменьшает APK. Старые 32-битные устройства не смогут установить приложение.

### Версия Android

- `android.api = 34` — target API (Android 14).
- `android.minapi = 24` — минимальная версия (Android 7.0).
- `android.ndk_api = 24` — API для NDK.

Требования Google Play к target API меняются каждый год. Если Play требует более новую версию, увеличьте `android.api` и пересоберите.

---

## GitHub Actions

В ZIP есть `.github/workflows/android.yml`. Он собирает debug APK на `ubuntu-22.04` и загружает артефакт `apk`.

Порядок:

1. Создайте репозиторий GitHub.
2. Загрузите **содержимое** папки Android-пакета (не сам ZIP).
3. Откройте **Actions → Build Android APK → Run workflow**.
4. После завершения скачайте артефакт `apk` внизу страницы запуска.

Workflow кеширует `~/.buildozer` и `.buildozer`, поэтому повторные сборки быстрее.

> GitHub Actions удобен для проверки сборки, но не заменяет локальную отладку. Логи `buildozer` подробнее в локальном терминале.

---

## Release-подпись

Debug APK подписан отладочным ключом и **не подходит для публикации** в Google Play.

### 1. Создайте keystore

```bash
keytool -genkey -v -keystore release.keystore -alias reasonable \
  -keyalg RSA -keysize 2048 -validity 10000
```

Сохраните файл и пароли в надёжном месте. Потеря ключа означает невозможность обновлять приложение в Play.

### 2. Включите подпись в `buildozer.spec`

Раскомментируйте и заполните:

```ini
android.release_artifact = aab
android.signing = True
android.keystore = release.keystore
android.keystore_alias = reasonable
android.keystore_pwd = ВАШ_ПАРОЛЬ_ХРАНИЛИЩА
android.key_pwd = ВАШ_ПАРОЛЬ_КЛЮЧА
```

Для Google Play нужен формат **AAB**, для прямой установки — APK. Можно переключать `release_artifact`.

### 3. Соберите release

```bash
buildozer android release
```

Готовый файл появится в `bin/`. Не коммитьте `release.keystore` и пароли в репозиторий.

---

## Проверка до сборки APK

Сначала убедитесь, что проект запускается на компьютере:

```bash
cd ~/android/Мой-проект-android
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RE_SKIP_SPLASH=1 RE_FRAMES=5 \
  PYTHONPATH="$PWD/_engine:$PWD" python3 main.py
```

Или через CLI:

```bash
PYTHONPATH="$PWD/_engine:$PWD" python3 -m reasonable.cli --project "$PWD" run --headless
```

Если здесь ошибка, Android-сборка не поможет: исправьте Python-код и ассеты.

Полезно проверить:

```bash
PYTHONPATH="$PWD/_engine:$PWD" python3 -m reasonable.cli --project "$PWD" validate
```

---

## Отладка на Android

### Логи

```bash
adb logcat | grep -i python
```

Или весь поток:

```bash
adb logcat > android.log
```

Ищите `Traceback`, `ModuleNotFoundError`, `pygame.error`, `FileNotFoundError`.

### Типичные проблемы

| Проблема | Решение |
|---|---|
| `Command failed: ... aidl` | Установите OpenJDK 17, проверьте `java -version` |
| `No module named pygame` | Проверьте `requirements` в `buildozer.spec`; попробуйте `pygame-ce` |
| Сборка падает на Cython | Обновите `cython` и `buildozer`; очистите кеш |
| Долгая сборка в `/mnt/c` | Перенесите проект в `~/android` |
| APK устанавливается, но чёрный экран | `adb logcat`; проверьте `main.py`, пути к ассетам, splash |
| Нет звука | Проверьте формат (`ogg`/`wav`), громкость, `SDL_AUDIODRIVER` |
| Не работают касания | Используйте `VirtualJoystick`/`TouchButton`; проверьте координаты при разных разрешениях |
| Play отклоняет APK | Нужен AAB, release-подпись и актуальный target API |
| `buildozer` не найден | `export PATH="$HOME/.local/bin:$PATH"` |
| Ошибка лицензии SDK | `android.accept_sdk_license = True`, повторите сборку |

### Очистка кеша

```bash
buildozer android clean
rm -rf .buildozer
```

После этого сборка снова скачает зависимости. Используйте при странных ошибках p4a.

### Логи buildozer

```bash
buildozer -v android debug 2>&1 | tee build.log
```

`-v` включает подробный вывод. В конце ищите первую ошибку, а не последнюю строку.

---

## Особенности Android для кода

- **Экран и DPI.** Не хардкодьте координаты под один телефон. Используйте относительные размеры, `Camera`, `ScrollView` и якоря UI.
- **Касания.** Мышь и палец приходят как события `pygame.FINGERDOWN/FINGERMOTION/FINGERUP`. В runtime есть `Input`, `VirtualJoystick` и `TouchButton`.
- **Клавиатура.** На телефоне её может не быть. Все действия должны быть доступны касанием.
- **Пауза.** Android может приостановить приложение. Сохраняйте состояние в `SaveData` и обрабатывайте `APP_WILLENTERBACKGROUND`, если это важно.
- **Энергия.** `android.wakelock = True` не даёт экрану гаснуть во время игры.
- **Ориентация.** Смена ориентации перезапускает Activity. Не храните критичное состояние только в памяти. Если проект сконвертирован в портрет, проверьте, что меню и HUD помещаются по вертикали.
- **Конвертированный код.** После `convert --to android` логика остаётся прежней. Проверьте мышиные подсказки, правую кнопку, hover-эффекты и горячие клавиши — на телефоне их нет.
- **Файлы.** `_engine` и `assets` доступны только для чтения. Сохранения пишутся в приватную папку приложения.
- **Размер.** Тяжёлые PNG и музыку стоит оптимизировать: APK с десятками мегабайт ассетов собирается дольше и хуже устанавливается.

---

## Заставка и запуск

Перед приложением всегда проигрывается процедурная заставка Reasonable Engine (~2,8 с, пропуск после 0,85 с). Она не требует видеофайлов и работает офлайн.

Для отладки:

```bash
RE_SKIP_SPLASH=1 python3 main.py
```

В `buildozer.spec` presplash — статичная картинка Android, а анимированная заставка рисуется runtime уже после старта Python. Это две разные вещи:

- `presplash.png` — системный экран загрузки Android;
- `play_splash()` — анимированная заставка движка внутри приложения.

---

## Ограничения

- Windows не собирает APK напрямую.
- Первая сборка требует интернета и много места.
- Не все Python-пакеты имеют рецепты python-for-android. Runtime специально ограничен `pygame` и стандартной библиотекой.
- PySide6 в Android-пакет не входит: редактор остаётся на Windows, а игры и приложения используют pygame.
- Тесты Reasonable Engine проверяют содержимое ZIP и запуск проекта на ПК, но **не собирают APK** в автоматическом режиме.
- Конвертация Windows→Android меняет метаданные, ориентацию, окно и инструкции, но не переписывает игру. Адаптация вёрстки и управления остаётся ручной задачей или задачей агента.

---

## Чек-лист перед публикацией

- [ ] Проект запускается на ПК и проходит `validate`.
- [ ] Проект сконвертирован в Android или изначально создан с `platform: android`.
- [ ] После конвертации проверены касания, узкий экран и safe margins.
- [ ] Имя и package id уникальны.
- [ ] Версия обновлена.
- [ ] Иконка и presplash выглядят корректно.
- [ ] Ориентация правильная.
- [ ] Касания покрывают все действия.
- [ ] Сохранения работают после перезапуска.
- [ ] Собран release AAB.
- [ ] AAB подписан release-ключом.
- [ ] Ключ и пароли сохранены вне репозитория.
- [ ] Проверена установка на реальном устройстве.
- [ ] Target API соответствует текущим требованиям Google Play.

---

## Связанные документы

- [CLI.md](CLI.md) — `re.bat export android` и другие команды.
- [EXTERNAL_AGENTS.md](EXTERNAL_AGENTS.md) — если Android-проект ведёт внешний агент.
- [ARCHITECTURE.md](ARCHITECTURE.md) — почему runtime общий для Windows и Android.
