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


class NotAvailableWithCurrentAccessError(WallapopError):
    """La operacion no esta disponible con el acceso autorizado actual.

    Se lanza en lugar de simular la accion. El codigo
    `NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS` se muestra tal cual en la
    interfaz y se devuelve tal cual a la IA.

    El nombre habla de «acceso» y no de «API» a proposito: el mecanismo
    autorizado puede no ser una API.
    """

    code = "NOT_AVAILABLE_WITH_CURRENT_WALLAPOP_ACCESS"
    user_message = (
        "Esta función requiere una operación o un permiso que el acceso "
        "autorizado a Wallapop no proporciona actualmente."
    )

    def __init__(self, operation: str, reason: str = "") -> None:
        self.operation = operation
        self.reason = reason
        detail = f"{self.code}: operación '{operation}' no disponible."
        if reason:
            detail += f" {reason}"
        super().__init__(detail)


#: Nombre anterior, mantenido para no romper importaciones existentes.
NotAvailableWithCurrentAPIError = NotAvailableWithCurrentAccessError


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
    """Falta configuracion obligatoria para usar el acceso real."""

    user_message = (
        "El acceso a Wallapop no está configurado. Revisa el perfil de acceso "
        "autorizado en Configuración → Wallapop."
    )


class AccessNotConfiguredError(WallapopError):
    """No hay ningun mecanismo de acceso autorizado declarado.

    Lleva la lista exacta de lo que falta, para poder mostrarla al usuario en
    vez de un mensaje generico.
    """

    user_message = (
        "Todavía no está configurado el mecanismo de acceso autorizado a Wallapop."
    )

    def __init__(self, missing: list[str] | None = None) -> None:
        self.missing = missing or []
        detail = "Acceso no configurado."
        if self.missing:
            detail += " Falta: " + " | ".join(self.missing)
        super().__init__(detail)
