"""Contracts for the existing commerce API; identifiers match its VARCHAR(64)."""
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StrictInt, StringConstraints

Text = Annotated[str, StringConstraints(strict=True, min_length=1)]


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("用户 ID 或订单号格式无效。")
    return value


class Envelope(BaseModel):
    code: StrictInt
    data: dict


class OrderStatus(BaseModel):
    order_id: Text
    status: Text
    status_desc: Text


class OrderSummary(BaseModel):
    order_id: Text
    title: Text
    status: Text
    amount: Decimal = Field(ge=0)
    created_at: datetime
    cover_url: str | None = None


class UserOrders(BaseModel):
    user_id: Text
    orders: list[OrderSummary]


class Trace(BaseModel):
    time: datetime
    desc: Text


class Logistics(OrderStatus):
    logistics_company: Text
    tracking_number: Text
    traces: list[Trace]


class ShippingResult(OrderStatus):
    request_type: Literal['shipping_reminder']
    request_id: Text
    status: Literal['submitted', 'processing', 'completed']


class RefundResult(OrderStatus):
    request_type: Literal['refund_application']
    request_id: Text
    status: Literal['submitted', 'processing', 'completed', 'rejected']

class ProductData(BaseModel):
    product_id: Text
    title: Text
    description: Text
    price: Decimal = Field(ge=0)
    stock_status: Text
    cover_url: str | None = None
    attributes: dict
