from __future__ import annotations

import unittest

from converter.convert import _clean_text


class ConverterCleaningTest(unittest.TestCase):
    def test_c1_control_characters_are_normalized_as_spaces(self) -> None:
        examples = {
            "M. Antoine Léaument. Très bon sujet!": "M. Antoine Léaument. Très bon sujet !",
            "M. Antoine Léaument. C’est vrai!": "M. Antoine Léaument. C’est vrai !",
            "Quel est l’avis du Gouvernement?": "Quel est l’avis du Gouvernement ?",
            "en janvier2009": "en janvier 2009",
            "décédé– et il faut": "décédé – et il faut",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(_clean_text(source), expected)


if __name__ == "__main__":
    unittest.main()
