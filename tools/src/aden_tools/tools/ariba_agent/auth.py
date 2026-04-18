
import httpx
import time


class OAuth2Client:
    def __init__(self, client_id, client_secret, token_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.token = None
        self.expiry = 0

    async def get_token_async(self):
        if self.token and time.time() < self.expiry:
            return self.token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

        data = response.json()
        self.token = data["access_token"]
        self.expiry = time.time() + data["expires_in"] - 60

        return self.token
