from __future__ import annotations

import unittest

import pandas as pd

from eda.interjection_filter import (
    filter_reaction_interjections,
    is_reaction_interjection,
    normalize_interjection_text,
)


class InterjectionFilterTests(unittest.TestCase):
    def test_keeps_reaction_interjections(self) -> None:
        examples = [
            '\\"" ( Applaudissements sur divers bancs. ) \\""',
            '\\"" ( Sourires. ) \\""',
            '\\"" ( Rires et applaudissements sur de nombreux bancs. ) \\""',
            '\\"" ( Murmures sur les bancs du groupe. ) \\""',
            '\\"" ( Protestations sur quelques bancs. ) \\""',
            '\\"" ( \\"" Très bien! \\"" sur plusieurs bancs. ) \\""',
            '\\"" ( Mmes et MM. les députés se lèvent et applaudissent. ) \\""',
        ]

        for text in examples:
            with self.subTest(text=text):
                self.assertTrue(is_reaction_interjection(text))

    def test_rejects_structural_false_positives(self) -> None:
        examples = [
            '\\"" TAUX DE CONVERSION DE L\\\' EURO \\""',
            '\\"" AIDE À DOMICILE \\""',
            '\\"" ( n o 88 ) \\""',
            '\\"" ( rapport n o 1058 ) \\""',
            '\\"" ( La séance est levée à dix heures dix. ) \\""',
            '\\"" Exception d\\\' irrecevabilité \\""',
            '\\"" CTE? \\""',
        ]

        for text in examples:
            with self.subTest(text=text):
                self.assertFalse(is_reaction_interjection(text))

    def test_filter_reaction_interjections_uses_flag_and_text(self) -> None:
        frame = pd.DataFrame(
            {
                "interjection": [True, True, False, True],
                "text": [
                    '\\"" ( Sourires. ) \\""',
                    '\\"" AIDE À DOMICILE \\""',
                    '\\"" ( Applaudissements. ) \\""',
                    '\\"" ( n o 88 ) \\""',
                ],
            }
        )

        filtered = filter_reaction_interjections(frame)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(
            normalize_interjection_text(filtered.iloc[0]["text"]),
            "( Sourires. )",
        )


if __name__ == "__main__":
    unittest.main()
