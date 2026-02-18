# Shop Backend Auth API

Production-oriented authentication and approval workflow for:
- `system_owner`
- `business_owner`
- `employee`

## Features
- Signup with `email`, `username`, `password`, `shopId`, optional `role` (defaults to `employee`)
- JWT access tokens + rotating refresh sessions
- Approval workflow:
  - `system_owner` is auto-approved
  - `business_owner` and `employee` are created as `pending`
  - only `system_owner` can approve/reject pending users
- Email verification + password reset one-time token flows
- MFA (TOTP) setup/enable/disable
- Login brute-force controls:
  - per-IP+identity sliding-window rate limiting
  - account lockout after repeated failed attempts
- Session management (`list`, `revoke`, `logout`)
- Audit logging for auth and approval events
- Inventory domain:
  - shops with unique codes
  - products with unique SKUs and unit of measure (`piece`, `kg`, `litre`, `carton`)
  - stock levels per shop/product
  - manual stock adjustments with history
  - stock transfer between shops
  - sales with revenue/cost/profit tracking
  - sale returns/refunds with optional restocking
  - expense tracking with net-profit reporting
  - supplier registry + purchase/restock records
  - low-stock alerts
  - profit reporting by shop/date range
  - per-product profit reports + dashboard summary
  - chart-ready analytics for line/bar/pie visualizations

## Endpoints
- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/token` (OAuth2 password flow for Swagger Authorize)
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /auth/pending-users` (system owner only)
- `POST /auth/users/{user_id}/approve` (system owner only)
- `POST /auth/users/{user_id}/reject` (system owner only)
- `POST /auth/email-verification/request`
- `POST /auth/email-verification/verify`
- `POST /auth/password-reset/request`
- `POST /auth/password-reset/confirm`
- `POST /auth/mfa/setup`
- `POST /auth/mfa/enable`
- `POST /auth/mfa/disable`
- `GET /auth/sessions`
- `POST /auth/sessions/{session_id}/revoke`
- `POST /auth/maintenance/cleanup-stale-users` (system owner)
- `GET /health`
- `POST /inventory/shops`
- `PATCH /inventory/shops/{shop_id}`
- `DELETE /inventory/shops/{shop_id}` (archive)
- `POST /inventory/shops/{shop_id}/activate`
- `GET /inventory/shops`
- `POST /inventory/products`
- `PATCH /inventory/products/{product_id}`
- `DELETE /inventory/products/{product_id}` (archive)
- `POST /inventory/products/{product_id}/activate`
- `GET /inventory/products`
- `POST /inventory/suppliers`
- `PATCH /inventory/suppliers/{supplier_id}`
- `DELETE /inventory/suppliers/{supplier_id}` (archive)
- `POST /inventory/suppliers/{supplier_id}/activate`
- `GET /inventory/suppliers`
- `POST /inventory/purchases`
- `PATCH /inventory/purchases/{purchase_id}`
- `DELETE /inventory/purchases/{purchase_id}`
- `GET /inventory/purchases`
- `GET /inventory/purchases/export/csv`
- `GET /inventory/purchases/export/pdf`
- `PUT /inventory/stocks`
- `GET /inventory/stocks`
- `DELETE /inventory/stocks/{stock_id}`
- `POST /inventory/stocks/{stock_id}/adjust`
- `GET /inventory/stock-adjustments`
- `POST /inventory/expenses`
- `GET /inventory/expenses`
- `PATCH /inventory/expenses/{expense_id}`
- `DELETE /inventory/expenses/{expense_id}`
- `POST /inventory/sales`
- `GET /inventory/sales`
- `POST /inventory/sales/{sale_id}/returns`
- `GET /inventory/returns`
- `GET /inventory/reports/profit/{shop_id}`
- `GET /inventory/alerts/low-stock`
- `GET /inventory/alerts/reorder-suggestions`
- `GET /inventory/audit/timeline`
- `POST /inventory/transfers`
- `PATCH /inventory/transfers/{transfer_id}`
- `DELETE /inventory/transfers/{transfer_id}`
- `GET /inventory/transfers`
- `GET /inventory/reports/profit-by-product`
- `GET /inventory/reports/dashboard`
- `GET /inventory/reports/dashboard-charts` (`granularity=day|week|month`, `top_n`)

## Run
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# first-time setup:
Copy-Item .env.example .env
# then edit .env with your real SMTP + DB credentials
alembic upgrade head
uvicorn app.main:app --reload
```

## Notes
- Change secrets/config via environment variables (`SECRET_KEY`, `DATABASE_URL`, etc.).
- For production, set `EXPOSE_DEBUG_TOKENS=false`.
- Email delivery:
  - `EMAIL_PROVIDER=console` for local development
  - `EMAIL_PROVIDER=smtp` for real delivery (recommended quick path: Brevo SMTP)
  - `EMAIL_PROVIDER=sendgrid` for transactional email API delivery
  - Brevo SMTP settings:
    - `EMAIL_FROM` (verified sender in Brevo)
    - `SMTP_HOST=smtp-relay.brevo.com`
    - `SMTP_PORT=587`
    - `SMTP_USERNAME` (Brevo SMTP login)
    - `SMTP_PASSWORD` (Brevo SMTP key)
    - `SMTP_STARTTLS=true`
    - `SMTP_USE_SSL=false`
  - SendGrid settings:
    - `EMAIL_FROM` (must be verified sender/domain in SendGrid)
    - `SENDGRID_API_KEY`
  - SMTP settings:
    - `EMAIL_FROM`
    - `SMTP_HOST`
    - `SMTP_PORT`
    - `SMTP_USERNAME`
    - `SMTP_PASSWORD`
    - `SMTP_STARTTLS=true|false`
    - `SMTP_USE_SSL=true|false`
  - Frontend links in emails use `FRONTEND_BASE_URL`
- Activation behavior:
  - User becomes fully active only when BOTH are true:
    1. user verifies email
    2. system owner approves account
  - Activation hook is logged as `users.activated` in `audit_logs`
- Automatic cleanup:
  - Deletes users that are both:
    - `approval_status = pending`
    - email not verified
    - older than configured cutoff
  - Env controls:
    - `CLEANUP_ENABLED=true|false`
    - `CLEANUP_INTERVAL_MINUTES` (default: `30`)
    - `CLEANUP_UNVERIFIED_PENDING_AFTER_HOURS` (default: `72`)
- Schema is now migration-driven via Alembic. Apply migrations before app startup.
- If your DB already has tables from older `create_all` startup logic, run one-time:
  - `alembic stamp head`
- In Swagger `Authorize`, use:
  - `username`: email or username
  - `password`: account password
  - `client_id` and `client_secret`: leave empty
