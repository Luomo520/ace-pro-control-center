from __future__ import annotations

import pytest

from ace_driver.protocol import (
    ProtocolCapabilities,
    create_protocol,
    crc16_mcrf4xx,
)
from ace_driver.protocol_ace1 import Ace1Protocol
from ace_driver.protocol_ace2 import Ace2Protocol


def test_factory_exports_stable_protocol_contract():
    for model, expected_type in (("ace1", Ace1Protocol), ("ace2", Ace2Protocol)):
        protocol = create_protocol(model)
        assert isinstance(protocol, expected_type)
        assert isinstance(protocol.capabilities, ProtocolCapabilities)
        assert callable(protocol.encode_request)
        assert callable(protocol.decode_response)
        assert callable(protocol.normalize_status)


def test_factory_rejects_unknown_models():
    with pytest.raises(ValueError, match="Unsupported ACE model"):
        create_protocol("future-ace")


def test_crc16_mcrf4xx_known_vector():
    assert crc16_mcrf4xx(b"123456789") == 0x6F91
