# NanoHUB Changelog

## 2026-04-05 — DDM server_token sync fix

### Bug fixes
- **server_token not synced from KMFDDM to DB** — after uploading a declaration via Dashboard UI, server_token in MySQL stayed NULL. Root cause: KMFDDM PUT API returns 204 No Content (no body), so token was never captured. Fix: after successful PUT, fetch token via GET and save to DB.
- **304 Not Modified treated as error** — urllib raises HTTPError for 304. Now handled as success (declaration unchanged).
- **Manual upload endpoint payload bug** — /api/ddm/declarations/<id>/upload sent raw payload instead of {Type, Identifier, Payload} wrapper. Refactored to use shared upload_declaration_to_kmfddm() function.

### Changes
- New helper: fetch_server_token_from_kmfddm(identifier) — fetches ServerToken via GET from KMFDDM API
- upload_declaration_to_kmfddm() returns (success, error, server_token) 3-tuple (was 2-tuple)
- All 3 upload call sites (create, manual upload, bulk import) now save server_token to DB
- File: backend_api/nanohub_admin/routes/ddm.py
