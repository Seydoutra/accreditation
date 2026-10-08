// npm install --no-save playwright && npx playwright install chromium
// PNA_URL=http://127.0.0.1:3000 PNA_ADMIN_EMAIL=... PNA_ADMIN_PASSWORD=... node tests/browser.cjs
// À lancer sur une base de test locale, en mode --dev. Crée un événement et un dossier.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PNA_BROWSER || chromium.executablePath() });
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const url = process.env.PNA_URL || 'http://127.0.0.1:3000';
  try {
    await page.goto(url + '/#login');
    await page.getByLabel('Adresse e-mail', { exact: true }).fill(process.env.PNA_ADMIN_EMAIL || 'admin@example.org');
    await page.getByLabel('Connexion administrateur').check();
    await page.getByLabel('Mot de passe administrateur').fill(process.env.PNA_ADMIN_PASSWORD || 'browser-test-password-123');
    await page.getByRole('button', { name: 'Continuer', exact: true }).click();
    await page.getByRole('heading', { name: 'Administration', exact: true }).waitFor();
    await page.getByRole('link', { name: 'Créer un événement' }).click();
    const name = 'Forum navigateur ' + Date.now() + ' <img src=x onerror=alert(1)>';
    await page.getByLabel('Titre', { exact: true }).fill(name);
    await page.getByLabel('Lieu', { exact: true }).fill('Conakry');
    const date = days => new Date(Date.now() + days * 86400000).toISOString().slice(0,16);
    await page.getByLabel('Début (heure de Guinée, UTC)', { exact: true }).fill(date(2));
    await page.getByLabel('Fin (heure de Guinée, UTC)', { exact: true }).fill(date(3));
    await page.getByLabel('Clôture des inscriptions (heure de Guinée, UTC)', { exact: true }).fill(date(1));
    await page.getByLabel('Publier l’événement').check();
    await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
    await page.getByRole('heading', { name: 'Administration', exact: true }).waitFor();
    const events = await (await context.request.get(url + '/api/events')).json();
    const ev = events.find(ev => ev.title === name); assert.ok(ev);
    await page.getByRole('link', { name: 'Connexion', exact: true }).click();
    await page.getByRole('button', { name: 'Se déconnecter' }).click();
    await page.getByLabel('Adresse e-mail', { exact: true }).fill('browser-' + Date.now() + '@example.org');
    await page.getByRole('button', { name: 'Continuer', exact: true }).click();
    await page.getByLabel('Code à 6 chiffres').waitFor();
    const codeText = await page.locator('form .notice').textContent();
    await page.getByLabel('Code à 6 chiffres').fill(codeText.match(/\d{6}/)[0]);
    await page.getByRole('button', { name: 'Vérifier le code' }).click();
    await page.getByRole('heading', { name: 'Mes demandes', exact: true }).waitFor();
    await page.goto(url + '/#apply/' + ev.id);
    await page.getByLabel('Nom complet', { exact: true }).fill('Participant test');
    await page.getByLabel('Catégorie', { exact: true }).selectOption('VIP');
    await page.getByLabel('Titre / institution', { exact: true }).fill('Organisation test');
    await page.getByLabel('Je certifie', { exact: false }).check();
    await page.getByRole('button', { name: 'Envoyer le dossier' }).click();
    await page.getByRole('heading', { name: 'Mes demandes', exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Participant test', exact: true }).waitFor();
    let requests = await (await context.request.get(url + '/api/requests')).json();
    assert.equal(requests.length, 1); assert.equal(requests[0].status, 'pending');
    const ref = requests[0].ref;
    const adminContext = await browser.newContext();
    const login = await adminContext.request.post(url + '/api/login', {
      headers: { Origin: url }, data: { email: process.env.PNA_ADMIN_EMAIL || 'admin@example.org', password: process.env.PNA_ADMIN_PASSWORD || 'browser-test-password-123' }
    }); assert.equal(login.status(),200);
    const decision = await adminContext.request.patch(url + '/api/requests/' + ref, { headers: { Origin: url }, data: { status: 'approved' } });
    assert.equal(decision.status(),200);
    await page.reload();
    await page.getByRole('link', { name: 'Voir le badge', exact: true }).click();
    await page.getByRole('heading', { name: 'Badge délivré', exact: true }).waitFor();
    await page.locator('.badge img.qr').waitFor();
    assert.ok(await page.locator('.badge img.qr').evaluate(img => img.complete && img.naturalWidth > 0));
    assert.equal(await page.locator('main img:not(.qr)').count(), 0, 'Le titre HTML doit rester du texte');
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('header').isVisible(),false);
    assert.equal(await page.locator('.badge').isVisible(),true);
    await page.emulateMedia({ media: 'screen' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url + '/#events');
    await page.getByRole('heading', { name: 'Événements', exact: true }).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Pas de débordement horizontal sur mobile');
    assert.deepEqual(errors, []);
    console.log('OK : création, OTP, demande, approbation, badge QR, impression, mobile, titre hostile rendu comme texte.');
    await adminContext.close();
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
