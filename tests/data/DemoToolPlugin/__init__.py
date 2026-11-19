# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Test plug-in for SlicerSwap: one tool-bar button that does nothing.

Its icon is the interesting part. Cura recolours tool-bar icons by inserting fill="..." after
"<svg " in the icon file, so demo_tool.svg must NOT have a fill attribute on its <svg> tag.
SlicerSwap's tests make a broken copy (with one) to prove it is refused.
"""
from UM.Tool import Tool


class DemoTool(Tool):
    def __init__(self):
        super().__init__()


def getMetaData():
    return {
        "tool": {
            "name": "SlicerSwap Demo Tool",
            "description": "Does nothing (SlicerSwap test plug-in)",
            "icon": "demo_tool.svg",
            "weight": 9,
        }
    }


def register(app):
    return {"tool": DemoTool()}
