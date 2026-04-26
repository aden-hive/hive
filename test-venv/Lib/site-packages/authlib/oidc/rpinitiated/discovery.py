from authlib.common.security import is_secure_transport


class OpenIDProviderMetadata(dict):
    REGISTRY_KEYS = ["end_session_endpoint"]

    def validate_end_session_endpoint(self):
        # rpinitiated §2.1: "end_session_endpoint - URL at the OP to which an
        # RP can perform a redirect to request that the End-User be logged out
        # at the OP. This URL MUST use the https scheme."
        url = self.get("end_session_endpoint")
        if url and not is_secure_transport(url):
            raise ValueError('"end_session_endpoint" MUST use "https" scheme')
