"""Schemas Pydantic — Circa Integration API v1."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class BodegaUpsertRequest(BaseModel):
    """Alta o actualización de bodega/cliente desde el sistema del socio."""

    external_id: Optional[str] = Field(
        default=None,
        description="ID del cliente en el sistema del socio (recomendado para no duplicar).",
        max_length=64,
    )
    telefono_whatsapp: str = Field(
        ...,
        description="WhatsApp del dueño. 9 dígitos o +51XXXXXXXXX",
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
    created_at: Optional[str] = None
    items: Optional[list[dict[str, Any]]] = None


class ListResponse(BaseModel):
    total: int
    items: list[dict[str, Any]]


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
