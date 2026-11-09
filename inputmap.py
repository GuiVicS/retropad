"""Mapeamento de caracteres e nomes de teclas para códigos evdev (layout US).

Módulo puro (sem uinput), para poder ser testado em qualquer máquina.
Caracteres que não existem no layout US (ç, ã, é...) não têm tecla própria e
devolvem None: o servidor os ignora em vez de digitar a tecla errada.
"""
from evdev import ecodes as e

_LETTERS = {c: getattr(e, "KEY_" + c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}
_DIGITS = {str(n): getattr(e, "KEY_" + str(n)) for n in range(10)}
_PUNCT = {
    " ": e.KEY_SPACE, "\n": e.KEY_ENTER, "\t": e.KEY_TAB,
    "-": e.KEY_MINUS, "=": e.KEY_EQUAL, "[": e.KEY_LEFTBRACE, "]": e.KEY_RIGHTBRACE,
    "\\": e.KEY_BACKSLASH, ";": e.KEY_SEMICOLON, "'": e.KEY_APOSTROPHE,
    "`": e.KEY_GRAVE, ",": e.KEY_COMMA, ".": e.KEY_DOT, "/": e.KEY_SLASH,
}
# Caractere digitado com Shift -> caractere da mesma tecla sem Shift.
_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8",
    "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "~": "`", "<": ",", ">": ".", "?": "/",
}

_BASE = {**_LETTERS, **_DIGITS, **_PUNCT}

# Teclas por nome, usadas pela barra de teclas extras do celular.
NAMED_KEYS = {
    "esc": e.KEY_ESC, "tab": e.KEY_TAB, "enter": e.KEY_ENTER, "backspace": e.KEY_BACKSPACE,
    "delete": e.KEY_DELETE, "insert": e.KEY_INSERT, "space": e.KEY_SPACE,
    "home": e.KEY_HOME, "end": e.KEY_END, "pageup": e.KEY_PAGEUP, "pagedown": e.KEY_PAGEDOWN,
    "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
    "capslock": e.KEY_CAPSLOCK, "printscreen": e.KEY_SYSRQ, "menu": e.KEY_COMPOSE,
    **{f"f{n}": getattr(e, f"KEY_F{n}") for n in range(1, 13)},
}

# Modificadores (o celular manda os que estão "travados" na barra).
MODIFIERS = {
    "ctrl": e.KEY_LEFTCTRL, "alt": e.KEY_LEFTALT,
    "shift": e.KEY_LEFTSHIFT, "meta": e.KEY_LEFTMETA,
}

MOUSE_BUTTONS = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}


def char_to_key(ch):
    """Devolve (código, precisa_shift) para um caractere, ou None se não existir no layout US."""
    if len(ch) != 1:
        return None
    if ch in _BASE:
        return _BASE[ch], False
    if ch.isascii() and ch.isalpha() and ch.lower() in _LETTERS:   # maiúsculas
        return _LETTERS[ch.lower()], True
    base = _SHIFTED.get(ch)
    if base is not None:
        return _BASE[base], True
    return None


def all_keyboard_codes():
    """Todos os códigos que o teclado virtual precisa declarar ao uinput."""
    codes = set(_BASE.values()) | set(NAMED_KEYS.values()) | set(MODIFIERS.values())
    return sorted(codes)
