<div align="center">

# Chrome Glass Remastered

**Помните стеклянные курсоры из 2006-го? Они вернулись - и больше не превращаются в кашу на 4K.**

[![English version](https://img.shields.io/badge/README-in%20English-0B67A0?style=flat-square)](README.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](../../releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-2496ED?style=flat-square&logo=windows&logoColor=white)](#-windows-10--11)
[![Linux](https://img.shields.io/badge/Linux-Xcursor-FCC624?style=flat-square&logo=linux&logoColor=black)](#-linux)
[![macOS](https://img.shields.io/badge/macOS-Mousecape-000000?style=flat-square&logo=apple&logoColor=white)](#-macos)
[![License](https://img.shields.io/badge/код-MIT-green?style=flat-square)](LICENSE)

<img src="preview.png" alt="preview" width="640">

</div>

В 2006 году на DeviantArt вышел набор курсоров «Chrome Glass» - стеклянный, живой, но нарисованный под 32 px, поэтому на 4K превращается в кашу. Я пересобрал его для больших экранов, сохранив шарм.

![оригинал против ремастера на HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Разрешение | 32 px | **до 256 px** (Windows) / **512 px** (Linux), векторные края без мыла. Анимированные - до 96 px на Windows и 384 px на Linux |
| Анимация | 9 кадров (у NO - 11), ~20 fps | **27 кадров, 60 fps** у ожидания, запуска и руки-указателя на Windows/macOS, ~20 fps на Linux. Handwriting и NO везде сохраняют авторский тайминг |
| Курсоры | 15 стандартных слотов Windows | плюс свои **Pin** и **Person** (только Windows) |
| Платформы | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

## Установка

Всё лежит в [последнем релизе](../../releases/latest).

### 🪟 Windows 10 / 11

1. Скачайте и распакуйте `ChromeGlassRemastered-windows.zip`.
2. ПКМ по `Install.inf` -> **Установить**.
3. Параметры -> Мышь -> *Дополнительные параметры мыши* -> **Указатели** -> схема **Chrome Glass Remastered** -> Применить.

Чтобы удалить: ПКМ по тому же `Install.inf` -> **Удалить**. Схема снимется, скопированные курсоры удалятся.

### 🐧 Linux

| Дистрибутив | Команда |
|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_*_all.deb` |
| Arch / Manjaro | `cd packaging && makepkg -si` ([PKGBUILD](packaging/PKGBUILD)) - у копии из релиза заполнена контрольная сумма |
| Без root | `mkdir -p ~/.icons/ && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.icons/` |

`.deb` дополнительно регистрирует тему через `update-alternatives`, поэтому она может стать системной; `sudo dpkg -r chrome-glass-remastered-cursors` откатывает это начисто.

Дальше включите тему:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Или выберите её в GNOME Tweaks / параметрах KDE. На голом X11/Wayland пропишите `XCURSOR_THEME="Chrome Glass Remastered"`.

> **Курсор не меняется?** Некоторые архиваторы при «Извлечь в папку...» создают лишнюю папку-обёртку. Проверьте, что тема лежит прямо в `~/.icons/Chrome Glass Remastered/`, а не на уровень глубже. После смены темы GNOME на X11 нужно перезапустить Shell (`killall -3 gnome-shell`), на Wayland и в KDE - перелогиниться.

> **Курсор мигает?** Раньше анимация шла на 60 fps и периодически не попадала в такт с 60-герцовым экраном - отсюда мигание у ожидания, запуска и руки-указателя. Теперь эти три на Linux идут на ~20 fps, как в оригинале, мигать нечему. Handwriting и NO сохраняют более быстрый авторский темп: они проигрываются один раз и замирают, а не зациклены. Если мигает после обновления темы - перезапустите приложение: курсоры кэшируются при старте.

### 🍎 macOS

Темы курсоров на macOS ставит бесплатный [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Скачайте `ChromeGlassRemastered.cape`, откройте двойным кликом.
3. ПКМ по cape -> **Apply**.

Cape меняет двенадцать курсоров: стрелку, текст, руку-указатель, крест, перемещение, ожидание, запрет, справку и четыре стрелки resize. Остальные - системные.

> **Важно:** с каждой версией macOS Apple всё сильнее закручивает гайки на тему курсоров. Mousecape требует частично отключённого SIP и может не работать на Apple Silicon вовсе. Если `Apply` ничего не даёт - это ограничение Mousecape/macOS, не баг набора. Загляните в [issues Mousecape](https://github.com/alexzielenski/Mousecape/issues), прежде чем писать сюда.

## В движении

![анимированные курсоры](assets/animations.webp)

## Как это устроено

Курсор - это три слоя: **оригинал 32 px** для подлинности, **AI-апскейл до 512 px** для цвета и переливов (посчитан один раз и лежит в репозитории - ужать чище, чем растянуть) и **векторный контур** для чётких краёв на любом масштабе. Апскейлер настроен под иллюстрации, поэтому даже бледные курсоры (Help, IBeam, Cross, стрелки resize) получают ровный цвет без шума, а отдельный проход резкости подчёркивает края.

Прозрачность увеличивают отдельно от цвета: растянутая прямо с 32 px, она теряет стеклянный блеск. Цвета в альфа-канале нет и портить нечего, поэтому увеличенную версию используют все курсоры, включая бледные.

## Сборка из исходников

Все AI-мастера уже в репозитории - GPU и torch для обычной сборки не нужны.

```sh
pip install -r requirements.txt
python3 build.py
```

Скрипт пересобирает `dist/`, `packages/`, превью, а в конце сверяет результат с оригиналом (альфа, насыщенность, тайминг) и ругается, если что-то поехало. Два рычага: `BUILD_SERIAL=1` считает в одно ядро вместо всех, `ALLOW_METRIC_WARN=1` выпускает несмотря на предупреждение о дрейфе.

`dist/original/Chrome Glass (2006)/` - нетронутый набор 2006 года, пересобранный как эталон для сверки. Он сознательно только локальный: не пакуется и не попадает в релизы.

### Что за что отвечает

| Папка / файл | Что там |
|---|---|
| `src/orig/` | нетронутая графика 2006 года, 32 px - эталон для сверки |
| `src/ai/` | AI-апскейл до 128 px, из него `trace.py` берёт формы |
| `src/ai512/` | цветной AI-мастер, нативное разрешение |
| `src/aialpha/` | AI-апскейл прозрачности, отдельно от цвета |
| `traced.json` | векторные контуры из `trace.py` |

Порядок сборки: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

Пара мелочей нарисована вручную в `cursors.py`, а не найдена трассировщиком - например, точка под знаком «?» у Help: она стоит отдельно от стрелки, и автоматика её не видит.

### Пересчитать AI-файлы самому (по желанию)

Нужно, только если хотите посчитать апскейлы заново, а не брать готовые из репозитория. Единственный шаг, для которого нужны видеокарта и torch (PyTorch):

```sh
pip install -r requirements-ai.txt

python3 tools/upscale128.py     # src/orig -> src/ai       (база 128 px)
python3 tools/upscale512.py     # src/ai   -> src/ai512    (мастер цвета)
python3 tools/upscale_alpha.py  # src/orig -> src/aialpha  (мастер альфы)
```

Нужен один файл весов - `RealESRGAN_x4plus_anime_6B.pth` (~18 МБ, под иллюстрации), положите его в `weights/` сами (`upscale_lib.load_model` грузит локально, без скачивания). Результаты уже закоммичены, поэтому остальным этим заниматься не нужно.

## Лицензия

Оригинальная графика: [«Chrome Glass» от yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (см. [`NOTICE`](NOTICE)). Код - **MIT** ([`LICENSE`](LICENSE)).

Chrome Glass годами остаётся моим любимым набором курсоров - спасибо, yoyos.

---

<div align="center">

*Накрыло ностальгией? Поставьте звезду - так курсоры найдут остальных, кто скучает по 2006-му.* ⭐

</div>
