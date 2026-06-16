-- PostgreSQL / psql script.
-- Run from the repository root:
--   psql -d YOUR_DATABASE -f sql/create_and_import_postgres.sql

BEGIN;

CREATE TABLE country (
    country_id      INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    parliament_name TEXT NOT NULL,
    seats           INTEGER NOT NULL CHECK (seats > 0)
);

CREATE TABLE party (
    party_id                     VARCHAR(4) PRIMARY KEY,
    acronym                      TEXT NOT NULL,
    name                         TEXT NOT NULL,
    mandates                     INTEGER NOT NULL,
    source_political_group_count INTEGER NOT NULL,
    source_political_groups      TEXT NOT NULL,
    interjection_mentions        INTEGER NOT NULL,
    interjection_aliases         TEXT NOT NULL,
    wiki_url                     TEXT NOT NULL,
    country_id                   INTEGER NOT NULL REFERENCES country(country_id)
);

CREATE TABLE politician (
    mp_id           VARCHAR(8) PRIMARY KEY,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    birth_date      DATE,
    birth_place     TEXT,
    education_level TEXT,
    school          TEXT,
    academic_title  TEXT,
    profession      TEXT,
    languages       TEXT,
    seniority       NUMERIC(5, 2),
    status          TEXT NOT NULL,
    country_id      INTEGER NOT NULL REFERENCES country(country_id)
);

CREATE TABLE mandate (
    mandate_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mp_id         VARCHAR(8) NOT NULL REFERENCES politician(mp_id),
    term          INTEGER NOT NULL,
    -- Some CSV values contain multiple parties, for example: P004;P002.
    party_id      TEXT,
    club          TEXT,
    "list"        TEXT,
    constituency  TEXT NOT NULL,
    committees    TEXT,
    mandate_start DATE NOT NULL,
    mandate_end   DATE,
    election_date DATE NOT NULL,
    votes         INTEGER,
    source_url    TEXT NOT NULL,
    country_id    INTEGER NOT NULL REFERENCES country(country_id),
    UNIQUE (mp_id, term)
);

CREATE TABLE mandate_party (
    mandate_id BIGINT NOT NULL REFERENCES mandate(mandate_id) ON DELETE CASCADE,
    party_id   VARCHAR(4) NOT NULL REFERENCES party(party_id),
    PRIMARY KEY (mandate_id, party_id)
);

CREATE TABLE speech (
    -- This receives the unnamed first column exported by pandas.
    csv_row_id          BIGINT PRIMARY KEY,
    source_files        TEXT NOT NULL,
    source_speech_id    TEXT,
    -- Kept as text because one source batch contains a filename instead of a date.
    speech_date_raw     TEXT NOT NULL,
    text_speech_brut    TEXT,
    text_speech_clean   TEXT,
    topic               TEXT,
    subtopic1           TEXT,
    subtopic2           TEXT,
    speaker             TEXT NOT NULL,
    link_speaker        TEXT,
    role                TEXT,
    gender              TEXT,
    speech_interjection TEXT,
    "quote"             TEXT,
    mp_id               VARCHAR(8) REFERENCES politician(mp_id)
);

\copy country (country_id, name, parliament_name, seats) FROM 'data/final/country.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

\copy party (party_id, acronym, name, mandates, source_political_group_count, source_political_groups, interjection_mentions, interjection_aliases, wiki_url, country_id) FROM 'data/final/party.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

\copy politician (mp_id, first_name, last_name, birth_date, birth_place, education_level, school, academic_title, profession, languages, seniority, status, country_id) FROM 'data/final/politician.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

\copy mandate (mp_id, term, party_id, club, "list", constituency, committees, mandate_start, mandate_end, election_date, votes, source_url, country_id) FROM 'data/final/mandate.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

INSERT INTO mandate_party (mandate_id, party_id)
SELECT m.mandate_id, split_party.party_id
FROM mandate AS m
CROSS JOIN LATERAL regexp_split_to_table(m.party_id, ';') AS split_party(party_id)
WHERE m.party_id IS NOT NULL;

\copy speech (csv_row_id, source_files, source_speech_id, speech_date_raw, text_speech_brut, text_speech_clean, topic, subtopic1, subtopic2, speaker, link_speaker, role, gender, speech_interjection, "quote", mp_id) FROM 'data/final/speech.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

CREATE INDEX idx_party_country_id ON party(country_id);
CREATE INDEX idx_politician_country_id ON politician(country_id);
CREATE INDEX idx_mandate_country_id ON mandate(country_id);
CREATE INDEX idx_mandate_mp_id ON mandate(mp_id);
CREATE INDEX idx_mandate_party_party_id ON mandate_party(party_id);
CREATE INDEX idx_speech_mp_id ON speech(mp_id);
CREATE INDEX idx_speech_source_speech_id ON speech(source_speech_id);

COMMIT;

