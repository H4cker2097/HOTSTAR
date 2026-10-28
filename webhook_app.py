import os
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify

from database import init_db, get_order, update_order_status

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("payment_webhook")
app = Flask(__name__)
init_db()


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.post("/webhook/payment")
def payment_webhook():
    """
    Generic HMAC-SHA256 sample only. Adapt signature header, canonical payload, timestamp
    tolerance, and event schema to the selected provider's official webhook documentation.
    Do not deploy until adapted and tested for the real provider.
    """
    secret = os.getenv("PAYMENT_WEBHOOK_SECRET", "")
    if not secret:
        return jsonify({"error": "webhook not configured"}), 503

    raw = request.get_data(cache=False)
    signature = request.headers.get("X-Provider-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        return jsonify({"error": "invalid signature"}), 401

    try:
        event = json.loads(raw.decode("utf-8"))
        order_id = str(event["order_id"])
        provider_status = str(event["status"]).lower()
        transaction_id = str(event.get("transaction_id", ""))
    except (ValueError, KeyError, TypeError):
        return jsonify({"error": "invalid event"}), 400

    order = get_order(order_id)
    if not order:
        return jsonify({"error": "unknown order"}), 404

    # Only provider-confirmed successful events update payment state. Validate amount/currency
    # and deduplicate event IDs using the selected provider's real schema before production use.
    if provider_status == "succeeded" and transaction_id:
        update_order_status(order_id, "PAYMENT_VERIFIED", provider_txn_id=transaction_id)
    elif provider_status in ("failed", "cancelled"):
        update_order_status(order_id, "PAYMENT_FAILED")

    return jsonify({"received": True}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
