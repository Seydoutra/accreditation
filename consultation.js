'use strict';
// Version distincte de consultation. Aucun appel au serveur et aucune écriture persistante.
window.PNA_CONSULTATION = (() => {
  let role = 'citizen';
  const participant = 'participant@exemple.test';
  const categories = {
    VVIP: ['Titre / rang protocolaire', 'Institution / pays'], VIP: ['Titre / institution'],
    Intervenant: ['Sujet d’intervention', 'Biographie courte'],
    'Délégué': ['Organisation', 'Fonction officielle'], Presse: ['Média / rédaction', 'Type de média']
  };
  const documents = { VVIP: [], VIP: [], Intervenant: ['Photo professionnelle'],
    'Délégué': ['Pièce d’identité'], Presse: ['Carte de presse'] };
  const future = days => new Date(Date.now() + days * 86400000).toISOString();
  const events = [
    { id: 'forum-demo', title: 'Forum de démonstration — Conakry', venue: 'Conakry · Lieu fictif', starts: future(7), ends: future(9), deadline: future(5),
      description: 'Événement fictif pour consulter le parcours d’accréditation. Découvrez les catégories, le formulaire, le suivi des dossiers et le badge.', published: true, open: true,
      quotas: { VVIP: 20, VIP: 40, Intervenant: 30, 'Délégué': 120, Presse: 80 },
      used: { VVIP: 6, VIP: 13, Intervenant: 24, 'Délégué': 48, Presse: 80 } },
    { id: 'conference-demo', title: 'Conférence de démonstration — Institutions', venue: 'Kaloum · Lieu fictif', starts: future(15), ends: future(16), deadline: future(12),
      description: 'Deuxième exemple pour examiner le filtrage des dossiers par événement. Toutes les informations sont fictives.', published: true, open: true,
      quotas: { VVIP: 10, VIP: 20, Intervenant: 15, 'Délégué': 80, Presse: 40 },
      used: { VVIP: 2, VIP: 4, Intervenant: 3, 'Délégué': 14, Presse: 5 } }
  ];
  const make = (ref, event, name, email, category, status, answers, reason = '') => ({
    ref, event_id: event.id, name, email, category, status, answers, reason, files: [], phone: '',
    title: event.title, venue: event.venue, starts: event.starts, ends: event.ends,
    created: new Date().toISOString(), ...(status === 'approved' ? { verify_token: 'DEMONSTRATION-BADGE-2026-001' } : {})
  });
  const requests = [
    make('GN-DEMO-001', events[0], 'Participant Exemple', participant, 'VIP', 'approved', { 'Titre / institution': 'Institution de démonstration' }),
    make('GN-DEMO-002', events[1], 'Participant Exemple', participant, 'Délégué', 'pending', { Organisation: 'Organisation de démonstration', 'Fonction officielle': 'Délégué — exemple' }),
    make('GN-DEMO-003', events[0], 'Intervenante Exemple', 'intervenante@exemple.test', 'Intervenant', 'pending', { 'Sujet d’intervention': 'Présentation de démonstration', 'Biographie courte': 'Profil fictif utilisé pour la consultation.' }),
    make('GN-DEMO-004', events[0], 'Journaliste Exemple', 'presse@exemple.test', 'Presse', 'refused', { 'Média / rédaction': 'Média de démonstration', 'Type de média': 'Rédaction' }, 'Exemple de refus : justificatif incomplet.'),
    make('GN-DEMO-005', events[1], 'Invité Exemple', 'invite@exemple.test', 'VIP', 'revoked', { 'Titre / institution': 'Institution de démonstration' }, 'Exemple de révocation : badge déclaré perdu.')
  ];
  function identity() { return { email: role === 'admin' ? 'administration@exemple.test' : participant, role }; }
  async function api(path, method, body) {
    const [resource, query] = path.split('?');
    if (method !== 'GET') {
      if (resource === 'verify' && method === 'POST') return {
        valid: body.eventId === events[0].id && body.token === 'DEMONSTRATION-BADGE-2026-001',
        name: body.token === 'DEMONSTRATION-BADGE-2026-001' ? 'Participant Exemple · Démonstration' : null, category: 'VIP'
      };
      throw new Error('Version de consultation : aucune modification ni donnée personnelle n’est enregistrée.');
    }
    if (resource === 'config') return { categories, documents, development: false };
    if (resource === 'me') return identity();
    if (resource === 'events') return structuredClone(events);
    if (resource === 'requests') {
      const event = new URLSearchParams(query).get('eventId');
      return structuredClone(requests.filter(r => (role === 'admin' || r.email === participant) && (!event || r.event_id === event)));
    }
    if (resource === 'audit') return [
      { created: new Date().toISOString(), actor: 'administration@exemple.test', action: 'Exemple : dossier approuvé', ref: 'GN-DEMO-001' },
      { created: new Date().toISOString(), actor: participant, action: 'Exemple : dossier déposé', ref: 'GN-DEMO-002' },
      { created: new Date().toISOString(), actor: 'administration@exemple.test', action: 'Exemple : badge révoqué', ref: 'GN-DEMO-005' }
    ];
    throw new Error('Écran de consultation indisponible.');
  }
  function login({ main, heading, button, state, route }) {
    heading('Choisir une vue de consultation');
    const p = document.createElement('p'); p.textContent = 'Explorez le parcours participant ou le tableau de bord avec des exemples fictifs. Aucun identifiant ou mot de passe n’est nécessaire.';
    main.append(p);
    for (const [value, label, hash] of [['citizen', 'Vue participant', '#requests'], ['admin', 'Vue administration', '#admin']]) {
      main.append(button(label, () => {
        role = value; state.user = identity(); document.getElementById('admin-link').hidden = role !== 'admin'; location.hash = hash;
      }));
    }
  }
  return { api, login };
})();
