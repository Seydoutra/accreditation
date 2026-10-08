# État de la correction

## Réalisé dans le noyau

Sessions serveur, mot de passe vérifié, OTP e-mail avec expiration et usage unique,
isolation des dossiers, validation et conservation des réponses et fichiers,
consentement explicite, publication persistante des événements, dates et quotas
transactionnels, décisions contrôlées, révocation distincte, badges avec QR
aléatoire, contrôles serveur et journal, CSV neutralisant les formules,
impression dédiée, labels associés, HTML construit sans injection de saisies,
caméra arrêtée après capture ou navigation. La bibliothèque QR initiale est
conservée une seule fois dans le portail servi. Aucune dépendance CDN.

## À développer, sans fausse confirmation de réussite

1. Permissions par rôle et événement : organisateur, valideur, agent de contrôle,
   protocole et auditeur. Actuellement, tout administrateur voit tous les événements.
2. Populations configurables : questions, justificatifs, règles de décision et droits
   d’accès par zone. Actuellement cinq catégories fixes et validation manuelle.
3. Logistique : affectations hôtels/transport, visas, véhicules, visites et quotas
   de prestations, avec objets persistants et historique.
4. Délégations, créneaux et programme ; tests des capacités et chevauchements.
5. Notifications de décisions : SMTP ou fournisseur SMS, suivi des erreurs et reprises.
6. Contrôle hors ligne : téléchargement signé de droits, expiration, file locale,
   politique de révocation et résolution des conflits. Aucun repli local silencieux.
7. Impression professionnelle et Wallet : intégrations et validation des formats.
8. Gouvernance : conservation et suppression des pièces, traces de consultation,
   antivirus, sauvegardes chiffrées et restauration.
9. Exploitation : serveur HTTP de production, limites au proxy, supervision,
   pagination, tests de charge et tests sur lecteurs et téléphones réels.

La maquette 3D demeure consultable dans le fichier de référence. Elle est exclue
du parcours opérationnel : son QR décoratif et son animation ne doivent pas
être confondus avec un badge valide.
