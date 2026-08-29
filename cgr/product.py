"""One product record per cursor name: which platforms ship it, under what
role, at what sizes, animated or not.

build.py decides how each platform actually assembles its files, and keeps
owning that - Windows walks STATIC/ANIM and consults WIN_SLOTS only for
Install.inf, Linux walks XROLES (where the key IS the cursor name), macOS
walks MAC_CURSORS. Those three tables are correct and independently
authored; nothing here replaces them. This module only answers the question
none of the three answers alone - "for this name, what ships where" - so a
tool that needs the shape of the product (visual_audit, a future package
round-trip check) has one place to ask instead of re-deriving it three times.
"""
from . import build as B


def _windows_roles():
    """{name: slot role}, from WIN_SLOTS' (role, "Name.ext") pairs."""
    return {fn.rsplit(".", 1)[0]: role for role, fn in B.WIN_SLOTS}


def _macos_by_name():
    """{name: (mousecape id, ships as its own animation)}, from MAC_CURSORS."""
    return {name: (ident, animated) for ident, name, animated in B.MAC_CURSORS}


def manifest():
    """{name: {"animated": bool, "windows": {...}|None, "linux": {...}|None,
               "macos": {...}|None}}, one entry per cursor the product has -
    STATIC + ANIM, 18 names. A platform key is None when that platform ships
    nothing under this name; Arrow_Down is windows=None too even though
    build_windows() does write Arrow_Down.cur to dist/ - WIN_UNSHIPPED keeps
    it out of Install.inf and the release archive, so nobody who installs the
    theme gets a slot pointing at it."""
    win_roles = _windows_roles()
    mac_by_name = _macos_by_name()
    out = {}
    for name in sorted(set(B.STATIC) | set(B.ANIM)):
        animated = name in B.ANIM
        windows = None
        if name in win_roles:
            windows = {"slot": win_roles[name],
                       "sizes": list(B.ANI_SIZES_WIN if animated else B.SIZES)}
        linux = None
        if name in B.XROLES:
            linux = {"roles": list(B.XROLES[name]),
                     "sizes": list(B.ANI_SIZES if animated else B.LINUX_SIZES)}
        macos = None
        if name in mac_by_name:
            ident, ships_animated = mac_by_name[name]
            macos = {"id": ident, "ships_animated": ships_animated,
                     "sizes": [32 * s for s in B.MAC_SCALES]}
        out[name] = {"animated": animated, "windows": windows,
                     "linux": linux, "macos": macos}
    return out
