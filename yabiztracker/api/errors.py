class ApiError(RuntimeError):
    def __init__(self, message, *, api="", status=None, technical=""):
        super().__init__(message); self.api=api; self.status=status; self.technical=technical or message
class ApiLimitError(ApiError): pass
class ApiAuthError(ApiError): pass
class ApiNetworkError(ApiError): pass
class ApiServerError(ApiError): pass
class ApiInvalidResponseError(ApiError): pass
class ApiCancelledError(ApiError): pass
