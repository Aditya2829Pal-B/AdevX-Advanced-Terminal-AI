from __future__ import annotations

import unittest

from adevx.providers.http_compat import _extract_text, _map_role


class HttpCompatHelpersTests(unittest.TestCase):
    def test_map_role_developer_to_system(self) -> None:
        self.assertEqual(_map_role("developer"), "system")
        self.assertEqual(_map_role("user"), "user")

    def test_extract_text_from_string(self) -> None:
        self.assertEqual(_extract_text("hello"), "hello")

    def test_extract_text_from_parts(self) -> None:
        payload = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
        self.assertEqual(_extract_text(payload), "hello\nworld")


if __name__ == "__main__":
    unittest.main()

