from __future__ import annotations

import unittest

import pandas as pd

from eda.speech_grouping import group_consecutive_speeches


class SpeechGroupingTests(unittest.TestCase):
    def test_groups_consecutive_speaker_rows_and_attaches_interjections(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "id": 1,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": False,
                    "text": '\\"" Première phrase. \\""',
                },
                {
                    "id": 2,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": False,
                    "text": '\\"" Deuxième phrase. \\""',
                },
                {
                    "id": 3,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": True,
                    "text": '\\"" ( Applaudissements. ) \\""',
                },
                {
                    "id": 4,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": False,
                    "text": '\\"" Troisième phrase. \\""',
                },
                {
                    "id": 5,
                    "speaker": "B",
                    "role": "gov",
                    "interjection": False,
                    "text": '\\"" Réponse. \\""',
                },
            ]
        )

        grouped = group_consecutive_speeches(frame)

        self.assertEqual(grouped["speech_order"].tolist(), [1, 2])
        self.assertEqual(
            grouped.loc[0, "speech_text"],
            "Première phrase. Deuxième phrase. Troisième phrase.",
        )
        self.assertEqual(grouped.loc[0, "interjections"], ["( Applaudissements. )"])
        self.assertEqual(grouped.loc[0, "source_row_orders"], [1, 2, 3, 4])
        self.assertEqual(grouped.loc[1, "speech_text"], "Réponse.")

    def test_false_positive_interjection_stays_in_speech_text(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "id": 1,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": False,
                    "text": '\\"" Intro. \\""',
                },
                {
                    "id": 2,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": True,
                    "text": '\\"" AIDE À DOMICILE \\""',
                },
            ]
        )

        grouped = group_consecutive_speeches(frame)

        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped.loc[0, "speech_text"], "Intro. AIDE À DOMICILE")
        self.assertEqual(grouped.loc[0, "interjections"], [])

    def test_reaction_before_any_speech_gets_ordered_row(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "id": 1,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": True,
                    "text": '\\"" ( Sourires. ) \\""',
                },
                {
                    "id": 2,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": False,
                    "text": '\\"" Début. \\""',
                },
            ]
        )

        grouped = group_consecutive_speeches(frame)

        self.assertEqual(grouped["speech_order"].tolist(), [1])
        self.assertEqual(grouped.loc[0, "speech_text"], "Début.")
        self.assertEqual(grouped.loc[0, "interjections"], ["( Sourires. )"])
        self.assertEqual(grouped.loc[0, "source_row_orders"], [1, 2])

    def test_uses_existing_source_order_column(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "row_order": 10,
                    "id": 1,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": False,
                    "text": "Bonjour.",
                },
                {
                    "row_order": 20,
                    "id": 2,
                    "speaker": "A",
                    "role": "mp",
                    "interjection": True,
                    "text": "( Applaudissements. )",
                },
            ]
        )

        grouped = group_consecutive_speeches(frame, source_order_col="row_order")

        self.assertEqual(grouped.loc[0, "source_row_orders"], [10, 20])
        self.assertEqual(grouped.loc[0, "first_row_order"], 10)
        self.assertEqual(grouped.loc[0, "last_row_order"], 20)

    def test_structure_rows_are_separate_procedures(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "row_order": 1,
                    "id": 1,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": False,
                    "structure_level": "speech",
                    "text": "La séance est ouverte.",
                },
                {
                    "row_order": 2,
                    "id": 2,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": False,
                    "structure_level": "major_topic",
                    "major_topic_order": 2,
                    "major_topic": "QUESTIONS AU GOUVERNEMENT",
                    "text": "2 QUESTIONS à le GOUVERNEMENT",
                },
                {
                    "row_order": 3,
                    "id": 3,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": True,
                    "structure_level": "subtopic",
                    "major_topic_order": 2,
                    "major_topic": "QUESTIONS AU GOUVERNEMENT",
                    "subtopic": "TAUX DE CONVERSION DE L'EURO",
                    "text": "TAUX DE CONVERSION DE L' EURO",
                },
                {
                    "row_order": 4,
                    "id": 4,
                    "speaker": "le président",
                    "role": "presidency",
                    "interjection": False,
                    "structure_level": "speech",
                    "major_topic_order": 2,
                    "major_topic": "QUESTIONS AU GOUVERNEMENT",
                    "subtopic": "TAUX DE CONVERSION DE L'EURO",
                    "text": "La parole est à M. X.",
                },
            ]
        )

        grouped = group_consecutive_speeches(
            frame,
            source_order_col="row_order",
            procedure_col="structure_level",
        )

        self.assertEqual(grouped["speech_order"].tolist(), [1, 2, 3, 4])
        self.assertEqual(grouped["row_type"].tolist(), ["speech", "procedure", "procedure", "speech"])
        self.assertEqual(grouped.loc[0, "speech_text"], "La séance est ouverte.")
        self.assertEqual(grouped.loc[1, "procedure_type"], "major_topic")
        self.assertEqual(grouped.loc[1, "major_topic_order"], 2)
        self.assertEqual(grouped.loc[1, "major_topic"], "QUESTIONS AU GOUVERNEMENT")
        self.assertIsNone(grouped.loc[1, "subtopic"])
        self.assertEqual(grouped.loc[1, "speech_text"], "QUESTIONS AU GOUVERNEMENT")
        self.assertEqual(grouped.loc[2, "procedure_type"], "subtopic")
        self.assertEqual(grouped.loc[2, "major_topic_order"], 2)
        self.assertEqual(grouped.loc[2, "major_topic"], "QUESTIONS AU GOUVERNEMENT")
        self.assertEqual(grouped.loc[2, "subtopic"], "TAUX DE CONVERSION DE L'EURO")
        self.assertEqual(grouped.loc[2, "speech_text"], "TAUX DE CONVERSION DE L'EURO")
        self.assertEqual(grouped.loc[3, "major_topic_order"], 2)
        self.assertEqual(grouped.loc[3, "major_topic"], "QUESTIONS AU GOUVERNEMENT")
        self.assertEqual(grouped.loc[3, "subtopic"], "TAUX DE CONVERSION DE L'EURO")
        self.assertEqual(grouped.loc[3, "speech_text"], "La parole est à M. X.")


if __name__ == "__main__":
    unittest.main()
