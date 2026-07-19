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

В 2006 году на DeviantArt появился набор курсоров «Chrome Glass» - полупрозрачный, переливающийся, живой. На современных экранах его 32-пиксельная графика превратилась в мутные кляксы - я вернул её к жизни. **Это тот самый набор, а не подражание**: подлинная графика 2006 года входит в комплект нетронутой, отдельной готовой к установке темой *Chrome Glass (2006)*, а ремастер пересобирает из неё каждый курсор - чётким от 32 до 512 px.

![оригинал против ремастера на HiDPI](assets/comparison.png)

| | Chrome Glass (2006) | Chrome Glass Remastered |
|---|---|---|
| Разрешение | 32 px | **до 256 px** (Windows) / **512 px** (Linux), векторные кромки без растрового мыла |
| Анимация | 9 кадров, ~20 fps | **27 кадров, 60 fps**, авторский ритм сохранён |
| Роли курсоров | 15 слотов Windows | плюс **Pin** и **Person** в стиле набора |
| Платформы | Windows | Windows, Linux (Xcursor, deb, PKGBUILD), macOS (Mousecape) |

Нетронутый набор 2006 года собирается рядом с ремастером (`dist/original/`), так что референс всегда в одной сборке от вас.

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
| Любой, без root | `tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.local/share/icons/` |

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

## В движении

![анимированные курсоры](assets/animations.webp)

| Ожидание (busy) | Запуск приложения (progress) |
|:---:|:---:|
| ![](assets/Wait.webp) | ![](assets/AppStarting.webp) |

## Как это устроено

Каждый курсор - гибрид трёх источников: оригинальные кадры 32 px (`src/orig/`) дают родную стеклянную полупрозрачность, AI-апскейл - авторские переливы (цветоперенос Рейнхарда возвращает смытую насыщенность), векторные силуэты (`traced.json`) - чёткую кромку на любом размере. Единый native-256 px мастер Real-ESRGAN (`src/ai256/`, статика и анимация) служит источником цвета для всего набора - каждый размер, включая 32 px, супсемплится из него вниз или шарпится вверх, так что ничто больше не привязано к мягким 128 px. Мастера закоммичены, так что сборке torch не нужен. Малонасыщенные курсоры (IBeam, Cross, стрелки resize) намеренно пропускают AI - на прозрачном стекле он выдумывает штриховой шум.

## Сборка из исходников

```sh
pip install pillow numpy
python3 build.py
```

Скрипт пересобирает `dist/`, `packages/` и превью, а в конце сверяет результат с оригиналом (альфа, насыщенность, тайминг) и предупреждает, если что-то уехало. Карта конвейера: `src/` -> `trace.py` -> `traced.json` -> `hybrid.py` + `glyphs.py` -> `build.py` -> `curlib.py` / `vectorlib.py`.

## Лицензия

Оригинальная графика: [«Chrome Glass» от yoyos, DeviantArt, 2006](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748) (см. [`NOTICE`](NOTICE)). Код - **MIT** ([`LICENSE`](LICENSE)).

Долгие годы Chrome Glass остаётся моим любимым набором курсоров - спасибо автору за него. Этот репозиторий - логическое продолжение его работы и попытка вдохнуть в неё новую жизнь.

---

<div align="center">

*Вернуло в прошлое? Поставьте звезду - так курсоры найдут и те, кто тоже скучает по 2006 году.* ⭐

</div>
