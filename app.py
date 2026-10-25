"""Site de classement de volley-ball, avec Flask.

Lancer le site :  python app.py   puis ouvrir http://127.0.0.1:5000
"""

import csv
import hmac
import io
import os
import secrets
from datetime import date
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for

import db
import importer
import volley

DOSSIER = Path(__file__).parent
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOIS_LONGS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
              "octobre", "novembre", "décembre"]


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(16),
        DATABASE=str(DOSSIER / "volley.db"),
        FICHIER_DONNEES=str(DOSSIER / "data" / "poule_R2M_C_2026-2027.json"),
        # Mot de passe demandé pour saisir un résultat. À changer avant de mettre le site en ligne !
        MOT_DE_PASSE_ADMIN=os.environ.get("ADMIN_PASSWORD", "volley"),
        # Identifiant de l'équipe à mettre en avant (ex. "BUSSY"), ou None.
        EQUIPE_SUIVIE=os.environ.get("EQUIPE_SUIVIE"),
        AUJOURDHUI=None,  # permet de fixer la date du jour dans les tests
        # Textes affichés dans l'en-tête du site
        SITE_NOM="IDF Volley R2M",
        SITE_POULE="Poule C",
        SITE_DIVISION="Championnat Régional 2",
        SITE_ZONE="Poule C Île-de-France",
        # Zones du classement, d'après le règlement de la Régionale 2 masculine 2026/2027 (RPE, art. 14) :
        # le 1er monte en Régionale 1, le 2e dispute un match de classement pour une éventuelle
        # montée supplémentaire, les 8e, 9e et 10e descendent en Accession Régionale.
        ZONE_ACCESSION=1,
        ZONE_BARRAGE=1,
        ZONE_RELEGATION=3,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    importer.init_app(app)
    # Au premier lancement, la base n'existe pas encore : on la crée à partir du fichier JSON.
    if not Path(app.config["DATABASE"]).exists():
        with app.app_context():
            db.init_db(app.config["FICHIER_DONNEES"])

    enregistrer_filtres(app)
    enregistrer_routes(app)
    return app


# --- Petites fonctions d'affichage, utilisables dans les templates -------------------------


def enregistrer_filtres(app):
    @app.template_filter("date_fr")
    def date_fr(texte):
        jour = date.fromisoformat(texte)
        return f"{JOURS[jour.weekday()]} {jour.day} {MOIS[jour.month - 1]}"

    @app.template_filter("date_longue")
    def date_longue(texte):
        jour = date.fromisoformat(texte)
        return f"{jour.day} {MOIS_LONGS[jour.month - 1]} {jour.year}"

    app.add_template_filter(format_coeff, "coeff")

    @app.context_processor
    def variables_communes():
        # Disponibles dans tous les templates
        site = {cle[5:].lower(): valeur for cle, valeur in app.config.items() if cle.startswith("SITE_")}
        return {"infos": db.lire_infos(), "equipe_suivie": app.config["EQUIPE_SUIVIE"], "site": site}


def places(premiere, derniere):
    """places(1, 1) -> "1er" ; places(8, 10) -> "8e à 10e"."""
    nom = lambda n: "1er" if n == 1 else f"{n}e"
    return nom(premiere) if premiere == derniere else f"{nom(premiere)} à {nom(derniere)}"


def format_coeff(valeur):
    """2.3333 -> "2,33" ; un coefficient infini (aucun set perdu) s'affiche "max"."""
    if valeur == float("inf"):
        return "max"
    return f"{valeur:.2f}".replace(".", ",")


def etat_de_la_poule(matchs, lignes):
    """Journée en cours (la première qui a encore un match à jouer) et équipe en tête."""
    journee = next((m["journee"] for m in sorted(matchs, key=lambda m: m["journee"]) if not m["sets"]), None)
    leader = lignes[0] if lignes and lignes[0].joues else None
    return {"journee_en_cours": journee, "leader": leader, "nb_equipes": len(lignes)}


def aujourdhui(app):
    return app.config["AUJOURDHUI"] or date.today().isoformat()


# --- Pages du site --------------------------------------------------------------------------


def enregistrer_routes(app):
    @app.route("/")
    def classement():
        matchs = db.lire_matchs()
        lignes = volley.calculer_classement(db.lire_equipes(), matchs)

        # Zone de chaque équipe : montée, match de classement (barrage) ou descente
        nb_haut, nb_barrage, nb_bas = (app.config["ZONE_ACCESSION"], app.config["ZONE_BARRAGE"],
                                       app.config["ZONE_RELEGATION"])
        classement = []
        for rang, ligne in enumerate(lignes, start=1):
            zone = None
            if rang <= nb_haut:
                zone = "accession"
            elif rang <= nb_haut + nb_barrage:
                zone = "barrage"
            elif nb_bas and rang > len(lignes) - nb_bas:
                zone = "relegation"
            classement.append({"rang": rang, "ligne": ligne, "zone": zone})

        legende = []
        if nb_haut:
            legende.append(("accession", f"Montée en R1 ({places(1, nb_haut)})"))
        if nb_barrage:
            legende.append(("barrage", f"Match de classement ({places(nb_haut + 1, nb_haut + nb_barrage)})"))
        if nb_bas:
            legende.append(("relegation", f"Descente ({places(len(lignes) - nb_bas + 1, len(lignes))})"))

        joues = [m for m in matchs if m["sets"]]
        a_venir = [m for m in matchs if not m["sets"] and m["date"] >= aujourdhui(app)]
        derniers = sorted(joues, key=lambda m: (m["date"], m["heure"]), reverse=True)[:5]
        prochains = sorted(a_venir, key=lambda m: (m["date"], m["heure"]))[:5]
        return render_template(
            "classement.html", classement=classement, legende=legende, derniers=derniers, prochains=prochains,
            etat=etat_de_la_poule(matchs, lignes), nb_journees=max((m["journee"] for m in matchs), default=0),
            journees_derniers=sorted({m["journee"] for m in derniers}),
            journees_prochains=sorted({m["journee"] for m in prochains}),
        )

    @app.route("/export/classement.csv")
    def exporter_classement():
        """Télécharge le classement au format CSV (s'ouvre directement dans Excel)."""
        lignes = volley.calculer_classement(db.lire_equipes(), db.lire_matchs())
        fichier = io.StringIO()
        ecrivain = csv.writer(fichier, delimiter=";")
        ecrivain.writerow(["Rang", "Équipe", "Points", "Joués", "Victoires", "Défaites", "Sets gagnés",
                           "Sets perdus", "Coeff. sets", "Points marqués", "Points encaissés", "Coeff. points"])
        for rang, l in enumerate(lignes, start=1):
            ecrivain.writerow([rang, l.nom, l.points, l.joues, l.gagnes, l.perdus, l.sets_pour, l.sets_contre,
                               format_coeff(l.coeff_sets), l.points_pour, l.points_contre,
                               format_coeff(l.coeff_points)])
        return Response(
            "\ufeff" + fichier.getvalue(),  # le caractère invisible \ufeff aide Excel à lire les accents
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=classement.csv"},
        )

    @app.route("/calendrier")
    def calendrier():
        equipe_id = request.args.get("equipe") or None
        equipe = db.lire_equipe(equipe_id) if equipe_id else None
        if equipe_id and equipe is None:
            abort(404)
        matchs = db.lire_matchs(equipe_id=equipe_id)

        journees = {}
        for match in matchs:
            journees.setdefault(match["journee"], []).append(match)
        # Prochaine journée : la première qui contient encore un match à jouer
        prochaine = next((j for j, liste in journees.items() if any(not m["sets"] for m in liste)), None)
        return render_template("calendrier.html", journees=journees, equipe=equipe,
                               equipes=db.lire_equipes(), prochaine=prochaine,
                               nb_matchs=len(matchs), nb_joues=sum(1 for m in matchs if m["sets"]))

    @app.route("/equipe/<equipe_id>")
    def equipe(equipe_id):
        equipe = db.lire_equipe(equipe_id)
        if equipe is None:
            abort(404)
        lignes = volley.calculer_classement(db.lire_equipes(), db.lire_matchs())
        rang, ligne = next((i, l) for i, l in enumerate(lignes, start=1) if l.equipe_id == equipe_id)
        matchs = db.lire_matchs(equipe_id=equipe_id)
        return render_template("equipe.html", equipe=equipe, rang=rang, ligne=ligne,
                               joues=[m for m in matchs if m["sets"]],
                               a_venir=[m for m in matchs if not m["sets"]])

    @app.route("/match/<code>/resultat", methods=["GET", "POST"])
    def saisir_resultat(code):
        match = db.lire_match(code)
        if match is None:
            abort(404)

        # Valeurs pré-remplies dans le formulaire : le résultat existant s'il y en a un
        valeurs = [{"domicile": d, "exterieur": e} for d, e in match["sets"]]
        valeurs += [{"domicile": "", "exterieur": ""}] * (volley.SETS_MAXIMUM - len(valeurs))
        erreur = None

        if request.method == "POST":
            valeurs = [
                {"domicile": request.form.get(f"set{n}_domicile", "").strip(),
                 "exterieur": request.form.get(f"set{n}_exterieur", "").strip()}
                for n in range(1, volley.SETS_MAXIMUM + 1)
            ]
            mot_de_passe = request.form.get("mot_de_passe", "")
            try:
                if not hmac.compare_digest(mot_de_passe, app.config["MOT_DE_PASSE_ADMIN"]):
                    raise volley.ScoreInvalide("Mot de passe incorrect")
                sets = lire_sets_du_formulaire(valeurs)
                volley.verifier_match(sets)
            except volley.ScoreInvalide as e:
                erreur = str(e)
            else:
                db.enregistrer_resultat(code, sets)
                dom, ext = volley.score_en_sets(sets)
                flash(f"Résultat enregistré : {match['nom_domicile']} {dom}-{ext} {match['nom_exterieur']}")
                return redirect(url_for("calendrier", _anchor=f"journee-{match['journee']}"))

        return render_template("resultat.html", match=match, valeurs=valeurs, erreur=erreur)

    @app.errorhandler(404)
    def page_introuvable(_erreur):
        return render_template("404.html"), 404


def lire_sets_du_formulaire(valeurs):
    """Transforme les champs du formulaire en liste de sets, en ignorant les sets laissés vides."""
    sets = []
    set_vide_rencontre = False
    for numero, valeur in enumerate(valeurs, start=1):
        if valeur["domicile"] == "" and valeur["exterieur"] == "":
            set_vide_rencontre = True
            continue
        if set_vide_rencontre:
            raise volley.ScoreInvalide("Remplissez les sets dans l'ordre, sans en sauter")
        try:
            sets.append((int(valeur["domicile"]), int(valeur["exterieur"])))
        except ValueError:
            raise volley.ScoreInvalide(f"Set {numero} : les deux scores doivent être des nombres") from None
    return sets


if __name__ == "__main__":
    create_app().run(debug=True)
