import unittest
from pathlib import Path
from unittest.mock import patch

from convert_acteurs_to_csv import (
    DeputyLink,
    ScrapedDeputy,
    ScrapedMandate,
    augment_from_sycomore,
    generated_sycomore_pa_id,
)


class ConvertActeursToCsvTest(unittest.TestCase):
    def test_generated_sycomore_pa_id_does_not_use_raw_sycomore_pa_id(self) -> None:
        self.assertEqual(generated_sycomore_pa_id("1566", set()), "PA9001566")
        self.assertEqual(
            generated_sycomore_pa_id("1566", {"PA9001566"}),
            "PA9001566001",
        )

    def test_sycomore_fallback_collision_adds_distinct_politician(self) -> None:
        politicians = [
            {
                "mp_id": "PA1566",
                "first_name": "Arnaud Cazin",
                "last_name": "d'Honincthun",
                "birth_date": "1949-01-26",
                "birth_place": "New-york (Usa)",
                "education_level": "",
                "school": "",
                "academic_title": "",
                "profession": "",
                "languages": "",
                "seniority": "",
                "status": "ASSEMBLEE",
                "country_id": "3",
            }
        ]
        mandates = []
        deputy = ScrapedDeputy(
            sycomore_id="1566",
            url="https://www2.assemblee-nationale.fr/sycomore/fiche/1566?legislature=58",
            pa_id="",
            full_name="Nicole Catala",
            birth_date="1936-02-02",
            birth_place="",
            mandates=[
                ScrapedMandate(
                    term="11",
                    start="1997-06-01",
                    end="2002-06-18",
                    constituency="Paris",
                    club="Rassemblement pour la République",
                )
            ],
        )

        with patch(
            "convert_acteurs_to_csv.collect_deputy_links",
            return_value=[DeputyLink("Nicole Catala", deputy.url, "1566")],
        ), patch("convert_acteurs_to_csv.fetch", return_value=""), patch(
            "convert_acteurs_to_csv.parse_deputy",
            return_value=deputy,
        ):
            updated_politicians, updated_mandates, reports = augment_from_sycomore(
                politicians,
                mandates,
                {"Rassemblement pour la République": "P004"},
                [11],
                Path("/tmp"),
                0,
                False,
                "3",
            )

        by_id = {row["mp_id"]: row for row in updated_politicians}
        self.assertEqual(by_id["PA1566"]["first_name"], "Arnaud Cazin")
        self.assertIn("PA9001566", by_id)
        self.assertEqual(by_id["PA9001566"]["first_name"], "Nicole")
        self.assertEqual(updated_mandates[0]["mp_id"], "PA9001566")
        self.assertEqual(reports["fallback_pa_ids.csv"][0]["mp_id"], "PA9001566")


if __name__ == "__main__":
    unittest.main()
