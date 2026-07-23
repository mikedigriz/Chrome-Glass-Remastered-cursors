<div align="center">

# Chrome Glass Remastered

**Помните стеклянные курсоры из 2006 года? Они вернулись - и теперь чёткие даже на 4K-экране.**

[![English version](https://img.shields.io/badge/README-in%20English-0B67A0?style=flat-square)](README.md)
[![Release](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](../../releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-2496ED?style=flat-square&logo=windows&logoColor=white)](#-windows-10--11)
[![Linux](https://img.shields.io/badge/Linux-Xcursor-FCC624?style=flat-square&logo=linux&logoColor=black)](#-linux)
[![macOS](https://img.shields.io/badge/macOS-Mousecape-000000?style=flat-square&logo=apple&logoColor=white)](#-macos)
[![License](https://img.shields.io/badge/код-MIT-green?style=flat-square)](LICENSE)

![preview](preview.png)

</div>

В 2006 году на DeviantArt появился набор курсоров «Chrome Glass» - полупрозрачный, переливающийся, живой. Его рисовали для 32-пиксельных экранов, поэтому на 4K-дисплее он превращается в мутную кляксу. Я пересобрал набор так, чтобы он оставался чётким на любом экране - и не потерял обаяния оригинала.

**Это тот самый набор, а не подражание.** Графика 2006 года тоже входит в комплект нетронутой - отдельной готовой темой *Chrome Glass (2006)* (при сборке из исходников она же собирается в `dist/original/`) - чтобы всегда можно было сверить их бок о бок.

![оригинал против ремастера на HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Разрешение | 32 px | **до 256 px** (Windows) / **512 px** (Linux), векторные кромки без растрового мыла |
| Анимация | 9 кадров, ~20 fps | **27 кадров, 60 fps**, авторский ритм сохранён |
| Роли курсоров | 15 слотов Windows | плюс **Pin** и **Person** в стиле набора |
| Платформы | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

## Установка

Всё нужное лежит в [последнем релизе](../../releases/latest).

### 🪟 Windows 10 / 11

1. Скачайте и распакуйте `ChromeGlassRemastered-windows.zip`.
2. Щёлкните правой кнопкой по **`Install.inf`** -> **Установить**.
3. Параметры -> Мышь -> *Дополнительные параметры мыши* -> вкладка **Указатели** -> схема **Chrome Glass Remastered** -> Применить.

### 🐧 Linux

| Дистрибутив | Команда |
|---|---|
| Debian / Ubuntu / Mint | `sudo dpkg -i chrome-glass-remastered-cursors_1.0.0_all.deb` |
| Arch / Manjaro | `cd packaging && makepkg -si` ([PKGBUILD](packaging/PKGBUILD)) |
| Любой, без root | `mkdir -p ~/.local/share/icons/ && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.local/share/icons/` |

Дальше включите тему:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE
```

Или выберите её в GNOME Tweaks / Параметрах KDE. На голых X11/Wayland-композиторах пропишите `XCURSOR_THEME="Chrome Glass Remastered"`.

### 🍎 macOS

Темы курсоров в macOS применяет бесплатный [Mousecape](https://github.com/alexzielenski/Mousecape):

1. `brew install --cask mousecape`
2. Скачайте `ChromeGlassRemastered.cape` и откройте двойным щелчком.
3. Правой кнопкой по cape -> **Apply**.

Cape заменяет основные курсоры (стрелка, текст, перекрестие, рука, перемещение, ожидание); остальные остаются системными.

> **Важно:** с каждой версией macOS темизацию курсоров закручивают всё сильнее. Mousecape требует частично отключённого SIP и может вовсе не заработать на Apple Silicon. Если после **Apply** ничего не изменилось - это ограничение Mousecape и macOS, а не баг набора. Прежде чем заводить баг здесь, загляните в [трекер issues Mousecape](https://github.com/alexzielenski/Mousecape/issues).

## В движении

![анимированные курсоры](assets/animations.webp)

## Как это устроено

Каждый курсор собран из трёх вещей: **оригинальной графики 32 px**, для подлинности; **версии, увеличенной нейросетью** - её один раз считают до 512 px и кладут в репозиторий, она даёт цвет и переливы на всех размерах поменьше (ужать чище, чем растянуть); и **векторного контура**, чтобы края были чёткими на любом масштабе. Цвет от нейросети теперь получают даже бледные, почти серые курсоры (Help, IBeam, Cross, стрелки resize) - апскейлер настроен под чистую графику и держит плоское серое стекло гладким, а не засыпает выдуманным шумом, а отдельный проход резкости добавляет чёткие кромки без лишней текстуры.

Прозрачность увеличивают так же, но отдельно от цвета - растянутая прямо с 32 px, она размывается и уносит с собой стеклянное свечение. Цвета у неё нет, выдумывать нейросети нечего, поэтому увеличенную версию используют все курсоры, включая бледные.

## Сборка из исходников

Все AI-мастера уже лежат в репозитории, поэтому обычной сборке не нужны ни GPU, ни torch.

```sh
pip install -r requirements.txt
python3 build.py
```

Скрипт пересобирает `dist/`, `packages/` и превью, а в конце сверяет результат с оригиналом (альфа, насыщенность, тайминг) и предупреждает, если что-то уехало.

### Что за что отвечает

| Папка / файл | Что там лежит |
|---|---|
| `src/orig/` | нетронутая графика 2006 года, 32 px - эталон, с которым всё сверяется |
| `src/ai/` | AI-увеличение до 128 px, промежуточный шаг к большим размерам |
| `src/ai512/`, `src/ai256/` | цветные AI-мастера - сборка берёт 512 px, если есть, иначе 256 px, иначе простой ресайз |
| `src/aialpha/` | AI-увеличение прозрачности, отдельно от цвета |
| `traced.json` | векторные контуры, генерирует `trace.py` |

Порядок сборки: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

Пара мелочей нарисована вручную в `cursors.py`, а не найдена автоматически - например, точка под знаком `?` у курсора Help. Она стоит отдельно от стрелки, и автоматический трассировщик её просто не видит.

### Как пересчитать AI-файлы самому (по желанию)

Нужно, только если хотите посчитать увеличенные версии заново, а не использовать те, что уже лежат в репозитории. Это единственный шаг, для которого нужна видеокарта и библиотека torch (PyTorch, большая библиотека машинного обучения):

```sh
pip install -r requirements-ai.txt

python3 tools/upscale128.py     # src/orig -> src/ai       (база 128 px)
python3 tools/upscale512.py     # src/ai   -> src/ai512    (основной мастер цвета)
python3 tools/upscale256.py     # src/ai   -> src/ai256    (запасной мастер цвета)
python3 tools/upscale_alpha.py  # src/orig -> src/aialpha  (мастер альфы)
```

Порядок именно такой: мастера цвета строятся из базы 128 px, мастер альфы - из альфы оригинала. Единственный нужный файл весов - `RealESRGAN_x4plus_anime_6B.pth` (~18 МБ, настроен под иллюстрации), положите его в `weights/` сами (`upscale_lib.load_model` грузит его локально, без авто-скачивания). Результаты закоммичены - поэтому всем остальным это делать не нужно.

## Лицензия

Оригинальная графика: [«Chrome Glass» от yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (см. [`NOTICE`](NOTICE)). Код - **MIT** ([`LICENSE`](LICENSE)).

Долгие годы Chrome Glass остаётся моим любимым набором курсоров - спасибо автору за него. Этот репозиторий - логическое продолжение его работы и попытка вдохнуть в неё новую жизнь.

---

<div align="center">

*Вернуло в прошлое? Поставьте звезду - так курсоры найдут и те, кто тоже скучает по 2006 году.* ⭐

</div>
