"""
Plaid Integration for Banking Data

Secure access to bank accounts, transactions, and balances.
"""

import os
from typing import Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    from plaid.api import plaid_api
    from plaid.model.transactions_get_request import TransactionsGetRequest
    from plaid.model.accounts_get_request import AccountsGetRequest
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient
    PLAID_AVAILABLE = True
except ImportError:
    PLAID_AVAILABLE = False


@dataclass
class PlaidConfig:
    """Configuration for Plaid API."""
    client_id: str
    secret: str
    environment: str = "sandbox"  # sandbox, development, production
    access_token: Optional[str] = None  # Obtained after account linking


class PlaidConnector:
    """
    Connector for Plaid banking API.
    
    Supports:
    - Account balances
    - Transaction history
    - Institution metadata
    - Secure token management
    """
    
    def __init__(self, config: PlaidConfig):
        if not PLAID_AVAILABLE:
            raise ImportError("plaid-python package required. Install: pip install plaid-python")
        
        self.config = config
        self.client = self._create_client()
        
    def _create_client(self):
        """Initialize Plaid API client."""
        configuration = Configuration(
            host=self._get_host(),
            api_key={
                'clientId': self.config.client_id,
                'secret': self.config.secret
            }
        )
        api_client = ApiClient(configuration)
        return plaid_api.PlaidApi(api_client)
    
    def _get_host(self) -> str:
        """Get Plaid API host based on environment."""
        hosts = {
            "sandbox": "https://sandbox.plaid.com",
            "development": "https://development.plaid.com",
            "production": "https://production.plaid.com"
        }
        return hosts.get(self.config.environment, hosts["sandbox"])
    
    def fetch_accounts(self) -> list[dict]:
        """
        Fetch all connected bank accounts.
        
        Returns:
            List of account dictionaries with balance info
        """
        if not self.config.access_token:
            raise ValueError("No access token. Link account first.")
        
        try:
            request = AccountsGetRequest(access_token=self.config.access_token)
            response = self.client.accounts_get(request)
            
            accounts = []
            for account in response['accounts']:
                accounts.append({
                    'account_id': account['account_id'],
                    'name': account['name'],
                    'type': account['type'],
                    'subtype': account.get('subtype'),
                    'balance': {
                        'available': account['balances'].get('available'),
                        'current': account['balances'].get('current'),
                        'currency': account['balances'].get('iso_currency_code', 'USD')
                    },
                    'institution': response['item'].get('institution_id')
                })
            
            return accounts
            
        except Exception as e:
            raise ConnectionError(f"Failed to fetch accounts: {e}")
    
    def fetch_transactions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account_ids: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Fetch transactions for specified date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD), defaults to 30 days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            account_ids: Specific accounts to query, or all if None
            
        Returns:
            List of transaction dictionaries
        """
        if not self.config.access_token:
            raise ValueError("No access token. Link account first.")
        
        # Default to last 30 days
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        try:
            request = TransactionsGetRequest(
                access_token=self.config.access_token,
                start_date=start_date,
                end_date=end_date,
                account_ids=account_ids or []
            )
            
            response = self.client.transactions_get(request)
            
            transactions = []
            for txn in response['transactions']:
                transactions.append({
                    'transaction_id': txn['transaction_id'],
                    'account_id': txn['account_id'],
                    'amount': txn['amount'],
                    'currency': txn.get('iso_currency_code', 'USD'),
                    'date': txn['date'],
                    'name': txn['name'],
                    'merchant_name': txn.get('merchant_name'),
                    'category': txn.get('category', []),
                    'pending': txn['pending'],
                    'payment_channel': txn.get('payment_channel')
                })
            
            return transactions
            
        except Exception as e:
            raise ConnectionError(f"Failed to fetch transactions: {e}")
    
    def reconcile_with_gl(
        self,
        gl_entries: list[dict],
        tolerance: float = 0.01
    ) -> dict:
        """
        Reconcile bank transactions with GL entries.
        
        Args:
            gl_entries: List of GL entries with 'amount', 'date', 'description'
            tolerance: Amount difference tolerance for matching
            
        Returns:
            Reconciliation report with matched/unmatched items
        """
        # Fetch bank transactions
        bank_txns = self.fetch_transactions()
        
        matched = []
        unmatched_bank = []
        unmatched_gl = []
        
        # Simple matching algorithm (can be enhanced)
        for gl in gl_entries:
            found_match = False
            for txn in bank_txns:
                # Match by amount (within tolerance) and approximate date
                amount_match = abs(abs(txn['amount']) - abs(gl['amount'])) <= tolerance
                date_match = txn['date'] == gl.get('date', txn['date'])
                
                if amount_match and date_match:
                    matched.append({
                        'gl_entry': gl,
                        'bank_transaction': txn,
                        'match_confidence': 'high' if amount_match and date_match else 'medium'
                    })
                    found_match = True
                    break
            
            if not found_match:
                unmatched_gl.append(gl)
        
        # Bank transactions not in GL
        matched_bank_ids = {m['bank_transaction']['transaction_id'] for m in matched}
        unmatched_bank = [t for t in bank_txns if t['transaction_id'] not in matched_bank_ids]
        
        return {
            'matched': matched,
            'unmatched_gl': unmatched_gl,
            'unmatched_bank': unmatched_bank,
            'summary': {
                'total_gl_entries': len(gl_entries),
                'total_bank_transactions': len(bank_txns),
                'matched_count': len(matched),
                'unmatched_gl_count': len(unmatched_gl),
                'unmatched_bank_count': len(unmatched_bank)
            }
        }
    
    def get_institution(self, institution_id: str) -> dict:
        """Get institution metadata."""
        try:
            from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
            
            request = InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=['US']
            )
            response = self.client.institutions_get_by_id(request)
            
            inst = response['institution']
            return {
                'institution_id': inst['institution_id'],
                'name': inst['name'],
                'products': inst.get('products', []),
                'country_codes': inst.get('country_codes', [])
            }
        except Exception as e:
            raise ConnectionError(f"Failed to get institution: {e}")
    
    def health_check(self) -> bool:
        """Verify Plaid API connectivity."""
        try:
            # Try to fetch accounts as health check
            if self.config.access_token:
                self.fetch_accounts()
            return True
        except Exception:
            return False


# Factory function
def create_plaid_connector_from_env() -> PlaidConnector:
    """Create connector from environment variables."""
    config = PlaidConfig(
        client_id=os.environ.get("PLAID_CLIENT_ID", ""),
        secret=os.environ.get("PLAID_SECRET", ""),
        environment=os.environ.get("PLAID_ENV", "sandbox"),
        access_token=os.environ.get("PLAID_ACCESS_TOKEN")
    )
    return PlaidConnector(config)