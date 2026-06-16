from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from converter import json_to_csv
from import_data.main import enrich_converted_with_num_seance


class NumSeancePipelineTest(unittest.TestCase):
    def test_num_seance_is_copied_from_raw_to_converted_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_dir = root / "raw" / "2026"
            converted_dir = root / "converted" / "2026" / "AN_20260123_011"
            raw_dir.mkdir(parents=True)
            converted_dir.mkdir(parents=True)

            (raw_dir / "CRI_20260123_011.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<PublicationDANBlanc>
  <CompteRendu>
    <Metadonnees>
      <dateSeance>2026-01-22</dateSeance>
      <numSeance>121</numSeance>
    </Metadonnees>
  </CompteRendu>
</PublicationDANBlanc>
""",
                encoding="utf-8",
            )
            speech_json = converted_dir / "speech_text_2026-01-22.json"
            speech_json.write_text(
                json.dumps(
                    {
                        "source_files": ["CRI_20260123_011.xml"],
                        "dateSeance": "2026-01-22",
                        "Para": [
                            {
                                "Ident": "p1",
                                "Para": "Texte.",
                                "Para_clean": "Texte.",
                                "Orateur": [
                                    {
                                        "attributes": {"href": "http://example.test/a"},
                                        "Nom": "Alice",
                                        "gender": "F",
                                    },
                                    {
                                        "attributes": {"href": "http://example.test/b"},
                                        "Nom": "Bob",
                                        "gender": "M",
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(enrich_converted_with_num_seance(raw_dir, converted_dir), 1)
            self.assertEqual(json.loads(speech_json.read_text(encoding="utf-8"))["numSeance"], "121")

            csv_file = root / "centralized_speeches.csv"
            json_to_csv.write_csv(json_to_csv.iter_rows(converted_dir), csv_file)
            with csv_file.open(encoding="utf-8") as input_file:
                reader = csv.DictReader(input_file)
                rows = list(reader)
                fieldnames = reader.fieldnames

            self.assertEqual(rows[0]["numSeance"], "121")
            self.assertEqual(rows[0]["speaker"], "Alice;Bob")
            self.assertEqual(rows[0]["link_speaker"], "http://example.test/a;http://example.test/b")
            self.assertEqual(rows[0]["gender"], "F;M")
            self.assertEqual(fieldnames[-1], "numSeance")


if __name__ == "__main__":
    unittest.main()
