-- Structure de la base de données (SQLite).
-- Trois tables reliées entre elles : une équipe joue des matchs, un match contient des sets.

DROP TABLE IF EXISTS sets;
DROP TABLE IF EXISTS matchs;
DROP TABLE IF EXISTS equipes;
DROP TABLE IF EXISTS infos;

-- Informations générales sur la compétition (nom, saison, source des données...)
CREATE TABLE infos (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);

CREATE TABLE equipes (
    id        TEXT PRIMARY KEY,      -- identifiant court, ex. 'BUSSY'
    nom       TEXT NOT NULL,         -- nom officiel
    nom_court TEXT NOT NULL,         -- nom affiché sur le site
    site_web  TEXT
);

CREATE TABLE matchs (
    code         TEXT PRIMARY KEY,   -- code officiel, ex. '2MCA001'
    journee      INTEGER NOT NULL,
    date         TEXT NOT NULL,      -- format AAAA-MM-JJ
    heure        TEXT NOT NULL,      -- format HH:MM
    domicile_id  TEXT NOT NULL REFERENCES equipes(id),
    exterieur_id TEXT NOT NULL REFERENCES equipes(id),
    gymnase      TEXT,
    CHECK (domicile_id <> exterieur_id)
);

-- Un match non joué n'a aucune ligne dans cette table.
CREATE TABLE sets (
    match_code       TEXT NOT NULL REFERENCES matchs(code) ON DELETE CASCADE,
    numero           INTEGER NOT NULL CHECK (numero BETWEEN 1 AND 5),
    points_domicile  INTEGER NOT NULL CHECK (points_domicile >= 0),
    points_exterieur INTEGER NOT NULL CHECK (points_exterieur >= 0),
    PRIMARY KEY (match_code, numero)
);
