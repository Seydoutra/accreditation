import base64
import concurrent.futures
import http.client
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server import CATEGORIES, Error, Store, make_server


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name)/'db.sqlite3'))
        self.store.admin('admin@example.org', 'correct-password-123')
        self.server = make_server(self.store, port=0, dev=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = self.server.origin
        self.admin = self.store.session('admin@example.org', 'admin')
        self.alice = self.store.session('alice@example.org', 'citizen')
        self.bob = self.store.session('bob@example.org', 'citizen')
        self.event = self.store.save_event(self.event_data(), 'admin@example.org')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def event_data(self, quota=10):
        now = datetime.now(timezone.utc)
        return {'title': 'Forum test', 'venue': 'Conakry', 'description': 'Conférences',
                'starts': (now+timedelta(days=2)).isoformat(), 'ends': (now+timedelta(days=3)).isoformat(),
                'deadline': (now+timedelta(days=1)).isoformat(), 'published': True,
                'quotas': {c: quota for c in CATEGORIES}}

    def dossier(self):
        return {'eventId': self.event, 'name': 'Alice Test', 'category': 'VIP', 'consent': True,
                'answers': {'Titre / institution': 'Institution A'}, 'files': [], 'phone': '+224 621 000000'}

    def call(self, path, method='GET', data=None, token=None, origin=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {}
        if token:
            headers['Cookie'] = 'pna_session='+token
        if data is not None:
            headers['Content-Type'] = 'application/json'
            if origin:
                headers['Origin'] = self.origin
        conn.request(method, path, json.dumps(data) if data is not None else None, headers)
        res = conn.getresponse()
        content = res.read()
        result = (res.status, json.loads(content) if res.getheader('Content-Type').startswith('application/json') else content, dict(res.getheaders()))
        conn.close()
        return result

    def submit(self, token=None, data=None):
        status, body, _ = self.call('/api/requests', 'POST', data or self.dossier(), token or self.alice)
        self.assertEqual(status, 201, body)
        return body['ref']

    def test_authentication_and_cookie(self):
        self.assertEqual(self.call('/api/requests')[0], 401)
        self.assertEqual(self.call('/api/events', 'POST', self.event_data(), self.alice)[0], 403)
        self.assertEqual(self.call('/api/login', 'POST', {'email':'admin@example.org','password':'wrong'})[0], 401)
        status, _, headers = self.call('/api/login', 'POST', {'email':'admin@example.org','password':'correct-password-123'})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def test_isolation_and_no_badge_before_approval(self):
        self.submit()
        self.assertEqual(self.call('/api/requests', token=self.bob)[1], [])
        alice = self.call('/api/requests', token=self.alice)[1]
        self.assertEqual(len(alice), 1)
        self.assertNotIn('verify_token', alice[0])
        self.assertEqual(alice[0]['answers'], self.dossier()['answers'])
        self.assertEqual(len(self.call('/api/requests', token=self.admin)[1]), 1)

    def test_files_private_and_persistent(self):
        data = self.dossier()
        raw = b'\x89PNG\r\n\x1a\n' + b'photo-test'
        data['files'] = [{'name':'portrait.png','kind':'Photo','data':base64.b64encode(raw).decode()}]
        ref = self.submit(data=data)
        self.assertEqual(self.call('/api/files/'+ref+'/0', token=self.alice)[1], raw)
        self.assertEqual(self.call('/api/files/'+ref+'/0', token=self.bob)[0], 404)
        self.assertEqual(self.call('/api/files/'+ref+'/-1', token=self.alice)[0], 404)
        self.assertEqual(self.call('/demo/portail-original.html')[0], 404)
        fresh = Store(self.store.path)
        self.assertEqual(len(fresh.requests({'email':'alice@example.org','role':'citizen'})), 1)

    def test_validation(self):
        for field, value in [('consent',False),('answers',{}),('category','Unknown'),('name','')]:
            data = self.dossier(); data[field] = value
            self.assertEqual(self.call('/api/requests', 'POST', data, self.alice)[0], 400)
        data = self.dossier(); data['category'] = 'Délégué'; data['answers'] = {'Organisation':'A','Fonction officielle':'B'}
        self.assertEqual(self.call('/api/requests', 'POST', data, self.alice)[0], 400)
        data = self.dossier(); data['files'] = [{'name':'evil.svg','kind':'Photo','data':base64.b64encode(b'<svg/>').decode()}]
        self.assertEqual(self.call('/api/requests','POST',data,self.alice)[0],400)

    def test_quota_atomic_and_duplicates(self):
        self.store.save_event(self.event_data(quota=1), 'admin@example.org', self.event)
        def attempt(address):
            try:
                return self.store.submit(self.dossier(), address)
            except Error as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, ['p'+str(i)+'@example.org' for i in range(6)]))
        self.assertEqual(sum(isinstance(r,str) for r in results),1)
        self.assertEqual(results.count(409),5)
        # Une répétition de l'envoi ne crée pas de deuxième dossier.
        self.assertEqual(self.call('/api/requests','POST',self.dossier(),self.alice)[0],409)

    def test_decisions_revocation_and_event_filter(self):
        ref = self.submit()
        self.assertEqual(self.call('/api/requests/'+ref,'PATCH',{'status':'approved'},self.alice)[0],403)
        self.assertEqual(self.call('/api/requests/'+ref,'PATCH',{'status':'approved'},self.admin)[0],200)
        req = self.call('/api/requests',token=self.alice)[1][0]
        token = req['verify_token']
        self.assertEqual(self.call('/api/verify','POST',{'eventId':self.event,'token':token},self.admin)[1]['valid'],False)
        data = self.event_data(); current = datetime.now(timezone.utc)
        data.update(starts=(current-timedelta(hours=1)).isoformat(), ends=(current+timedelta(hours=1)).isoformat(), deadline=(current-timedelta(hours=2)).isoformat())
        self.assertEqual(self.call('/api/events/'+self.event,'PATCH',data,self.admin)[0],200)
        self.assertTrue(self.call('/api/verify','POST',{'eventId':self.event,'token':token},self.admin)[1]['valid'])
        self.assertFalse(self.call('/api/verify','POST',{'eventId':'different','token':token},self.admin)[1]['valid'])
        self.assertEqual(self.call('/api/requests/'+ref,'PATCH',{'status':'revoked','reason':'Badge perdu'},self.admin)[0],200)
        self.assertFalse(self.call('/api/verify','POST',{'eventId':self.event,'token':token},self.admin)[1]['valid'])
        self.assertEqual(self.call('/api/requests/'+ref,'PATCH',{'status':'approved'},self.admin)[0],409)
        self.assertEqual(self.call('/api/requests?eventId=other',token=self.admin)[1],[])
        audit = self.call('/api/audit',token=self.admin)[1]
        self.assertTrue(any(r['action']=='request.revoked' for r in audit))
        self.assertEqual(self.call('/api/audit',token=self.alice)[0],403)

    def test_otp_expiration_attempts_and_replay(self):
        address = 'new@example.org'
        code = self.store.otp(address)
        for _ in range(5):
            with self.assertRaises(Error): self.store.verify_otp(address, '000000')
        with self.assertRaises(Error): self.store.verify_otp(address, code)
        code = self.store.otp(address)
        with self.store.connect() as db:
            db.execute('UPDATE otps SET expires=? WHERE email=?',(time.time()-1,address))
        with self.assertRaises(Error): self.store.verify_otp(address, code)
        code = self.store.otp(address)
        self.store.verify_otp(address, code)
        with self.assertRaises(Error): self.store.verify_otp(address, code)

    def test_otp_http_logout_and_production_no_code(self):
        status, body, _ = self.call('/api/otp','POST',{'email':'visitor@example.org'})
        self.assertEqual(status,200)
        status, _, headers = self.call('/api/otp/verify','POST',{'email':'visitor@example.org','code':body['developmentCode']})
        self.assertEqual(status,200)
        token = headers['Set-Cookie'].split(';')[0].split('=',1)[1]
        self.assertEqual(self.call('/api/me',token=token)[0],200)
        self.call('/api/logout','POST',{},token)
        self.assertEqual(self.call('/api/me',token=token)[0],401)
        delivered=[]; self.server.dev=False; self.server.deliver=lambda address,code: delivered.append((address,code))
        body=self.call('/api/otp','POST',{'email':'prod@example.org'})[1]
        self.assertNotIn('developmentCode',body)
        self.assertEqual(delivered[0][0],'prod@example.org')

    def test_origin_closed_event_and_quota_edit(self):
        self.assertEqual(self.call('/api/requests','POST',self.dossier(),self.alice,origin=False)[0],403)
        self.submit()
        data=self.event_data(quota=0)
        self.assertEqual(self.call('/api/events/'+self.event,'PATCH',data,self.admin)[0],400)
        data=self.event_data(); data['published']=False
        self.assertEqual(self.call('/api/events/'+self.event,'PATCH',data,self.admin)[0],200)
        self.assertEqual(self.call('/api/requests','POST',self.dossier(),self.bob)[0],409)
        self.assertEqual(self.call('/api/events')[1],[])

    def test_export_and_security_headers(self):
        data=self.dossier(); data['name']='=HYPERLINK("https://example.org")'
        self.submit(data=data)
        self.assertEqual(self.call('/api/export',token=self.alice)[0],403)
        status,body,_=self.call('/api/export',token=self.admin)
        self.assertEqual(status,200)
        self.assertIn(b"'=HYPERLINK",body)
        status,_,headers=self.call('/')
        self.assertEqual(status,200)
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'],'no-store')


if __name__=='__main__': unittest.main()
