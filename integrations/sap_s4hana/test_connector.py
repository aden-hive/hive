"""
Unit tests for SAP S/4HANA connector.
"""

import pytest
from unittest.mock import Mock, patch

from integrations.sap_s4hana.connector import SAPS4HANAConnector, SAPConnectionConfig


@pytest.fixture
def mock_config():
    return SAPConnectionConfig(
        base_url="https://test-sap-server/sap/opu/odata/sap",
        username="test_user",
        password="test_pass",
        client="100",
        verify_ssl=False
    )


@pytest.fixture
def connector(mock_config):
    return SAPS4HANAConnector(mock_config)


class TestSAPS4HANAConnector:
    """Test suite for SAP S/4HANA connector."""
    
    def test_initialization(self, connector, mock_config):
        """Test connector initializes correctly."""
        assert connector.config == mock_config
        assert connector.session.auth is not None
    
    def test_health_check_success(self, connector):
        """Test health check returns True on success."""
        with patch.object(connector.session, 'get') as mock_get:
            mock_get.return_value.status_code = 200
            assert connector.health_check() is True
    
    def test_health_check_failure(self, connector):
        """Test health check returns False on failure."""
        with patch.object(connector.session, 'get') as mock_get:
            mock_get.side_effect = Exception("Connection failed")
            assert connector.health_check() is False
    
    def test_fetch_purchase_orders_success(self, connector):
        """Test fetching purchase orders."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "d": {
                "results": [
                    {"PurchaseOrder": "4500000001", "Supplier": "12345"}
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(connector.session, 'get', return_value=mock_response):
            result = connector.fetch_purchase_orders()
            
            assert len(result) == 1
            assert result[0]["PurchaseOrder"] == "4500000001"
    
    def test_fetch_purchase_orders_with_filters(self, connector):
        """Test fetching purchase orders with filters."""
        mock_response = Mock()
        mock_response.json.return_value = {"d": {"results": []}}
        mock_response.raise_for_status = Mock()
        
        with patch.object(connector.session, 'get', return_value=mock_response) as mock_get:
            connector.fetch_purchase_orders(filters={"Supplier": "12345"})
            
            # Verify filter was applied in URL
            call_args = mock_get.call_args
            assert "$filter" in call_args[1]["params"]
            assert "Supplier eq '12345'" in call_args[1]["params"]["$filter"]
    
    def test_fetch_vendors_success(self, connector):
        """Test fetching vendors."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "d": {
                "results": [
                    {"BusinessPartner": "V001", "BusinessPartnerName": "Test Vendor"}
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(connector.session, 'get', return_value=mock_response):
            result = connector.fetch_vendors()
            
            assert len(result) == 1
            assert result[0]["BusinessPartner"] == "V001"
    
    def test_get_purchase_order_by_id(self, connector):
        """Test getting specific purchase order."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "d": {"PurchaseOrder": "4500000001", "Supplier": "12345"}
        }
        mock_response.raise_for_status = Mock()
        
        with patch.object(connector.session, 'get', return_value=mock_response):
            result = connector.get_purchase_order_by_id("4500000001")
            
            assert result["PurchaseOrder"] == "4500000001"
    
    def test_connection_error_handling(self, connector):
        """Test connection errors are handled gracefully."""
        with patch.object(connector.session, 'get') as mock_get:
            mock_get.side_effect = Exception("Network error")
            
            with pytest.raises(ConnectionError):
                connector.fetch_purchase_orders()