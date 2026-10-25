"""Import automatique des résultats depuis la page publique de la poule (site de la FFvolley).

C'est un petit pipeline de données en trois étapes :
  1. Extraire : télécharger la page HTML (une seule requête) ;
  2. Transformer : y retrouver, pour chaque match, la date, l'heure et les scores des sets ;
  3. Charger : comparer avec la base et n'enregistrer que ce qui a changé.

Règle d'or : on n'enregistre jamais une donnée douteuse. Si un match semble mal lu
(équipes introuvables, score impossible, total de points incohérent), il est ignoré et signalé.

Utilisation :
    flask --app app importer               # met à jour la base
    flask --app app importer --simulation  # affiche ce qui changerait, sans rien modifier
"""

import re
from dataclasses import dataclass, field
from datetime import date

import click
import requests
from bs4 import BeautifulSoup
from flask.cli import with_appcontext

import db
import volley

ENTETES = {"User-Agent": "classement-volley/1.0 (projet etudiant, une requete par mise a jour)"}

# Début d'un match dans le texte de la page : code, date et heure. Exemple : "2MCA001 04/10/26 14:00"
RE_DEBUT_MATCH = re.compile(r"\b(\d[A-Z]{2}[AR]\d{3})\s+(\d{2})/(\d{2})/(\d{2})\s+(\d{1,2}):(\d{2})\b")
# Scores des sets : 3 à 5 scores du type "25:23", séparés par des virgules ou des espaces
RE_SETS = re.compile(r"\d{1,2}:\d{1,2}(?:\s*,?\s*\d{1,2}:\d{1,2}){2,4}")
RE_UN_SET = re.compile(r"(\d{1,2}):(\d{1,2})")
# Total des points, affiché après les sets : "081-102"
RE_TOTAL = re.compile(r"^\s*(\d{2,3})\s*-\s*(\d{2,3})\b")


@dataclass
class MatchLu:
    """Ce que l'on a pu lire sur la page pour un match."""

    code: str
    date: str               # AAAA-MM-JJ
    heure: str              # HH:MM
    texte: str              # texte brut de la ligne, pour les vérifications
    sets: list = field(default_factory=list)
    total: tuple = None     # total des points affiché, ex. (81, 102), s'il est présent


@dataclass
class Rapport:
    nouveaux: list = field(default_factory=list)
    corriges: list = field(default_factory=list)
    reprogrammes: list = field(default_factory=list)
    ignores: list = field(default_factory=list)


# --- 1. Extraire ------------------------------------------------------------------------------


def telecharger_page(url):
    reponse = requests.get(url, headers=ENTETES, timeout=30)
    reponse.raise_for_status()
    # Le site n'annonce pas toujours son encodage : on laisse requests le deviner à partir du contenu.
    if "charset" not in reponse.headers.get("Content-Type", "").lower():
        reponse.encoding = reponse.apparent_encoding
    return reponse.text


# --- 2. Transformer ---------------------------------------------------------------------------


def texte_de_la_page(html):
    """Texte visible de la page, sur une seule ligne, sans balises HTML."""
    texte = BeautifulSoup(html, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", texte)


def extraire_matchs(html):
    """Renvoie {code: MatchLu} pour tous les matchs trouvés dans la page."""
    texte = texte_de_la_page(html)
    debuts = list(RE_DEBUT_MATCH.finditer(texte))
    matchs = {}
    for i, debut in enumerate(debuts):
        # Le texte d'un match va jusqu'au début du match suivant
        fin = debuts[i + 1].start() if i + 1 < len(debuts) else len(texte)
        code, jour, mois, annee, heures, minutes = debut.groups()
        reste = texte[debut.end():fin]

        match = MatchLu(code=code, date=f"20{annee}-{mois}-{jour}", heure=f"{int(heures):02d}:{minutes}", texte=reste)
        trouve = RE_SETS.search(reste)
        if trouve:
            match.sets = [(int(a), int(b)) for a, b in RE_UN_SET.findall(trouve.group())]
            total = RE_TOTAL.match(reste[trouve.end():])
            match.total = (int(total.group(1)), int(total.group(2))) if total else None
        matchs[code] = match
    return matchs


def normaliser(nom):
    """Majuscules et espaces simples, pour comparer des noms d'équipes."""
    return re.sub(r"\s+", " ", nom).strip().upper()


def verifier(match_lu, match_base):
    """Lève volley.ScoreInvalide si le résultat lu n'est pas fiable."""
    texte = normaliser(match_lu.texte)
    dom, ext = normaliser(match_base["nom_officiel_domicile"]), normaliser(match_base["nom_officiel_exterieur"])
    pos_dom, pos_ext = texte.find(dom), texte.find(ext)
    if pos_dom == -1 or pos_ext == -1 or pos_dom > pos_ext:
        raise volley.ScoreInvalide("équipes introuvables ou inversées dans la page")
    volley.verifier_match(match_lu.sets)
    total = match_lu.total
    if total and total != (sum(d for d, _ in match_lu.sets), sum(e for _, e in match_lu.sets)):
        raise volley.ScoreInvalide(f"le total des points affiché ({total[0]}-{total[1]}) ne correspond pas aux sets")


# --- 3. Charger ------------------------------------------------------------------------------


def importer(html, simulation=False):
    """Compare la page avec la base et enregistre les différences. Renvoie un Rapport."""
    rapport = Rapport()
    lus = extraire_matchs(html)

    for match in db.lire_matchs():
        lu = lus.get(match["code"])
        if lu is None:
            continue
        nom = f"{match['code']} {match['nom_domicile']} - {match['nom_exterieur']}"

        # Match déplacé à une autre date ou une autre heure
        if (lu.date, lu.heure) != (match["date"], match["heure"]):
            rapport.reprogrammes.append(f"{nom} : {match['date']} {match['heure']} -> {lu.date} {lu.heure}")
            if not simulation:
                db.modifier_horaire(match["code"], lu.date, lu.heure)

        if not lu.sets or lu.sets == match["sets"]:
            continue
        try:
            verifier(lu, match)
        except volley.ScoreInvalide as e:
            rapport.ignores.append(f"{nom} : {e}")
            continue

        dom, ext = volley.score_en_sets(lu.sets)
        ligne = f"{nom} : {dom}-{ext} ({', '.join(f'{a}-{b}' for a, b in lu.sets)})"
        (rapport.corriges if match["sets"] else rapport.nouveaux).append(ligne)
        if not simulation:
            db.enregistrer_resultat(match["code"], lu.sets)

    if not simulation:
        db.modifier_info("releve_le", date.today().isoformat())
    return rapport


@click.command("importer")
@with_appcontext
@click.option("--simulation", is_flag=True, help="Affiche les changements sans modifier la base.")
def importer_command(simulation):
    """Récupère les derniers résultats sur le site de la fédération."""
    url = db.lire_infos()["source"]
    click.echo(f"Téléchargement de {url}")
    try:
        html = telecharger_page(url)
    except requests.RequestException as e:
        click.echo(f"Impossible de récupérer la page de la fédération : {e}")
        click.echo("Vérifiez votre connexion internet, puis réessayez plus tard. Rien n'a été modifié.")
        return

    nombre = len(extraire_matchs(html))
    click.echo(f"{nombre} matchs trouvés dans la page.")
    if nombre == 0:
        click.echo("Aucun match reconnu : la page a peut-être changé de format. Rien n'a été modifié.")
        return

    rapport = importer(html, simulation=simulation)
    for titre, lignes in [("Nouveaux résultats", rapport.nouveaux), ("Résultats corrigés", rapport.corriges),
                          ("Matchs reprogrammés", rapport.reprogrammes), ("Matchs ignorés (données douteuses)", rapport.ignores)]:
        if lignes:
            click.echo(f"\n{titre} :")
            for ligne in lignes:
                click.echo(f"  - {ligne}")
    if not (rapport.nouveaux or rapport.corriges or rapport.reprogrammes or rapport.ignores):
        click.echo("Tout est déjà à jour.")
    if simulation:
        click.echo("\nSimulation : la base n'a pas été modifiée.")


def init_app(app):
    app.cli.add_command(importer_command)
