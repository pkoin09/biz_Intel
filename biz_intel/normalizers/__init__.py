"""
Business data normalizers.
"""

from .registry import registry

from .address import normalize_address
from .email import normalize_email
from .phone import normalize_phone
from .helpers.text import normalize_text
from .name import normalize_name
from .website import normalize_website


registry.register("name", normalize_name)
registry.register("category", normalize_text)

registry.register("address", normalize_address)
registry.register("city", normalize_text)
registry.register("state", normalize_text)
registry.register("country", normalize_text)

registry.register("phone", normalize_phone)
registry.register("email", normalize_email)
registry.register("website", normalize_website)
