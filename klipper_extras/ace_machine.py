"""Passive Klipper loader for Ace Pro Control Center [ace_machine] hooks."""


class AceMachineSection:
    def __init__(self, config):
        self.config = config

    def get_status(self, _eventtime=None):
        return {"managed_by": "ace"}


def load_config(config):
    return AceMachineSection(config)
