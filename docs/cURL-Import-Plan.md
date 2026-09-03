Phase 1 — Backend: cURL parser (core logic, unit-tested, no API yet)
New backend/app/parsers/curl_parser.py: tokenize a curl command string → extract method, URL, headers (-H), body (-d/--data/--data-raw/--data-binary), query params (from URL), auth (-u, --user), cookies (-b).
Support multiple curl commands pasted at once (one per endpoint) — split on lines starting with curl.
Reuse existing Endpoint/Suite models — a curl import produces the same internal representation the Swagger parser does, just without an OpenAPI spec wrapping it (so it needs a synthetic "suite" — e.g. name = user-supplied or "Imported from cURL").
Unit tests with realistic fixtures (GET, POST with JSON body, headers, auth, multiline \ continuations, Windows vs bash quoting).
Validation point for you: run parser against a handful of real curl commands you supply and confirm the extracted fields are correct.
Phase 2 — Backend: import service + endpoint
Extend import_service.py with import_from_curl(db, workspace_id, curl_text, suite_name=None), mirroring import_from_upload/import_from_url.
New route POST /api/imports/curl in imports.py (JSON body: raw curl text + optional suite name), returning SuiteDetailOut — same contract as existing import endpoints, so the frontend suite list/detail pages work unmodified.
Error handling: malformed curl, empty input, unsupported flags → 422 with a clear message (mirroring current SpecImportError pattern).
Tests: test_api_imports.py extended, plus a service-level test file.
Validation point: hit the new endpoint via curl/Postman yourself with a few real commands, confirm the created suite/endpoints look right in the DB/API response.
Phase 3 — Frontend: cURL import UI
Extend ImportPage.tsx with a third tab/mode alongside "Upload file" / "From URL": a textarea for pasting curl command(s), optional suite name field.
Wire to the new /imports/curl endpoint via the existing typed API client.
Reuse existing suite-detail navigation after successful import (same as current flows).
Validation point: you paste real curl commands from your own APIs in the browser and confirm the suite renders correctly end-to-end.
Phase 4 — Polish & edge cases
Multi-command paste → multiple endpoints in one suite (if not already handled in Phase 1/2).
Handle common curl quirks: -X vs implicit method from -d presence, --compressed, -k/--insecure (ignore), environment-variable-style tokens users sometimes paste (flag as unsupported rather than silently mis-parsing).
Duplicate-endpoint detection if re-importing into an existing suite (may piggyback on however Swagger import currently handles re-imports, if at all).
Validation point: stress-test with messy/copy-pasted curl commands (multi-line, escaped quotes, from different tools like Chrome vs Postman vs Insomnia) to shake out parser edge cases.