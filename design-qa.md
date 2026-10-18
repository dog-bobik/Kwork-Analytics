# Design QA — Kwork Pulse

- Reference: Kwork manage-kworks screenshot supplied by the user.
- Implementation: `http://127.0.0.1:8080` in the Codex in-app browser.
- Verified state: unauthenticated login screen after the production Docker rebuild.

## Verified

- The application opens without clipping or overlap in the desktop viewport.
- Login, password and optional phone-suffix controls have accessible labels.
- The screen explicitly states that the password and token are not persisted in PostgreSQL.
- The production frontend reaches the backend through nginx; `/api/health` reports a healthy database.

## Authenticated dashboard

- Code provides separate `Отклики` and `Кворки` navigation.
- Kwork cards read covers from `image_url` or `cover.tablet/phone` and statistics from the nested `activity` object used by the live API.
- Both pages provide list/grid modes, full-text search and page-specific filters/sorting.
- The offers page restores read/unread/active/ordered filters and the selected-order details dialog.
- The kworks page provides category/status filters and popularity/today/sales/price/title sorting.
- PostgreSQL evidence contains 10 current kworks with non-empty covers and activity values; production rendering is rebuilt from that schema.
- Authenticated visual verification requires the account owner to submit their credentials in the local login screen; credentials were intentionally not taken from `.env` during QA.

final result: passed for the public/login state; authenticated content is ready for owner login
