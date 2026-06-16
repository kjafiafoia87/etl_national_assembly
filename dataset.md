

B) Policorp : Parisparl + offical structure + speech ask Nina
    -  garder num de lignes 
    - garder les procedures et speech etc 

A) Dila gouv OPENDATA


- Speeches from 2011 to 2026:
  https://echanges.dila.gouv.fr/OPENDATA/Debats/AN/

  This is the main official open-data source used for recent French National
  Assembly debates. The files come from DILA, the French government's legal and
  administrative information directorate, and cover Assemblée nationale debate
  records from 2011 onward. Compared with reconstructed corpora, this source is
  more reliable for recent work because it provides the original parliamentary
  XML structure published by the administration.

  The local pipeline is split into three reproducible steps:

  - `converter/download_dila_debats.py` reads the DILA index, detects yearly
    `.taz`, `.tar`, `.tar.gz`, and `.tgz` archives, downloads the requested
    years, and extracts only XML files into `data/speech/2011_2026/raw`. The
    extraction keeps the year/session directory structure and protects against
    unsafe archive paths.
  - `converter/convert.py` parses each `CRI_*.xml` debate file and writes JSON
    documents under `data/speech/2011_2026/converted`. It preserves the paired
    `AAA_*.xml` source file name when present, extracts session metadata such as
    `dateSeance` and `numSeance`, keeps paragraph identifiers, speaker blocks,
    speaker links, roles, and the nested debate structure: section, subtopic 1,
    and subtopic 2.
  - `converter/json_to_csv.py` flattens the converted JSON documents into
    `data/speech/2011_2026/centralized_speeches.csv`, with one row per
    paragraph and stable columns such as `source_files`, `id`, `date`,
    `text_speech_brut`, `text_speech_clean`, `topic`, `subtopic1`,
    `subtopic2`, `speaker`, `link_speaker`, `role`, `gender`,
    `speech_interjection`, `quote`, and `numSeance`.

  The cleaning step is necessary because the source XML is parliamentary
  markup, not an analysis-ready table. Paragraph text can contain nested
  speaker tags, non-breaking spaces, repeated whitespace, procedural titles,
  interruptions, and section headers mixed with spoken content. The converter
  normalizes whitespace and stores a cleaned paragraph text in `Para_clean`,
  while preserving the raw paragraph text in `Para`. It also separates speaker
  metadata from speech text and carries forward the surrounding debate section
  so that each row can later be linked to topics and subtopics.

  Additional cleaning and exploratory analysis are handled in `eda/`, including
  title normalization, summary extraction, interjection filtering, consecutive
  speech grouping, and entity binding. The notebook `eda/data_analysis.ipynb`
  uses the centralized DILA data to explore how parliamentary groups and
  parties react to specific topics, including positive, negative, or neutral
  reactions and interruptions during debates.

  Typical commands:

  ```bash
  python3 main.py download --years 2011-2026
  python3 main.py convert
  python3 main.py csv
  ```

  Or run the complete DILA pipeline with existing defaults:

  ```bash
  python3 main.py all --years 2011-2026
  ```

B) Full Parisparl

1. Parisparl source:
https://zenodo.org/records/3819374
"The ParisParl Corpus of Parliamentary Debates, prepared in the PolMine Project, comprises all protocols of plenary sessions in the French Assemblée nationale between 1996 and 2019. The corpus is built based on pdf documents issued by the Assemblée nationale."

ParisParl is the historical source used to extend the speech corpus before the
DILA open-data period. It was produced in the PolMine project from official PDF
debate reports of the French Assemblée nationale. The source is especially
useful because it gives access to older plenary debates that are not available
in the same structured DILA XML format.

After exchanges with the University of Duisburg team that worked on this corpus
for several European parliaments, the original tabular dataset was no longer
available. However, the encoded Corpus Workbench (CWB) version was still
recoverable. Bilal Al Chami reversed this CWB format and reconstructed yearly
CSV files, stored locally under:

- `data/speech/1996_2019/parisparl_reden_YYYY.csv`

Although the source description covers 1996 to 2019, the local processed files
currently start in 1998. The missing first two years were identified during the
data quality review and are documented in `update.md`.

The cleaning step was heavier than expected because the ParisParl data comes
from PDF extraction rather than native structured XML. The text stream contains
OCR and detokenization artifacts, wrapped quotes, page-layout noise, table of
contents lines, procedural headings, major topics, subtopics, speeches, and
interjections in the same sequence. Some numeric strings are article numbers or
page references rather than debate topic numbers, and some presidency/procedure
rows can be incorrectly interpreted as speeches if they are not separated.

The local cleaning and restructuring work is mainly implemented in:

- `mine_parisparl.py` and `eda/mine_parisparl.ipynb`, which prototype the
  structure recovery rules on yearly ParisParl CSV files.
- `eda/summary_extraction.py`, which extracts the official `SOMMAIRE` zone and
  uses it as the preferred source for `major_topic_order`, `major_topic`, and
  `subtopic`.
- `eda/title_cleaning.py`, which fixes French detokenization artifacts in
  parliamentary titles, such as broken contractions and apostrophe spacing.
- `eda/interjection_filter.py`, which keeps genuine parliamentary reactions
  such as applause, laughter, protests, and interruptions while filtering
  structural false positives.
- `eda/speech_grouping.py`, which groups consecutive rows from the same speaker,
  keeps procedure rows separate, and attaches reaction interjections to the
  relevant speech group.
- `eda/entity_binding.py`, which links cleaned speeches to `party.csv` and
  `politician.csv` using normalized party labels and speaker names.

The resulting cleaned ParisParl outputs are stored as:

- `data/final/parisparl_speeches_1998_2010_processed.csv`
- `data/final/parisparl_speeches_1998_2019_processed.csv`

These files expose an analysis-ready structure with row type, procedure type,
source row ids, speaker role, date, session, topic hierarchy, grouped speech
text, attached interjections, `party_id`, and `mp_id`. This makes the historical
PDF-derived corpus usable together with the more recent DILA XML-derived corpus.

C) Deputes and their mandates

1. Primary structured source:
   https://data.assemblee-nationale.fr/acteurs/historique-des-deputes

   The local JSON files are stored in:

   - `data/deputes/acteur`
   - `data/deputes/organe`
   - `data/deputes/deport`

2. Complementary Sycomore source:
   https://www2.assemblee-nationale.fr/sycomore/recherche

The deputies and mandates dataset is built to provide the reference entities
used by both speech corpora. Speeches need stable `mp_id` values, mandate
periods, legislature numbers, and party/group information so that each speech
can be linked to a politician, a parliamentary term, and a political family.

The main pipeline is implemented in `convert_acteurs_to_csv.py`. The primary
source is the official Assemblée nationale structured data. The `acteur` files
contain civil identity, birth information, profession, and raw mandates. The
`organe` files provide labels for parliamentary groups, parties, and
committees. The `deport` files are kept locally with the deputy archive but are
not the main input for the final politician and mandate tables.

The official JSON source is preferred whenever it is available because it
contains structured identifiers, dates, and organ references. The conversion
extracts:

- one politician row per `PA...` identifier;
- one mandate row per `mp_id + legislature`;
- birth date and birth place;
- profession and current institutional status;
- assembly seniority computed from Assemblée mandate date ranges;
- constituency, mandate start/end, election date, parliamentary group, related
  committees, and source URL.

Some target fields are intentionally left empty because they are not available
in the source JSON files used here: `education_level`, `school`,
`academic_title`, `languages`, `list`, and `votes`.

Sycomore is used as a complementary source for legislatures 10 to 17. The
script reads the alphabetical Sycomore lists, follows deputy pages, parses
French date formats, extracts legislature periods, departments, groups, and
birth information, then adds only missing politicians or missing mandates. This
is especially useful for older legislatures where the local structured JSON can
be incomplete.

The merge rules are conservative:

- local Assemblée nationale JSON rows take priority over Sycomore rows;
- politicians are deduplicated by `mp_id`;
- mandates are deduplicated by `mp_id + term`;
- existing `PA...` identifiers are preserved;
- when Sycomore has no usable PA identifier, the script generates a
  deterministic PA-shaped fallback ID and records it in a report;
- no `SYC...` identifier is allowed to remain in the final validated tables;
- every mandate must point to an existing politician.

Party mapping is handled through `data/parties/party.csv`. Parliamentary group
labels from local `organe` data or Sycomore pages are normalized, matched
against party names, acronyms, historical group labels, and configured aliases.
The script also handles legacy labels such as historical socialist,
communist/GDR, RPR/UMP, UDF, and non-inscrit groups. When several group labels
are present for the same mandate, duplicate labels are removed and
`Députés n'appartenant à aucun groupe` is dropped if a more informative group is
also present.

The pipeline also writes audit reports under `deputes_boostrap/report`,
including:

- `new_politicians.csv`
- `new_mandates.csv`
- `fallback_pa_ids.csv`
- `duplicate_politicians.csv`
- `duplicate_mandates.csv`
- `unresolved_party_ids.csv`

Standard command:

```bash
python3 convert_acteurs_to_csv.py
```

Useful verification commands:

```bash
python3 convert_acteurs_to_csv.py --local-only --dry-run
python3 -m py_compile convert_acteurs_to_csv.py
```

The final reference tables used by the project are:

- `data/final/politician.csv`
- `data/final/mandate.csv`

D) political party (data/parties/party.csv)

`data/parties/party.csv` is the manually curated political-party reference table
used to standardize party identifiers across the deputies, mandates, and speech
datasets. It was built from online public sources and from the parliamentary
group labels observed in the Assemblée nationale and Sycomore data, with a
focus on the 10th to 17th legislatures.

The file is small, but it is central to the cleaning pipeline because political
labels are not stable over time. The same political family can appear under
different names depending on the legislature, the source, or the context:
official party name, parliamentary group name, acronym, historical label, or
short alias used in interjections. Without this mapping, the final datasets
would contain many near-duplicate groups and would be harder to compare across
time.

Main columns:

- `party_id`: stable internal identifier used by the project, such as `P008`.
- `acronym`: short label used in outputs and mappings, such as `SOC`, `UMP`,
  `LR`, or `GDR`.
- `name`: normalized party or parliamentary group name.
- `mandates`: number of mandate rows associated with the party in the local
  data review.
- `source_political_group_count`: number of distinct source group labels mapped
  to the party.
- `source_political_groups`: list of source labels found in Assemblée nationale
  or Sycomore data.
- `interjection_mentions`: count used during exploratory analysis of political
  reactions.
- `interjection_aliases`: labels and acronyms that can appear in reaction or
  interjection contexts.
- `wiki_url`: public documentation URL used as a manual verification source.
- `country_id`: country reference, set to `3` for France.

This table is used by `convert_acteurs_to_csv.py` to convert mandate
parliamentary group labels into `party_id` values. It is also used by
`eda/entity_binding.py` to bind speech rows to parties. Both scripts normalize
labels before matching: accents, case, punctuation, parenthetical details, and
some historical naming variants are handled so that labels such as socialist
groups, communist/GDR groups, RPR/UMP, UDF, and non-inscrit groups map to the
intended stable identifier.

Rows that cannot be mapped safely are kept unresolved rather than guessed. In
the deputies pipeline, they appear as empty or `P000` values and are written to
`deputes_boostrap/report/unresolved_party_ids.csv` for manual review.

E) Structure Kamil (Parisparl 1998 to 2010 + Dila 2011_2026):

Objective

Build one upload-ready speech table covering French National Assembly debates
from 1998 to 2026. The table keeps only speech-level rows and exposes the
minimal structure expected by Kamil:

```python
[
    "speech_id",
    "speech_text",
    "speech_interjection",
    "speech_date",
    "speaker_id",
    "country_id",
    "term",
]
```

The final dataframe is named `df_1998_2026` in
`eda/mine_parisparl.ipynb`. It can be exported as:

```python
df_1998_2026.to_csv("../data/final/speeches_1998_2026.csv", index=False)
```

Sources

- `data/final/parisparl_speeches_1998_2010_processed.csv`
  Historical Parisparl speeches processed locally for 1998-2010.
- `data/speech/2011_2026/centralized_speeches.csv`
  DILA open-data debates converted from official XML files for 2011-2026.
- `data/final/presidency.csv`
  Reference table used to bind Assembly presidents to a presidency identifier
  when a speech row is spoken by the chair and no deputy id is available.

Processing

1. `df_2011_2026` is reduced to the columns needed by the final structure:
   `date`, `text_speech_clean`, `id_mp`, `speaker`, and
   `speech_interjection`.
2. Rows without a speaker are dropped. Rows without `id_mp` are dropped except
   when the speaker label identifies the Assembly president, because those rows
   are bound later to `presidency.pr_id`.
3. DILA columns are renamed:
   `text_speech_clean` to `speech_text`, `date` to `speech_date`,
   `id_mp` to `speaker_id`, and `speaker` to the temporary `role` column.
4. Empty DILA dates are recovered from `source_files` when possible, for
   example from names such as `AAA_20121002_...xml`.
5. `df_1998_2010` is read from the processed Parisparl CSV and restricted to
   dates between 1998 and 2010.
6. Parisparl keeps `speech_order` as a numeric order column, so speech filtering
   uses `row_type == "speech"`.
7. Parisparl columns are renamed:
   `date` to `speech_date`, `mp_id` to `speaker_id`, and `interjections` to
   `speech_interjection`.
8. The two normalized speech tables are concatenated in chronological order.
   Existing source order is preserved inside each source.
9. For rows where `role` is the Assembly presidency and `speaker_id` is empty,
   `speaker_id` is filled with the matching `pr_id` from `presidency.csv`
   according to `speech_date`.
10. `country_id` is set to `3` for France.
11. `term` is computed from `speech_date` using the French legislature date
    ranges from the 11th to the 17th legislature.
12. `speech_id` is generated after sorting, starting at `1` and following the
    final chronological order.
13. Temporary columns such as `role`, parsed dates, and source ordering helpers
    are removed.

Final schema

- `speech_id`: sequential integer generated after the final chronological
  merge.
- `speech_text`: cleaned speech text.
- `speech_interjection`: interjection or reaction text associated with the
  speech row when available.
- `speech_date`: speech date formatted as `DD-MM-YYYY`.
- `speaker_id`: deputy id (`PA...`) or presidency id (`PRNA...`) when the row
  is spoken by the Assembly president.
- `country_id`: stable country reference, always `3` for France.
- `term`: legislature number at the speech date.

Quality checks

The notebook prints a `quality_report` and asserts that:

- the final column order matches the expected schema;
- `speech_id` is unique and monotonically increasing;
- `speech_date` is never missing;
- `speaker_id` is never empty after presidency binding;
- `country_id` is always `3`;
- `term` is never missing.

Rows that still have no `speaker_id` after the presidency binding are removed
from the final upload dataframe, because the target structure requires a bound
speaker identifier.
