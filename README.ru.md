<div align="center">

# Chrome Glass Remastered

**Курсоры Chrome Glass 2006 года, перерисованные под современные экраны.**

[![English version](https://img.shields.io/badge/README-in%20English-0B67A0?style=flat-square)](README.md)
[![Релиз](https://img.shields.io/github/v/release/mikedigriz/chrome-glass-remastered-cursors?style=flat-square&color=1E3A8A)](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest)
[![Лицензия](https://img.shields.io/badge/код-MIT-green?style=flat-square)](LICENSE)

[![Скачать последний релиз](https://img.shields.io/badge/%E2%AC%87%20%D0%A1%D0%BA%D0%B0%D1%87%D0%B0%D1%82%D1%8C%20%D0%BF%D0%BE%D1%81%D0%BB%D0%B5%D0%B4%D0%BD%D0%B8%D0%B9%20%D1%80%D0%B5%D0%BB%D0%B8%D0%B7-1E3A8A?style=for-the-badge)](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest)

**Windows 10/11 · Linux · macOS 15+**

<img src="assets/preview.png" alt="Витрина Chrome Glass Remastered: Arrow, Help, IBeam, Cross, SizeAll, курсоры изменения размера, UpArrow, Pin, Person, NO, Wait и AppStarting">

</div>

23 апреля 2006 года yoyos выложил на DeviantArt набор [Chrome Glass](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748): стеклянные указатели под ЭЛТ и первые ЖК, 32 пикселя, XP на 1280x1024. Двадцать лет спустя система растягивает те же 32 пикселя на указатель вчетверо больше, и от стекла остаётся мыло.

Здесь тот же набор, перерисованный в размерах до 512 пикселей. Форма, цвет и тайминг остались авторскими: 32-пиксельные кадры внутри курсоров лежат байт в байт как в 2006-м. Изменилось всё, что выше 32 пикселей, то есть ровно то, что вы сегодня и видите.

Проверено на Windows 11 и Debian 13 (GNOME, X11). Cape для macOS собирается и проходит проверку сборки, но на живой Mac его пока никто не ставил.

## Что скачивать

Все файлы лежат в [последнем релизе](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/releases/latest).

| Система | Файл | Как ставится |
|---|---|---|
| Windows 10/11 | `ChromeGlassRemastered-windows.zip` | правая кнопка по `Install.inf`, пункт **Установить** |
| Linux | `.deb` или `ChromeGlassRemastered-linux.tar.gz` | пакет или распаковка в `~/.local/share/icons` |
| macOS 15+ | `ChromeGlassRemastered.cape` | открыть в [Mousecape](https://github.com/sdmj76/Mousecape-swiftUI) |

## Поставить

<details open>
<summary><b>🪟 &nbsp;Windows 10 / 11</b></summary>

1. Распакуйте `ChromeGlassRemastered-windows.zip`.
2. Нажмите правой кнопкой по `Install.inf` и выберите **Установить**. В Windows 11 сначала откройте **Показать дополнительные параметры**, если пункт скрыт.
3. Откройте **Параметры → Bluetooth и устройства → Мышь → Дополнительные параметры мыши → Указатели**, выберите **Chrome Glass Remastered** в списке *Схема* и нажмите **Применить**.
4. Стоит сделать: **Параметры → Специальные возможности → Указатель мыши и сенсорное управление** и увеличить размер указателя. Всё, ради чего это перерисовывалось, видно выше минимального размера.

Как убрать: та же вкладка **Указатели**, выберите схему, нажмите **Удалить**, затем вернитесь на **Стандартная Windows**. Файлы останутся в `%WINDIR%`, пока вы их не удалите сами: см. [полное удаление](docs/DETAILS.ru.md#windows).

</details>

<details>
<summary><b>🐧 &nbsp;Linux</b></summary>

| Дистрибутив | Установка |
|---|---|
| Debian / Ubuntu / Mint | `sudo apt install ./chrome-glass-remastered-cursors_*_all.deb` |
| Arch / Manjaro | скачайте `PKGBUILD` из релиза и выполните `makepkg -si` в его каталоге |
| Любой, без root | `mkdir -p ~/.local/share/icons && tar -xzf ChromeGlassRemastered-linux.tar.gz -C ~/.local/share/icons/` |

Дальше выберите **Chrome Glass Remastered** в GNOME Tweaks или в **Параметры системы → Внешний вид → Курсоры** на KDE Plasma. Из терминала:

```sh
gsettings set org.gnome.desktop.interface cursor-theme "Chrome Glass Remastered"  # GNOME
plasma-apply-cursortheme "Chrome Glass Remastered"                                # KDE Plasma
```

Как убрать: `sudo apt remove chrome-glass-remastered-cursors`, `sudo pacman -R chrome-glass-remastered-cursors` или `rm -rf ~/.local/share/icons/"Chrome Glass Remastered"` для ручной установки.

</details>

<details>
<summary><b>🍎 &nbsp;macOS 15+</b></summary>

1. Установите [Mousecape SwiftUI](https://github.com/sdmj76/Mousecape-swiftUI/releases) - обычную сборку, не Debug. Нужна macOS Sequoia 15 или новее, приложение universal, идёт на Intel и Apple Silicon.
2. Скачайте `ChromeGlassRemastered.cape` из последнего релиза.
3. Откройте cape двойным щелчком или импортируйте его в Mousecape, затем выберите и примените.

Заменяются двенадцать системных курсоров: Arrow, IBeam, Move, Wait, Crosshair, Pointing Hand, Forbidden, Help и четыре направления изменения размера. Остальные остаются системными.

Вернуть системные: **File → Reset System Cursor** или <kbd>⌘</kbd>+<kbd>R</kbd>.

</details>

## Как это выглядело и как выглядит

Слева файл 2006 года в том виде, в каком его сегодня растягивает система. Справа те же два указателя, нарисованные в 512 пикселей. Сверху Arrow, снизу Wait.

![Оригинальные Arrow и Wait размером 32 px, увеличенные до 512 px, рядом с ремастером в 512 px](assets/comparison.png)

## Как оно двигается

Анимированы пять указателей: **AppStarting**, **Hand** на ссылке, **Handwriting**, **NO** и **Wait**.

![Анимированные AppStarting, Hand, Handwriting, NO и Wait рядом](assets/animations.webp)

## Не работает?

- **Темы нет в списке или указатель остался прежним.** Выйдите из сеанса и войдите снова. Приложения запоминают курсор при запуске, так что перезапустите те, где он не сменился.
- **Анимация идёт медленнее, чем на Windows.** Так и задумано: на Linux стоит авторский темп ~20 fps, потому что на 60 fps под X11 картинка мерцает.
- **На macOS курсор сменился не везде.** Часть приложений рисует свои курсоры, и Mousecape не может их безопасно подменить.

Остальные симптомы и полное удаление по платформам: **[docs/DETAILS.ru.md](docs/DETAILS.ru.md)**.

## Оригинал

Chrome Glass - [работа yoyos](https://www.deviantart.com/yoyos/art/Chrome-Glass-32252748). Это неофициальный ремастер, сделанный как дань уважения и сохраняющий авторство рядом с графикой. Если вы автор и хотите что-то изменить или убрать, откройте issue - это будет сделано.

Лицензия MIT **не распространяется** на графику курсоров, см. [`NOTICE`](NOTICE). Код сборки и упаковки - под MIT, см. [`LICENSE`](LICENSE).

## Дальше

- **[docs/DETAILS.ru.md](docs/DETAILS.ru.md)** - что внутри каждого пакета, что умеет и чего не умеет каждая платформа, полное удаление, контрольные суммы, длинный разбор проблем.
- **[docs/BUILD.ru.md](docs/BUILD.ru.md)** - собрать самому. Python, Pillow, NumPy, без видеокарты.
- Что-то сломалось? [Создайте issue](https://github.com/mikedigriz/Chrome-Glass-Remastered-cursors/issues) и укажите систему и окружение рабочего стола, версию релиза, размер указателя и способ установки.
