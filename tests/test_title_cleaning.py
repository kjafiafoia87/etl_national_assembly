from __future__ import annotations

import unittest

from eda.title_cleaning import clean_title, is_uppercase_title


class TitleCleaningTests(unittest.TestCase):
    def test_cleans_major_topic_examples(self) -> None:
        examples = {
            "SOUHAITS DE BIENVENUE à les PRÉSIDENTS D' ASSEMBLÉES PARLEMENTAIRES D' AFRIQUE": (
                "SOUHAITS DE BIENVENUE AUX PRÉSIDENTS D'ASSEMBLÉES PARLEMENTAIRES D'AFRIQUE"
            ),
            "QUESTIONS à le GOUVERNEMENT": "QUESTIONS AU GOUVERNEMENT",
            "ORDRE de le JOUR": "ORDRE DU JOUR",
            "MODIFICATION DE L' ORDRE de le JOUR": "MODIFICATION DE L'ORDRE DU JOUR",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(clean_title(source), expected)

    def test_uppercase_title_stays_uppercase(self) -> None:
        cleaned = clean_title("COMMUNICATION RELATIVE à les ASSEMBLÉES TERRITORIALES")

        self.assertEqual(cleaned, "COMMUNICATION RELATIVE AUX ASSEMBLÉES TERRITORIALES")
        self.assertTrue(is_uppercase_title(cleaned))
        self.assertNotRegex(cleaned, r"\b(aux|au|du|des)\b")

    def test_normal_case_title_stays_normal_case(self) -> None:
        self.assertEqual(
            clean_title("Questions à le Gouvernement"),
            "Questions au Gouvernement",
        )

    def test_uppercase_source_sequence_forces_uppercase_replacement(self) -> None:
        self.assertEqual(clean_title("Question À LES MINISTRES"), "Question AUX MINISTRES")

    def test_does_not_replace_inside_words(self) -> None:
        self.assertEqual(clean_title("PALÀ LESSONS D' HISTOIRE"), "PALÀ LESSONS D'HISTOIRE")

    def test_clean_title_is_idempotent(self) -> None:
        source = "MODIFICATION DE L' ORDRE de le JOUR"
        once = clean_title(source)

        self.assertEqual(clean_title(once), once)


if __name__ == "__main__":
    unittest.main()
