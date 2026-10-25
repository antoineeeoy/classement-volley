"""Règles du volley-ball et calcul du classement.

Ce module ne dépend ni de Flask ni de la base de données : il ne manipule que des
listes et des dictionnaires Python. C'est ce qui le rend facile à tester.
"""

from dataclasses import dataclass, field

POINTS_SET = 25          # un set se gagne à 25 points...
POINTS_TIE_BREAK = 15    # ... sauf le 5e set, qui se gagne à 15
ECART_MINIMUM = 2        # avec toujours 2 points d'écart
SETS_GAGNANTS = 3        # un match se joue en 3 sets gagnants
SETS_MAXIMUM = 5


class ScoreInvalide(ValueError):
    """Score impossible selon les règles du volley."""


# --- Validation des scores ------------------------------------------------------


def lire_set(texte):
    """Transforme "25:23" (ou "25-23") en tuple (25, 23)."""
    morceaux = texte.replace("-", ":").split(":")
    if len(morceaux) != 2:
        raise ScoreInvalide(f"Format de set invalide : « {texte} » (attendu : 25:23)")
    try:
        return int(morceaux[0]), int(morceaux[1])
    except ValueError:
        raise ScoreInvalide(f"Format de set invalide : « {texte} » (attendu : 25:23)") from None


def verifier_set(numero, points_domicile, points_exterieur):
    """Lève ScoreInvalide si le score du set numéro `numero` (1 à 5) est impossible."""
    objectif = POINTS_TIE_BREAK if numero == 5 else POINTS_SET
    gagnant = max(points_domicile, points_exterieur)
    perdant = min(points_domicile, points_exterieur)
    score = f"{points_domicile}-{points_exterieur}"

    if perdant < 0:
        raise ScoreInvalide(f"Set {numero} ({score}) : un score ne peut pas être négatif")
    if gagnant < objectif:
        raise ScoreInvalide(f"Set {numero} ({score}) : le vainqueur doit marquer au moins {objectif} points")
    if gagnant - perdant < ECART_MINIMUM:
        raise ScoreInvalide(f"Set {numero} ({score}) : il faut au moins 2 points d'écart")
    # Au-delà de l'objectif (ex. 27-25), le set s'arrête dès que l'écart atteint 2 points.
    if gagnant > objectif and gagnant - perdant != ECART_MINIMUM:
        raise ScoreInvalide(
            f"Set {numero} ({score}) : au-delà de {objectif} points, le set s'arrête dès qu'il y a 2 points d'écart"
        )


def verifier_match(sets):
    """Vérifie une liste de sets [(points_domicile, points_exterieur), ...].

    Un match valide compte 3 à 5 sets, une équipe gagne exactement 3 sets,
    et aucun set n'est joué après la fin du match.
    """
    if not SETS_GAGNANTS <= len(sets) <= SETS_MAXIMUM:
        raise ScoreInvalide(f"Un match se joue en 3 à 5 sets ({len(sets)} saisi(s))")
    gagnes_domicile = gagnes_exterieur = 0
    for numero, (domicile, exterieur) in enumerate(sets, start=1):
        if SETS_GAGNANTS in (gagnes_domicile, gagnes_exterieur):
            raise ScoreInvalide(f"Le match était déjà gagné avant le set {numero} : il y a un set en trop")
        verifier_set(numero, domicile, exterieur)
        if domicile > exterieur:
            gagnes_domicile += 1
        else:
            gagnes_exterieur += 1
    if SETS_GAGNANTS not in (gagnes_domicile, gagnes_exterieur):
        raise ScoreInvalide("Aucune équipe n'a gagné 3 sets : le match n'est pas terminé")


def score_en_sets(sets):
    """Nombre de sets gagnés par chaque équipe : [(25, 20), (20, 25), ...] -> (3, 1)."""
    domicile = sum(1 for d, e in sets if d > e)
    return domicile, len(sets) - domicile


def points_classement(sets_gagnes, sets_perdus):
    """Barème : victoire 3-0 ou 3-1 = 3 pts, victoire 3-2 = 2 pts, défaite 2-3 = 1 pt, sinon 0."""
    if sets_gagnes == SETS_GAGNANTS:
        return 2 if sets_perdus == 2 else 3
    return 1 if sets_gagnes == 2 else 0


# --- Classement ----------------------------------------------------------------------


@dataclass
class LigneClassement:
    """Statistiques cumulées d'une équipe."""

    equipe_id: str
    nom: str
    joues: int = 0
    gagnes: int = 0
    perdus: int = 0
    points: int = 0
    sets_pour: int = 0
    sets_contre: int = 0
    points_pour: int = 0
    points_contre: int = 0
    forme: list = field(default_factory=list)  # derniers résultats, du plus ancien au plus récent

    @property
    def coeff_sets(self):
        return _quotient(self.sets_pour, self.sets_contre)

    @property
    def coeff_points(self):
        return _quotient(self.points_pour, self.points_contre)


def _quotient(pour, contre):
    if contre == 0:
        return float("inf") if pour > 0 else 0.0
    return pour / contre


def calculer_classement(equipes, matchs, taille_forme=5):
    """Calcule le classement à partir des matchs joués.

    `equipes` : liste de dictionnaires {"id", "nom_court"}.
    `matchs`  : liste de dictionnaires {"domicile", "exterieur", "date", "sets"},
                où "sets" est une liste de tuples (points_domicile, points_exterieur),
                vide si le match n'est pas encore joué.

    Ordre du classement (RPE Régionale 2 masculine, art. 13) : points, puis nombre de victoires,
    puis coefficient de sets (sets gagnés / perdus), puis coefficient de points (marqués / encaissés).
    """
    lignes = {e["id"]: LigneClassement(e["id"], e["nom_court"]) for e in equipes}
    noms = {e["id"]: e["nom_court"] for e in equipes}

    for match in sorted(matchs, key=lambda m: (m["date"], m.get("heure", ""))):
        if not match["sets"]:
            continue
        sets_dom, sets_ext = score_en_sets(match["sets"])
        pts_dom = sum(d for d, _ in match["sets"])
        pts_ext = sum(e for _, e in match["sets"])

        for equipe, adversaire, gagnes, perdus, marques, encaisses in (
            (match["domicile"], match["exterieur"], sets_dom, sets_ext, pts_dom, pts_ext),
            (match["exterieur"], match["domicile"], sets_ext, sets_dom, pts_ext, pts_dom),
        ):
            ligne = lignes[equipe]
            victoire = gagnes == SETS_GAGNANTS
            ligne.joues += 1
            ligne.gagnes += victoire
            ligne.perdus += not victoire
            ligne.points += points_classement(gagnes, perdus)
            ligne.sets_pour += gagnes
            ligne.sets_contre += perdus
            ligne.points_pour += marques
            ligne.points_contre += encaisses
            ligne.forme.append({
                "victoire": victoire,
                "score": f"{gagnes}-{perdus}",
                "adversaire": noms[adversaire],
            })

    for ligne in lignes.values():
        ligne.forme = ligne.forme[-taille_forme:]

    return sorted(
        lignes.values(),
        key=lambda l: (-l.points, -l.gagnes, -l.coeff_sets, -l.coeff_points, l.nom.lower()),
    )
