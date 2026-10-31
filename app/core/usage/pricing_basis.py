"""Immutable effective unit prices for one subscription request."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.usage.pricing import ModelPrice, UsageTokens, _effective_rates


class RequestPricingBasis(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", allow_inf_nan=False, alias_generator=to_camel, populate_by_name=True
    )

    schema_version: Literal[1] = 1
    price_version: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model: str
    input_per_1m: float = Field(ge=0)
    cached_input_per_1m: float = Field(ge=0)
    cache_write_input_per_1m: float = Field(ge=0)
    output_per_1m: float = Field(ge=0)

    def effective_price(self) -> ModelPrice:
        return ModelPrice(
            input_per_1m=self.input_per_1m,
            cached_input_per_1m=self.cached_input_per_1m,
            cache_write_input_per_1m=self.cache_write_input_per_1m,
            output_per_1m=self.output_per_1m,
        )


def capture_pricing_basis(
    model: str, usage: UsageTokens, price: ModelPrice, service_tier: str | None
) -> RequestPricingBasis:
    encoded = json.dumps(
        {"model": model, "rates": asdict(price)}, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    input_rate, cached_rate, output_rate, write_rate = _effective_rates(usage, price, service_tier=service_tier)
    return RequestPricingBasis(
        price_version="sha256:" + hashlib.sha256(encoded.encode()).hexdigest(),
        model=model,
        input_per_1m=input_rate,
        cached_input_per_1m=cached_rate,
        cache_write_input_per_1m=write_rate,
        output_per_1m=output_rate,
    )
