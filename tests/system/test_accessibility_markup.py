"""Static guards for the Milestone 4 accessibility corrections (WCAG 2.1 AA). The pages were audited in a browser
(contrast of every visible text, labels, accessible names, keyboard access); these tests keep the fixes in place."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
DASHBOARD_CSS = (ROOT / "static" / "dashboard.css").read_text(encoding="utf-8")
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def css_var(css: str, name: str) -> str:
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", css).group(1)


class ContrastTests(unittest.TestCase):
    """Text colours against the lightest backgrounds they are drawn on must reach 4.5:1 (AA, normal text)."""

    def test_dashboard_text_colours(self):
        backgrounds = ["#ffffff", css_var(DASHBOARD_CSS, "bg"), "#fcebf0"]
        for name in ("ink", "muted", "high", "medium", "low"):
            for background in backgrounds:
                with self.subTest(colour=name, background=background):
                    self.assertGreaterEqual(contrast(css_var(DASHBOARD_CSS, name), background), 4.5)

    def test_admin_text_colours(self):
        pairs = [(css_var(ADMIN, "muted"), "#ffffff"), (css_var(ADMIN, "muted"), "#e8eef8"),
                 ("#ffffff", css_var(ADMIN, "green")), ("#ffffff", css_var(ADMIN, "red")),
                 (css_var(ADMIN, "green"), "#dff3e7"), (css_var(ADMIN, "yellow"), "#fdf0d5")]
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast(foreground, background), 4.5)


class FormAndKeyboardTests(unittest.TestCase):
    def test_every_admin_label_points_to_an_existing_field(self):
        labels = re.findall(r"<label([^>]*)>", ADMIN)
        self.assertGreaterEqual(len(labels), 17)
        for attributes in labels:
            with self.subTest(label=attributes):
                target = re.search(r'for="([^"]+)"', attributes)
                self.assertIsNotNone(target, "label without for=")
                self.assertIn(f'id="{target.group(1)}"', ADMIN)

    def test_field_ids_are_unique(self):
        ids = re.findall(r'\bid="([^"$]+)"', ADMIN)
        self.assertEqual(len(ids), len(set(ids)))

    def test_controls_without_a_visible_label_have_an_accessible_name(self):
        self.assertIn('id="collectionSelect" aria-label=', ADMIN)

    def test_clickable_group_items_are_reachable_and_operable_with_the_keyboard(self):
        for item in re.findall(r"<li [^>]*onclick=[^>]*>", ADMIN):
            with self.subTest(item=item[:60]):
                self.assertIn('tabindex="0"', item)
                self.assertIn('role="button"', item)
                self.assertIn("onkeydown=", item)

    def test_pages_declare_their_language(self):
        for page in (ADMIN, INDEX):
            self.assertRegex(page, r'<html lang="es"')


if __name__ == "__main__":
    unittest.main()
