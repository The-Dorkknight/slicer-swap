import json, os
from UM.Extension import Extension
from UM.Logger import Logger
from PyQt6.QtCore import QTimer


class Hook(Extension):
    def __init__(self):
        super().__init__()
        from cura.CuraApplication import CuraApplication
        self._app = CuraApplication.getInstance()
        self._app.initializationFinished.connect(self._later)

    def _later(self):
        QTimer.singleShot(4000, self._go)

    def _go(self):
        app = self._app
        out = {"imports": [], "errors": []}
        try:
            reg = app.getContainerRegistry()
            gs = app.getGlobalContainerStack()
            out["active_machine"] = gs.getName() if gs else None
            out["cura_version"] = app.getVersion()
            for p in [x for x in os.environ.get("SSW_IMPORT", "").split(os.pathsep) if x]:
                try:
                    res = reg.importProfile(p)
                except Exception as e:
                    res = {"status": "exception", "message": repr(e)}
                out["imports"].append({"file": p, "result": res})
                Logger.log("i", "SSWHOOK import %s -> %s", p, res)
            out["quality_changes"] = sorted({m.get("name") for m in reg.findInstanceContainersMetadata(type="quality_changes")})
            out["machines"] = sorted(m.get("name", m.get("id")) for m in reg.findContainerStacksMetadata(type="machine"))
            from UM.PluginRegistry import PluginRegistry
            pr = PluginRegistry.getInstance()
            ap = sorted(pr.getActivePlugins()); out["active_plugins_count"] = len(ap); out["active_plugins_user"] = [x for x in ap if os.environ.get("SSW_PLUGINS") and x in os.environ["SSW_PLUGINS"].split(",")]
            pm = app.getPackageManager()
            out["user_packages"] = sorted(getattr(pm, "_installed_package_dict", {}).keys()); out["to_install"] = sorted(getattr(pm, "_to_install_package_dict", {}).keys())
            try:
                from cura.Machines.ContainerTree import ContainerTree
                if gs:
                    groups = ContainerTree.getInstance().getCurrentQualityChangesGroups()
                    out["quality_changes_groups"] = [{"name": g.name, "quality_type": g.quality_type,
                                                     "available": bool(g.is_available),
                                                     "has_global": bool(g.metadata_for_global),
                                                     "extruders": sorted(g.metadata_per_extruder.keys())} for g in groups]
            except Exception as e:
                out["errors"].append("groups: " + repr(e))
            act = os.environ.get("SSW_ACTIVATE")
            if act and gs:
                try:
                    groups = ContainerTree.getInstance().getCurrentQualityChangesGroups()
                    g = [x for x in groups if x.name == act]
                    if g:
                        app.getMachineManager().setQualityChangesGroup(g[0], no_dialog=True)
                        ex = gs.extruderList[0]
                        keys = [k for k in os.environ.get("SSW_KEYS", "").split(",") if k]
                        out["activated"] = act
                        out["values"] = {k: (ex.getProperty(k, "value") if ex.getProperty(k, "value") is not None else gs.getProperty(k, "value")) for k in keys}
                        out["global_values"] = {k: gs.getProperty(k, "value") for k in keys}
                    else:
                        out["errors"].append("no group named " + act)
                except Exception as e:
                    import traceback
                    out["errors"].append("activate: " + traceback.format_exc())
        except Exception as e:
            import traceback
            out["errors"].append(traceback.format_exc())
        try:
            dump = os.environ.get("SSW_DUMP")
            gs = app.getGlobalContainerStack()
            if dump and gs:
                ex = gs.extruderList[0]
                d = {}
                for k in gs.getAllKeys():
                    try:
                        d[k] = {"g": gs.getProperty(k, "value"), "e": ex.getProperty(k, "value"),
                                "pe": gs.getProperty(k, "settable_per_extruder"), "t": gs.getProperty(k, "type")}
                    except Exception as e:
                        d[k] = {"err": repr(e)}
                with open(dump, "w") as fh:
                    json.dump({"stack": [c.getId() for c in ex.getContainers()], "gstack": [c.getId() for c in gs.getContainers()], "values": d}, fh, default=str)
        except Exception:
            import traceback
            out["errors"].append(traceback.format_exc())
        dst = os.environ.get("SSW_OUT")
        if dst:
            with open(dst, "w") as fh:
                json.dump(out, fh, indent=1, default=str)
        Logger.log("i", "SSWHOOK done %s", json.dumps(out, default=str)[:2000])
        if os.environ.get("SSW_QUIT"):
            QTimer.singleShot(int(os.environ.get("SSW_QUIT_MS", "25000")), app.closeApplication)


def getMetaData():
    return {}


def register(app):
    return {"extension": Hook()}
