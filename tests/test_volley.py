import json
from pathlib import Path

import pytest

import volley

DONNEES = json.loads((Path(__file__).parent.parent / "data" / "poule_R2M_C_2026-2027.json").read_text(encoding="utf-8"))


# --- Règles des sets et des matchs --------------------------------------------------

@pytest.mark.parametrize("numero, domicile, exterieur", [
    (1, 25, 0), (1, 25, 23), (2, 29, 27), (3, 28, 30), (5, 15, 13), (5, 9, 15), (5, 17, 15),
])
def test_sets_valides(numero, domicile, exterieur):
    volley.verifier_set(numero, domicile, exterieur)


@pytest.mark.parametrize("numero, domicile, exterieur", [
    (1, 24, 20),  # personne n'a atteint 25
    (1, 25, 24),  # pas 2 points d'écart
    (2, 27, 20),  # au-delà de 25, l'écart doit être exactement de 2
    (1, 15, 10),  # 15 points ne suffisent qu'au 5e set
    (5, 15, 14),  # pas 2 points d'écart au tie-break
    (5, 25, 20),  # au-delà de 15, l'écart doit être exactement de 2
    (1, -1, 25),  # score négatif
])
def test_sets_invalides(numero, domicile, exterieur):
    with pytest.raises(volley.ScoreInvalide):
        volley.verifier_set(numero, domicile, exterieur)


def test_match_valide_au_tie_break():
    volley.verifier_match([(23, 25), (28, 30), (25, 14), (25, 19), (13, 15)])


@pytest.mark.parametrize("sets", [
    [(25, 20), (25, 20)],                                      # trop peu de sets
    [(25, 20), (20, 25), (25, 20), (20, 25)],                  # personne n'a 3 sets
    [(25, 20), (25, 20), (25, 20), (20, 25)],                  # un set en trop
    [(25, 20), (20, 25), (25, 20), (20, 25), (15, 13), (15, 10)],  # 6 sets
])
def test_matchs_invalides(sets):
    with pytest.raises(volley.ScoreInvalide):
        volley.verifier_match(sets)


def test_lire_set():
    assert volley.lire_set("25:23") == (25, 23)
    assert volley.lire_set("25-23") == (25, 23)
    with pytest.raises(volley.ScoreInvalide):
        volley.lire_set("vingt-cinq")


def test_bareme_des_points():
    assert [volley.points_classement(g, p) for g, p in [(3, 0), (3, 1), (3, 2), (2, 3), (1, 3), (0, 3)]] == [3, 3, 2, 1, 0, 0]


# --- Données réelles ------------------------------------------------------------------

def matchs_reels():
    return [
        {"domicile": m["domicile"], "exterieur": m["exterieur"], "date": m["date"], "heure": m["heure"],
         "sets": [volley.lire_set(s) for s in m["sets"]]}
        for m in DONNEES["matchs"]
    ]


def test_tous_les_resultats_reels_respectent_les_regles():
    for match in matchs_reels():
        if match["sets"]:
            volley.verifier_match(match["sets"])


def test_le_classement_calcule_est_identique_au_classement_officiel():
    """Classement publié sur le site de la FFvolley le 23 octobre 2026 (après 11 matchs)."""
    officiel = [
        # équipe, points, joués, gagnés, sets pour, sets contre, points pour, points contre
        ("CARRIERES", 6, 2, 2, 6, 1, 177, 145),
        ("SARTROUVILLE", 6, 2, 2, 6, 1, 166, 155),
        ("VALEUROPE", 6, 3, 2, 7, 3, 236, 198),
        ("BUSSY", 5, 2, 2, 6, 2, 185, 160),
        ("LEVALLOIS", 4, 2, 1, 5, 4, 193, 181),
        ("COLOMBES", 3, 2, 1, 5, 5, 204, 218),
        ("FRANCONVILLE", 2, 2, 1, 4, 5, 185, 203),
        ("COURCOURONNES", 1, 2, 0, 2, 6, 175, 180),
        ("ANTONY", 0, 2, 0, 1, 6, 136, 169),
        ("FONTENAY", 0, 3, 0, 0, 9, 179, 227),
    ]
    lignes = volley.calculer_classement(DONNEES["equipes"], matchs_reels())

    calcule = [(l.equipe_id, l.points, l.joues, l.gagnes, l.sets_pour, l.sets_contre, l.points_pour, l.points_contre)
               for l in lignes]
    assert calcule == officiel


def test_la_forme_garde_les_derniers_resultats_dans_l_ordre():
    lignes = {l.equipe_id: l for l in volley.calculer_classement(DONNEES["equipes"], matchs_reels())}

    assert [r["score"] for r in lignes["VALEUROPE"].forme] == ["3-0", "1-3", "3-0"]
    assert [r["victoire"] for r in lignes["VALEUROPE"].forme] == [True, False, True]
    assert lignes["VALEUROPE"].forme[1]["adversaire"] == "Sartrouville 3"


def test_a_egalite_de_points_le_nombre_de_victoires_passe_avant_le_coefficient_de_sets():
    """RPE Régionale 2 masculine, art. 13 : points, puis victoires, puis coefficients."""
    equipes = [{"id": i, "nom_court": i} for i in "ABCDEF"]

    def match(dom, ext, *sets):
        return {"domicile": dom, "exterieur": ext, "date": "2026-10-01", "sets": list(sets)}

    matchs = [
        match("A", "C", (25, 20), (20, 25), (25, 20), (20, 25), (15, 10)),  # A gagne 3-2 : 2 pts
        match("A", "D", (25, 20), (20, 25), (25, 20), (20, 25), (15, 10)),  # A gagne 3-2 : 2 pts
        match("B", "E", (25, 20), (25, 20), (25, 20)),                      # B gagne 3-0 : 3 pts
        match("B", "F", (25, 20), (20, 25), (25, 20), (20, 25), (10, 15)),  # B perd 2-3 : 1 pt
    ]
    lignes = {l.equipe_id: l for l in volley.calculer_classement(equipes, matchs)}
    ordre = [l.equipe_id for l in volley.calculer_classement(equipes, matchs)]

    # A et B ont 4 points ; B a un meilleur coefficient de sets, mais A a plus de victoires
    assert lignes["A"].points == lignes["B"].points == 4
    assert lignes["B"].coeff_sets > lignes["A"].coeff_sets
    assert ordre.index("A") < ordre.index("B")
