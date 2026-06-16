from __future__ import annotations

import unittest

import pandas as pd

from eda.entity_binding import (
    bind_entities,
    bind_parties,
    bind_politicians,
    bind_politicians_with_mandates,
    bind_report,
    merge_missing_speaker_rows,
    missing_speaker_merge_report,
)


class EntityBindingTests(unittest.TestCase):
    def test_binds_party_from_group_then_party_fallback_and_legacy_alias(self) -> None:
        party = pd.DataFrame(
            [
                {
                    "party_id": "P008",
                    "acronym": "SOC",
                    "name": "Socialistes et apparentés",
                    "source_political_groups": "['Socialistes et apparentés']",
                    "interjection_aliases": "['SOC']",
                },
                {
                    "party_id": "P038",
                    "acronym": "R-UMP",
                    "name": "Rassemblement - Union pour un Mouvement Populaire",
                    "source_political_groups": "[]",
                    "interjection_aliases": "['R-UMP']",
                },
            ]
        )
        frame = pd.DataFrame(
            {
                "parliamentary_group": ["SOC", None, "RPR", "DL"],
                "party": ["IGNORED", "PS", None, None],
            }
        )

        bound = bind_parties(frame, party)

        self.assertEqual(bound["party_id"].tolist()[:3], ["P008", "P008", "P038"])
        self.assertEqual(bound.loc[0, "party_source_column"], "parliamentary_group")
        self.assertEqual(bound.loc[1, "party_source_column"], "party")
        self.assertEqual(bound.loc[3, "party_bind_status"], "unmatched")

    def test_binds_politician_by_normalized_speaker(self) -> None:
        deputes = pd.DataFrame(
            [
                {
                    "mp_id": "PA1494",
                    "first_name": "Valéry",
                    "last_name": "Giscard d'Estaing",
                }
            ]
        )
        frame = pd.DataFrame({"speaker": ["Valéry Giscard d’Estaing", "le président"]})

        bound = bind_politicians(frame, deputes)

        self.assertEqual(bound.loc[0, "mp_id"], "PA1494")
        self.assertEqual(bound.loc[0, "politician_bind_status"], "matched")
        self.assertEqual(bound.loc[1, "politician_bind_status"], "unmatched")

    def test_binds_politician_from_link_name_and_active_mandate(self) -> None:
        deputes = pd.DataFrame(
            [
                {"mp_id": "PA1790", "first_name": "Marc", "last_name": "Laffineur"},
                {"mp_id": "PA9999", "first_name": "Marc", "last_name": "Laffineur"},
                {
                    "mp_id": "PA773443",
                    "first_name": "Éric",
                    "last_name": "Dupond-Moretti",
                    "status": "GOUVERNEMENT",
                },
            ]
        )
        mandates = pd.DataFrame(
            [
                {
                    "mp_id": "PA1790",
                    "term": "13",
                    "mandate_start": "2007-06-20",
                    "mandate_end": "2012-06-19",
                },
                {
                    "mp_id": "PA9999",
                    "term": "16",
                    "mandate_start": "2022-06-22",
                    "mandate_end": "",
                },
            ]
        )
        frame = pd.DataFrame(
            {
                "speaker": [
                    "Marc Laffineur",
                    "Marc Laffineur",
                    "Éric Dupond-Moretti",
                    "le président",
                ],
                "link_speaker": [
                    "http://www.assemblee-nationale.fr/tribun/fiches_id/1790.asp",
                    "",
                    "",
                    "",
                ],
                "date": ["03-10-2011", "03-10-2011", "08-07-2020", "03-10-2011"],
            }
        )

        bound = bind_politicians_with_mandates(frame, deputes, mandates)

        self.assertEqual(bound.loc[0, "mp_id"], "PA1790")
        self.assertEqual(bound.loc[0, "politician_bind_method"], "link_name_mandate")
        self.assertEqual(bound.loc[1, "mp_id"], "PA1790")
        self.assertEqual(bound.loc[1, "politician_bind_method"], "name_exact_mandate")
        self.assertEqual(bound.loc[2, "mp_id"], "PA773443")
        self.assertEqual(bound.loc[2, "politician_bind_status"], "matched_no_active_mandate")
        self.assertEqual(bound.loc[2, "politician_bind_method"], "name_exact_no_active_mandate")
        self.assertTrue(pd.isna(bound.loc[3, "mp_id"]))
        self.assertEqual(bound.loc[3, "politician_bind_status"], "president")

    def test_binds_manual_speaker_aliases(self) -> None:
        deputes = pd.DataFrame(
            [
                {"mp_id": "PA793382", "first_name": "Emmanuel", "last_name": "Taché"},
                {"mp_id": "PA720046", "first_name": "Audrey", "last_name": "Dufeu"},
            ]
        )
        mandates = pd.DataFrame(
            [
                {
                    "mp_id": "PA793382",
                    "term": "16",
                    "mandate_start": "2022-06-22",
                    "mandate_end": "2024-06-09",
                },
                {
                    "mp_id": "PA720046",
                    "term": "15",
                    "mandate_start": "2017-06-21",
                    "mandate_end": "2022-06-21",
                },
            ]
        )
        frame = pd.DataFrame(
            {
                "speaker": [
                    "M. Emmanuel Taché de la Pagerie.",
                    "Mme Audrey Dufeu Schubert.",
                ],
                "link_speaker": ["", ""],
                "date": ["01-02-2023", "01-02-2020"],
            }
        )

        bound = bind_politicians_with_mandates(frame, deputes, mandates)

        self.assertEqual(bound.loc[0, "mp_id"], "PA793382")
        self.assertEqual(bound.loc[0, "politician_bind_method"], "manual_alias_mandate")
        self.assertEqual(bound.loc[1, "mp_id"], "PA720046")
        self.assertEqual(bound.loc[1, "politician_bind_method"], "manual_alias_mandate")

    def test_uses_source_files_date_when_date_column_is_missing(self) -> None:
        deputes = pd.DataFrame(
            [{"mp_id": "PA335159", "first_name": "Lionel", "last_name": "Tardy"}]
        )
        mandates = pd.DataFrame(
            [
                {
                    "mp_id": "PA335159",
                    "term": "14",
                    "mandate_start": "2012-06-20",
                    "mandate_end": "2017-06-20",
                }
            ]
        )
        frame = pd.DataFrame(
            {
                "speaker": ["M. Lionel Tardy."],
                "link_speaker": [
                    "http://www.assemblee-nationale.fr/14/tribun/fiches_id/335159.asp"
                ],
                "date": [pd.NA],
                "source_files": ["AAA_20121002_051.xml;CRI_20121002_051.xml"],
            }
        )

        bound = bind_politicians_with_mandates(frame, deputes, mandates)

        self.assertEqual(bound.loc[0, "mp_id"], "PA335159")
        self.assertEqual(bound.loc[0, "politician_date_source"], "source_files")

    def test_bind_report_counts_failures(self) -> None:
        party = pd.DataFrame([{"party_id": "P008", "acronym": "SOC", "name": "SOC"}])
        deputes = pd.DataFrame(
            [{"mp_id": "PA1", "first_name": "Jane", "last_name": "Doe"}]
        )
        frame = pd.DataFrame(
            {
                "parliamentary_group": ["SOC", "DL"],
                "party": [None, None],
                "speaker": ["Jane Doe", "Unknown Speaker"],
            }
        )

        reports = bind_report(bind_entities(frame, party, deputes))

        self.assertEqual(set(reports), {
            "party_rows",
            "party_unmatched_labels",
            "politician_rows",
            "politician_unmatched_speakers",
        })
        self.assertEqual(reports["party_unmatched_labels"].loc[0, "party_source_label"], "DL")
        self.assertEqual(
            reports["politician_unmatched_speakers"].loc[0, "speaker"],
            "Unknown Speaker",
        )

    def test_merges_missing_speaker_rows_with_audit(self) -> None:
        frame = pd.DataFrame(
            {
                "id": ["a1", "a2", "a3", "b1", "b2"],
                "source_files": ["s1", "s1", "s1", "s1", "s2"],
                "date": ["01-01-2020", "01-01-2020", "01-01-2020", "01-01-2020", "02-01-2020"],
                "numSeance": ["1", "1", "1", "1", "2"],
                "speaker": ["Alice Doe", pd.NA, pd.NA, "Bob Doe", pd.NA],
                "text_speech_clean": [
                    "Alice starts.",
                    "Alice continues.",
                    "M. Other Speaker, should not merge.",
                    "Bob starts.",
                    "Different session.",
                ],
                "text_speech_brut": [
                    "Alice starts raw.",
                    "Alice continues raw.",
                    "M. Other Speaker, should not merge raw.",
                    "Bob starts raw.",
                    "Different session raw.",
                ],
                "politician_bind_status": [
                    "matched",
                    "missing_speaker",
                    "missing_speaker",
                    "matched",
                    "missing_speaker",
                ],
                "mp_id": ["PA1", pd.NA, pd.NA, "PA2", pd.NA],
            }
        )

        compacted, audit = merge_missing_speaker_rows(frame)
        report = missing_speaker_merge_report(frame, compacted, audit)

        self.assertEqual(len(compacted), 4)
        self.assertIn("Alice continues.", compacted.loc[0, "text_speech_clean"])
        self.assertEqual(compacted.loc[0, "merged_missing_speaker_rows"], 1)
        self.assertEqual(compacted.loc[0, "merged_missing_speaker_ids"], "a2")
        self.assertIn("a3", compacted["id"].tolist())
        self.assertIn("b2", compacted["id"].tolist())
        self.assertEqual(
            audit.loc[audit["source_id"].eq("a3"), "status"].item(),
            "blocked_text_starts_with_speaker_marker",
        )
        self.assertEqual(
            audit.loc[audit["source_id"].eq("b2"), "status"].item(),
            "blocked_boundary_mismatch",
        )
        self.assertTrue(report["text_char_check_pass"])


if __name__ == "__main__":
    unittest.main()
