class AuthError(Exception):
    def __init__(self, provider_id: str, message: str = ""):
        self.provider_id = provider_id
        super().__init__(f"[{provider_id}] {message}" if message else provider_id)


class ProviderNotFoundError(AuthError):
    pass


class ClientCredsMissingError(AuthError):
    pass


class NotLoggedInError(AuthError):
    pass


class ReauthRequiredError(AuthError):
    pass


class ScopeNotGrantedError(AuthError):
    def __init__(self, provider_id: str, missing_scopes: list[str]):
        self.missing_scopes = missing_scopes
        super().__init__(provider_id, f"missing scopes: {', '.join(missing_scopes)}")


class LoginFlowExpired(AuthError):
    pass


class LoginDenied(AuthError):
    pass
