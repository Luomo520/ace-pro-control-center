"""Ace Pro Control Center Klipper extra entry point.

Keep imports lazy so protocol/configuration tooling can run outside Klipper.
"""

from typing import Any

PRODUCT_NAME = "Ace Pro Control Center"
PRODUCT_NAME_ZH = "ACE Pro 管理中心"
__version__ = "V2.5ahpha"


def load_config(config: Any) -> Any:
    from .klipper import KlipperAceComponent

    return KlipperAceComponent(config)


__all__ = ["PRODUCT_NAME", "PRODUCT_NAME_ZH", "__version__", "load_config"]
