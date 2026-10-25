import re


def ordre_classement(client):
    """Identifiants des équipes dans l'ordre du tableau de classement."""
    page = client.get("/").get_data(as_text=True)
    return re.findall(r'data-equipe="([A-Z]+)"', page)


def test_page_classement(client):
    assert ordre_classement(client) == [
        "CARRIERES", "SARTROUVILLE", "VALEUROPE", "BUSSY", "LEVALLOIS",
        "COLOMBES", "FRANCONVILLE", "COURCOURONNES", "ANTONY", "FONTENAY",
    ]


def test_pages_principales(client):
    for url in ["/calendrier", "/calendrier?equipe=BUSSY", "/equipe/BUSSY", "/match/2MCA011/resultat"]:
        assert client.get(url).status_code == 200, url


def test_pages_introuvables(client):
    assert client.get("/equipe/INCONNUE").status_code == 404
    assert client.get("/calendrier?equipe=INCONNUE").status_code == 404
    assert client.get("/match/XXX/resultat").status_code == 404


def formulaire(sets, mot_de_passe="secret"):
    donnees = {"mot_de_passe": mot_de_passe}
    for numero, (domicile, exterieur) in enumerate(sets, start=1):
        donnees[f"set{numero}_domicile"] = str(domicile)
        donnees[f"set{numero}_exterieur"] = str(exterieur)
    return donnees


def test_saisie_d_un_resultat_met_a_jour_le_classement(client):
    # Carrières (1er) perd 0-3 contre Colombes lors de la 3e journée
    reponse = client.post("/match/2MCA011/resultat", data=formulaire([(20, 25), (22, 25), (23, 25)]))

    assert reponse.status_code == 302  # redirection vers le calendrier
    assert "Résultat enregistré" in client.get("/calendrier").get_data(as_text=True)
    # Carrières garde 6 points mais son coefficient de sets baisse : Sartrouville passe devant
    ordre = ordre_classement(client)
    assert ordre.index("SARTROUVILLE") < ordre.index("CARRIERES")


def test_mauvais_mot_de_passe(client):
    reponse = client.post("/match/2MCA011/resultat", data=formulaire([(25, 20), (25, 20), (25, 20)], "faux"))

    assert "Mot de passe incorrect" in reponse.get_data(as_text=True)
    # Le match n'a pas été enregistré : la page propose toujours de saisir le résultat
    assert "Saisir un résultat" in client.get("/match/2MCA011/resultat").get_data(as_text=True)


def test_score_impossible_refuse(client):
    reponse = client.post("/match/2MCA011/resultat", data=formulaire([(25, 24), (25, 20), (25, 20)]))

    page = reponse.get_data(as_text=True)
    assert "il faut au moins 2 points d&#39;écart" in page
    assert 'value="24"' in page  # les valeurs saisies sont conservées


def test_set_saute_refuse(client):
    donnees = formulaire([(25, 20), (25, 20)])
    donnees.update({"set4_domicile": "25", "set4_exterieur": "20"})

    reponse = client.post("/match/2MCA011/resultat", data=donnees)

    assert "sans en sauter" in reponse.get_data(as_text=True)


def test_resume_de_la_poule(client):
    page = client.get("/").get_data(as_text=True)

    assert "J3</strong> en cours" in page
    assert "Carrières-sur-Seine (6 pts)" in page
    assert "Montée en R1 (1er)" in page
    assert "Match de classement (2e)" in page
    assert "Descente (8e à 10e)" in page


def test_export_csv(client):
    reponse = client.get("/export/classement.csv")
    texte = reponse.get_data(as_text=True)
    lignes = texte.lstrip("\ufeff").splitlines()

    assert reponse.mimetype == "text/csv"
    assert "attachment" in reponse.headers["Content-Disposition"]
    assert lignes[0].startswith("Rang;Équipe;Points")
    assert lignes[1].startswith("1;Carrières-sur-Seine;6;2;2;0;6;1;6,00")
    assert len(lignes) == 11
