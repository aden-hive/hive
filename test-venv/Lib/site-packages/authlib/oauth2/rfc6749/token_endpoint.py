from .endpoint import Endpoint


class TokenEndpoint(Endpoint):
    """Base class for token-based endpoints (revocation, introspection).

    Subclasses must implement :meth:`authenticate_token` and
    :meth:`create_endpoint_response`.
    """

    #: Supported token types
    SUPPORTED_TOKEN_TYPES = ("access_token", "refresh_token")
    #: Allowed client authenticate methods
    CLIENT_AUTH_METHODS = ["client_secret_basic"]

    def authenticate_endpoint_client(self, request):
        """Authenticate client for endpoint with ``CLIENT_AUTH_METHODS``."""
        client = self.server.authenticate_client(
            request, self.CLIENT_AUTH_METHODS, self.ENDPOINT_NAME
        )
        request.client = client
        return client

    def authenticate_token(self, request, client):
        """Authenticate and return the token. Subclasses must implement this."""
        raise NotImplementedError()

    def create_endpoint_response(self, request):
        """Process the request and return response. Subclasses must implement this."""
        raise NotImplementedError()
