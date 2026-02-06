import unittest
from unittest.mock import patch

import httpx

from aden_tools.tools.x_tool.x_tool import (
    _XClient,
)


class TestXClient(unittest.TestCase):
    @patch("httpx.request")
    def test_post(self, mock_req):
        mock_req.return_value = httpx.Response(200, json={"data": {"id": "1", "text": "hi"}})

        client = _XClient("fake")
        res = client.request("POST", "/tweets", json={"text": "hi"})

        self.assertIn("data", res)


if __name__ == "__main__":
    unittest.main()
