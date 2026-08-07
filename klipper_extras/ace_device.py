"""Passive Klipper loader for Ace Pro Control Center [ace_device aceN] sections."""


class AceDeviceSection:
    def __init__(self, config):
        self.config = config

    def get_status(self, _eventtime=None):
        name = self.config.get_name().split(None, 1)[-1]
        return {"device_id": name, "managed_by": "ace"}


def load_config_prefix(config):
    return AceDeviceSection(config)
