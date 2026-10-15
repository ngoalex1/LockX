"""HTTP contract tests using auth/Storage doubles. Never touches production.
Database lifecycle is tested separately by test_vault_database.mjs.
Run: python -m unittest test_digital_vault -v
"""
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from fastapi.testclient import TestClient
import main

class Response:
    def __init__(self, value): self.value = value
    def json(self): return self.value

class VaultHTTPTests(unittest.TestCase):
    def setUp(self):
        self.owner = str(uuid4())
        self.item = {'id': str(uuid4()), 'owner_id': self.owner, 'category': 'watch', 'item_name': 'Test watch', 'status': 'protected', 'currency': 'USD'}
        self.identity = {'id': self.owner, 'email': 'test@example.com', 'email_confirmed_at': '2026-01-01'}
        main.app.dependency_overrides[main.current_user] = lambda: self.owner
        main.app.dependency_overrides[main.authenticated_identity] = lambda: self.identity
        self.client = TestClient(main.app)
        self.calls, self.photos, self.rpc_error = [], [], None
        self.patcher = patch.object(main, 'supabase_request', side_effect=self.request)
        self.patcher.start()
        self.path = f"/api/v1/vault/items/{self.item['id']}"

    def tearDown(self):
        self.patcher.stop()
        main.app.dependency_overrides.clear()

    def request(self, method, path, payload=None, *args):
        self.calls.append((method, path, payload))
        if path == 'rpc/vault_mutate':
            if self.rpc_error: return Response(self.rpc_error)
            action = payload['p_action']
            if action in {'create', 'update'}: return Response({**self.item, **payload['p_payload'], 'id': payload['p_item']})
            if action == 'photo_delete': return Response({'storage_path': 'test/photo.jpg'})
            if action == 'recovery': return Response({'item': self.item, 'case_id': str(uuid4()), 'case_number': 'LX-TEST', 'search_status': 'ready_for_approved_sources'})
            return Response({'id': str(uuid4())})
        if path.startswith('vault_items?'): return Response([self.item])
        if path.startswith('vault_item_photos?'): return Response(self.photos)
        return Response([])

    def test_auth_required(self):
        main.app.dependency_overrides.clear()
        for path in ('/api/v1/vault/items', '/api/v1/vault/transfers', self.path+'/photos'):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_categories_and_input_validation(self):
        for category in ('watch', 'jewellery', 'handbag'):
            response = self.client.post('/api/v1/vault/items', json={'category': category, 'item_name': 'Test', 'purchase_date': '2025-01-01'})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()['category'], category)
        for payload in ({'category': 'car'}, {'item_name': ' '}, {'purchase_date': 'bad'}, {'estimated_value': -1}, {'currency': 'US'}):
            self.assertEqual(self.client.post('/api/v1/vault/items', json={'category': 'watch', 'item_name': 'Test', **payload}).status_code, 422)

    def test_optional_field_can_be_cleared(self):
        self.assertEqual(self.client.patch(self.path, json={'serial_number': None}).status_code, 200)
        self.assertEqual(self.calls[-1][2]['p_payload'], {'serial_number': None})
        for field in ('item_name', 'category', 'currency', 'status'):
            self.assertEqual(self.client.patch(self.path, json={field: None}).status_code, 422)

    def test_invalid_id_and_transfer_lock(self):
        self.assertEqual(self.client.get('/api/v1/vault/items/invalid/photos').status_code, 422)
        self.rpc_error = {'error': 409, 'message': 'Cancel the pending transfer'}
        self.assertEqual(self.client.patch(self.path, json={'item_name': 'New'}).status_code, 409)

    def test_photo_upload_validation_limit_storage_failure(self):
        path = self.path+'/photos'
        self.assertEqual(self.client.post(path, files={'photo': ('x.txt', b'x', 'text/plain')}).status_code, 415)
        self.assertEqual(self.client.post(path, files={'photo': ('x.jpg', b'', 'image/jpeg')}).status_code, 413)
        with patch.object(main, 'vault_upload') as store:
            self.assertEqual(self.client.post(path, files={'photo': ('x.jpg', b'\xff\xd8\xff', 'image/jpeg')}).status_code, 201)
            store.assert_called_once()
        self.photos = [{'id': str(uuid4())} for _ in range(20)]
        self.assertEqual(self.client.post(path, files={'photo': ('x.jpg', b'photo', 'image/jpeg')}).status_code, 409)
        self.photos = []
        with patch.object(main, 'vault_upload', side_effect=HTTPException(503, 'Storage unavailable')):
            self.assertEqual(self.client.post(path, files={'photo': ('x.jpg', b'photo', 'image/jpeg')}).status_code, 503)

    def test_failed_photo_commit_cleans_orphan(self):
        self.rpc_error = {'error': 409, 'message': 'Item transferred while uploading'}
        with patch.object(main, 'vault_upload'), patch.object(main, 'cleanup_vault_file') as cleanup:
            response = self.client.post(self.path+'/photos', files={'photo': ('x.jpg', b'photo', 'image/jpeg')})
            self.assertEqual(response.status_code, 409)
            cleanup.assert_called_once()

    def test_delete_photo_and_upload_document(self):
        with patch.object(main, 'cleanup_vault_file') as cleanup:
            self.assertEqual(self.client.post(self.path+f'/photos/{uuid4()}/delete').status_code, 204)
            cleanup.assert_called_once_with('test/photo.jpg')
        with patch.object(main, 'vault_upload'):
            response = self.client.post(self.path+'/documents', files={'document': ('receipt #1.pdf', b'%PDF', 'application/pdf')})
            self.assertEqual(response.status_code, 201)
            self.assertNotIn('#', self.calls[-1][2]['p_payload']['storage_path'])
            self.assertEqual(self.calls[-1][2]['p_payload']['file_name'], 'receipt #1.pdf')

    def test_verified_recipient_and_recovery(self):
        self.identity['email_confirmed_at'] = None
        self.assertEqual(self.client.post(f'/api/v1/vault/transfers/{uuid4()}/accept').status_code, 403)
        response = self.client.post(self.path+'/start-recovery', json={'status': 'missing'})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('owner_id', response.json()['item'])
        self.assertEqual(self.calls[-1][2]['p_action'], 'recovery')

if __name__ == '__main__': unittest.main()
