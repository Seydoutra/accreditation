'use strict';
const main = document.getElementById('content');
const message = document.getElementById('message');
const state = { user: null, config: null, events: [], stream: null, render: 0 };
const labels = { pending: 'En attente', approved: 'Approuvée', refused: 'Refusée', revoked: 'Révoquée' };
// Aucune saisie utilisateur n'est interprétée comme du HTML.
function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child != null) node.append(child);
  return node;
}
function notice(text, error = false) { message.textContent = text; message.className = error ? 'error' : 'success'; }
async function api(path, method = 'GET', body) {
  if (window.PNA_CONSULTATION) return window.PNA_CONSULTATION.api(path, method, body);
  let response;
  try {
    response = await fetch('/api/' + path, { method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined });
  } catch (_) { throw new Error('Serveur inaccessible. Le résultat de l’opération est inconnu. Rechargez vos demandes avant de réessayer.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Opération impossible.');
  return data;
}
function button(text, action, cls = '') { return el('button', { type: 'button', text, class: cls, onclick: action }); }
function link(text, hash) { return el('a', { href: '#' + hash, text, class: 'button' }); }
function field(form, name, label, type = 'text', value = '', required = true) {
  const id = 'field-' + name;
  const input = el(type === 'textarea' ? 'textarea' : 'input', { id, name, ...(type === 'textarea' ? {} : { type }), value, required });
  form.append(el('label', { htmlFor: id, text: label }), input);
  return input;
}
function heading(text) { main.replaceChildren(el('h1', { text })); }
function date(value) { return new Intl.DateTimeFormat('fr', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Africa/Conakry' }).format(new Date(value)); }
async function act(btn, work) {
  btn.disabled = true;
  try { await work(); } catch (error) { notice(error.message, true); }
  finally { btn.disabled = false; }
}
function stopCamera() { if (state.stream) state.stream.getTracks().forEach(t => t.stop()); state.stream = null; }
async function refreshIdentity() {
  try { state.user = await api('me'); }
  catch (_) { state.user = null; }
  document.getElementById('admin-link').hidden = state.user?.role !== 'admin';
}
function needUser(admin = false) {
  if (!state.user || (admin && state.user.role !== 'admin')) {
    heading('Connexion requise'); main.append(link('Se connecter', 'login')); return false;
  }
  return true;
}
function login() {
  if (window.PNA_CONSULTATION) return window.PNA_CONSULTATION.login({main, heading, button, state, route});
  heading('Connexion');
  if (state.user) {
    main.append(el('p', { text: 'Connecté : ' + state.user.email }), button('Se déconnecter', async e => {
      await act(e.currentTarget, async () => { await api('logout', 'POST', {}); await refreshIdentity(); login(); });
    })); return;
  }
  const form = el('form', { class: 'card form' });
  const address = field(form, 'email', 'Adresse e-mail', 'email'); address.autocomplete = 'email';
  const admin = el('input', { type: 'checkbox', id: 'is-admin' });
  form.append(el('label', { htmlFor: 'is-admin' }, admin, ' Connexion administrateur'));
  const password = field(form, 'password', 'Mot de passe administrateur', 'password', '', false);
  password.autocomplete = 'current-password'; password.hidden = true; password.previousSibling.hidden = true;
  admin.onchange = () => { password.hidden = !admin.checked; password.previousSibling.hidden = !admin.checked; password.required = admin.checked; };
  const submit = el('button', { type: 'submit', text: 'Continuer' }); form.append(submit);
  form.onsubmit = e => { e.preventDefault(); act(submit, async () => {
    if (admin.checked) {
      await api('login', 'POST', { email: address.value, password: password.value });
      await refreshIdentity(); location.hash = '#admin';
    } else {
      const target = address.value;
      const result = await api('otp', 'POST', { email: target });
      form.replaceChildren(el('p', { text: result.developmentCode ? 'Code de test local généré. Il expire dans 5 minutes.' : 'Code envoyé par e-mail. Il expire dans 5 minutes.' }));
      if (result.developmentCode) form.append(el('p', { class: 'notice', text: 'Développement local — code : ' + result.developmentCode }));
      const code = field(form, 'code', 'Code à 6 chiffres', 'text'); code.pattern = '[0-9]{6}'; code.maxLength = 6; code.autocomplete = 'one-time-code'; code.inputMode = 'numeric';
      submit.textContent = 'Vérifier le code'; form.append(submit);
      form.onsubmit = event => { event.preventDefault(); act(submit, async () => {
        await api('otp/verify', 'POST', { email: target, code: code.value }); await refreshIdentity(); location.hash = '#requests';
      }); };
    }
  }); };
  main.append(form);
}
function events() {
  heading('Événements');
  main.append(el('p', { class: 'lead', text: 'Explorez les événements, le formulaire et les dossiers fictifs de cette version de consultation.' }));
  const grid = el('div', { class: 'grid' });
  for (const ev of state.events.filter(e => e.published)) grid.append(el('article', { class: 'card' },
    el('span', { class: 'tag', text: ev.open ? 'Inscriptions ouvertes' : 'Inscriptions closes' }),
    el('h2', { text: ev.title }), el('p', { text: ev.venue }), el('p', { text: date(ev.starts) + ' — ' + date(ev.ends) }),
    link('Voir l’événement', 'event/' + ev.id)));
  main.append(grid);
  if (!grid.childElementCount) main.append(el('p', { text: 'Aucun événement publié pour le moment.' }));
}
function detail(id) {
  const ev = state.events.find(e => e.id === id);
  if (!ev) return heading('Événement introuvable');
  heading(ev.title);
  main.append(el('p', { text: ev.venue + ' · ' + date(ev.starts) + ' — ' + date(ev.ends) }),
    el('p', { text: ev.description }), el('p', { text: 'Clôture des inscriptions : ' + date(ev.deadline) }));
  const list = el('ul');
  for (const [cat, quota] of Object.entries(ev.quotas)) list.append(el('li', { text: cat + ' : ' + Math.max(0, quota - (ev.used[cat] || 0)) + ' place(s) disponible(s)' }));
  main.append(list);
  if (ev.open) main.append(link('Consulter le formulaire', 'apply/' + id));
}
async function fileValue(file, kind) {
  if (!file || !file.size) return null;
  if (file.size > 2 * 1024 * 1024) throw new Error('Chaque fichier doit faire au plus 2 Mo.');
  if (!['image/jpeg', 'image/png', 'application/pdf'].includes(file.type)) throw new Error('Formats acceptés : JPEG, PNG, PDF.');
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(new Error('Lecture du fichier impossible.')); reader.readAsDataURL(file);
  });
  return { name: file.name, kind, data };
}
function apply(id) {
  if (!needUser()) return;
  const ev = state.events.find(e => e.id === id);
  if (!ev?.open) return heading('Inscriptions indisponibles');
  heading('Demande pour ' + ev.title);
  const form = el('form', { class: 'card form' });
  const name = field(form, 'name', 'Nom complet'); name.maxLength = 250; name.autocomplete = 'name';
  const phone = field(form, 'phone', 'Téléphone (facultatif)', 'tel', '', false); phone.autocomplete = 'tel';
  form.append(el('label', { htmlFor: 'category', text: 'Catégorie' }));
  const category = el('select', { id: 'category', required: true }, el('option', { value: '', text: 'Choisissez une catégorie' }));
  for (const [cat, quota] of Object.entries(ev.quotas)) category.append(el('option', { value: cat, text: cat, disabled: quota <= (ev.used[cat] || 0) }));
  const dynamic = el('fieldset', {}, el('legend', { text: 'Informations et justificatifs' }));
  let answers = {}, files = {}, captured = null;
  category.onchange = () => {
    stopCamera(); captured = null; answers = {}; files = {}; dynamic.replaceChildren(el('legend', { text: 'Informations et justificatifs' }));
    if (!category.value) return;
    state.config.categories[category.value].forEach((label, i) => { answers[label] = field(dynamic, 'answer-' + i, label); answers[label].maxLength = 3000; });
    for (const [i, kind] of ['Photo', ...state.config.documents[category.value]].entries()) {
      const input = field(dynamic, 'file-' + i, kind + (kind === 'Photo' ? ' (facultatif)' : ' (requis)'), 'file', '', kind !== 'Photo');
      input.disabled = true; input.accept = kind === 'Photo' ? 'image/jpeg,image/png' : 'image/jpeg,image/png,application/pdf'; files[kind] = input;
    }
    dynamic.append(el('p', { text: 'Maximum 2 Mo par fichier. Formats : JPEG, PNG et PDF.' }));
    const video = el('video', { autoplay: true, muted: true, playsInline: true, hidden: true });
    const preview = el('img', { alt: 'Photo capturée', hidden: true, width: 120 });
    const snap = button('Prendre la photo', () => {
      if (!video.videoWidth) return notice('La caméra n’est pas encore prête.', true);
      const canvas = el('canvas', { width: Math.min(800, video.videoWidth), height: Math.round(Math.min(800, video.videoWidth) * video.videoHeight / video.videoWidth) });
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/jpeg', 0.85); captured = { name: 'photo.jpg', kind: 'Photo', data: data.split(',')[1] };
      preview.src = data; preview.hidden = false; stopCamera(); video.hidden = true; snap.hidden = true;
    }); snap.hidden = true;
    /* Caméra non activée dans la version de consultation. */
    const cameraButton = button('Utiliser la caméra', async e => act(e.currentTarget, async () => {
      stopCamera(); const version = state.render; const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      if (version !== state.render || !video.isConnected) { stream.getTracks().forEach(t => t.stop()); return; }
      state.stream = stream;
      video.srcObject = state.stream; video.hidden = false; snap.hidden = false;
    }), 'secondary');
  };
  const consent = el('input', { type: 'checkbox', id: 'consent', required: true });
  const submit = el('button', { type: 'submit', text: 'Envoi désactivé — consultation', disabled: true });
  form.append(category, dynamic, el('label', { htmlFor: 'consent' }, consent, ' Je certifie l’exactitude des informations et j’accepte leur traitement pour cette accréditation.'), submit);
  form.onsubmit = e => { e.preventDefault(); act(submit, async () => {
    const attachments = [];
    for (const [kind, input] of Object.entries(files)) {
      const f = await fileValue(input.files[0], kind); if (f) attachments.push(f);
      else if (kind === 'Photo' && captured) attachments.push(captured);
    }
    const result = await api('requests', 'POST', { eventId: id, name: name.value, phone: phone.value,
      category: category.value, consent: consent.checked, answers: Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, v.value])), files: attachments });
    stopCamera(); notice('Dossier enregistré : ' + result.ref); location.hash = '#requests';
  }); };
  main.append(form);
}
async function requests(admin = false) {
  if (!needUser(admin)) return;
  heading(admin ? 'Administration' : 'Mes demandes');
  let filter = '';
  if (admin) {
    main.append(link('Créer un événement', 'create'), link('Journal des opérations', 'audit'));
    const select = el('select', { id: 'event-filter' }, el('option', { value: '', text: 'Tous les événements' }));
    state.events.forEach(ev => select.append(el('option', { value: ev.id, text: ev.title })));
    main.append(el('label', { htmlFor: 'event-filter', text: 'Événement' }), select);
    main.append(el('div', { class: 'actions' }, el('a', { href: './exemple-dossiers.csv', text: 'Télécharger les exemples (CSV)', id: 'csv' }),
      button('Contrôler un badge', () => { if (!select.value) return notice('Choisissez d’abord un événement.', true); location.hash = '#verify/' + select.value; })));
    const management = el('div', { class: 'actions' });
    state.events.forEach(ev => management.append(link('Modifier : ' + ev.title, 'edit/' + ev.id))); main.append(management);
    select.onchange = async () => { filter = select.value; document.getElementById('csv').href = './exemple-dossiers.csv'; await load(); };
  }
  const box = el('div'); main.append(box);
  async function load() {
    try {
      const list = await api('requests' + (filter ? '?eventId=' + encodeURIComponent(filter) : ''));
      box.replaceChildren();
      if (admin) box.append(el('p', { text: `${list.length} dossier(s) · ${list.filter(r => r.status === 'pending').length} en attente · ${list.filter(r => r.status === 'approved').length} approuvé(s)` }));
      for (const r of list) {
        const card = el('article', { class: 'card' }, el('span', { class: 'tag', text: labels[r.status] }),
          el('h2', { text: r.name }), el('p', { text: r.title + ' · ' + r.category }), el('p', { text: r.ref + ' · ' + r.email }));
        if (r.reason) card.append(el('p', { text: 'Motif : ' + r.reason }));
        const details = el('details', {}, el('summary', { text: 'Consulter le dossier' }));
        const dl = el('dl'); Object.entries(r.answers).forEach(([k, v]) => dl.append(el('dt', { text: k }), el('dd', { text: v })));
        details.append(dl);
        r.files.forEach((f, i) => details.append(el('p', {}, el('a', { href: '/api/files/' + encodeURIComponent(r.ref) + '/' + i, text: f.kind + ' : ' + f.name })))); card.append(details);
        const actions = el('div', { class: 'actions' });
        if (r.status === 'approved') actions.append(link('Voir le badge', 'badge/' + r.ref));
        if (!window.PNA_CONSULTATION && admin && ['pending', 'approved'].includes(r.status)) {
          for (const status of r.status === 'pending' ? ['approved', 'refused'] : ['revoked']) actions.append(button(labels[status], async e => {
            const reason = status === 'approved' ? '' : prompt('Motif de la décision :'); if (reason === null) return;
            await act(e.currentTarget, async () => { await api('requests/' + r.ref, 'PATCH', { status, reason }); notice('Décision enregistrée.'); await load(); });
          }, status === 'approved' ? '' : 'danger'));
        }
        card.append(actions); box.append(card);
      }
      if (!list.length) box.append(el('p', { text: 'Aucun dossier.' }));
    } catch (error) { notice(error.message, true); }
  }
  await load();
}
async function badge(ref) {
  if (!needUser()) return;
  const list = await api('requests'); const r = list.find(d => d.ref === ref);
  if (!r || r.status !== 'approved') return heading('Badge indisponible');
  heading('Exemple de badge');
  const card = el('article', { class: 'badge printable' }, el('h2', { text: r.title }), el('p', { class: 'name', text: r.name }),
    el('p', { text: r.category }), el('p', { text: r.ref }), el('p', { text: r.venue }), el('p', { text: date(r.starts) + ' — ' + date(r.ends) }));
  const i = r.files.findIndex(f => f.kind === 'Photo' || f.kind === 'Photo professionnelle');
  if (i >= 0 && r.files[i].mime.startsWith('image/')) card.prepend(el('img', { src: '/api/files/' + encodeURIComponent(r.ref) + '/' + i, alt: 'Photo du titulaire' }));
  card.append(el('p', { text: 'Code de contrôle à présenter à l’agent :' }), el('code', { text: r.verify_token }), el('p', { text: 'Badge fictif présenté pour la consultation. Il ne donne accès à aucun événement.' }));
  const qr = qrcode(0, 'M'); qr.addData(r.verify_token); qr.make();
  card.append(el('img', { class: 'qr', alt: 'QR code de contrôle du badge', src: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(qr.createSvgTag({ scalable: true, margin: 4 })) }));
  main.append(card, button('Imprimer le badge', () => window.print(), 'no-print'));
}
function eventForm(id) {
  if (!needUser(true)) return;
  const existing = state.events.find(e => e.id === id);
  if (id && !existing) return heading('Événement introuvable');
  heading(id ? 'Modifier un événement' : 'Créer un événement');
  const form = el('form', { class: 'card form' });
  const title = field(form, 'title', 'Titre', 'text', existing?.title || '');
  const venue = field(form, 'venue', 'Lieu', 'text', existing?.venue || '');
  const dates = {};
  for (const [key, label] of [['starts','Début'],['ends','Fin'],['deadline','Clôture des inscriptions']]) {
    dates[key] = field(form, key, label + ' (heure de Guinée, UTC)', 'datetime-local', existing?.[key]?.slice(0, 16) || '');
  }
  const description = field(form, 'description', 'Présentation', 'textarea', existing?.description || '', false);
  const quotas = {};
  for (const cat of Object.keys(state.config.categories)) { quotas[cat] = field(form, 'quota-' + cat, 'Quota ' + cat, 'number', existing?.quotas[cat] ?? 50); quotas[cat].min = 0; quotas[cat].max = 100000; }
  const published = el('input', { id: 'published', type: 'checkbox', checked: existing?.published || false });
  const submit = el('button', { type: 'submit', text: 'Enregistrement désactivé — consultation', disabled: true });
  form.append(el('label', { htmlFor: 'published' }, published, ' Publier l’événement'), submit);
  form.onsubmit = e => { e.preventDefault(); act(submit, async () => {
    await api(id ? 'events/' + id : 'events', id ? 'PATCH' : 'POST', { title: title.value, venue: venue.value, description: description.value,
      ...Object.fromEntries(Object.entries(dates).map(([k, v]) => [k, v.value + ':00+00:00'])),
      quotas: Object.fromEntries(Object.entries(quotas).map(([k, v]) => [k, Number(v.value)])), published: published.checked });
    notice('Événement enregistré.'); location.hash = '#admin';
  }); }; main.append(form);
}
function verify(id) {
  if (!needUser(true)) return;
  const ev = state.events.find(e => e.id === id); if (!ev) return heading('Événement introuvable');
  heading('Contrôle d’accès — ' + ev.title);
  const form = el('form', { class: 'card form' }); const token = field(form, 'token', 'Code de contrôle du badge');
  const submit = el('button', { type: 'submit', text: 'Vérifier l’accès' }); const verdict = el('p', { role: 'status' }); form.append(submit, verdict);
  if (!window.PNA_CONSULTATION && 'BarcodeDetector' in window) {
    const video = el('video', { autoplay: true, muted: true, playsInline: true, hidden: true });
    form.append(button('Scanner le QR avec la caméra', async e => act(e.currentTarget, async () => {
      stopCamera(); const detector = new BarcodeDetector({ formats: ['qr_code'] }); const version = state.render;
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      if (version !== state.render || !video.isConnected) { stream.getTracks().forEach(t => t.stop()); return; }
      state.stream = stream;
      video.srcObject = state.stream; video.hidden = false;
      const scan = async () => {
        if (!state.stream || !video.isConnected) return;
        try {
          const results = video.readyState >= 2 ? await detector.detect(video) : [];
          if (results.length) { token.value = results[0].rawValue; stopCamera(); video.hidden = true; form.requestSubmit(); return; }
          setTimeout(scan, 300);
        } catch (error) { stopCamera(); video.hidden = true; notice('Lecture caméra indisponible. Saisissez le code du badge.', true); }
      }; scan();
    }), 'secondary'), video);
  } else form.append(el('p', { text: 'Utilisez un lecteur QR externe ou copiez le code du badge. Le scan caméra dépend du navigateur.' }));
  form.onsubmit = e => { e.preventDefault(); act(submit, async () => {
    const result = await api('verify', 'POST', { eventId: id, token: token.value });
    verdict.className = result.valid ? 'success' : 'error'; verdict.textContent = (result.valid ? 'Exemple : badge reconnu' : 'Exemple : badge non reconnu') + (result.name ? ' · ' + result.name + ' · ' + result.category : ' · Badge inconnu');
  }); }; main.append(form);
}
async function audit() {
  if (!needUser(true)) return; heading('Journal des opérations');
  const rows = await api('audit'); const table = el('table', {}, el('caption', { text: '200 dernières opérations' }));
  table.append(el('thead', {}, el('tr', {}, ['Date','Acteur','Action','Référence'].map(text => el('th', { scope: 'col', text })))));
  table.append(el('tbody', {}, rows.map(r => el('tr', {}, [date(r.created),r.actor,r.action,r.ref].map(text => el('td', { text }))))));
  main.append(el('div', { class: 'table-wrap' }, table));
}
async function route() {
  stopCamera(); const version = ++state.render;
  try {
    state.events = await api('events'); if (version !== state.render) return;
    const [page, id] = (location.hash.slice(1) || 'events').split('/');
    const routes = { events, event: () => detail(id), apply: () => apply(id), login,
      requests: () => requests(), admin: () => requests(true), create: () => eventForm(),
      edit: () => eventForm(id), badge: () => badge(id), verify: () => verify(id), audit };
    await (routes[page] || (() => heading('Page introuvable')))();
    document.title = (main.querySelector('h1')?.textContent || 'Portail') + ' · Accréditation'; main.focus();
  } catch (error) { notice(error.message, true); }
}
window.addEventListener('hashchange', route);
window.addEventListener('pagehide', stopCamera);
(async () => {
  try {
    state.config = await api('config'); await refreshIdentity();
    if (state.config.development) { const p = document.getElementById('environment'); p.hidden = false; p.textContent = 'Mode développement local : les codes de connexion sont affichés pour les essais.'; }
    await route();
  } catch (error) { notice(error.message, true); }
})();
