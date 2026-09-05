"""Schemas Pydantic — Circa Integration API v1."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class BodegaUpsertRequest(BaseModel):
    """Alta o actualización de bodega/cliente desde el sistema del socio.

    En producción el socio debe usar `multipart/form-data` e incluir
    `foto_dueno` + `foto_bodega`. Este schema documenta los campos de texto;
    las fotos van como archivos en el mismo POST.
    """

    external_id: Optional[str] = Field(
        default=None,
        description="ID del cliente en el sistema del socio (opcional).",
        max_length=64,
    )
    telefono_whatsapp: str = Field(
        ...,
        description="Celular del dueño. 9 dígitos o +51XXXXXXXXX",
        examples=["987654321"],
    )
    dni_representante: Optional[str] = Field(
        default=None,
        description="DNI 8 dígitos o CE 9 dígitos",
        examples=["42868000"],
    )
    ruc: Optional[str] = Field(default=None, description="RUC 11 dígitos (opcional)")
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    representante_legal: Optional[str] = None
    direccion_fiscal: Optional[str] = None
    distrito: Optional[str] = None
    solo_dni_sin_ruc: bool = Field(
        default=True,
        description="True si no tiene RUC (onboarding solo DNI/CE)",
    )

    @model_validator(mode="after")
    def _exige_identidad(self) -> "BodegaUpsertRequest":
        if not (self.dni_representante or "").strip() and not (self.ruc or "").strip():
            raise ValueError("Envíe dni_representante o ruc")
        return self


class BodegaPatchRequest(BaseModel):
    telefono_whatsapp: Optional[str] = None
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    representante_legal: Optional[str] = None
    direccion_fiscal: Optional[str] = None
    distrito: Optional[str] = None
    external_id: Optional[str] = None


class BodegaResponse(BaseModel):
    id: str
    external_id: Optional[str] = None
    telefono_whatsapp: Optional[str] = None
    dni_representante: Optional[str] = None
    ruc: Optional[str] = None
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    estado: Optional[str] = None
    onboarding_fase: Optional[str] = None
    kyc_nivel: Optional[str] = None
    linea_aprobada: Optional[float] = None
    linea_disponible: Optional[float] = None
    situacion: Literal[
        "en_evaluacion",
        "no_disponible",
        "con_linea",
    ] = Field(
        ...,
        description=(
            "Resumen para UI del socio: "
            "en_evaluacion = data ya enviada / sin activar; "
            "no_disponible = activa sin cupo; "
            "con_linea = puede financiar (SVC-04). "
            "En listados vacíos usar situacion=no_registrada a nivel respuesta."
        ),
    )
    tiene_foto_dueno: bool = False
    tiene_foto_bodega: bool = False
    es_test: bool = Field(
        default=False,
        description="True si la bodega pertenece al modo prueba (/api/v1/test)",
    )
    created: bool = Field(default=False, description="True si se creó en este request")


class PreventaItem(BaseModel):
    sku: Optional[str] = None
    nombre: str
    cantidad: float = Field(..., gt=0)
    precio_unitario: float = Field(..., ge=0)
    unidad: Optional[str] = "UND"


class PreventaCreateRequest(BaseModel):
    external_id: Optional[str] = Field(
        default=None,
        description="ID de la preventa/pedido en el sistema del socio",
    )
    bodega_id: Optional[str] = Field(default=None, description="UUID Circa de la bodega")
    bodega_external_id: Optional[str] = Field(
        default=None,
        description="external_id de la bodega en el sistema del socio (alternativa a bodega_id)",
    )
    telefono_whatsapp: Optional[str] = Field(
        default=None,
        description="WhatsApp bodega (alternativa de lookup)",
    )
    items: list[PreventaItem] = Field(..., min_length=1)
    monto_a_financiar: float = Field(
        ...,
        gt=0,
        description="Monto a financiar con Circa (S/). Debe ser ≤ total de ítems y ≤ linea_disponible",
    )
    plazo_dias: Literal[7, 15, 30] = Field(
        ...,
        description="Plazo del crédito en días: 7, 15 o 30",
    )
    vendedor_codigo: Optional[str] = None
    notas: Optional[str] = None


class PedidoEstadoPatch(BaseModel):
    estado: str = Field(
        ...,
        description="Nuevo estado operativo",
        examples=["recibido", "en_camino", "entregado", "preventa_aceptada"],
    )
    comentario: Optional[str] = None


class PedidoResponse(BaseModel):
    id: str
    external_id: Optional[str] = None
    numero: Optional[str] = None
    bodega_id: Optional[str] = None
    estado: Optional[str] = None
    tipo_operacion: Optional[str] = None
    total_pedido: Optional[float] = None
    monto_financiado: Optional[float] = None
    plazo_dias: Optional[int] = None
    created_at: Optional[str] = None
    items: Optional[list[dict[str, Any]]] = None


class ListResponse(BaseModel):
    total: int
    items: list[dict[str, Any]]
    situacion: Literal[
        "no_registrada",
        "en_evaluacion",
        "no_disponible",
        "con_linea",
    ] = Field(
        ...,
        description=(
            "Situación del primer match (o no_registrada si total=0). "
            "El socio debe preferir items[0].situacion si eligió otro item."
        ),
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "circa-integration-api"
    version: str = "1.0.0"
    data_mode: Literal["prod", "test"] = Field(
        default="prod",
        description="prod = /api/v1 · test = /api/v1/test",
    )


class TokenRequest(BaseModel):
    grant_type: Literal["client_credentials"] = "client_credentials"
    client_id: str = Field(..., min_length=1, description="api_client_id del distribuidor")
    client_secret: str = Field(..., min_length=1, description="api_client_secret del distribuidor")
    data_mode: Literal["prod", "test"] = Field(
        default="prod",
        description="prod → access_token de producción; test → access_token de pruebas",
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    data_mode: Literal["prod", "test"]
    expires_in: Optional[int] = Field(
        default=None,
        description="Null = token de larga duración (no expira automáticamente)",
    )
    distribuidor_id: str
    distribuidor: Optional[str] = None
