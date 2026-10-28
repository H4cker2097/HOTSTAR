# JioHotstar Assisted Activation Telegram Bot

Python Telegram bot starter for guiding users to the official Hotstar checkout, collecting optional screenshots, and tracking order/payment status.

## Important limitations

- The checkout URL opens the official Hotstar site. Users enter their own OTP directly on Hotstar.
- The bot never asks for or stores login OTPs, passwords, cookies, or session tokens.
- A screenshot is not proof of payment.
- Automatic verification works only after integrating a real, authorized payment provider API or webhook.
- **This starter is not production-ready for payments yet.** `payment_provider.py` contains an illustrative API contract that must be adapted to your selected provider's official docs.
- `webhook_app.py` shows generic HMAC verification but must be adapted to the real provider's signature scheme, amount/currency validation, event IDs, replay protection, and idempotency before production.
- The current database adapter uses SQLite for local development. Railway's local filesystem may be ephemeral. Replace `database.py` with PostgreSQL-backed persistence before production use.

## Local setup

1. Install Python 3.12+.
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `BOT_TOKEN` and `ADMIN_IDS`.
4. Export environment variables before running, or use a local dotenv loader if you add one. The project intentionally does not load `.env` automatically.
5. Run the Telegram bot:
   ```bash
   python bot.py
   ```
6. In a second terminal, run the webhook app:
   ```bash
   python webhook_app.py
   ```
   Health endpoint: `http://127.0.0.1:8080/health`.

## Railway deployment

Deploy the bot and webhook as **separate Railway services** from the same GitHub repository, with separate start commands:

- Bot service: `python bot.py`
- Webhook service: `gunicorn --bind 0.0.0.0:$PORT webhook_app:app`

Set environment variables in Railway service settings; do not commit `.env`.

Required bot variables:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `HOTSTAR_CHECKOUT_URL`

Required provider variables after choosing a provider:
- `PAYMENT_API_BASE_URL`
- `PAYMENT_API_KEY`
- `PAYMENT_WEBHOOK_SECRET`
- `EXPECTED_PAYMENT_AMOUNT`
- `EXPECTED_PAYMENT_CURRENCY`
- `PUBLIC_WEBHOOK_URL`

Provision Railway PostgreSQL and update the code's database adapter before using production traffic. Merely setting `DATABASE_URL` does not switch this starter's SQLite adapter to PostgreSQL.

## GitHub

1. Create a private repository.
2. Upload the project files.
3. Confirm `.env` and `bot.db` are not committed.
4. Connect the repository to Railway.
5. Add variables through Railway's dashboard.
6. Deploy the bot and webhook services separately.

## Bot commands

User:
- `/start`
- `/upload ORDER_ID`

Admin (IDs in `ADMIN_IDS`):
- `/admin`
- `/orders`
- `/order ORDER_ID`
- `/verify ORDER_ID`
- `/activation ORDER_ID confirmed|failed`

## Before production

- Select a payment provider and implement its documented API contract.
- Implement provider-specific webhook signature validation and replay protection.
- Add persistent PostgreSQL storage and migrations.
- Add provider transaction uniqueness and webhook event deduplication.
- Add rate limiting, retention rules for screenshots, and privacy/terms text.
- Test failed, pending, duplicate, mismatched-amount, and forged-webhook cases.
