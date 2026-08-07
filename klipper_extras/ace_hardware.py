"""Passive Klipper loader for the Ace Pro Control Center [ace_hardware] section."""


class AceHardwareSection:
    def __init__(self, config):
        self.config = config

    def get_status(self, _eventtime=None):
        return {"managed_by": "ace", "schema_version": 3}


def load_config(config):
    return AceHardwareSection(config)
