"""Basic QuickBooks API client with OAuth refresh and retry support."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .credentials import resolve_quickbooks_credentials


class QuickBooksAPIError(RuntimeError):
    """Raised when QuickBooks API operations fail."""


@dataclass
class QuickBooksConfig:
    client_id: str
    client_secret: str
    realm_id: str
    refresh_token: str
    environment: str = "sandbox"


class QuickBooksAPI:
    """Minimal QuickBooks API client for PurchaseOrder create flow."""

    def __init__(
        self,
        config: QuickBooksConfig,
        token_cache_path: Path | None = None,
    ) -> None:
        self.config = config
        self.token_cache_path = token_cache_path
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._load_token_cache()

    @staticmethod
    def from_env(
        token_cache_path: Path | None = None,
        credential_ref: str | None = None,
    ) -> "QuickBooksAPI":
        creds = resolve_quickbooks_credentials(credential_ref=credential_ref)

        missing = [
            key
            for key, value in {
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "realm_id": creds.realm_id,
                "refresh_token": creds.refresh_token,
            }.items()
            if not value
        ]
        if missing:
            raise QuickBooksAPIError(
                "Missing QuickBooks values for real API mode "
                f"(source={creds.source}): {', '.join(missing)}"
            )

        return QuickBooksAPI(
            config=QuickBooksConfig(
                client_id=str(creds.client_id),
                client_secret=str(creds.client_secret),
                realm_id=str(creds.realm_id),
                refresh_token=str(creds.refresh_token),
                environment=str(creds.environment or "sandbox"),
            ),
            token_cache_path=token_cache_path,
        )

    def create_purchase_order(self, po_data: dict[str, Any]) -> dict[str, Any]:
        """Create a PurchaseOrder in QuickBooks with retry and token refresh."""
        if os.environ.get("QUICKBOOKS_USE_MOCK", "false").lower() == "true":
            po_number = str(po_data.get("po_number", "PO-MOCK"))
            return {
                "id": f"QB-{po_number}",
                "doc_number": po_number,
                "sync_status": "mock_synced",
                "raw": {"mock": True, "po_data": po_data},
            }

        payload = self._build_purchase_order_payload(po_data)
        response = self._request_with_retry(
            method="POST",
            url=self._purchase_order_url(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=json.dumps(payload).encode("utf-8"),
        )

        po = response.get("PurchaseOrder", {})
        qb_id = str(po.get("Id") or po.get("id") or "")
        doc_number = str(po.get("DocNumber") or payload.get("DocNumber") or "")
        if not qb_id:
            raise QuickBooksAPIError(f"QuickBooks response missing PurchaseOrder ID: {response}")

        return {
            "id": qb_id,
            "doc_number": doc_number,
            "sync_status": "synced",
            "raw": response,
        }

    def _build_purchase_order_payload(self, po_data: dict[str, Any]) -> dict[str, Any]:
        po_number = str(po_data.get("po_number", ""))
        amount = float(po_data.get("amount", 0) or 0)
        currency = str(po_data.get("currency", "USD"))
        vendor_name = str(po_data.get("vendor", "Unknown Vendor"))

        # Basic payload that remains reviewable; production mapping can be expanded.
        return {
            "DocNumber": po_number,
            "VendorRef": {
                "name": vendor_name,
            },
            "PrivateNote": f"Procurement approval sync for {po_number}",
            "CurrencyRef": {"value": currency},
            "Line": [
                {
                    "Amount": amount,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "Description": f"Purchase order {po_number}",
                    "AccountBasedExpenseLineDetail": {},
                }
            ],
        }

    def _purchase_order_url(self) -> str:
        base = self._api_base_url()
        return f"{base}/v3/company/{self.config.realm_id}/purchaseorder"

    def _api_base_url(self) -> str:
        env = self.config.environment.lower()
        if env == "production":
            return "https://quickbooks.api.intuit.com"
        return "https://sandbox-quickbooks.api.intuit.com"

    def _token_url(self) -> str:
        return "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

    def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
        retries: int = 3,
        base_delay: float = 0.5,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                access_token = self._ensure_access_token()
                req_headers = {
                    **headers,
                    "Authorization": f"Bearer {access_token}",
                }
                req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    content = resp.read().decode("utf-8")
                    return json.loads(content) if content else {}
            except urllib.error.HTTPError as exc:
                # One token refresh retry path on auth failure.
                if exc.code == 401:
                    self._refresh_access_token(force=True)
                elif exc.code in (429, 500, 502, 503, 504):
                    pass
                else:
                    detail = exc.read().decode("utf-8", errors="ignore")
                    raise QuickBooksAPIError(
                        f"QuickBooks API HTTP {exc.code}: {detail or exc.reason}"
                    ) from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc

            if attempt < retries - 1:
                time.sleep(base_delay * (2**attempt))

        raise QuickBooksAPIError(f"QuickBooks API request failed after retries: {last_error}")

    def _ensure_access_token(self) -> str:
        # Refresh if missing or expiring within 60 seconds.
        if not self._access_token or time.time() > (self._token_expires_at - 60):
            self._refresh_access_token()
        if not self._access_token:
            raise QuickBooksAPIError("Failed to obtain QuickBooks access token")
        return self._access_token

    def _refresh_access_token(self, force: bool = False) -> None:
        if self._access_token and not force and time.time() <= (self._token_expires_at - 60):
            return

        auth = base64.b64encode(
            f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        ).decode("utf-8")
        form = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.config.refresh_token,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._token_url(),
            data=form,
            headers={
                "Authorization": f"Basic {auth}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise QuickBooksAPIError(
                f"QuickBooks token refresh failed ({exc.code}): {detail or exc.reason}"
            ) from exc

        self._access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expires_at = time.time() + expires_in
        self._save_token_cache()

    def _load_token_cache(self) -> None:
        if not self.token_cache_path or not self.token_cache_path.exists():
            return
        try:
            payload = json.loads(self.token_cache_path.read_text(encoding="utf-8"))
            self._access_token = payload.get("access_token")
            self._token_expires_at = float(payload.get("token_expires_at", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            self._access_token = None
            self._token_expires_at = 0.0

    def _save_token_cache(self) -> None:
        if not self.token_cache_path:
            return
        self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache_path.write_text(
            json.dumps(
                {
                    "access_token": self._access_token,
                    "token_expires_at": self._token_expires_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
