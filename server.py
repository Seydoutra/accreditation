"""Portail d'accréditation. Python 3.9+, SQLite, aucune dépendance externe."""
import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
MAX_BODY = 9 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
CATEGORIES = {
    'VVIP': ['Titre / rang protocolaire', 'Institution / pays'],
    'VIP': ['Titre / institution'],
    'Intervenant': ["Sujet d’intervention", 'Biographie courte'],
    'Délégué': ['Organisation', 'Fonction officielle'],
    'Presse': ['Média / rédaction', 'Type de média'],
}
DOCUMENTS = {'VVIP': [], 'VIP': [], 'Intervenant': ['Photo professionnelle'],
             'Délégué': ["Pièce d’identité"], 'Presse': ['Carte de presse']}


class Error(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def require(condition, message, status=400):
    if not condition:
        raise Error(status, message)


def text(value, label, maximum=250):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum,
            label + ' : valeur manquante ou trop longue.')
    return value.strip()


def email(value):
    value = text(value, 'E-mail', 254).lower()
    require(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value), 'Adresse e-mail invalide.')
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS admins(email TEXT PRIMARY KEY, salt TEXT, digest TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, email TEXT, role TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS otps(email TEXT PRIMARY KEY, salt TEXT, digest TEXT, expires REAL, attempts INTEGER);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, title TEXT, venue TEXT,
                starts TEXT, ends TEXT, deadline TEXT, description TEXT, published INTEGER, quotas TEXT);
            CREATE TABLE IF NOT EXISTS requests(ref TEXT PRIMARY KEY, event_id TEXT, email TEXT,
                name TEXT, category TEXT, status TEXT, created TEXT, payload TEXT, verify_token TEXT UNIQUE,
                reason TEXT DEFAULT '', FOREIGN KEY(event_id) REFERENCES events(id));
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT, action TEXT, ref TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS limits(key TEXT, created REAL);
            CREATE INDEX IF NOT EXISTS limits_key ON limits(key,created);
            CREATE INDEX IF NOT EXISTS requests_owner ON requests(email,event_id);
            ''')
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def limit(self, key, count=5, period=300):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM limits WHERE created < ?', (time.time()-3600,))
            n = db.execute('SELECT count(*) FROM limits WHERE key=? AND created>?',
                           (key, time.time()-period)).fetchone()[0]
            require(n < count, 'Trop de tentatives. Réessayez plus tard.', 429)
            db.execute('INSERT INTO limits VALUES (?,?)', (key, time.time()))

    def admin(self, address, password):
        address = email(address)
        require(len(password) >= 14, 'Le mot de passe doit contenir au moins 14 caractères.')
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO admins VALUES (?,?,?)', (address, salt, digest))

    def login(self, address, password):
        with self.connect() as db:
            row = db.execute('SELECT * FROM admins WHERE email=?', (address,)).fetchone()
        salt = row['salt'] if row else '00'*16
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
        require(row is not None and hmac.compare_digest(digest, row['digest']), 'Identifiants incorrects.', 401)

    def session(self, address, role):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),
                       address, role, time.time()+28800))
        return token

    def identity(self, token):
        with self.connect() as db:
            row = db.execute('SELECT email,role FROM sessions WHERE token=? AND expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        require(row is not None, 'Connexion requise.', 401)
        return dict(row)

    def otp(self, address):
        code, salt = str(secrets.randbelow(900000)+100000), secrets.token_hex(16)
        digest = hashlib.sha256((salt+code).encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO otps VALUES (?,?,?,?,0)',
                       (address, salt, digest, time.time()+300))
        return code

    def verify_otp(self, address, code):
        valid = False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM otps WHERE email=?', (address,)).fetchone()
            if row and row['expires'] > time.time() and row['attempts'] < 5:
                valid = hmac.compare_digest(hashlib.sha256((row['salt']+code).encode()).hexdigest(), row['digest'])
                if valid:
                    db.execute('DELETE FROM otps WHERE email=?', (address,))
                else:
                    db.execute('UPDATE otps SET attempts=attempts+1 WHERE email=?', (address,))
        require(valid, 'Code invalide ou expiré.', 401)

    @staticmethod
    def event_row(row):
        value = dict(row)
        value['quotas'] = json.loads(value['quotas'])
        value['published'] = bool(value['published'])
        return value

    def events(self, admin=False):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events '+('' if admin else 'WHERE published=1 ')+
                              'ORDER BY starts').fetchall()
            events = []
            for row in rows:
                value = self.event_row(row)
                value['used'] = {r['category']: r['n'] for r in db.execute(
                    "SELECT category,count(*) n FROM requests WHERE event_id=? AND status IN ('pending','approved') GROUP BY category",
                    (row['id'],))}
                value['open'] = value['published'] and datetime.fromisoformat(value['deadline']) > datetime.now(timezone.utc)
                events.append(value)
        return events

    def save_event(self, data, actor, event_id=None):
        title, venue = text(data.get('title'), 'Titre'), text(data.get('venue'), 'Lieu')
        dates = []
        for field in ['starts', 'ends', 'deadline']:
            try:
                date = datetime.fromisoformat(data[field])
                require(date.tzinfo is not None, 'Fuseau horaire requis.')
                dates.append(date.astimezone(timezone.utc))
            except (ValueError, KeyError, TypeError):
                raise Error(400, 'Date invalide : '+field)
        require(dates[0] <= dates[1] and dates[2] <= dates[0], 'Ordre des dates invalide.')
        quotas = data.get('quotas')
        require(isinstance(quotas, dict) and set(quotas) == set(CATEGORIES), 'Quotas incomplets.')
        require(all(type(v) is int and 0 <= v <= 100000 for v in quotas.values()), 'Quota invalide.')
        description = data.get('description', '')
        require(isinstance(description, str) and len(description) <= 10000, 'Description trop longue.')
        require(type(data.get('published')) is bool, 'Statut de publication invalide.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if event_id:
                require(db.execute('SELECT id FROM events WHERE id=?', (event_id,)).fetchone(), 'Événement introuvable.', 404)
                used = dict(db.execute("SELECT category,count(*) FROM requests WHERE event_id=? AND status IN ('pending','approved') GROUP BY category", (event_id,)))
                require(all(quotas[c] >= used.get(c, 0) for c in CATEGORIES), 'Quota inférieur aux places déjà réservées.')
            else:
                event_id = str(uuid.uuid4())
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,venue=excluded.venue,starts=excluded.starts,ends=excluded.ends,deadline=excluded.deadline,description=excluded.description,published=excluded.published,quotas=excluded.quotas',
                       (event_id, title, venue, *[d.isoformat() for d in dates], description,
                        int(data['published']), json.dumps(quotas)))
            db.execute('INSERT INTO audit(actor,action,ref,created) VALUES (?,?,?,?)',
                       (actor, 'event.saved', event_id, now()))
        return event_id

    @staticmethod
    def files(data):
        require(isinstance(data, list) and len(data) <= 3, 'Nombre de fichiers invalide.')
        checked = []
        for f in data:
            require(isinstance(f, dict), 'Fichier invalide.')
            name = text(f.get('name'), 'Nom de fichier', 150)
            kind = text(f.get('kind'), 'Type de justificatif')
            try:
                raw = base64.b64decode(f.get('data', ''), validate=True)
            except (ValueError, TypeError):
                raise Error(400, 'Encodage de fichier invalide.')
            require(0 < len(raw) <= MAX_FILE, 'Chaque fichier doit faire au plus 2 Mo.')
            mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'application/pdf' if raw.startswith(b'%PDF-') else None
            require(mime is not None, 'Formats acceptés : JPEG, PNG, PDF.')
            require(kind not in ['Photo', 'Photo professionnelle'] or mime.startswith('image/'), 'La photo doit être JPEG ou PNG.')
            checked.append({'name': name, 'kind': kind, 'mime': mime, 'data': base64.b64encode(raw).decode()})
        return checked

    def submit(self, data, actor):
        event_id = text(data.get('eventId'), 'Événement', 100)
        require(data.get('consent') is True, 'Votre accord est requis pour envoyer le dossier.')
        name = text(data.get('name'), 'Nom complet')
        category = data.get('category')
        require(category in CATEGORIES, 'Catégorie inconnue.')
        answers = data.get('answers')
        require(isinstance(answers, dict), 'Réponses manquantes.')
        clean = {key: text(answers.get(key), key, 3000) for key in CATEGORIES[category]}
        files = self.files(data.get('files', []))
        require(len({f['kind'] for f in files}) == len(files), 'Justificatif en double.')
        require(set(f['kind'] for f in files).issubset({'Photo', *DOCUMENTS[category]}), 'Justificatif inattendu.')
        for kind in DOCUMENTS[category]:
            require(any(f['kind'] == kind for f in files), 'Justificatif requis : '+kind)
        phone = data.get('phone', '')
        require(isinstance(phone, str), 'Téléphone invalide.')
        phone = phone.strip()
        require(not phone or re.fullmatch(r'\+?[0-9 ()-]{6,25}', phone), 'Téléphone invalide.')
        ref = 'GN-'+datetime.now(timezone.utc).strftime('%Y')+'-'+secrets.token_hex(6).upper()
        payload = json.dumps({'answers': clean, 'files': files, 'phone': phone, 'consentAt': now()}, ensure_ascii=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            ev = db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
            require(ev is not None, 'Événement introuvable.', 404)
            require(ev['published'] and datetime.fromisoformat(ev['deadline']) > datetime.now(timezone.utc), 'Inscriptions closes.', 409)
            require(not db.execute("SELECT ref FROM requests WHERE event_id=? AND email=? AND status IN ('pending','approved')",
                                   (ev['id'], actor)).fetchone(), 'Vous avez déjà un dossier actif pour cet événement.', 409)
            used = db.execute("SELECT count(*) FROM requests WHERE event_id=? AND category=? AND status IN ('pending','approved')",
                              (ev['id'], category)).fetchone()[0]
            require(used < json.loads(ev['quotas'])[category], 'Cette catégorie est complète.', 409)
            db.execute('INSERT INTO requests(ref,event_id,email,name,category,status,created,payload,verify_token) VALUES (?,?,?,?,?,?,?,?,?)',
                       (ref, ev['id'], actor, name, category, 'pending', now(), payload, secrets.token_urlsafe(32)))
            db.execute('INSERT INTO audit(actor,action,ref,created) VALUES (?,?,?,?)', (actor, 'request.created', ref, now()))
        return ref

    def requests(self, user, event_id=None):
        query = 'SELECT r.*,e.title,e.venue,e.starts,e.ends FROM requests r JOIN events e ON e.id=r.event_id WHERE 1=1'
        params = []
        if user['role'] != 'admin':
            query += ' AND r.email=?'
            params.append(user['email'])
        if event_id:
            query += ' AND r.event_id=?'
            params.append(event_id)
        with self.connect() as db:
            rows = db.execute(query+' ORDER BY r.created DESC', params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            payload = json.loads(d.pop('payload'))
            d['answers'] = payload['answers']
            d['phone'] = payload['phone']
            d['files'] = [{k: v for k, v in f.items() if k != 'data'} for f in payload['files']]
            if d['status'] != 'approved':
                d.pop('verify_token')
            result.append(d)
        return result

    def decide(self, ref, status, reason, actor):
        require(status in ['approved', 'refused', 'revoked'], 'Décision invalide.')
        require(isinstance(reason, str), 'Motif invalide.')
        reason = reason.strip()
        require(len(reason) <= 2000 and (status == 'approved' or reason), 'Un motif est requis pour refuser ou révoquer.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM requests WHERE ref=?', (ref,)).fetchone()
            require(row is not None, 'Dossier introuvable.', 404)
            require((row['status'] == 'pending' and status in ['approved', 'refused']) or
                    (row['status'] == 'approved' and status == 'revoked'), 'Transition de statut interdite.', 409)
            db.execute('UPDATE requests SET status=?,reason=? WHERE ref=?', (status, reason, ref))
            db.execute('INSERT INTO audit(actor,action,ref,created) VALUES (?,?,?,?)', (actor, 'request.'+status, ref, now()))


class Handler(BaseHTTPRequestHandler):
    server_version = 'PNA'

    def send(self, status, body, mime='application/json; charset=utf-8', cookie=None, download=None):
        raw = json.dumps(body, ensure_ascii=False).encode() if mime.startswith('application/json') else body
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Permissions-Policy', 'camera=(self), microphone=(), geolocation=()')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="'+download+'"')
        self.end_headers()
        self.wfile.write(raw)

    def cookie(self, token):
        return 'pna_session='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age='+('28800' if token else '0')+('; Secure' if self.server.secure else '')

    def user(self, admin=False):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
            token = jar['pna_session'].value if 'pna_session' in jar else ''
        except Exception:
            token = ''
        user = self.server.store.identity(token)
        require(not admin or user['role'] == 'admin', 'Accès administrateur requis.', 403)
        return user

    def body(self):
        require(self.headers.get('Origin') == self.server.origin, 'Origine de requête interdite.', 403)
        require(self.headers.get('Content-Type', '').split(';')[0] == 'application/json', 'JSON requis.', 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise Error(400, 'Taille invalide.')
        require(0 < size <= MAX_BODY, 'Requête trop volumineuse.', 413)
        try:
            data = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            raise Error(400, 'JSON invalide.')
        require(isinstance(data, dict), 'Objet JSON requis.')
        return data

    def dispatch(self):
        require(self.headers.get('Host') == urlparse(self.server.origin).netloc, 'Hôte interdit.', 403)
        url = urlparse(self.path)
        path, store = url.path, self.server.store
        method = self.command
        if method == 'GET' and not path.startswith('/api/'):
            allowed = {'/': ('index.html','text/html; charset=utf-8'), '/app.js': ('app.js','text/javascript; charset=utf-8'), '/qr.js': ('qr.js','text/javascript; charset=utf-8'), '/style.css': ('style.css','text/css; charset=utf-8')}
            require(path in allowed, 'Page introuvable.', 404)
            filename, mime = allowed[path]
            return self.send(200, (ROOT/'public'/filename).read_bytes(), mime)
        if method == 'GET' and path == '/api/config':
            return self.send(200, {'categories': CATEGORIES, 'documents': DOCUMENTS, 'development': self.server.dev})
        if method == 'GET' and path == '/api/me':
            return self.send(200, self.user())
        if method == 'GET' and path == '/api/events':
            admin = False
            try:
                admin = self.user()['role'] == 'admin'
            except Error:
                pass
            return self.send(200, store.events(admin))
        if method == 'GET' and path == '/api/requests':
            user = self.user()
            event_id = parse_qs(url.query).get('eventId', [None])[0]
            return self.send(200, store.requests(user, event_id))
        if method == 'GET' and path == '/api/audit':
            self.user(True)
            with store.connect() as db:
                rows = [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')]
            return self.send(200, rows)
        if method == 'GET' and path.startswith('/api/files/'):
            user = self.user()
            parts = path.split('/')
            require(len(parts) == 5, 'Fichier introuvable.', 404)
            with store.connect() as db:
                row = db.execute('SELECT email,payload FROM requests WHERE ref=?', (parts[3],)).fetchone()
            require(row and (user['role'] == 'admin' or row['email'] == user['email']), 'Fichier introuvable.', 404)
            try:
                files = json.loads(row['payload'])['files']
                index = int(parts[4])
                require(0 <= index < len(files), 'Fichier introuvable.', 404)
                f = files[index]
            except (ValueError, IndexError):
                raise Error(404, 'Fichier introuvable.')
            return self.send(200, base64.b64decode(f['data']), f['mime'], download='justificatif.'+('pdf' if f['mime']=='application/pdf' else 'png' if f['mime']=='image/png' else 'jpg'))
        if method == 'GET' and path == '/api/export':
            user = self.user(True)
            event_id = parse_qs(url.query).get('eventId', [None])[0]
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(['Référence','Nom','E-mail','Catégorie','Événement','Statut'])
            for r in store.requests(user, event_id):
                # Neutraliser les formules lorsque le fichier est ouvert dans Excel.
                writer.writerow([("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@')) else v
                                 for v in [r['ref'],r['name'],r['email'],r['category'],r['title'],r['status']]])
            return self.send(200, ('\ufeff'+out.getvalue()).encode(), 'text/csv; charset=utf-8', download='accreditations.csv')
        data = self.body() if method in ['POST', 'PATCH'] else {}
        if method == 'POST' and path == '/api/login':
            store.limit('login:'+self.client_address[0], 10)
            address = email(data.get('email'))
            password = text(data.get('password'), 'Mot de passe', 500)
            store.login(address, password)
            return self.send(200, {'ok': True}, cookie=self.cookie(store.session(address, 'admin')))
        if method == 'POST' and path == '/api/otp':
            address = email(data.get('email'))
            store.limit('otp-ip:'+self.client_address[0], 10)
            store.limit('otp:'+address, 3)
            code = store.otp(address)
            if self.server.dev:
                return self.send(200, {'developmentCode': code})
            try:
                self.server.deliver(address, code)
            except Exception:
                with store.connect() as db:
                    db.execute('DELETE FROM otps WHERE email=?', (address,))
                raise Error(503, 'Envoi indisponible. Réessayez plus tard.')
            return self.send(200, {'ok': True})
        if method == 'POST' and path == '/api/otp/verify':
            store.limit('verify:'+self.client_address[0], 15)
            address = email(data.get('email'))
            store.verify_otp(address, text(data.get('code'), 'Code', 6))
            return self.send(200, {'ok': True}, cookie=self.cookie(store.session(address, 'citizen')))
        if method == 'POST' and path == '/api/logout':
            jar = SimpleCookie(self.headers.get('Cookie', ''))
            token = jar['pna_session'].value if 'pna_session' in jar else ''
            with store.connect() as db:
                db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
            return self.send(200, {'ok': True}, cookie=self.cookie(''))
        if method == 'POST' and path == '/api/events':
            user = self.user(True)
            return self.send(201, {'id': store.save_event(data, user['email'])})
        if method == 'PATCH' and path.startswith('/api/events/'):
            user = self.user(True)
            return self.send(200, {'id': store.save_event(data, user['email'], path.split('/')[-1])})
        if method == 'POST' and path == '/api/requests':
            user = self.user()
            store.limit('submit:'+user['email'], 10)
            return self.send(201, {'ref': store.submit(data, user['email'])})
        if method == 'PATCH' and path.startswith('/api/requests/'):
            user = self.user(True)
            store.decide(path.split('/')[-1], text(data.get('status'), 'Statut'), data.get('reason', ''), user['email'])
            return self.send(200, {'ok': True})
        if method == 'POST' and path == '/api/verify':
            user = self.user(True)
            token = text(data.get('token'), 'Code du badge', 100)
            event_id = text(data.get('eventId'), 'Événement')
            with store.connect() as db:
                row = db.execute('SELECT r.ref,r.name,r.category,r.status,e.starts,e.ends FROM requests r JOIN events e ON e.id=r.event_id WHERE r.verify_token=? AND r.event_id=?', (token, event_id)).fetchone()
                valid = bool(row and row['status'] == 'approved' and datetime.fromisoformat(row['starts']) <= datetime.now(timezone.utc) <= datetime.fromisoformat(row['ends']))
                db.execute('INSERT INTO audit(actor,action,ref,created) VALUES (?,?,?,?)',
                           (user['email'], 'access.allowed' if valid else 'access.denied', row['ref'] if row else 'unknown', now()))
            return self.send(200, {'valid': valid, 'name': row['name'] if row else None,
                                   'category': row['category'] if row else None})
        raise Error(404, 'Ressource introuvable.')

    def run(self):
        try:
            self.dispatch()
        except Error as e:
            self.send(e.status, {'error': e.message})
        except Exception as e:
            # Ne jamais journaliser les corps de requêtes, photos, codes ou mots de passe.
            print('Erreur serveur :', type(e).__name__, flush=True)
            self.send(500, {'error': 'Erreur serveur. Aucune réussite ne peut être confirmée.'})

    do_GET = run
    do_POST = run
    do_PATCH = run

    def log_message(self, *_):
        pass  # Les URLs de justificatifs ne sont pas copiées dans les journaux.


def make_server(store, host='127.0.0.1', port=3000, origin=None, dev=False):
    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store
    server.origin = origin or 'http://127.0.0.1:'+str(server.server_port)
    server.secure = server.origin.startswith('https://')
    server.dev = dev
    def deliver(address, code):
        msg = EmailMessage()
        msg['From'] = os.environ['SMTP_FROM']
        msg['To'] = address
        msg['Subject'] = 'Votre code de connexion au portail d’accréditation'
        msg.set_content('Votre code : '+code+'\nIl expire dans 5 minutes et ne peut être utilisé qu’une fois.')
        with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT', '587')), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if os.environ.get('SMTP_USER'):
                smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            smtp.send_message(msg)
    server.deliver = deliver
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dev', action='store_true', help='Codes OTP visibles, uniquement sur localhost')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--create-admin', metavar='EMAIL')
    args = parser.parse_args()
    store = Store(os.environ.get('PNA_DB', str(ROOT/'data'/'pna.sqlite3')))
    if args.create_admin:
        import getpass
        store.admin(args.create_admin, getpass.getpass('Mot de passe (14 caractères minimum) : '))
        print('Administrateur enregistré.')
    else:
        if args.dev and args.host not in ['127.0.0.1', 'localhost', '::1']:
            parser.error('--dev est réservé à une interface locale.')
        origin = os.environ.get('PNA_ORIGIN')
        if not args.dev and (not origin or not origin.startswith('https://') or
                             not os.environ.get('SMTP_HOST') or not os.environ.get('SMTP_FROM')):
            parser.error('Production : PNA_ORIGIN HTTPS, SMTP_HOST et SMTP_FROM sont requis.')
        server = make_server(store, args.host, args.port, origin, args.dev)
        print('Portail disponible : '+server.origin, flush=True)
        server.serve_forever()
