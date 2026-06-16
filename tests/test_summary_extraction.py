from __future__ import annotations

import unittest

from eda.summary_extraction import (
    detect_summary_zone,
    extract_body_heading_structure,
    extract_official_summary_structure,
    normalize_ocr_text,
    repair_wrapped_summary_lines,
    split_accidentally_merged_major_topics,
)


class SummaryExtractionTests(unittest.TestCase):
    def _topics(self, text: str) -> list[tuple[str, str | None]]:
        frame = extract_official_summary_structure(text)
        return list(zip(frame["major_topic"], frame["subtopic"]))

    def test_pdf_100_uses_official_summary_not_body_headings(self) -> None:
        text = """
        99E SÉANCE
        SOMMAIRE
        1 ORDRE DU JOUR DES PROCHAINES SÉANCES
        COMPTE RENDU INTÉGRAL
        100E SÉANCE
        SOMMAIRE
        1 LOI DE FINANCEMENT DE LA SÉCURITÉ SOCIALE POUR 1999 34
        2 ORDRE DU JOUR DES PROCHAINES SÉANCES 78
        COMPTE RENDU INTÉGRAL
        PRÉSIDENCE DE M. LAURENT FABIUS
        TITRE Ier
        ORIENTATIONS ET OBJECTIFS DE LA POLITIQUE DE SANTÉ ET DE SÉCURITÉ SOCIALE
        """

        frame = extract_official_summary_structure(text, target_session_number=100)
        topics = list(zip(frame["major_topic"], frame["subtopic"]))

        self.assertIn(("LOI DE FINANCEMENT DE LA SÉCURITÉ SOCIALE POUR 1999", None), topics)
        self.assertIn(("ORDRE DU JOUR DES PROCHAINES SÉANCES", None), topics)
        self.assertNotIn(("LOI DE FINANCEMENT DE LA SÉCURITÉ SOCIALE POUR 1999", "TITRE Ier"), topics)
        self.assertFalse(
            any(
                subtopic == "ORIENTATIONS ET OBJECTIFS DE LA POLITIQUE DE SANTÉ ET DE SÉCURITÉ SOCIALE"
                for _, subtopic in topics
            )
        )

    def test_pdf_103_repairs_wrapped_questions_and_quotes(self) -> None:
        text = '''
        SOMMAIRE
        1 QUESTIONS ORALES SANS DÉBAT
        AMÉNAGEMENT DE LA RN 51
        ENTRE EPERNAY ET REIMS
        ABROGATION DE LA LOI QUINQUENNALE DE 1993
        RELATIVE AU TRAVAIL, À L'EMPLOI ET À LA FORMATION PROFESSIONNELLE
        MISE EN LIQUIDATION JUDICIAIRE DE L'ASSOCIATION NATIONALE DES ANCIENS DES MAQUIS DE L'AIN ET DU HAUT JURA
        \\"""" ARTICLE 515-3 DU CODE CIVIL \\""""
        2 ORDRE DU JOUR DE LA PROCHAINE SÉANCE
        PRÉSIDENCE DE M. LE PRÉSIDENT
        '''

        frame = extract_official_summary_structure(text)
        questions = frame[frame["major_topic"].eq("QUESTIONS ORALES SANS DÉBAT")]
        subtopics = set(questions["subtopic"].dropna())

        self.assertIn("AMÉNAGEMENT DE LA RN 51 ENTRE ÉPERNAY ET REIMS", subtopics)
        self.assertIn(
            "ABROGATION DE LA LOI QUINQUENNALE DE 1993 RELATIVE AU TRAVAIL, À L'EMPLOI ET À LA FORMATION PROFESSIONNELLE",
            subtopics,
        )
        self.assertIn(
            "MISE EN LIQUIDATION JUDICIAIRE DE L'ASSOCIATION NATIONALE DES ANCIENS DES MAQUIS DE L'AIN ET DU HAUT JURA",
            subtopics,
        )
        self.assertIn("ARTICLE 515-3 DU CODE CIVIL", subtopics)
        self.assertTrue((questions["major_topic_order"] == 1).all())

    def test_pdf_106_splits_merged_entries_and_filters_body_table_heading(self) -> None:
        text = """
        SOMMAIRE
        1 QUESTIONS AU GOUVERNEMENT
        RE ´ FORME DE L'AUDIOVISUEL
        2 PACTE CIVIL DE SOLIDARITÉ
        4,FAIT PERSONNEL,) 5 ORDRE DU JOUR DE LA PROCHAINE SÉANCE
        PRÉSIDENCE DE M. LE PRÉSIDENT
        FRACTION DE LA PART NETTE TAXABLE TARIF APPLICABLE
        """

        topics = self._topics(text)

        self.assertIn(("FAIT PERSONNEL", None), topics)
        self.assertIn(("ORDRE DU JOUR DE LA PROCHAINE SÉANCE", None), topics)
        self.assertIn(("QUESTIONS AU GOUVERNEMENT", "RÉFORME DE L'AUDIOVISUEL"), topics)
        frame = extract_official_summary_structure(text)
        major_by_order = dict(
            zip(
                frame.loc[frame["structure_level"].eq("major_topic"), "major_topic_order"],
                frame.loc[frame["structure_level"].eq("major_topic"), "major_topic"],
            )
        )
        self.assertEqual(major_by_order[4], "FAIT PERSONNEL")
        self.assertEqual(major_by_order[5], "ORDRE DU JOUR DE LA PROCHAINE SÉANCE")

        with self.assertLogs("eda.summary_extraction", level="WARNING"):
            body = extract_body_heading_structure(
                ["1 PACTE CIVIL DE SOLIDARITÉ", "FRACTION DE LA PART NETTE TAXABLE TARIF APPLICABLE"]
            )
        self.assertFalse(body["subtopic"].eq("FRACTION DE LA PART NETTE TAXABLE TARIF APPLICABLE").any())

    def test_low_level_ocr_and_line_repair_helpers(self) -> None:
        self.assertEqual(normalize_ocr_text("RE ´ FORME DE L'AUDIOVISUEL"), "RÉFORME DE L'AUDIOVISUEL")
        self.assertEqual(normalize_ocr_text("E´PERNAY"), "ÉPERNAY")
        self.assertEqual(normalize_ocr_text("PRE´SIDENCE"), "PRÉSIDENCE")
        self.assertEqual(normalize_ocr_text("WA ¨ RTSILA ¨"), "WÄRTSILÄ")
        self.assertEqual(
            split_accidentally_merged_major_topics("4,FAIT PERSONNEL,) 5 ORDRE DU JOUR DE LA PROCHAINE SÉANCE"),
            ["4,FAIT PERSONNEL,", "5 ORDRE DU JOUR DE LA PROCHAINE SÉANCE"],
        )
        self.assertEqual(
            repair_wrapped_summary_lines(["AMÉNAGEMENT DE LA RN 51", "ENTRE EPERNAY ET REIMS"]),
            ["AMÉNAGEMENT DE LA RN 51 ENTRE ÉPERNAY ET REIMS"],
        )

    def test_filters_false_summary_subtopics_with_warning(self) -> None:
        text = """
        SOMMAIRE
        1 LOI DE FINANCEMENT DE LA SÉCURITÉ SOCIALE POUR 1999
        TITRE I er
        ORIENTATIONS ET OBJECTIFS DE LA POLITIQUE DE SANTÉ ET DE SÉCURITÉ SOCIALE
        FRACTION DE LA PART NETTE TAXABLE TARIF APPLICABLE
        ARTICLE 515-8 DU CODE CIVIL
        COMPTE RENDU INTÉGRAL
        """

        with self.assertLogs("eda.summary_extraction", level="WARNING") as logs:
            frame = extract_official_summary_structure(text)

        subtopics = set(frame["subtopic"].dropna())
        self.assertNotIn("TITRE Ier", subtopics)
        self.assertFalse(any(item.startswith("ORIENTATIONS ET OBJECTIFS") for item in subtopics))
        self.assertNotIn("FRACTION DE LA PART NETTE TAXABLE TARIF APPLICABLE", subtopics)
        self.assertIn("ARTICLE 515-8 DU CODE CIVIL", subtopics)
        self.assertTrue(any("Filtered false summary subtopic" in line for line in logs.output))

    def test_detect_summary_zone_can_target_session_number(self) -> None:
        text = """
        99E SÉANCE
        SOMMAIRE
        1 MAUVAISE SÉANCE
        COMPTE RENDU INTÉGRAL
        103E SÉANCE
        SOMMAIRE
        1 QUESTIONS ORALES SANS DÉBAT
        COMPTE RENDU INTÉGRAL
        """

        self.assertEqual(
            detect_summary_zone(text, target_session_number=103),
            ["1 QUESTIONS ORALES SANS DÉBAT"],
        )


if __name__ == "__main__":
    unittest.main()
