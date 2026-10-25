"""Tests de l'import automatique.

On ne télécharge rien pendant les tests : on fabrique une page HTML qui reproduit la structure
de la page de la fédération (un tableau de classement, puis une ligne par match), à partir des
données de la poule. On peut ainsi simuler de nouveaux résultats, un match déplacé ou une erreur.
"""

import html
import json
from pathlib import Path

import pytest

import db
import importer

DONNEES = json.loads((Path(__file__).parent.parent / "data" / "poule_R2M_C_2026-2027.json").read_text(encoding="utf-8"))
NOMS = {e["id"]: e["nom"] for e in DONNEES["equipes"]}


def page_federation(modifications=None, sets_dans_des_cellules_separees=False):
    """Fabrique une page HTML semblable à celle de la fédération.

    `modifications` : {code: {"sets": [...], "date": "JJ/MM/AA", "heure": "HH:MM", "total": "075-063"}}
    """
    modifications = modifications or {}
    lignes = ["<html><body><table>"]
    for equipe in DONNEES["equipes"]:  # tableau de classement (sans codes de match)
        lignes.append(f"<tr><td>1.</td><td>{html.escape(equipe['nom'])}</td><td>6</td><td>2</td></tr>")
    lignes.append("</table>")

    journee = 0
    for match in DONNEES["matchs"]:
        modif = modifications.get(match["code"], {})
        if match["journee"] != journee:
            journee = match["journee"]
            lignes.append(f"<p>Journ&eacute;e {journee:02d}</p><table>")
        a, m, j = match["date"].split("-")
        date_page = modif.get("date", f"{j}/{m}/{a[2:]}")
        heure = modif.get("heure", match["heure"])
        sets = modif.get("sets", match["sets"])

        cellules = [match["code"], date_page, heure, html.escape(NOMS[match["domicile"]]),
                    '<img src="ballon_volley.jpg">', html.escape(NOMS[match["exterieur"]])]
        if sets:
            dom = sum(1 for s in sets if int(s.split(":")[0]) > int(s.split(":")[1]))
            pts_dom = sum(int(s.split(":")[0]) for s in sets)
            pts_ext = sum(int(s.split(":")[1]) for s in sets)
            total = modif.get("total", f"{pts_dom:03d}-{pts_ext:03d}")
            cellules += [str(dom), str(len(sets) - dom)]
            cellules += sets if sets_dans_des_cellules_separees else [", ".join(sets)]
            cellules += [total, "NOM ARBITRE"]
        else:
            cellules += ["", "", "", "", match["gymnase"] or "", "NOM ARBITRE"]
        lignes.append("<tr>" + "".join(f"<td>{c}</td>" for c in cellules) + "</tr>")
        if match["code"].endswith(("005", "010", "015", "020", "025", "030", "035", "040", "045",
                                   "050", "055", "060", "065", "070", "075", "080", "085", "090")):
            lignes.append("</table>")
    lignes.append("</body></html>")
    return "\n".join(lignes)


# --- Lecture de la page ------------------------------------------------------------------------

@pytest.mark.parametrize("cellules_separees", [False, True])
def test_lit_tous_les_matchs_et_les_resultats(cellules_separees):
    lus = importer.extraire_matchs(page_federation(sets_dans_des_cellules_separees=cellules_separees))

    assert len(lus) == 90
    assert lus["2MCA001"].date == "2026-10-04"
    assert lus["2MCA001"].heure == "14:00"
    assert lus["2MCA001"].sets == [(14, 25), (29, 27), (20, 25), (18, 25)]
    assert lus["2MCA001"].total == (81, 102)
    assert lus["2MCA011"].sets == []  # pas encore joué
    assert sum(1 for m in lus.values() if m.sets) == 11


# --- Mise à jour de la base ---------------------------------------------------------------------

def test_ajoute_un_nouveau_resultat(app):
    page = page_federation({"2MCA012": {"sets": ["20:25", "25:22", "18:25", "23:25"]}})

    with app.app_context():
        rapport = importer.importer(page)
        match = db.lire_match("2MCA012")

    assert len(rapport.nouveaux) == 1 and "Franconville - Bussy Volley : 1-3" in rapport.nouveaux[0]
    assert match["sets"] == [(20, 25), (25, 22), (18, 25), (23, 25)]


def test_ne_change_rien_si_tout_est_a_jour(app):
    with app.app_context():
        rapport = importer.importer(page_federation())

    assert rapport.nouveaux == rapport.corriges == rapport.reprogrammes == rapport.ignores == []


def test_la_simulation_ne_modifie_pas_la_base(app):
    page = page_federation({"2MCA012": {"sets": ["25:20", "25:20", "25:20"]}})

    with app.app_context():
        rapport = importer.importer(page, simulation=True)
        match = db.lire_match("2MCA012")

    assert len(rapport.nouveaux) == 1
    assert match["sets"] == []


def test_met_a_jour_un_match_reprogramme(app):
    with app.app_context():
        rapport = importer.importer(page_federation({"2MCA013": {"date": "01/11/26", "heure": "15:30"}}))
        match = db.lire_match("2MCA013")

    assert len(rapport.reprogrammes) == 1
    assert (match["date"], match["heure"]) == ("2026-11-01", "15:30")


def test_corrige_un_resultat_deja_saisi(app):
    with app.app_context():
        db.enregistrer_resultat("2MCA012", [(25, 20), (25, 20), (25, 20)])  # saisi à la main, mais faux
        rapport = importer.importer(page_federation({"2MCA012": {"sets": ["20:25", "20:25", "20:25"]}}))

    assert len(rapport.corriges) == 1


@pytest.mark.parametrize("modification, raison", [
    ({"sets": ["25:24", "25:20", "25:20"]}, "2 points d'écart"),     # score impossible
    ({"sets": ["25:20", "25:20", "25:20"], "total": "070-060"}, "total des points"),  # total incohérent
])
def test_ignore_les_donnees_douteuses(app, modification, raison):
    with app.app_context():
        rapport = importer.importer(page_federation({"2MCA014": modification}))
        match = db.lire_match("2MCA014")

    assert len(rapport.ignores) == 1 and raison in rapport.ignores[0]
    assert match["sets"] == []  # rien n'a été enregistré


def test_ignore_un_match_dont_les_equipes_ne_correspondent_pas(app):
    page = page_federation({"2MCA012": {"sets": ["25:20", "25:20", "25:20"]}})
    # Dans la ligne du match 2MCA012, on remplace Bussy par une équipe inconnue
    page = "\n".join(
        ligne.replace(html.escape(NOMS["BUSSY"]), "UNE AUTRE EQUIPE") if "2MCA012" in ligne else ligne
        for ligne in page.split("\n")
    )

    with app.app_context():
        rapport = importer.importer(page)

    assert any("équipes introuvables" in ligne for ligne in rapport.ignores)


# --- Commande en ligne -----------------------------------------------------------------------

def test_commande_importer(app, monkeypatch):
    page = page_federation({"2MCA012": {"sets": ["20:25", "25:22", "18:25", "23:25"]}})
    monkeypatch.setattr(importer, "telecharger_page", lambda url: page)

    resultat = app.test_cli_runner().invoke(args=["importer"])

    assert "90 matchs trouvés" in resultat.output
    assert "Nouveaux résultats" in resultat.output
    assert "Franconville - Bussy Volley : 1-3" in resultat.output


def test_commande_importer_page_illisible(app, monkeypatch):
    monkeypatch.setattr(importer, "telecharger_page", lambda url: "<html>Maintenance en cours</html>")

    resultat = app.test_cli_runner().invoke(args=["importer"])

    assert "Aucun match reconnu" in resultat.output


def test_commande_importer_sans_connexion(app, monkeypatch):
    def echec(url):
        raise importer.requests.ConnectionError("pas de réseau")
    monkeypatch.setattr(importer, "telecharger_page", echec)

    resultat = app.test_cli_runner().invoke(args=["importer"])

    assert "Impossible de récupérer la page" in resultat.output
