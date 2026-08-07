from klipper_extras.ace_device import load_config_prefix
from klipper_extras.ace_hardware import load_config as load_hardware
from klipper_extras.ace_machine import load_config as load_machine


class Config:
    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name


def test_passive_config_sections_are_loadable_by_stock_klipper():
    assert load_hardware(Config("ace_hardware")).get_status()["schema_version"] == 3
    assert load_machine(Config("ace_machine")).get_status()["managed_by"] == "ace"
    assert load_config_prefix(Config("ace_device ace2")).get_status()["device_id"] == "ace2"
