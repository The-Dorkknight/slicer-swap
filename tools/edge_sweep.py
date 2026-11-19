"""Run: python3 tools/edge_sweep.py   (no slicer needed; about 10 s)

Edge-case sweep for SlicerSwap. Every case must end in a clear, expected error or a correct result, never a crash
(an exception type the window does not turn into a message) and never a changed file it should not touch."""
import json, os, shutil, sys, tempfile, time, traceback, zipfile

REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
import test_manage as T  # noqa: E402
from slicerswap import install, inventory, pack, plugcheck, slicers  # noqa: E402
from slicerswap.convert import Options, convert  # noqa: E402

CLEAN = (install.InstallError, pack.PackError, ValueError, FileNotFoundError)
try:
    from slicerswap.convert import ConvertError
    CLEAN += (ConvertError,)
except ImportError:
    pass
results = []
tmp = tempfile.mkdtemp(prefix="sweep-")
pack.snapshot_dir = lambda: os.path.join(tmp, "safety")
slicers.is_running = pack.is_running = install.is_running = lambda s: False


def case(name, fn, expect="ok"):
    t = time.time()
    try:
        out = fn()
        got = f"WRONG: {out}" if isinstance(out, str) else "ok"
    except CLEAN as e:
        got = "clean-error"
        out = str(e)[:160]
    except SystemExit as e:
        got = "clean-error"
        out = str(e)[:160]
    except Exception as e:
        got = "CRASH"
        out = f"{type(e).__name__}: {e}"[:200] + "\n" + traceback.format_exc(limit=3)[-400:]
    ok = got == expect or (expect == "either" and got in ("ok", "clean-error"))
    results.append((ok, name, got, round(time.time() - t, 2), out if not ok or got != "ok" else ""))


def wb(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def rb(path):
    with open(path, "rb") as fh:
        return fh.read()


n = [0]


def fresh(sub=None):
    n[0] += 1
    return T.make_cura(os.path.join(tmp, sub or f"h{n[0]}"))


# ---------------- converter inputs ----------------
odd = os.path.join(tmp, "in")
for ext in (".ini", ".json", ".curaprofile", ".inst.cfg", ".3mf", ".orca_printer"):
    p = wb(os.path.join(odd, "empty" + ext), b"")
    case(f"convert empty {ext}", lambda p=p: convert([p], Options(target="cura", outdir=os.path.join(tmp, "o"))), "clean-error")
    p = wb(os.path.join(odd, "junk" + ext), os.urandom(4096))
    case(f"convert random bytes {ext}", lambda p=p: convert([p], Options(target="orca", outdir=os.path.join(tmp, "o"))), "clean-error")
p = wb(os.path.join(odd, "list.json"), b"[1,2,3]")
case("convert Orca json that is a list", lambda: convert([p], Options(target="prusa", outdir=os.path.join(tmp, "o"))), "clean-error")
p = wb(os.path.join(odd, "types.json"), json.dumps({"type": "process", "layer_height": ["x"], "wall_loops": {"a": 1},
                                                   "sparse_infill_density": None, "name": 5}).encode())
case("convert Orca json with wrong value types", lambda: convert([p], Options(target="cura", outdir=os.path.join(tmp, "o"))), "either")
ini = rb(os.path.join(T.DATA, [f for f in os.listdir(T.DATA) if f.endswith(".ini")][0]))
for label, data in (("BOM", b"\xef\xbb\xbf" + ini), ("CRLF", ini.replace(b"\n", b"\r\n")),
                    ("latin-1 byte", ini + b"\nnotes = caf\xe9\n"), ("junk lines", b"no equals here\n[[[\n" + ini),
                    ("duplicate keys", ini + b"\nlayer_height = 0.3\nlayer_height = 0.1\n")):
    p = wb(os.path.join(odd, label.replace(" ", "_") + ".ini"), data)
    case(f"convert Prusa .ini with {label}", lambda p=p: convert([p], Options(target="cura", outdir=os.path.join(tmp, "o"))), "either")
for nm in ("profil ünïcødé 日本.ini", "-starts-with-dash.ini", "a" * 200 + ".ini", "spaces  and . dots..ini"):
    p = wb(os.path.join(odd, "names", nm), ini)
    case(f"convert odd file name {nm[:30]!r}", lambda p=p: convert([p], Options(target="orca", outdir=os.path.join(tmp, "o2"))))
big = wb(os.path.join(odd, "big.ini"), ini + b"\n" + b"; padding comment line\n" * 2_000_000)
case("convert 46 MB .ini (time)", lambda: convert([big], Options(target="cura", outdir=os.path.join(tmp, "o"))), "either")
z = os.path.join(odd, "evil.3mf")
with zipfile.ZipFile(z, "w") as zf:
    zf.writestr("../../escape.txt", "x")
    zf.writestr("Metadata/Slic3r_PE.config", "; nothing\n")
case("convert .3mf with ../ names (must not write outside)",
     lambda: (convert([z], Options(target="cura", outdir=os.path.join(tmp, "o"))), os.path.exists(os.path.join(tmp, "escape.txt")) and "escaped")[1] or None,
     "either")
bomb = os.path.join(odd, "bomb.3mf")
with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("Metadata/Slic3r_PE.config", b"; " + b"0" * 400_000_000)
case("convert .3mf whose config unpacks to 400 MB", lambda: convert([bomb], Options(target="cura", outdir=os.path.join(tmp, "o"))), "either")
ro = os.path.join(tmp, "readonly")
os.makedirs(ro)
os.chmod(ro, 0o555)
case("convert into a read-only folder", lambda: convert([os.path.join(odd, "BOM.ini")], Options(target="cura", outdir=ro)), "either")
case("convert into a folder that does not exist", lambda: convert([os.path.join(odd, "BOM.ini")], Options(target="cura", outdir=os.path.join(tmp, "new", "deeper"))))

# ---------------- backups ----------------
src = fresh("bsrc")
good = os.path.join(tmp, "good.slicerpack")
pack.create(src, inventory.inventory(src), good, redact_secrets=False)
raw = rb(good)
for label, data in (("truncated", raw[: len(raw) // 2]), ("empty", b""), ("not a zip", b"hello"),
                    ("random", os.urandom(5000))):
    p = wb(os.path.join(tmp, "bk", label + ".slicerpack"), data)
    case(f"open backup: {label}", lambda p=p: pack.plan(p, fresh()), "clean-error")


def edited(label, fn):
    p = os.path.join(tmp, "bk", label + ".slicerpack")
    with zipfile.ZipFile(good) as a, zipfile.ZipFile(p, "w") as b:
        m = json.loads(a.read("slicerpack.json"))
        files = {n: a.read(n) for n in a.namelist() if n != "slicerpack.json"}
        m2, files = fn(m, files)
        b.writestr("slicerpack.json", m2 if isinstance(m2, (bytes, str)) else json.dumps(m2))
        for k, v in files.items():
            b.writestr(k, v)
    return p


p1 = edited("manifest not json", lambda m, f: (b"{not json", f))
p2 = edited("manifest a list", lambda m, f: (b"[]", f))
p3 = edited("no items key", lambda m, f: ({k: v for k, v in m.items() if k != "items"}, f))
p4 = edited("item without files", lambda m, f: (dict(m, items=[{"kind": "profile", "name": "x"}]), f))
p5 = edited("wrong sha", lambda m, f: (m, {k: (b"tampered" if i == 0 else v) for i, (k, v) in enumerate(f.items())}))
p6 = edited("file listed but missing", lambda m, f: (m, dict(list(f.items())[1:])))
p7 = edited("absolute path", lambda m, f: (dict(m, items=[dict(m["items"][0], files=[dict(m["items"][0]["files"][0], path="/etc/passwd")])]), f))
p8 = edited("unknown root", lambda m, f: (dict(m, items=[dict(m["items"][0], files=[dict(m["items"][0]["files"][0], root="home")])]), f))
p9 = edited("other slicer", lambda m, f: (dict(m, slicer="prusa"), f))
p10 = edited("newer format", lambda m, f: (dict(m, format=99), f))
for p in (p1, p2, p3, p4, p7, p8):
    case(f"restore backup: {os.path.basename(p)[:-11]}", lambda p=p: pack.restore(p, fresh()), "clean-error")
for p in (p5, p6):
    def chk(p=p):
        d = fresh()
        shutil.rmtree(os.path.join(d.roots["data"], "quality_changes"))
        shutil.rmtree(os.path.join(d.roots["data"], "machine_instances"))
        before = {r: rb(os.path.join(d.roots["data"], r)) for r in ("packages.json",)}
        try:
            pack.restore(p, d)
        finally:
            if rb(os.path.join(d.roots["data"], "packages.json")) != before["packages.json"]:
                return "packages.json changed by a refused restore"
    case(f"restore backup: {os.path.basename(p)[:-11]}", chk, "clean-error")
case("restore Cura backup into PrusaSlicer", lambda: pack.restore(good, T.make_prusa(os.path.join(tmp, "pr"))), "clean-error")
case("restore backup claiming another slicer", lambda: pack.restore(p9, fresh()), "clean-error")
case("restore backup in a newer format", lambda: pack.restore(p10, fresh()), "clean-error")


# interrupted restore, then undo, then undo again
def interrupted():
    d = T.make_cura(os.path.join(tmp, "intr"))
    for r, dirs, fs in os.walk(d.roots["data"]):
        for f in fs:
            if f.endswith(".inst.cfg"):
                with open(os.path.join(r, f), "a") as fh:
                    fh.write("\n# changed\n")
    before = {os.path.join(r, f): rb(os.path.join(r, f)) for root in d.roots.values() for r, _d, fs in os.walk(root) for f in fs}
    real, calls = pack._atomic_write, [0]

    def flaky(dst, data, executable=False):
        calls[0] += 1
        if calls[0] == 3:
            raise OSError(28, "No space left on device")
        return real(dst, data, executable)
    pack._atomic_write = flaky
    try:
        pack.restore(good, d)
        return "restore did not fail"
    except pack.PackError:
        pass
    finally:
        pack._atomic_write = real
    snaps = pack.list_snapshots("cura")
    if not snaps:
        return "no safety copy after an interrupted restore"
    pack.undo(snaps[0], d)
    after = {os.path.join(r, f): rb(os.path.join(r, f)) for root in d.roots.values() for r, _d, fs in os.walk(root) for f in fs}
    diff = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    if diff:
        return f"undo did not give back the state before: {diff[:3]}"
    try:
        pack.undo(snaps[0], d)          # second undo: must be refused
        return "second undo was allowed"
    except pack.PackError:
        pass
    after2 = {os.path.join(r, f): rb(os.path.join(r, f)) for root in d.roots.values() for r, _d, fs in os.walk(root) for f in fs}
    if after2 != after:
        return "second undo changed files"


case("restore interrupted by a full disk, then undo, then undo again", interrupted)


def undo_after_user_edit():
    d = T.make_cura(os.path.join(tmp, "ue"))
    for r, dirs, fs in os.walk(d.roots["data"]):
        for f in fs:
            if f.endswith("my_profile.inst.cfg"):
                with open(os.path.join(r, f), "a") as fh:
                    fh.write("\n# old\n")
    pack.restore(good, d)
    snap = pack.list_snapshots("cura")[0]
    pack.undo(snap, d)
    target = [os.path.join(r, f) for r, _d, fs in os.walk(d.roots["data"]) for f in fs if f.endswith("ender3_my_profile.inst.cfg")][0]
    with open(target, "a") as fh:
        fh.write("\n# user edit after undo\n")
    try:
        pack.undo(snap, d)   # a second undo days later
    except pack.PackError:
        pass
    if b"user edit after undo" not in rb(target):
        return "a second undo silently overwrote a change made after the first undo"


case("undo twice after the user edited a file in between", undo_after_user_edit)


def readonly_restore():
    d = T.make_cura(os.path.join(tmp, "ro2"))
    shutil.rmtree(os.path.join(d.roots["data"], "quality_changes"))
    os.chmod(d.roots["data"], 0o555)
    try:
        pack.restore(good, d)
    finally:
        os.chmod(d.roots["data"], 0o755)


case("restore into a read-only Cura folder", readonly_restore, "either")
case("restore into a folder that does not exist yet", lambda: pack.restore(good, slicers.Install("cura", "5.13", {
    k: os.path.join(tmp, "nothere", k) for k in ("config", "data", "cache")})))
case("restore with Cura open", lambda: pack.restore(good, fresh(), allow_running=False) if not setattr(pack, "is_running", lambda s: True) else None, "clean-error")
pack.is_running = lambda s: False
install.is_running = lambda s: True
case("install plug-in with Cura open", lambda: install.install_cura_plugin(fresh(), T.CuraPluginFaults.TOOL), "clean-error")
install.is_running = lambda s: False

# ---------------- plug-ins ----------------
DEMO = os.path.join(T.DATA, "DemoCuraPlugin")


def zipof(name, entries):
    p = os.path.join(tmp, "plug", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with zipfile.ZipFile(p, "w") as zf:
        for k, v in entries.items():
            zf.writestr(k, v)
    return p


INIT = "def getMetaData():\n    return {}\ndef register(app):\n    return {}\n"
cases = {
    "plugin.json not json": zipof("a.zip", {"P/plugin.json": "{nope", "P/__init__.py": INIT}),
    "plugin.json a list": zipof("b.zip", {"P/plugin.json": "[]", "P/__init__.py": INIT}),
    "plugin.json not UTF-8": zipof("c.zip", {"P/plugin.json": b"\xff\xfe{}", "P/__init__.py": INIT}),
    "no plugin.json": zipof("d.zip", {"P/__init__.py": INIT}),
    "curapackage with ../ id": zipof("e.curapackage", {"package.json": json.dumps({"package_id": "../../../evil", "package_type": "plugin"}),
                                                       "files/plugins/evil/plugin.json": "{}", "files/plugins/evil/__init__.py": INIT}),
    "curapackage id not a string": zipof("f.curapackage", {"package.json": json.dumps({"package_id": {"a": 1}}),
                                                           "files/plugins/x/plugin.json": "{}", "files/plugins/x/__init__.py": INIT}),
    "curapackage package.json broken": zipof("g.curapackage", {"package.json": "{", "files/plugins/x/plugin.json": "{}"}),
    "zip with ../ entries": zipof("h.zip", {"P/plugin.json": '{"name":"P","version":"1.0.0","api":8}', "P/__init__.py": INIT,
                                            "P/../../../escaped.py": "x"}),
}
for label, p in cases.items():
    def go(p=p, label=label):
        d = fresh()
        pk = rb(os.path.join(d.roots["data"], "packages.json"))
        try:
            install.install_cura_plugin(d, p)
        finally:
            leaked = [os.path.join(r, f) for r, _d, fs in os.walk(tmp) for f in fs if f in ("evil.curapackage", "escaped.py")]
            if leaked:
                return f"wrote outside Cura's folders: {leaked}"
    case(f"install plug-in: {label}", go, "clean-error" if "../ entries" not in label else "either")
d = os.path.join(tmp, "plug", "My Odd-Plugin v2")
shutil.copytree(DEMO, d)
def oddfolder():
    r = install.install_cura_plugin(fresh(), d)
    if r.name != "MyOddPlugin":
        return f"id {r.name!r}"
    r2 = install.read_plugin_source(zipof("MyOdd-Plugin-main.zip", {"MyOdd-Plugin-main/plugin.json": '{"name":"x"}', "MyOdd-Plugin-main/__init__.py": INIT}))
    if r2["plugin_id"] != "MyOddPlugin":
        return f"zip id {r2['plugin_id']!r} differs from folder id"
case("install plug-in from a folder with spaces/dashes in its name", oddfolder)
corrupt_zip = wb(os.path.join(tmp, "plug", "corrupt.zip"), rb(zipof("ok.zip", {"P/plugin.json": '{"name":"P"}', "P/__init__.py": INIT}))[:-30])
case("install plug-in from a truncated zip", lambda: install.install_cura_plugin(fresh(), corrupt_zip), "clean-error")


def reinstall():
    inst = fresh()
    install.install_cura_plugin(inst, DEMO)
    install.install_cura_plugin(inst, DEMO)
    _p, pk = inventory.cura_packages(inst)
    if list(pk["to_install"]).count("DemoCuraPlugin") != 1 or "PkgPlugin" not in pk["installed"]:
        return "queue wrong after installing twice"


case("install the same plug-in twice before starting Cura", reinstall)


def queued_for_removal():
    inst = fresh()
    install.remove_cura_plugin(inst, "PkgPlugin")
    st = dict((p["plugin_id"], s) for p, s, _w in install.cura_plugin_report(inst))
    if st.get("PkgPlugin") != "waiting":
        return f"queued-for-removal shows {st.get('PkgPlugin')}"
    install.remove_cura_plugin(inst, "PkgPlugin")   # twice
    if inventory.cura_packages(inst)[1]["to_remove"].count("PkgPlugin") != 1:
        return "listed twice for removal"


case("remove a plug-in twice", queued_for_removal)


def disabled():
    inst = fresh()
    T.w(os.path.join(inst.roots["config"], "plugins.json"), '{"disabled": ["LoosePlugin"]}')
    st, why = install.check_cura_plugin(inst, "LoosePlugin")
    if st != "failed" or "Switched off" not in why:
        return f"{st}: {why}"
    T.w(os.path.join(inst.roots["config"], "plugins.json"), '{"disabled": "LoosePlugin"')   # broken plugins.json
    install.check_cura_plugin(inst, "LoosePlugin")


case("disabled plug-in, then a broken plugins.json", disabled)
case("remove a plug-in that is not there", lambda: install.remove_cura_plugin(fresh(), "Nope"), "clean-error")
case("remove with a name containing ../", lambda: install.remove_cura_plugin(fresh(), "../../.."), "clean-error")

# ---------------- Cura's log ----------------
for label, data in (("missing", None), ("empty", b""), ("binary", os.urandom(20000)),
                    ("cut mid-line", T.LOG_START.format(t="10:00:00").encode() + b"2026-10-06 10:00:01,000 - INFO - [MainThread] UM.PluginRegistry.loadPlugin [540]: Loaded plu"),
                    ("not UTF-8", T.LOG_START.format(t="10:00:00").encode() + "Loaded plugin LoosePlugin 1.2.0 caf\xe9\n".encode("latin-1")),
                    ("100 MB", b"2026-10-06 09:00:00,000 - DEBUG - [MainThread] x.y [1]: filler line\n" * 1_400_000 + rb(os.path.join(fresh("lg").roots["data"], "cura.log")))):
    def lg(label=label, data=data):
        inst = fresh()
        p = os.path.join(inst.roots["data"], "cura.log")
        if data is None:
            os.remove(p)
        else:
            wb(p, data)
        t = time.time()
        rep = install.cura_plugin_report(inst)
        if time.time() - t > 10:
            return f"took {time.time() - t:.0f} s"
        if label == "100 MB":
            st = dict((p["plugin_id"], s) for p, s, _w in rep)
            if st.get("LoosePlugin") != "loaded":
                return f"LoosePlugin {st.get('LoosePlugin')} at the end of a big log"
    case(f"Cura log: {label}", lg)


def two_versions():
    h = os.path.join(tmp, "multi")
    a, b = T.make_cura(h, "5.12"), T.make_cura(h, "5.13")
    install.install_cura_plugin(b, DEMO)
    if "DemoCuraPlugin" in inventory.cura_packages(a)[1].get("to_install", {}):
        return "installed into the wrong Cura version"


case("two Cura versions side by side", two_versions)

# ---------------- report ----------------
shutil.rmtree(tmp, ignore_errors=True)
bad = [r for r in results if not r[0]]
for ok, name, got, secs, out in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  [{got}, {secs}s]" + (f"\n      {out}" if out else ""))
print(f"\n{len(results) - len(bad)}/{len(results)} as expected")
