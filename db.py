"""Accès à la base de données SQLite : création, chargement des données et requêtes SQL."""

import json
import sqlite3
from pathlib import Path

import click
from flask import current_app, g
from flask.cli import with_appcontext

import volley

SCHEMA = Path(__file__).parent / "schema.sql"


def get_db():
    """Renvoie la connexion à la base pour la requête en cours (une seule par requête)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row  # accès aux colonnes par leur nom : ligne["nom"]
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_erreur=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(fichier_donnees):
    """Recrée les tables puis les remplit avec le fichier JSON de la poule."""
    db = get_db()
    db.executescript(SCHEMA.read_text(encoding="utf-8"))

    donnees = json.loads(Path(fichier_donnees).read_text(encoding="utf-8"))
    for cle in ("competition", "ligue", "saison", "source", "releve_le"):
        db.execute("INSERT INTO infos (cle, valeur) VALUES (?, ?)", (cle, donnees[cle]))
    for equipe in donnees["equipes"]:
        db.execute(
            "INSERT INTO equipes (id, nom, nom_court, site_web) VALUES (?, ?, ?, ?)",
            (equipe["id"], equipe["nom"], equipe["nom_court"], equipe["site_web"]),
        )
    for match in donnees["matchs"]:
        db.execute(
            "INSERT INTO matchs (code, journee, date, heure, domicile_id, exterieur_id, gymnase)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (match["code"], match["journee"], match["date"], match["heure"],
             match["domicile"], match["exterieur"], match["gymnase"]),
        )
        for numero, texte in enumerate(match["sets"], start=1):
            domicile, exterieur = texte.split(":")
            db.execute(
                "INSERT INTO sets (match_code, numero, points_domicile, points_exterieur) VALUES (?, ?, ?, ?)",
                (match["code"], numero, int(domicile), int(exterieur)),
            )
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Commande `flask --app app init-db` : remet la base à zéro à partir du fichier JSON."""
    init_db(current_app.config["FICHIER_DONNEES"])
    click.echo("Base de données initialisée.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)


# --- Lecture ----------------------------------------------------------------------------


def lire_infos():
    return {ligne["cle"]: ligne["valeur"] for ligne in get_db().execute("SELECT cle, valeur FROM infos")}


def lire_equipes():
    return [dict(ligne) for ligne in get_db().execute("SELECT * FROM equipes ORDER BY nom_court")]


def lire_equipe(equipe_id):
    ligne = get_db().execute("SELECT * FROM equipes WHERE id = ?", (equipe_id,)).fetchone()
    return dict(ligne) if ligne else None


def lire_matchs(equipe_id=None, code=None):
    """Matchs avec le nom des deux équipes (jointure) et la liste de leurs sets.

    Filtres facultatifs : une équipe (ses matchs à domicile et à l'extérieur) ou un code de match.
    """
    requete = """
        SELECT m.code, m.journee, m.date, m.heure, m.gymnase,
               m.domicile_id  AS domicile,  dom.nom_court AS nom_domicile,  dom.nom AS nom_officiel_domicile,
               m.exterieur_id AS exterieur, ext.nom_court AS nom_exterieur, ext.nom AS nom_officiel_exterieur
        FROM matchs m
        JOIN equipes dom ON dom.id = m.domicile_id
        JOIN equipes ext ON ext.id = m.exterieur_id
    """
    conditions, parametres = [], []
    if equipe_id:
        conditions.append("(m.domicile_id = ? OR m.exterieur_id = ?)")
        parametres += [equipe_id, equipe_id]
    if code:
        conditions.append("m.code = ?")
        parametres.append(code)
    if conditions:
        requete += " WHERE " + " AND ".join(conditions)
    requete += " ORDER BY m.journee, m.date, m.heure, m.code"

    matchs = [dict(ligne) for ligne in get_db().execute(requete, parametres)]

    # Une seconde requête récupère tous les sets ; on les range ensuite par match.
    sets_par_match = {}
    for ligne in get_db().execute(
        "SELECT match_code, points_domicile, points_exterieur FROM sets ORDER BY match_code, numero"
    ):
        sets_par_match.setdefault(ligne["match_code"], []).append(
            (ligne["points_domicile"], ligne["points_exterieur"])
        )
    for match in matchs:
        match["sets"] = sets_par_match.get(match["code"], [])
        # Score en sets, ex. (3, 1), ou None si le match n'est pas encore joué
        match["score"] = volley.score_en_sets(match["sets"]) if match["sets"] else None
    return matchs


def lire_match(code):
    matchs = lire_matchs(code=code)
    return matchs[0] if matchs else None


# --- Écriture ---------------------------------------------------------------------------


def enregistrer_resultat(code, sets):
    """Remplace les sets d'un match. `sets` a déjà été vérifié par volley.verifier_match."""
    db = get_db()
    with db:  # transaction : tout est enregistré, ou rien en cas d'erreur
        db.execute("DELETE FROM sets WHERE match_code = ?", (code,))
        db.executemany(
            "INSERT INTO sets (match_code, numero, points_domicile, points_exterieur) VALUES (?, ?, ?, ?)",
            [(code, numero, domicile, exterieur) for numero, (domicile, exterieur) in enumerate(sets, start=1)],
        )


def modifier_horaire(code, nouvelle_date, nouvelle_heure):
    db = get_db()
    with db:
        db.execute("UPDATE matchs SET date = ?, heure = ? WHERE code = ?", (nouvelle_date, nouvelle_heure, code))


def modifier_info(cle, valeur):
    db = get_db()
    with db:
        db.execute("UPDATE infos SET valeur = ? WHERE cle = ?", (valeur, cle))
