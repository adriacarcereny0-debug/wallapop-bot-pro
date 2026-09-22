"""Errores de la integracion con Wallapop.

Todos llevan un mensaje entendible para el usuario (`user_message`) y un
detalle tecnico que va al log. Nunca se ocultan los errores de Wallapop.
"""

from __future__ import annotations


class WallapopError(Exception):
    """Error base de la capa de integracion."""

    user_message = "Se ha producido un error al comunicar con Wallapop."
    retryable = False

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        self.detail = detail
        if user_message:
            self.user_message = user_message
        super().__init__(detail or self.user_message)


class NotAvailableWithCurrentAPIError(WallapopError):
    """La operacion no esta disponible con la API/permisos autorizados.

    Se lanza en lugar de simular la accion. El codigo de error
    `NOT_AVAILABLE_WITH_CURRENT_API` se muestra tal cual en la interfaz.
    """

    code = "NOT_AVAILABLE_WITH_CURRENT_API"
    user_message = (
        "Esta funcion requiere un endpoint o permiso que la integracion "
        "autorizada no proporciona actualmente."
    )

    def __init__(self, operation: str, reason: str = "") -> None:
        self.operation = operation
        self.reason = reason
        detail = f"{self.code}: operacion '{operation}' no disponible."
        if reason:
            detail += f" {reason}"
        super().__init__(detail)


class AuthenticationError(WallapopError):
    """Token ausente, caducado o rechazado."""

    user_message = (
        "La cuenta no esta autorizada o la sesion ha caducado. "
        "Vuelve a conectar la cuenta desde la pantalla Cuentas Wallapop."
    )


class AuthorizationError(WallapopError):
    """El token es valido pero no tiene el permiso (scope) necesario."""

    user_message = (
        "La cuenta no tiene permisos suficientes para esta operacion. "
        "Revisa los permisos concedidos a la integracion."
    )


class RateLimitError(WallapopError):
    """Wallapop ha limitado el numero de peticiones."""

    user_message = "Wallapop ha limitado temporalmente las peticiones. Reintenta en unos minutos."
    retryable = True

    def __init__(self, detail: str = "", retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(detail)


class ValidationRejectedError(WallapopError):
    """Wallapop ha rechazado los datos enviados."""

    user_message = (
        "Wallapop no ha aceptado la publicacion. Revisa los campos obligatorios del anuncio."
    )

    def __init__(self, detail: str = "", fields: dict[str, str] | None = None) -> None:
        self.fields = fields or {}
        super().__init__(detail)


class NotFoundError(WallapopError):
    user_message = "El elemento solicitado ya no existe en Wallapop."


class NetworkError(WallapopError):
    user_message = "No hay conexion con Wallapop. Comprueba tu conexion a internet."
    retryable = True


class ServiceUnavailableError(WallapopError):
    user_message = "Wallapop no esta disponible en este momento. Reintenta mas tarde."
    retryable = True


class ConfigurationError(WallapopError):
    """Falta configuracion obligatoria para usar la integracion real."""

    user_message = (
        "La integracion con Wallapop no esta configurada. "
        "Revisa las credenciales y el mapa de endpoints oficial."
    )
