import os
import requests


class ProviderNotConfigured(RuntimeError):
    pass


def verify_payment_for_order(order):
    """
    Provider adapter placeholder.

    Configure a documented, authorized payment API before use. This deliberately does not
    infer payment success from screenshots or arbitrary redirects. The example expects the
    provider to expose GET {PAYMENT_API_BASE_URL}/payments/by-order/{order_id} and return:
      {"status":"succeeded","transaction_id":"...","order_id":"...","amount":1,"currency":"INR"}
    This is an illustrative adapter contract, NOT a claim that any provider has this endpoint.
    Replace the URL, authentication, signature checks, and response mapping with the provider's
    official documentation.
    """
    base_url = os.getenv("PAYMENT_API_BASE_URL", "").rstrip("/")
    api_key = os.getenv("PAYMENT_API_KEY", "")
    expected_amount = os.getenv("EXPECTED_PAYMENT_AMOUNT", "")
    expected_currency = os.getenv("EXPECTED_PAYMENT_CURRENCY", "INR").upper()

    if not base_url or not api_key:
        raise ProviderNotConfigured("Set PAYMENT_API_BASE_URL and PAYMENT_API_KEY after choosing a provider.")

    response = requests.get(
        f"{base_url}/payments/by-order/{order['order_id']}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    if str(data.get("order_id")) != str(order["order_id"]):
        return {"verified": False, "status": "MISMATCH", "message": "Provider order reference does not match."}
    if str(data.get("currency", "")).upper() != expected_currency:
        return {"verified": False, "status": "CURRENCY_MISMATCH", "message": "Currency does not match."}
    if expected_amount and str(data.get("amount")) != expected_amount:
        return {"verified": False, "status": "AMOUNT_MISMATCH", "message": "Amount does not match."}
    if data.get("status") != "succeeded" or not data.get("transaction_id"):
        return {"verified": False, "status": str(data.get("status", "PENDING")).upper(), "message": "Provider has not confirmed a successful payment."}

    return {"verified": True, "status": "SUCCEEDED", "transaction_id": str(data["transaction_id"]), "message": "Provider confirmed payment."}
