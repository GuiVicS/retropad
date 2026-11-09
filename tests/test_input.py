"""Testes do mapeamento de teclas e da lógica de mouse/teclado/gamepad (sem uinput real)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evdev import ecodes as e  # noqa: E402

import inputmap  # noqa: E402


class CharToKey(unittest.TestCase):
    def test_lowercase_letter(self):
        self.assertEqual(inputmap.char_to_key("a"), (e.KEY_A, False))

    def test_uppercase_needs_shift(self):
        self.assertEqual(inputmap.char_to_key("A"), (e.KEY_A, True))

    def test_digits_and_symbols(self):
        self.assertEqual(inputmap.char_to_key("5"), (e.KEY_5, False))
        self.assertEqual(inputmap.char_to_key("!"), (e.KEY_1, True))
        self.assertEqual(inputmap.char_to_key("?"), (e.KEY_SLASH, True))
        self.assertEqual(inputmap.char_to_key("."), (e.KEY_DOT, False))

    def test_whitespace(self):
        self.assertEqual(inputmap.char_to_key(" "), (e.KEY_SPACE, False))
        self.assertEqual(inputmap.char_to_key("\n"), (e.KEY_ENTER, False))

    def test_characters_outside_us_layout_are_ignored(self):
        for ch in "çãé€😀":
            self.assertIsNone(inputmap.char_to_key(ch), ch)

    def test_multi_character_string_is_rejected(self):
        self.assertIsNone(inputmap.char_to_key("ab"))

    def test_every_mapped_key_is_declared_to_uinput(self):
        declared = set(inputmap.all_keyboard_codes())
        for ch in "abcXYZ019 !@#$%^&*()_+{}|:\"~<>?-=[]\;',./`\n\t":
            self.assertIn(inputmap.char_to_key(ch)[0], declared, ch)
        self.assertTrue(set(inputmap.NAMED_KEYS.values()) <= declared)
        self.assertTrue(set(inputmap.MODIFIERS.values()) <= declared)


class FakeUInput:
    instances = []

    def __init__(self, caps, name="?", **kw):
        self.name, self.caps, self.events = name, caps, []
        FakeUInput.instances.append(self)

    def write(self, etype, code, value):
        self.events.append((etype, code, value))

    def syn(self):
        pass


class ServerLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("RETROPAD_LOG", "/tmp/retropad-test.log")
        import server
        cls.server = server

    def setUp(self):
        s = self.server
        FakeUInput.instances.clear()
        s.UInput = FakeUInput
        s.pads.clear(); s.state.clear(); s.touchpad.clear()

    def keys(self, dev):
        return [(c, v) for t, c, v in dev.events if t == e.EV_KEY]

    def test_type_text_uses_shift_and_backspace(self):
        s = self.server
        s.type_text(1, "Hi!")
        ev = self.keys(s.touchpad["kbd"])
        self.assertEqual(ev[:2], [(e.KEY_BACKSPACE, 1), (e.KEY_BACKSPACE, 0)])
        self.assertIn((e.KEY_LEFTSHIFT, 1), ev)
        self.assertIn((e.KEY_H, 1), ev)
        self.assertIn((e.KEY_1, 1), ev)   # "!" = Shift + 1
        # todo Shift apertado é solto
        self.assertEqual(ev.count((e.KEY_LEFTSHIFT, 1)), ev.count((e.KEY_LEFTSHIFT, 0)))

    def test_ctrl_combination(self):
        s = self.server
        s.type_text(0, "c", ["ctrl"])
        ev = self.keys(s.touchpad["kbd"])
        self.assertEqual(ev, [(e.KEY_LEFTCTRL, 1), (e.KEY_C, 1), (e.KEY_C, 0), (e.KEY_LEFTCTRL, 0)])

    def test_unknown_character_types_nothing(self):
        s = self.server
        s.type_text(0, "ç")
        self.assertEqual(self.keys(s.touchpad["kbd"]), [])

    def test_text_and_backspace_are_capped(self):
        s = self.server
        s.type_text(10**6, "a" * 10**6)
        ev = self.keys(s.touchpad["kbd"])
        self.assertLessEqual(len(ev), 2 * (s.MAX_TEXT * 2))

    def test_named_key_and_unknown_key(self):
        s = self.server
        s.key_tap("f5")
        s.key_tap("not-a-key")
        self.assertEqual(self.keys(s.touchpad["kbd"]), [(e.KEY_F5, 1), (e.KEY_F5, 0)])

    def test_mouse_move_scroll_click(self):
        s = self.server
        s.mouse_move(10, -5)
        s.mouse_scroll(-2)
        s.mouse_button("left", True)
        s.mouse_button("left", False)
        s.mouse_button("bogus", True)
        dev = s.touchpad["mouse"]
        self.assertIn((e.EV_REL, e.REL_X, 10), dev.events)
        self.assertIn((e.EV_REL, e.REL_Y, -5), dev.events)
        self.assertIn((e.EV_REL, e.REL_WHEEL, -2), dev.events)
        self.assertEqual(self.keys(dev), [(e.BTN_LEFT, 1), (e.BTN_LEFT, 0)])

    def test_mouse_move_is_clamped(self):
        s = self.server
        s.mouse_move(10**6, 0)
        self.assertIn((e.EV_REL, e.REL_X, s.MAX_REL), s.touchpad["mouse"].events)

    def test_gamepad_has_no_keyboard_keys(self):
        s = self.server
        s.get_pad(1)
        keys = set(FakeUInput.instances[0].caps[e.EV_KEY])
        self.assertNotIn(e.KEY_A, keys)
        self.assertIn(e.BTN_TL2, keys)

    def test_gamepad_axes_and_release(self):
        s = self.server
        s.apply_state(1, ["a", "l2", "bogus"], (1, 0), {"x": 1.0, "ry": -0.5})
        dev = s.pads[1]
        self.assertIn((e.EV_ABS, e.ABS_X, 32767), dev.events)
        self.assertIn((e.EV_ABS, e.ABS_RY, int(-0.5 * 32767)), dev.events)
        self.assertIn((e.EV_KEY, e.BTN_TL2, 1), dev.events)
        s.release(1)
        self.assertIn((e.EV_KEY, e.BTN_SOUTH, 0), dev.events)
        self.assertIn((e.EV_ABS, e.ABS_X, 0), dev.events)
        self.assertEqual(s.state[1]["buttons"], set())


if __name__ == "__main__":
    unittest.main()
