"""Valores seguros para los logs (app/logsafe.py).

Lo que llega del cliente (ids en la URL, referencias de pago, nombres de archivo) se limpia
antes de escribirlo en un log: sin saltos de línea ni caracteres de control, nadie puede
inyectar líneas falsas, y se recorta para no inflar el archivo.
"""

from __future__ import annotations

import re
from typing import Any

_CONTROL = re.compile(r"[\x00-\x1f\x7f  ]")


def clean(value: Any, limit: int = 120) -> str:
    return _CONTROL.sub(" ", str(value))[:limit]
