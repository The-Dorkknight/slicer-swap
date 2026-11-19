# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""A do-nothing Cura plug-in used by SlicerSwap's tests of plug-in installation."""
from UM.Extension import Extension
from UM.Logger import Logger


class DemoCuraPlugin(Extension):
    def __init__(self):
        super().__init__()
        self.setMenuName("SlicerSwap demo")
        self.addMenuItem("Say hello in the log", self._hello)

    def _hello(self):
        Logger.log("i", "SlicerSwap demo plug-in says hello")


def getMetaData():
    return {}


def register(app):
    return {"extension": DemoCuraPlugin()}
