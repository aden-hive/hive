"""
Unit tests for Plaid connector.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from integrations.plaid.connector import PlaidConnector, PlaidConfig


@pytest.fixture
def mock_config():
    return PlaidConfig(
        client_id="test_client_id",
        secret="test_secret",
        environment="sandbox",
        access_token="test_access_token"
    )


@pytest.fixture
def connector(mock_config):
    with patch('integrations.plaid.connector.plaid_api') as mock_plaid:
        mock_client = MagicMock()
        mock_plaid.PlaidApi.return_value = mock_client
        return PlaidConnector(mock_config)


class TestPlaidConnector:
    """Test suite for Plaid connector."""
    
    def test_initialization(self, connector, mock_config):
        """Test connector initializes correctly."""
        assert connector.config == mock_config
    
    def test_fetch_accounts_success(self, connector):
        """Test fetching accounts."""
        mock_response = {
            'accounts': [
                {
                    'account_id': 'acc_123',
                    'name': 'Checking',
                    'type': 'depository',
                    'subtype': 'checking',
                    'balances': {
                        'available': 1000.00,
                        'current': 1200.00,
                        'iso_currency_code': 'USD'
                    }
                }
            ],
            'item': {'institution_id': 'ins_123'}
        }
        
        connector.client.accounts_get.return_value = mock_response
        
        accounts = connector.fetch_accounts()
        
        assert len(accounts) == 1
        assert accounts[0]['account_id'] == 'acc_123'
        assert accounts[0]['balance']['available'] == 1000.00
    
    def test_fetch_transactions_success(self, connector):
        """Test fetching transactions."""
        mock_response = {
            'transactions': [
                {
                    'transaction_id': 'txn_123',
                    'account_id': 'acc_123',
                    'amount': 50.00,
                    'date': '2024-01-15',
                    'name': 'Coffee Shop',
                    'merchant_name': 'Starbucks',
                    'category': ['Food and Drink', 'Coffee Shop'],
                    'pending': False,
                    'payment_channel': 'in store'
                }
            ],
            'total_transactions': 1
        }
        
        connector.client.transactions_get.return_value = mock_response
        
        transactions = connector.fetch_transactions(
            start_date="2024-01-01",
            end_date="2024-01-31"
        )
        
        assert len(transactions) == 1
        assert transactions[0]['transaction_id'] == 'txn_123'
        assert transactions[0]['amount'] == 50.00
    
    def test_reconcile_with_gl(self, connector):
        """Test GL reconciliation."""
        # Mock transactions
        mock_txns = {
            'transactions': [
                {
                    'transaction_id': 'txn_123',
                    'account_id': 'acc_123',
                    'amount': 100.00,
                    'date': '2024-01-15',
                    'name': 'Vendor Payment'
                }
            ],
            'total_transactions': 1
        }
        connector.client.transactions_get.return_value = mock_txns
        
        gl_entries = [
            {'amount': 100.00, 'date': '2024-01-15', 'description': 'Vendor payment'}
        ]
        
        report = connector.reconcile_with_gl(gl_entries)
        
        assert report['summary']['matched_count'] == 1
        assert report['summary']['unmatched_gl_count'] == 0
    
    def test_reconcile_with_unmatched_entries(self, connector):
        """Test reconciliation with unmatched GL entries."""
        mock_txns = {
            'transactions': [],
            'total_transactions': 0
        }
        connector.client.transactions_get.return_value = mock_txns
        
        gl_entries = [
            {'amount': 100.00, 'date': '2024-01-15', 'description': 'Missing txn'}
        ]
        
        report = connector.reconcile_with_gl(gl_entries)
        
        assert report['summary']['matched_count'] == 0
        assert report['summary']['unmatched_gl_count'] == 1
    
    def test_health_check_success(self, connector):
        """Test health check returns True."""
        mock_response = {
            'accounts': [],
            'item': {}
        }
        connector.client.accounts_get.return_value = mock_response
        
        assert connector.health_check() is True
    
    def test_health_check_failure(self, connector):
        """Test health check returns False on error."""
        connector.client.accounts_get.side_effect = Exception("API error")
        
        assert connector.health_check() is False
    
    def test_no_access_token_error(self, connector):
        """Test error when no access token provided."""
        connector.config.access_token = None
        
        with pytest.raises(ValueError, match="No access token"):
            connector.fetch_accounts()
    
    def test_plaid_not_installed(self):
        """Test error when plaid-python not installed."""
        with patch('integrations.plaid.connector.PLAID_AVAILABLE', False):
            with pytest.raises(ImportError):
                PlaidConnector(Mock())