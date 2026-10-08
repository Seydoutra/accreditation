# Portail d’accréditation — Guinée

Le portail permet de publier des événements, déposer un dossier avec justificatifs,
examiner les demandes, délivrer un badge et vérifier sa validité à l’entrée.
Les décisions et les contrôles sont enregistrés dans un journal.

Le fichier initial est conservé dans `demo/portail-original.html` pour référence.
Cette démonstration contient des fonctions simulées ; elle **n’est pas servie** par
le serveur et ne doit pas recevoir de données personnelles réelles.

## Démarrage local

Python 3.9 ou supérieur, sans installation de dépendances :

```sh
python3 server.py --create-admin admin@example.org
python3 server.py --dev
```

Ouvrir http://127.0.0.1:3000. Créer puis publier un événement depuis
« Connexion → Connexion administrateur ». Aucun événement historique ni compte
de démonstration n’est injecté dans la base.

En mode `--dev`, les codes de connexion sont explicitement affichés dans le
navigateur. Ce mode n’est autorisé que sur une interface locale. En production,
les codes sont envoyés par SMTP et ne sont jamais renvoyés au client.

## Vérification

```sh
python3 -m unittest discover -s tests -v
```

Les tests vérifient les permissions, l’isolation des participants, les pièces
privées, les quotas concurrents, l’expiration et l’usage unique des codes, les
décisions, la révocation, les dates, la persistance et les protections HTTP.

Le workflow GitHub Actions exécute également `tests/browser.cjs` dans Chromium :
création d’événement, connexion par code, soumission, approbation, badge QR,
impression, largeur mobile et affichage d’un titre contenant du HTML hostile.
Ce scénario s’exécute sur une base de test locale, jamais sur une base réelle.

## Production

Placer le serveur derrière un reverse proxy HTTPS sur le même domaine. Le proxy
doit conserver le `Host` public et transmettre `Origin` sans modification.
Les fichiers statiques et l’API doivent rester sur la même origine.

Variables requises :

```sh
export PNA_ORIGIN=https://votre-domaine.example
export SMTP_HOST=smtp.votre-fournisseur.example
export SMTP_PORT=587
export SMTP_FROM=accreditation@votre-domaine.example
# Si le serveur SMTP demande une connexion : SMTP_USER et SMTP_PASSWORD.
# Facultatif : PNA_DB=/chemin/prive/pna.sqlite3
python3 server.py
```

Ne pas placer la base SQLite dans un dossier public. Utiliser un compte système
dédié et des permissions privées. Sauvegarder la base et tester sa restauration.
Les mots de passe administrateurs sont hachés avec PBKDF2-HMAC-SHA256 (600 000
itérations et sel aléatoire individuel). Les cookies de session
sont HttpOnly, SameSite=Strict et Secure en production, avec une durée de 8 heures.
Les données personnelles ne sont pas conservées dans localStorage.

Le serveur Python fourni convient au développement et à un pilote supervisé.
Il ne constitue pas à lui seul une infrastructure de production dimensionnée.
Les limites de requêtes sont basées sur l’adresse réseau directement connectée :
derrière un proxy, elles peuvent être communes aux utilisateurs. Configurer
également les limites, délais et tailles de requêtes au niveau du proxy.
Ne jamais activer `--dev` sur un service accessible au public.

## Comportement métier

- Une adresse e-mail vérifiée possède ses dossiers ; un administrateur peut les examiner.
- Une seule demande active par participant et événement.
- Les demandes en attente et approuvées réservent une place. Refus et révocation la libèrent.
- Les catégories et leurs questions obligatoires sont validées côté serveur.
- Les réponses, pièces et consentement horodaté sont conservés dans la base.
- Chaque fichier est limité à 2 Mo ; JPEG, PNG et PDF sont acceptés. Les signatures
  de format sont contrôlées, mais cela ne remplace pas un antivirus.
- Seul un dossier approuvé délivre un badge. Le QR contient un jeton aléatoire,
  pas des données personnelles ou une référence prévisible.
- Le contrôle nécessite une session administrateur, le bon événement et une date
  comprise entre son début et sa fin. La révocation est prise en compte immédiatement.
- Le scan caméra utilise BarcodeDetector lorsqu’il est disponible. Un lecteur QR
  externe ou la saisie du code restent possibles sur les autres navigateurs.
- L’impression utilise le navigateur avec une feuille de style dédiée au badge.
- Les écritures exigent une connexion serveur ; aucune réussite hors ligne n’est annoncée.

## Périmètre restant

Les fonctions logistiques de la maquette (visas, hôtels, véhicules, visites,
délégations, créneaux, programmation, communications automatisées), le Wallet,
les modèles d’impression professionnels, les quotas personnalisables par
population, les rôles fins par événement et la synchronisation hors ligne ne
sont pas réalisés dans cette version. Voir `docs/ROADMAP.md`.

Avant une exploitation officielle, définir les responsables, durées de
conservation, procédures de suppression, mentions de confidentialité, permissions
par agent et règles de contrôle des documents. Configurer la messagerie réelle,
tester le déploiement, les sauvegardes, la charge et les terminaux de scan.
