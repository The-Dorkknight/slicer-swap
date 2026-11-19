# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
# WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN
"""The SlicerSwap window: Slicers, Convert, Back up, Restore and Plug-ins tabs (tkinter only)."""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import threading
import time
import traceback

from . import VERSION_LINE, __build_date__, __version__

APP = "SlicerSwap"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "slicerswap")
ACCEPT_FILE = os.path.join(CONFIG_DIR, "disclaimer_accepted_0.2")

DISCLAIMER = (
    "SlicerSwap converts slicer settings between programs that do not work the same way, and it can "
    "write into your slicers' settings folders (restore a backup, install profiles and plug-ins).\n\n"
    "Wrong temperatures, speeds, retraction or start G-code can ruin prints or damage a printer. "
    "Read the conversion report and check every preset in the slicer before printing. Plug-ins are "
    "programs: only install ones you trust.\n\n"
    "Before it replaces any file SlicerSwap keeps a safety copy, and it never changes your original "
    "profile files. Even so: this is work-in-progress, source-available software provided as is, "
    "without any warranty. The author accepts no liability for any damage or loss."
)

CHECKED, UNCHECKED, PARTIAL = "\u2611", "\u2610", "\u25a3"


def open_folder(path: str):
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def run(prefill=None) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("tkinter is not installed. On Linux Mint/Ubuntu: sudo apt install python3-tk\n"
              "You can still use the command line: python3 -m slicerswap --help")
        return 1

    from . import install as installer
    from . import inventory as inv
    from . import pack, plugcheck, slicers
    from .convert import LABEL, Options, convert, detect
    from .cura_engine import Resources, candidate_resource_dirs

    root = tk.Tk()
    root.title(f"{APP} {__version__} (Built {__build_date__}) - WORK IN PROGRESS")
    root.minsize(860, 660)
    try:
        root.iconphoto(True, tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "data", "icon-64.png")))
    except Exception:
        pass
    pf = prefill or {}
    status = tk.StringVar(value=f"v{__version__} - {__build_date__} - WORK IN PROGRESS")
    BASE_STATUS = f"v{__version__} - {__build_date__} - WORK IN PROGRESS"

    def set_status(msg: str = ""):
        status.set(f"{msg}   |   {BASE_STATUS}" if msg else BASE_STATUS)

    # ---- disclaimer -------------------------------------------------------
    def disclaimer() -> bool:
        if os.path.exists(ACCEPT_FILE):
            return True
        dlg = tk.Toplevel(root)
        dlg.title(f"{APP} - please read")
        dlg.transient(root)
        dlg.resizable(False, False)
        ok = {"v": False}
        tk.Label(dlg, text="Before you start", font=("TkDefaultFont", 12, "bold")).pack(padx=18, pady=(16, 6), anchor="w")
        tk.Message(dlg, text=DISCLAIMER, width=500).pack(padx=18, anchor="w")
        agree = tk.BooleanVar(value=False)
        row = tk.Frame(dlg)
        btn = ttk.Button(row, text="I agree", state="disabled")
        ttk.Checkbutton(dlg, text="I understand and will check presets and plug-ins before printing",
                        variable=agree, command=lambda: btn.configure(state="normal" if agree.get() else "disabled")
                        ).pack(padx=18, pady=10, anchor="w")

        def accept():
            ok["v"] = True
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(ACCEPT_FILE, "w", encoding="utf-8") as fh:
                    fh.write(__version__ + "\n")
            except OSError:
                pass  # shown again next time, which is fine
            dlg.destroy()
        btn.configure(command=accept)
        row.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(row, text="Quit", command=dlg.destroy).pack(side="right")
        btn.pack(side="right", padx=8)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - dlg.winfo_reqwidth()) // 2)
        y = root.winfo_rooty() + 80
        dlg.geometry(f"+{x}+{y}")
        dlg.grab_set()
        root.wait_window(dlg)
        return ok["v"]

    # ---- shared state -------------------------------------------------------
    state = {"installs": [], "custom": [], "res": None, "listeners": []}

    def resources():
        if state["res"] is None:
            d = (candidate_resource_dirs() or [None])[0]
            try:
                state["res"] = Resources(d)
            except Exception:
                state["res"] = Resources()
        return state["res"]

    def installs(slicer=None):
        return [i for i in state["installs"] if slicer is None or i.slicer == slicer]

    def rescan():
        found = slicers.detect()
        keys = {i.key for i in found}
        state["installs"] = found + [c for c in state["custom"] if c.key not in keys]
        for fn in state["listeners"]:
            fn()

    def by_label(label, slicer=None):
        return next((i for i in installs(slicer) if i.label == label or f"{i.label}  -  {i.main_folder}" == label), None)

    def long_label(i):
        return f"{i.label}  -  {i.main_folder}"

    def open_ok(inst):
        """None = the user backed out. Otherwise the allow_running flag for the engine call.
        The slicer keeps its settings in memory while it is open and may write them back when it closes."""
        if not slicers.is_running(inst.slicer):
            return False
        name = slicers.SLICER_NAMES[inst.slicer]
        if messagebox.askyesno(APP, f"{name} seems to be open.\n\nIt is safer to close it first: {name} only reads these "
                                    f"files when it starts, and it may overwrite them when it closes.\n\n"
                                    "Continue anyway?", icon="warning", default="no"):
            return True
        return None

    def bg(work, done=None, busy="Working...", always=None):
        """Run work() off the UI thread; done(result) or an error box afterwards; always() in both cases."""
        set_status(busy)

        def runner():
            try:
                result = work()
                root.after(0, lambda: (set_status(), always() if always else None, done(result) if done else None))
            except Exception as exc:
                if always:
                    root.after(0, always)
                tb = traceback.format_exc()
                msg = str(exc) or exc.__class__.__name__
                if isinstance(exc, PermissionError):
                    msg = (f"No permission to write {exc.filename or 'there'}. "
                           "Pick another folder, or check the folder is not read-only.")
                elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
                    msg = f"The disk is full ({exc.filename or ''}). Free some space and try again."
                expected = isinstance(exc, (pack.PackError, installer.InstallError, OSError, ValueError))
                root.after(0, lambda: (set_status("Stopped: " + msg[:80]),
                                       messagebox.showerror(APP, msg if expected else f"{msg}\n\n{tb[-900:]}")))
        threading.Thread(target=runner, daemon=True).start()

    def text_box(parent, height=8, **kw):
        kw.setdefault("font", "TkDefaultFont")
        kw.setdefault("padx", 6)
        kw.setdefault("pady", 4)
        fr = ttk.Frame(parent)
        fr.rowconfigure(0, weight=1)
        fr.columnconfigure(0, weight=1)
        t = tk.Text(fr, height=height, **kw)
        sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        return fr, t

    def set_text(t, txt):
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", txt)
        t.configure(state="disabled")

    class CheckTree:
        """A Treeview with tick boxes: group rows (kinds) and item rows."""

        def __init__(self, parent, columns, height=10):
            self.frame = ttk.Frame(parent)
            self.frame.rowconfigure(0, weight=1)
            self.frame.columnconfigure(0, weight=1)
            self.tree = ttk.Treeview(self.frame, columns=[c[0] for c in columns], height=height, selectmode="browse")
            self.tree.heading("#0", text="Item", anchor="w")
            self.tree.column("#0", width=330, stretch=True)
            for cid, title, width in columns:
                self.tree.heading(cid, text=title, anchor="w")
                self.tree.column(cid, width=width, stretch=True)
            sb = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            sb.grid(row=0, column=1, sticky="ns")
            self.checked = {}       # iid -> bool (item rows only)
            self.labels = {}
            self.tree.bind("<Button-1>", self._click)
            self.tree.bind("<space>", lambda e: self._toggle(self.tree.focus()))
            self.on_change = None

        def clear(self):
            self.tree.delete(*self.tree.get_children())
            self.checked.clear()
            self.labels.clear()

        def add_group(self, gid, label):
            self.labels[gid] = label
            self.tree.insert("", "end", iid=gid, text=f"{UNCHECKED} {label}", open=True)

        def add_item(self, gid, iid, label, values, checked=False, tags=()):
            self.labels[iid] = label
            self.checked[iid] = checked
            self.tree.insert(gid, "end", iid=iid, text=f"{CHECKED if checked else UNCHECKED} {label}", values=values, tags=tags)

        def refresh(self):
            for iid, on in self.checked.items():
                self.tree.item(iid, text=f"{CHECKED if on else UNCHECKED} {self.labels[iid]}")
            for gid in self.tree.get_children():
                kids = self.tree.get_children(gid)
                on = [self.checked.get(k, False) for k in kids]
                mark = CHECKED if kids and all(on) else (PARTIAL if any(on) else UNCHECKED)
                n = f"  ({sum(on)} of {len(kids)})" if kids else ""
                self.tree.item(gid, text=f"{mark} {self.labels[gid]}{n}")
            if self.on_change:
                self.on_change()

        def _toggle(self, iid):
            if not iid:
                return
            if iid in self.checked:
                self.checked[iid] = not self.checked[iid]
            else:
                kids = self.tree.get_children(iid)
                target = not all(self.checked.get(k, False) for k in kids)
                for k in kids:
                    self.checked[k] = target
            self.refresh()

        def _click(self, event):
            iid = self.tree.identify_row(event.y)
            if iid and self.tree.identify("element", event.x, event.y) != "Treeitem.indicator":
                self._toggle(iid)

        def set_all(self, on):
            for k in self.checked:
                self.checked[k] = on
            self.refresh()

        def selected(self):
            return [k for k, on in self.checked.items() if on]

    # ======================================================================
    # the status bar is packed first so it is never squeezed off the bottom of a small window
    ttk.Label(root, textvariable=status, relief="sunken", anchor="w", padding=(8, 2)).pack(side="bottom", fill="x")
    main = ttk.Frame(root, padding=(12, 10, 12, 6))
    main.pack(fill="both", expand=True)
    hdr = ttk.Frame(main)
    hdr.pack(fill="x")
    ttk.Label(hdr, text=APP, font=("TkDefaultFont", 16, "bold")).pack(side="left")
    ttk.Label(hdr, text="   Cura, PrusaSlicer and OrcaSlicer: convert, back up, install").pack(side="left")
    ttk.Button(hdr, text="About", command=lambda: messagebox.showinfo(
        f"About {APP}",
        f"{VERSION_LINE}\n\nCopyright Matthew Armstrong\nhttps://github.com/The-Dorkknight\n\n"
        "Source-available under the PolyForm Noncommercial License 1.0.0.\nNo warranty, no liability.\n\n"
        "Bundles Cura setting definitions and profiles (LGPLv3, Ultimaker). Not affiliated with UltiMaker, "
        "Prusa Research or the OrcaSlicer project.")).pack(side="right")
    nb = ttk.Notebook(main)
    nb.pack(fill="both", expand=True, pady=(10, 0))

    # ======================================================================
    # Tab 1: Slicers
    # ======================================================================
    t_home = ttk.Frame(nb, padding=10)
    nb.add(t_home, text="  Slicers  ")
    t_home.columnconfigure(0, weight=1)
    t_home.rowconfigure(1, weight=1)
    ttk.Label(t_home, text="Slicers found on this computer", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
    cols = (("ver", "Version", 70), ("prof", "Profiles", 70), ("mat", "Materials", 75), ("prn", "Printers", 70),
            ("plg", "Plug-ins", 70), ("run", "Open now?", 80), ("dir", "Settings folder", 330))
    home_tree = ttk.Treeview(t_home, columns=[c[0] for c in cols], height=5, selectmode="browse")
    home_tree.heading("#0", text="Slicer", anchor="w")
    home_tree.column("#0", width=170, stretch=False)
    for cid, title, width in cols:
        home_tree.heading(cid, text=title, anchor="w")
        home_tree.column(cid, width=width, stretch=(cid == "dir"))
    home_tree.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    t_home.rowconfigure(1, weight=0)
    t_home.rowconfigure(3, weight=1)
    hb = ttk.Frame(t_home)
    hb.grid(row=2, column=0, sticky="ew", pady=8)
    fr_h, home_detail = text_box(t_home, height=10, wrap="word")
    fr_h.grid(row=3, column=0, sticky="nsew")
    home_hint = tk.Message(t_home, width=900, fg="#444", text="")
    home_hint.grid(row=4, column=0, sticky="w", pady=(6, 0))

    def home_show(*_a):
        i = home_selected()
        if i is None:
            set_text(home_detail, "Select a slicer above to see what it holds.")
            return
        lines = [f"{i.label}" + ("   (open now)" if slicers.is_running(i.slicer) else "")]
        for rootname, path in i.roots.items():
            if rootname != "cache" and (rootname == "data" or path != i.roots.get("data")):
                lines.append(f"    {'settings' if rootname == 'config' else 'data'} folder: {path}")
        try:
            items = inv.inventory(i)
        except Exception as exc:
            items = []
            lines.append(f"Could not read this folder: {exc}")
        for kind in inv.KIND_ORDER:
            group = [it for it in items if it.kind == kind]
            if group:
                lines.append("")
                lines.append(f"{inv.KIND_LABEL[kind]} ({len(group)})")
                lines += [f"    {it.name}   -   {it.detail}" for it in group]
        set_text(home_detail, "\n".join(lines))

    def refresh_home():
        home_tree.delete(*home_tree.get_children())
        for n, i in enumerate(installs()):
            try:
                s = inv.summary(inv.inventory(i))
            except Exception:
                s = {}
            home_tree.insert("", "end", iid=str(n), text=i.label.rsplit(" ", 1)[0] if i.version else i.label,
                             values=(i.version or "?", s.get("profile", 0), s.get("material", 0), s.get("printer", 0),
                                     s.get("plugin", 0), "yes" if slicers.is_running(i.slicer) else "no", i.main_folder))
        if installs():
            home_tree.selection_set("0")
        home_show()
        if installs():
            home_hint.configure(text="Counts are things you made or installed yourself; the profiles that ship with a slicer are "
                                     "not counted. 'Open now?' matters because a slicer saves its settings when it closes: "
                                     "close it before restoring or installing.")
        else:
            home_hint.configure(text="No Cura, PrusaSlicer or OrcaSlicer settings were found in the usual places. If a slicer keeps "
                                     "its settings somewhere else (portable install, another disk), use 'Add a settings folder...'. "
                                     "The Convert tab works without any slicer installed.")
    state["listeners"].append(refresh_home)

    def add_folder():
        d = filedialog.askdirectory(title="Choose a slicer's settings folder")
        if not d:
            return
        i = slicers.from_folder(d)
        if i is None:
            messagebox.showwarning(APP, "That folder doesn't look like a Cura, PrusaSlicer or OrcaSlicer settings folder.\n\n"
                                        "Cura: the folder with cura.cfg (named after the version, e.g. 5.8).\n"
                                        "PrusaSlicer: the folder with PrusaSlicer.ini.\nOrcaSlicer: the folder with OrcaSlicer.conf.")
            return
        state["custom"].append(i)
        rescan()

    def home_selected():
        sel = home_tree.selection()
        return installs()[int(sel[0])] if sel and int(sel[0]) < len(installs()) else None
    home_tree.bind("<<TreeviewSelect>>", lambda e: home_show())

    def home_open():
        i = home_selected()
        if i:
            open_folder(i.main_folder)

    def home_backup():
        i = home_selected()
        if i:
            bk_inst.set(long_label(i))
            bk_load()
            nb.select(t_backup)
    ttk.Button(hb, text="Look again", command=lambda: rescan()).pack(side="left")
    ttk.Button(hb, text="Add a settings folder...", command=add_folder).pack(side="left", padx=8)
    ttk.Button(hb, text="Open folder", command=home_open).pack(side="left")
    ttk.Button(hb, text="Back up the selected slicer...", command=home_backup).pack(side="left", padx=8)
    home_tree.bind("<Double-1>", lambda e: home_backup())

    # ======================================================================
    # Tab 2: Convert
    # ======================================================================
    t_conv = ttk.Frame(nb, padding=10)
    nb.add(t_conv, text="  Convert  ")
    t_conv.columnconfigure(0, weight=1)
    files: list = []
    src_var = tk.StringVar(value="auto")
    tgt_var = tk.StringVar(value="orca")
    dest_var = tk.StringVar(value="folder")
    dest_inst = tk.StringVar()
    cura_printer = tk.StringVar()
    name_var, out_var = tk.StringVar(), tk.StringVar()
    machine_var = tk.StringVar()
    material_var = tk.StringVar(value="(from profile)")
    orca_dir_var = tk.StringVar()
    noz_var, bed_var = tk.StringVar(), tk.StringVar()
    inh = {k: tk.StringVar() for k in ("print", "filament", "printer")}

    machines = resources().machines()
    machine_labels = [f"{name}  [{mid}]" for mid, name in machines]
    label_to_id = {f"{name}  [{mid}]": mid for mid, name in machines}
    materials = ["(from profile)"] + sorted(resources().generic_materials)

    f1 = ttk.LabelFrame(t_conv, text="1. Profile files to convert", padding=8)
    f1.grid(row=0, column=0, sticky="ew")
    f1.columnconfigure(0, weight=1)
    lst = tk.Listbox(f1, height=3)
    lst.grid(row=0, column=0, rowspan=3, sticky="ew")
    det = ttk.Label(f1, text="Add a Cura .curaprofile/.inst.cfg/.3mf, a PrusaSlicer .ini/.3mf, or OrcaSlicer "
                             ".json files (process + filament + printer).", foreground="#555", wraplength=640)
    det.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def conv_source():
        src = src_var.get()
        if src == "auto" and files:
            try:
                return detect(files)
            except Exception:
                return "auto"
        return src

    def refresh_files():
        lst.delete(0, "end")
        for f in files:
            lst.insert("end", os.path.basename(f))
        if files:
            try:
                fmt = conv_source()
                det.configure(text=f"Detected: {LABEL[fmt]} ({len(files)} file{'s' if len(files) > 1 else ''})")
                if not out_var.get():
                    out_var.set(os.path.join(os.path.dirname(files[0]), "converted"))
            except Exception as exc:
                det.configure(text=f"Can't read: {exc}")
        update_options()

    def add_files():
        got = filedialog.askopenfilenames(title="Choose profile file(s)", filetypes=[
            ("Slicer profiles", "*.curaprofile *.cfg *.3mf *.ini *.json *.orca_printer *.orca_filament *.zip"),
            ("All files", "*")])
        for g in got:
            if g not in files:
                files.append(g)
        refresh_files()
    ttk.Button(f1, text="Add files...", command=add_files).grid(row=0, column=1, padx=(8, 0), sticky="ew")
    ttk.Button(f1, text="Clear", command=lambda: (files.clear(), refresh_files())).grid(row=1, column=1, padx=(8, 0), sticky="ew")
    srcbox = ttk.Combobox(f1, textvariable=src_var, state="readonly", width=12, values=["auto", "cura", "prusa", "orca"])
    srcbox.grid(row=2, column=1, padx=(8, 0), sticky="ew")
    srcbox.bind("<<ComboboxSelected>>", lambda e: refresh_files())

    f2 = ttk.LabelFrame(t_conv, text="2. Convert to", padding=8)
    f2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    f2.columnconfigure(3, weight=1)
    for i, (val, lab) in enumerate((("orca", "OrcaSlicer"), ("prusa", "PrusaSlicer"), ("cura", "Cura"))):
        ttk.Radiobutton(f2, text=lab, value=val, variable=tgt_var, command=lambda: update_options()).grid(
            row=0, column=i, padx=(0, 18), sticky="w")
    ttk.Radiobutton(f2, text="and save the new files in a folder", value="folder", variable=dest_var,
                    command=lambda: update_options()).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    rb_inst = ttk.Radiobutton(f2, text="and put them straight into:", value="install", variable=dest_var,
                              command=lambda: update_options())
    rb_inst.grid(row=2, column=0, columnspan=2, sticky="w")
    cb_dest = ttk.Combobox(f2, textvariable=dest_inst, state="readonly")
    cb_dest.grid(row=2, column=2, columnspan=2, sticky="ew")
    lab_cp = ttk.Label(f2, text="for Cura printer:")
    cb_cp = ttk.Combobox(f2, textvariable=cura_printer, state="readonly")
    lab_cp.grid(row=3, column=1, sticky="e", pady=(4, 0))
    cb_cp.grid(row=3, column=2, columnspan=2, sticky="ew", pady=(4, 0))
    cb_dest.bind("<<ComboboxSelected>>", lambda e: update_options())

    f3 = ttk.LabelFrame(t_conv, text="3. Options", padding=8)
    f3.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    f3.columnconfigure(1, weight=1)
    ttk.Label(f3, text="New preset name").grid(row=0, column=0, sticky="w")
    ttk.Entry(f3, textvariable=name_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
    lab_m = ttk.Label(f3, text="Cura printer type")
    cb_m = ttk.Combobox(f3, textvariable=machine_var, values=machine_labels)
    lab_m.grid(row=1, column=0, sticky="w")
    cb_m.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)

    def filter_machines(_e=None):
        t = machine_var.get().lower()
        cb_m.configure(values=[m for m in machine_labels if t in m.lower()] or machine_labels)
    cb_m.bind("<KeyRelease>", filter_machines)
    lab_mat = ttk.Label(f3, text="Cura material")
    cb_mat = ttk.Combobox(f3, textvariable=material_var, values=materials, state="readonly")
    lab_mat.grid(row=2, column=0, sticky="w")
    cb_mat.grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)
    lab_o = ttk.Label(f3, text="Orca profiles folder")
    ent_o = ttk.Entry(f3, textvariable=orca_dir_var)
    btn_o = ttk.Button(f3, text="Browse", command=lambda: orca_dir_var.set(filedialog.askdirectory() or orca_dir_var.get()))
    lab_o.grid(row=3, column=0, sticky="w")
    ent_o.grid(row=3, column=1, sticky="ew", pady=2)
    btn_o.grid(row=3, column=2, padx=(6, 0))
    tf = ttk.Frame(f3)
    tf.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Label(tf, text="Force nozzle °C").pack(side="left")
    ttk.Entry(tf, textvariable=noz_var, width=6).pack(side="left", padx=(4, 14))
    ttk.Label(tf, text="Force bed °C").pack(side="left")
    ttk.Entry(tf, textvariable=bed_var, width=6).pack(side="left", padx=(4, 14))
    ttk.Label(tf, text="(blank = use the profile)", foreground="#555").pack(side="left")
    inh_frame = ttk.Frame(f3)
    inh_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 0))
    ttk.Label(inh_frame, text="Inherit system presets (optional):").grid(row=0, column=0, columnspan=6, sticky="w")
    for i, k in enumerate(("print", "filament", "printer")):
        ttk.Label(inh_frame, text=k).grid(row=1, column=i * 2, sticky="w", padx=(0, 4))
        ttk.Entry(inh_frame, textvariable=inh[k], width=22).grid(row=1, column=i * 2 + 1, padx=(0, 10))
    lab_out = ttk.Label(f3, text="Output folder")
    ent_out = ttk.Entry(f3, textvariable=out_var)
    btn_out = ttk.Button(f3, text="Browse", command=lambda: out_var.set(filedialog.askdirectory() or out_var.get()))
    lab_out.grid(row=6, column=0, sticky="w", pady=(6, 0))
    ent_out.grid(row=6, column=1, sticky="ew", pady=(6, 0))
    btn_out.grid(row=6, column=2, padx=(6, 0), pady=(6, 0))

    def conv_dest_install():
        return by_label(dest_inst.get(), tgt_var.get()) if dest_var.get() == "install" else None

    def update_options():
        src, tgt = conv_source(), tgt_var.get()
        labels = [long_label(i) for i in installs(tgt)]
        cb_dest.configure(values=labels)
        if dest_inst.get() not in labels:
            dest_inst.set(labels[0] if labels else "")
        if not labels:
            if dest_var.get() == "install":
                dest_var.set("folder")
            rb_inst.configure(state="disabled", text=f"and put them straight into: (no {LABEL[tgt]} found on this computer)")
        else:
            rb_inst.configure(state="normal", text="and put them straight into:")
        to_install = dest_var.get() == "install"
        cb_dest.grid() if labels else cb_dest.grid_remove()
        di = conv_dest_install()
        show_cp = bool(to_install and di is not None and di.slicer == "cura")
        if show_cp:
            names = [m["name"] for m in inv.cura_machines(di)]
            cb_cp.configure(values=names)
            if cura_printer.get() not in names:
                cura_printer.set(names[0] if names else "")
        for w in (lab_cp, cb_cp):
            w.grid() if show_cp else w.grid_remove()
        show_m = src == "cura" or (tgt == "cura" and not to_install)
        for w in (lab_m, cb_m):
            w.grid() if show_m else w.grid_remove()
        for w in (lab_mat, cb_mat):
            w.grid() if src == "cura" else w.grid_remove()
        for w in (lab_o, ent_o, btn_o):
            w.grid() if src == "orca" else w.grid_remove()
        inh_frame.grid() if tgt in ("orca", "prusa") else inh_frame.grid_remove()
        for w in (lab_out, ent_out, btn_out):
            w.grid_remove() if to_install else w.grid()
        lab_m.configure(text="Cura printer type (source)" if src == "cura" and tgt != "cura" else "Cura printer type")
        go.configure(text="Convert and install" if to_install else "Convert")
    state["listeners"].append(lambda: update_options())

    f4 = ttk.Frame(t_conv)
    f4.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    go = ttk.Button(f4, text="Convert")
    go.pack(side="left")
    openb = ttk.Button(f4, text="Open output folder", state="disabled")
    openb.pack(side="left", padx=8)
    cnb = ttk.Notebook(t_conv)
    cnb.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
    t_conv.rowconfigure(4, weight=1)
    fr_s, summ = text_box(cnb, height=6, wrap="word")
    fr_f, full = text_box(cnb, height=6, wrap="none", font=("TkFixedFont", 9))
    cnb.add(fr_s, text="Summary")
    cnb.add(fr_f, text="Full report")
    set_text(summ, "Add profile files, pick a target and press Convert.\n\n"
                   "You get new presets plus a report of what was converted, approximated or left out. "
                   "Your original files are never changed.")
    last_out = {"dir": ""}

    def show_report(rep):
        lines = [f"{rep.source} -> {rep.target}: {len(rep.converted)} settings converted, "
                 f"{len(rep.approximations)} approximated, {len(rep.not_converted)} source settings left out.\n"]
        if rep.approximations:
            lines += ["Approximated - check these:"] + [f"  ~ {a}" for a in rep.approximations] + [""]
        if rep.notes:
            lines += ["Read this:"] + [f"  - {n}" for n in rep.notes] + [""]
        if rep.gcode_notes:
            lines += ["Start/end G-code:"] + [f"  - {g}" for g in rep.gcode_notes] + [""]
        lines.append("Files written:")
        lines += [f"  {f}" for f in rep.files]
        set_text(summ, "\n".join(lines))
        set_text(full, rep.to_text())

    openb.configure(command=lambda: open_folder(last_out["dir"]) if last_out["dir"] else None)

    def do_convert():
        if not files:
            messagebox.showwarning(APP, "Add at least one profile file first.")
            return
        mid = label_to_id.get(machine_var.get(), machine_var.get().strip() or None)
        if mid and mid not in dict(machines):
            messagebox.showwarning(APP, f"Unknown Cura printer type '{machine_var.get()}'. Pick one from the list.")
            return
        overrides = {}
        for key, var in (("nozzle_temp", noz_var), ("nozzle_temp_first_layer", noz_var), ("bed_temp", bed_var),
                         ("bed_temp_first_layer", bed_var)):
            v = var.get().strip()
            if v:
                try:
                    overrides[key] = float(v)
                except ValueError:
                    messagebox.showwarning(APP, f"'{v}' is not a number.")
                    return
        mat = material_var.get()
        di = conv_dest_install()
        if dest_var.get() == "install" and di is None:
            messagebox.showwarning(APP, "Choose which slicer to put the presets into.")
            return
        opts = Options(target=tgt_var.get(), source=None if src_var.get() == "auto" else src_var.get(),
                       name=name_var.get().strip() or None, outdir=out_var.get() or os.getcwd(),
                       cura_machine=mid, cura_material=None if mat.startswith("(") else mat,
                       cura_resources=(candidate_resource_dirs() or [None])[0],
                       orca_profiles=[orca_dir_var.get()] if orca_dir_var.get().strip() else [],
                       inherits={k: v.get().strip() for k, v in inh.items() if v.get().strip()}, overrides=overrides)
        running = open_ok(di) if di is not None else False
        if running is None:
            return
        go.configure(state="disabled")

        def work():
            if di is not None:
                rep, _res = installer.send_converted(list(files), opts, di, cura_printer=cura_printer.get() or None,
                                                     allow_running=running)
                return rep, di.main_folder, f"Installed into {di.label}: start it and look under your own presets"
            rep = convert(list(files), opts)
            return rep, opts.outdir, f"Done: {len(rep.files)} files in {opts.outdir}"

        def done(result):
            rep, folder, msg = result
            last_out["dir"] = folder
            show_report(rep)
            openb.configure(state="normal", text="Open slicer folder" if di is not None else "Open output folder")
            set_status(msg)
            if di is not None:
                rescan()
        bg(work, done, "Converting...", always=lambda: go.configure(state="normal"))
    go.configure(command=do_convert)

    # ======================================================================
    # Tab 3: Back up
    # ======================================================================
    t_backup = ttk.Frame(nb, padding=10)
    nb.add(t_backup, text="  Back up  ")
    t_backup.columnconfigure(0, weight=1)
    t_backup.rowconfigure(1, weight=1)
    bk_inst = tk.StringVar()
    bk_redact = tk.BooleanVar(value=True)
    bk_items = {}
    top = ttk.Frame(t_backup)
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)
    ttk.Label(top, text="Back up from").grid(row=0, column=0, sticky="w")
    bk_cb = ttk.Combobox(top, textvariable=bk_inst, state="readonly")
    bk_cb.grid(row=0, column=1, sticky="ew", padx=8)
    bk_tree = CheckTree(t_backup, (("detail", "Details", 420),), height=12)
    bk_tree.frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    bk_count = ttk.Label(t_backup, text="", foreground="#444")
    bk_count.grid(row=2, column=0, sticky="w", pady=(6, 0))
    bb = ttk.Frame(t_backup)
    bb.grid(row=3, column=0, sticky="ew", pady=(6, 0))
    ttk.Checkbutton(t_backup, variable=bk_redact,
                    text="Leave out passwords, API keys and account logins (recommended, and needed if you share the file)"
                    ).grid(row=4, column=0, sticky="w", pady=(6, 0))
    fr_b, bk_log = text_box(t_backup, height=5, wrap="word")
    fr_b.grid(row=5, column=0, sticky="ew", pady=(8, 0))
    set_text(bk_log, "Tick what you want to keep and press 'Save backup...'. A backup is one .slicerpack file. "
                     "Nothing in the slicer is changed by making a backup.")

    def bk_update_count():
        ids = bk_tree.selected()
        n_files = len({f for i in ids for f in bk_items[i].files})
        bk_count.configure(text=f"{len(ids)} item(s) ticked, {n_files} file(s)")
    bk_tree.on_change = bk_update_count

    def bk_load(*_a):
        bk_tree.clear()
        bk_items.clear()
        i = by_label(bk_inst.get())
        if i is None:
            bk_update_count()
            return
        items = inv.inventory(i)
        for kind in inv.KIND_ORDER:
            group = [it for it in items if it.kind == kind]
            if not group:
                continue
            bk_tree.add_group("g:" + kind, inv.KIND_LABEL[kind])
            for it in group:
                bk_items[it.id] = it
                bk_tree.add_item("g:" + kind, it.id, it.name, (it.detail,), checked=(kind not in ("other",)))
        bk_tree.refresh()
    bk_cb.bind("<<ComboboxSelected>>", bk_load)

    def bk_refresh_installs():
        labels = [long_label(i) for i in installs()]
        bk_cb.configure(values=labels)
        if bk_inst.get() not in labels:
            bk_inst.set(labels[0] if labels else "")
        bk_load()
    state["listeners"].append(bk_refresh_installs)

    def bk_save():
        i = by_label(bk_inst.get())
        ids = bk_tree.selected()
        if i is None or not ids:
            messagebox.showwarning(APP, "Choose a slicer and tick at least one item.")
            return
        full_bk = len(ids) == len(bk_items)
        path = filedialog.asksaveasfilename(title="Save backup as", defaultextension=pack.EXT,
                                            initialfile=pack.default_name(i, full_bk),
                                            filetypes=[("SlicerSwap backup", "*" + pack.EXT)])
        if not path:
            return
        chosen = [bk_items[x] for x in ids]

        def done(m):
            size = os.path.getsize(path)
            n = sum(len(it["files"]) for it in m["items"])
            lines = [f"Saved and checked: {path}", f"{pack.describe(m)}.",
                     f"{n} file entries, {size / 1024:.0f} KB. Every file was read back and matches."]
            if m.get("redacted_values"):
                lines.append(f"{m['redacted_values']} password/key value(s) were left out.")
            if slicers.is_running(i.slicer):
                lines.append(f"Note: {i.label} is open. Changes it has not saved yet are not in the backup.")
            lines += [f"Warning: {w}" for w in m.get("warnings", [])]
            set_text(bk_log, "\n".join(lines))
            set_status("Backup saved")
        bg(lambda: pack.create(i, chosen, path, redact_secrets=bk_redact.get(), full=full_bk), done, "Saving backup...")
    ttk.Button(bb, text="Tick everything", command=lambda: bk_tree.set_all(True)).pack(side="left")
    ttk.Button(bb, text="Untick everything", command=lambda: bk_tree.set_all(False)).pack(side="left", padx=8)
    ttk.Button(bb, text="Save backup...", command=bk_save).pack(side="right")

    # ======================================================================
    # Tab 4: Restore
    # ======================================================================
    t_rest = ttk.Frame(nb, padding=10)
    nb.add(t_rest, text="  Restore  ")
    t_rest.columnconfigure(0, weight=1)
    t_rest.rowconfigure(3, weight=1)
    rs_file, rs_inst = tk.StringVar(), tk.StringVar()
    rs_newer = tk.BooleanVar(value=False)
    rs_state = {"manifest": None}
    r1 = ttk.Frame(t_rest)
    r1.grid(row=0, column=0, sticky="ew")
    r1.columnconfigure(1, weight=1)
    ttk.Label(r1, text="Backup file").grid(row=0, column=0, sticky="w")
    ttk.Entry(r1, textvariable=rs_file, state="readonly").grid(row=0, column=1, sticky="ew", padx=8)
    ttk.Label(r1, text="Restore into").grid(row=1, column=0, sticky="w", pady=(6, 0))
    rs_cb = ttk.Combobox(r1, textvariable=rs_inst, state="readonly")
    rs_cb.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))
    rs_info = ttk.Label(t_rest, text="Choose a .slicerpack backup made on the Back up tab.", foreground="#444", wraplength=820)
    rs_info.grid(row=1, column=0, sticky="w", pady=(8, 0))
    rs_tree = CheckTree(t_rest, (("status", "Compared with this slicer now", 220), ("detail", "Details", 260)), height=10)
    rs_tree.frame.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
    rs_tree.tree.tag_configure("same", foreground="#777")
    rs_tree.tree.tag_configure("unsafe", foreground="#b42318")
    rb2 = ttk.Frame(t_rest)
    rb2.grid(row=4, column=0, sticky="ew", pady=(6, 0))
    rs_newer_cb = ttk.Checkbutton(rb2, text="Allow a backup from a newer Cura version", variable=rs_newer)
    fr_r, rs_log = text_box(t_rest, height=6, wrap="word")
    fr_r.grid(row=5, column=0, sticky="ew", pady=(8, 0))
    set_text(rs_log, "Restoring puts the ticked items back into the slicer's settings folder. Files that would be replaced "
                     "are first copied to a safety copy, so 'Undo last restore' can put them back.")

    def rs_compare(*_a):
        rs_tree.clear()
        m = rs_state["manifest"]
        if not m:
            return
        target = by_label(rs_inst.get(), m["slicer"])
        status_by_item = {}
        if target is not None:
            try:
                _m, actions = pack.plan(rs_file.get(), target)
                for a in actions:
                    status_by_item.setdefault(a.item, []).append(a.status)
            except pack.PackError as exc:
                rs_info.configure(text=str(exc))
        for kind in inv.KIND_ORDER:
            group = [it for it in m["items"] if it["kind"] == kind]
            if not group:
                continue
            rs_tree.add_group("g:" + kind, inv.KIND_LABEL[kind])
            for it in group:
                iid = pack.item_id(it)
                sts = status_by_item.get(iid, [])
                if not sts:
                    text, tag = "", ()
                elif "unsafe" in sts:
                    text, tag = "would stop Cura starting: left out", ("unsafe",)
                elif all(s == "same" for s in sts):
                    text, tag = "already there, identical", ("same",)
                elif all(s == "new" for s in sts):
                    text, tag = "not there yet: will be added", ()
                else:
                    n = sum(1 for s in sts if s == "differs")
                    text, tag = f"different: replaces {n} file(s)", ()
                rs_tree.add_item("g:" + kind, iid, it["name"], (text, it.get("detail", "")),
                                 checked=(tag not in (("same",), ("unsafe",)) and kind not in ("other", "settings")), tags=tag)
        rs_tree.refresh()
        if any("unsafe" in sts for sts in status_by_item.values()):
            try:
                set_text(rs_log, "\n\n".join("Left out of any restore: " + why
                                             for why in pack.faulty_plugins(rs_file.get()).values()))
            except pack.PackError:
                pass

    def rs_refresh_installs():
        m = rs_state["manifest"]
        labels = [long_label(i) for i in installs(m["slicer"] if m else None)]
        rs_cb.configure(values=labels)
        if rs_inst.get() not in labels:
            rs_inst.set(labels[0] if labels else "")
        rs_compare()
    state["listeners"].append(rs_refresh_installs)
    rs_cb.bind("<<ComboboxSelected>>", rs_compare)

    def rs_open(path=None):
        path = path or filedialog.askopenfilename(title="Choose a backup", filetypes=[
            ("SlicerSwap backup", "*" + pack.EXT), ("All files", "*")])
        if not path:
            return
        try:
            m = pack.read_manifest(path)
            problems = pack.verify(path)
        except pack.PackError as exc:
            messagebox.showerror(APP, str(exc))
            return
        rs_state["manifest"] = m
        rs_file.set(path)
        text = pack.describe(m) + "."
        if m.get("note"):
            text += " " + m["note"]
        if problems:
            text += f"  WARNING: {len(problems)} file(s) in this backup are damaged ({problems[0]})."
        if not installs(m["slicer"]):
            text += f"  No {slicers.SLICER_NAMES[m['slicer']]} settings folder was found on this computer: start it once, or add its folder on the Slicers tab."
        rs_info.configure(text=text)
        if m["slicer"] == "cura":
            rs_newer_cb.pack(side="left", padx=(12, 0))
        else:
            rs_newer_cb.pack_forget()
        rs_refresh_installs()
        set_status("Backup opened and checked" if not problems else "Backup opened: it has damaged files")

    def rs_do():
        m = rs_state["manifest"]
        target = by_label(rs_inst.get(), m["slicer"]) if m else None
        ids = rs_tree.selected()
        if not m or target is None or not ids:
            messagebox.showwarning(APP, "Choose a backup, the slicer to restore into, and tick at least one item.")
            return
        _m, actions = pack.plan(rs_file.get(), target, ids)
        n_new = sum(1 for a in actions if a.status == "new")
        n_rep = sum(1 for a in actions if a.status == "differs")
        n_out = len({a.item for a in actions if a.status == "unsafe"})
        if not n_new and not n_rep:
            messagebox.showinfo(APP, "Nothing to do: the ticked plug-in would stop Cura from starting, so it is left out."
                                if n_out else "Everything ticked is already there and identical. Nothing to do.")
            return
        left = f"\n{n_out} plug-in(s) that would stop Cura from starting will be left out.\n" if n_out else ""
        if not messagebox.askokcancel(APP, f"Restore into {target.label}?\n\n{n_new} file(s) will be added and {n_rep} replaced.\n"
                                           f"Replaced files are first saved to a safety copy.\n{left}\nFolder: {target.main_folder}"):
            return
        running = open_ok(target)
        if running is None:
            return
        lines = []

        def done(res):
            out = [f"Restored into {target.label}: {res.created} file(s) added, {res.replaced} replaced, "
                   f"{res.unchanged} already identical.",
                   "Checked: every written file was read back and matches the backup." if res.verified else "NOT verified."]
            if res.snapshot:
                out.append(f"Safety copy of the previous files: {res.snapshot}")
            out += [f"Note: {n}" for n in res.notes]
            out.append(f"Now start {slicers.SLICER_NAMES[target.slicer]} and check the result.")
            set_text(rs_log, "\n".join(out + [""] + lines[-200:]))
            set_status("Restore finished")
            rescan()
        bg(lambda: pack.restore(rs_file.get(), target, ids, allow_newer=rs_newer.get(), progress=lines.append,
                                allow_running=running), done, "Restoring...")

    def rs_undo():
        m = rs_state["manifest"]
        target = by_label(rs_inst.get(), m["slicer"] if m else None) or (by_label(rs_inst.get()))
        snaps = pack.list_snapshots(target.slicer if target else None)
        if target is None or not snaps:
            messagebox.showinfo(APP, "No safety copy found. One is made each time a restore replaces or adds files.\n\n"
                                     f"They are kept in: {pack.snapshot_dir()}")
            return
        snap = snaps[0]
        info = pack.read_manifest(snap)
        if not messagebox.askokcancel(APP, f"Undo the last restore into {target.label}?\n\n{info.get('note', '')}\n"
                                           f"({info.get('created', '').replace('T', ' ')})\n\n"
                                           "Replaced files are put back; files the restore added are removed if they are unchanged."):
            return
        running = open_ok(target)
        if running is None:
            return

        def done(res):
            out = [f"Undone: {res.replaced} file(s) put back, {res.created} added file(s) removed."] + [f"Note: {n}" for n in res.notes]
            set_text(rs_log, "\n".join(out))
            set_status("Undo finished")
            rescan()
        bg(lambda: pack.undo(snap, target, allow_running=running), done, "Undoing...")
    ttk.Button(r1, text="Choose backup...", command=lambda: rs_open()).grid(row=0, column=2)
    ttk.Button(rb2, text="Tick everything", command=lambda: rs_tree.set_all(True)).pack(side="left")
    ttk.Button(rb2, text="Untick everything", command=lambda: rs_tree.set_all(False)).pack(side="left", padx=8)
    ttk.Button(rb2, text="Restore ticked items", command=rs_do).pack(side="right")
    ttk.Button(rb2, text="Undo last restore...", command=rs_undo).pack(side="right", padx=8)

    # ======================================================================
    # Tab 5: Plug-ins
    # ======================================================================
    t_plug = ttk.Frame(nb, padding=10)
    nb.add(t_plug, text="  Plug-ins  ")
    t_plug.columnconfigure(0, weight=1)
    t_plug.rowconfigure(1, weight=1)
    pl_inst = tk.StringVar()
    p1 = ttk.Frame(t_plug)
    p1.grid(row=0, column=0, sticky="ew")
    p1.columnconfigure(1, weight=1)
    ttk.Label(p1, text="Cura").grid(row=0, column=0, sticky="w")
    pl_cb = ttk.Combobox(p1, textvariable=pl_inst, state="readonly")
    pl_cb.grid(row=0, column=1, sticky="ew", padx=8)
    pcols = (("ver", "Version", 70), ("how", "Installed as", 175), ("status", "What Cura says", 405))
    pl_tree = ttk.Treeview(t_plug, columns=[c[0] for c in pcols], height=9, selectmode="browse")
    pl_tree.heading("#0", text="Plug-in / script", anchor="w")
    pl_tree.column("#0", width=230, stretch=False)
    for cid, title, width in pcols:
        pl_tree.heading(cid, text=title, anchor="w")
        pl_tree.column(cid, width=width, stretch=(cid == "status"))
    pl_tree.tag_configure("loaded", foreground="#1a7f37")
    pl_tree.tag_configure("failed", foreground="#b42318")
    pl_tree.tag_configure("waiting", foreground="#9a6700")
    pl_tree.tag_configure("unsure", foreground="#9a6700")
    pl_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    pb = ttk.Frame(t_plug)
    pb.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    pb2 = ttk.Frame(t_plug)
    pb2.grid(row=3, column=0, sticky="ew", pady=(6, 0))
    fr_p, pl_log = text_box(t_plug, height=6, wrap="word")
    fr_p.grid(row=4, column=0, sticky="ew", pady=(8, 0))
    PL_HELP = ("Cura is the only one of the three with installable plug-ins. SlicerSwap first checks the plug-in for a "
               "fault that stops Cura from starting, then hands it to Cura's own package manager, so Cura installs it on "
               "its next start and lists it under Marketplace > Manage packages.\n\n"
               "Press Start Cura: this list then updates by itself. Green means Cura loaded the plug-in AND finished "
               "starting; the answer comes from Cura's own files, not from a guess.\n\n"
               "PrusaSlicer and OrcaSlicer have no plug-in system. Orca's optional vendor network plug-in is covered by "
               "the Back up tab.")
    set_text(pl_log, PL_HELP)
    pl_rows = {}

    def pl_target():
        return by_label(pl_inst.get(), "cura")

    def pl_refresh(*_a):
        pl_tree.delete(*pl_tree.get_children())
        pl_rows.clear()
        i = pl_target()
        if i is None:
            return
        warn = inv.packages_problem(i)
        if warn:
            set_text(pl_log, "WARNING: " + warn + "\n\n" + PL_HELP)
        for n, (p, st, why) in enumerate(installer.cura_plugin_report(i)):
            how = "Cura package" if p["package"] else ("package folder" if p["packaged"] else "copied folder")
            iid = f"p{n}"
            pl_rows[iid] = ("plugin", p)
            pl_tree.insert("", "end", iid=iid, text=p["name"], values=(p["version"], how, why), tags=(st,))
        seen = set()
        for rootname in ("config", "data"):
            sdir = os.path.join(i.roots[rootname], "scripts")
            if os.path.isdir(sdir):
                for fn in sorted(os.listdir(sdir)):
                    if fn.endswith(".py") and fn not in seen:
                        seen.add(fn)
                        iid = f"s{len(seen)}"
                        pl_rows[iid] = ("script", os.path.join(sdir, fn))
                        pl_tree.insert("", "end", iid=iid, text=fn, values=("", "post-processing script",
                                       "In Cura: Extensions > Post Processing > Modify G-Code"))

    def pl_refresh_installs():
        labels = [long_label(i) for i in installs("cura")]
        pl_cb.configure(values=labels)
        if pl_inst.get() not in labels:
            pl_inst.set(labels[0] if labels else "")
        pl_refresh()
        if not labels:
            set_text(pl_log, "No Cura settings folder was found on this computer. Start Cura once, or add its folder on the "
                             "Slicers tab.\n\n" + PL_HELP)
    state["listeners"].append(pl_refresh_installs)
    pl_cb.bind("<<ComboboxSelected>>", pl_refresh)

    def pl_show_row(_e=None):
        sel = pl_tree.selection()
        if sel:
            vals = pl_tree.item(sel[0])
            set_text(pl_log, f"{vals['text']}  {vals['values'][0]}\nInstalled as: {vals['values'][1]}\n{vals['values'][2]}")
    pl_tree.bind("<<TreeviewSelect>>", pl_show_row)

    def pl_install(source):
        i = pl_target()
        if i is None or not source:
            if i is None:
                messagebox.showwarning(APP, "No Cura found to install into.")
            return
        try:
            info = installer.read_plugin_source(source)
        except (installer.InstallError, ValueError, OSError) as exc:
            messagebox.showerror(APP, str(exc))
            return
        meta = info.get("meta") or {}
        faults = info.get("faults") or []
        shown = meta.get("name") or info["plugin_id"]
        if plugcheck.stops_cura(faults):
            set_text(pl_log, "Not installed. " + plugcheck.explain(shown, faults))
            messagebox.showerror(APP, "Not installed.\n\n" + plugcheck.headline(shown, faults) +
                                 "\n\nThe details are in the box at the bottom of the window.")
            return
        if not messagebox.askokcancel(APP, f"Install this plug-in into {i.label}?\n\n"
                                           f"{meta.get('name') or info['plugin_id']}  {meta.get('version') or ''}\n"
                                           f"by {meta.get('author') or 'unknown'}\n\n"
                                           "A plug-in is a program that runs inside Cura with your user rights. "
                                           "Only install plug-ins from people you trust."):
            return
        running = open_ok(i)
        if running is None:
            return

        def done(res):
            set_text(pl_log, "\n".join(res.notes + ["", "Files written (read back and checked):"] + [f"  {f}" for f in res.files]))
            pl_refresh()
        bg(lambda: installer.install_cura_plugin(i, source, allow_running=running), done, "Installing plug-in...")

    def pl_pick_file():
        pl_install(filedialog.askopenfilename(title="Choose a Cura plug-in", filetypes=[
            ("Cura plug-in", "*.curapackage *.zip"), ("All files", "*")]))

    def pl_pick_script():
        i = pl_target()
        p = filedialog.askopenfilename(title="Choose a post-processing script", filetypes=[("Python script", "*.py")])
        if i is None or not p:
            return

        def done(res):
            set_text(pl_log, "\n".join(res.notes + [f"  {f}" for f in res.files]))
            pl_refresh()
        bg(lambda: installer.install_cura_script(i, p), done, "Installing script...")

    def pl_summary(extra=None):
        """Refresh the list and say in words what Cura's files show. Returns the set of states seen."""
        pl_refresh()
        rows = [pl_tree.item(r) for r in pl_tree.get_children() if r in pl_rows and pl_rows[r][0] == "plugin"]
        by = {}
        for r in rows:
            by.setdefault(r["tags"][0] if r["tags"] else "", []).append(r)
        i = pl_target()
        lines = list(extra or [])
        lines.append(f"Checked against Cura's own files ({inv.cura_log_path(i)})." if i else "")
        warn = inv.packages_problem(i) if i else None
        if warn:
            lines.insert(0, "WARNING: " + warn)
        for r in by.get("failed", []) + by.get("unsure", []):
            lines.append(f"{r['text']}: {r['values'][2]}")
        if by.get("loaded"):
            lines.append(f"{len(by['loaded'])} plug-in(s) confirmed: loaded by Cura, and Cura finished starting: "
                         + ", ".join(r["text"] for r in by["loaded"]) + ".")
            lines.append(installer.WHERE_HINT)
        if by.get("waiting"):
            lines.append("Waiting for a Cura start: " + ", ".join(r["text"] for r in by["waiting"]) + ".")
        if not rows:
            lines.append("No plug-ins of your own are installed in this Cura.")
        set_text(pl_log, "\n\n".join(x for x in lines if x))
        return set(by)

    def pl_check():
        watch["until"] = 0
        pl_summary()
        set_status("Plug-ins checked against Cura's own files")

    def pl_remove():
        i = pl_target()
        sel = pl_tree.selection()
        if i is None or not sel:
            messagebox.showinfo(APP, "Select a plug-in in the list first.")
            return
        kind, obj = pl_rows[sel[0]]
        if kind == "script":
            messagebox.showinfo(APP, f"Scripts are plain files. To remove one, delete it from:\n{os.path.dirname(obj)}")
            return
        key = obj["folder"] or obj["plugin_id"]
        if not messagebox.askokcancel(APP, f"Remove '{obj['name']}' from {i.label}?"):
            return
        running = open_ok(i)
        if running is None:
            return

        def done(res):
            set_text(pl_log, "\n".join(res.notes))
            pl_refresh()
        bg(lambda: installer.remove_cura_plugin(i, key, allow_running=running), done, "Removing...")

    watch = {"until": 0.0}

    def pl_watch():
        """After 'Start Cura': keep looking until Cura has loaded (or refused) what was waiting."""
        if time.time() > watch["until"]:
            return
        states = pl_summary(["Cura is starting. This list updates by itself for two minutes..."])
        i = pl_target()
        booted = crashed = False
        if i is not None:
            sess = plugcheck.read_session(inv.cura_log_path(i))
            fresh = bool(sess and sess.start and sess.start >= watch["since"])      # Cura's log shows this start
            booted = fresh and bool(sess.booted)
            crashed = fresh and not sess.booted and not slicers.is_running("cura") and time.time() - watch["began"] > 8
        if i is None or ((booted or crashed) and "waiting" not in states):
            watch["until"] = 0
            pl_summary(["Cura finished starting." if booted else "Cura stopped before it finished starting."])
            set_status("Plug-ins checked against Cura's own files")
            return
        root.after(2000, pl_watch)

    def pl_start():
        i = pl_target()
        if slicers.is_running("cura"):
            set_text(pl_log, "Cura is already open. Close it and start it again so it picks up the changes, "
                             "then press Check.")
            return
        progs = slicers.find_cura_programs(i.version if i else "")
        if not progs:
            path = filedialog.askopenfilename(title="Choose the Cura program (AppImage, .exe or .app)")
            if not path:
                set_text(pl_log, "SlicerSwap could not find the Cura program on this computer. Start Cura the way you "
                                 "normally do, wait until its window is up, then press Check.")
                return
            progs = [(os.path.basename(path), ["open", "-a", path] if path.endswith(".app") else [path])]
        label, cmd = progs[0]
        try:
            slicers.launch(cmd)
        except OSError as exc:
            set_text(pl_log, f"Could not start Cura: {exc}")
            return
        set_text(pl_log, f"Starting {label}. Waiting for Cura to load its plug-ins (this can take a minute)...")
        now = datetime.datetime.now()
        watch.update(until=time.time() + 150, began=time.time(),
                     since=(now - datetime.timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S"))
        root.after(3000, pl_watch)
    ttk.Button(pb, text="Install plug-in file...", command=pl_pick_file).pack(side="left")
    ttk.Button(pb, text="Install plug-in folder...", command=lambda: pl_install(filedialog.askdirectory(
        title="Choose the plug-in's folder (the one with plugin.json)"))).pack(side="left", padx=8)
    ttk.Button(pb, text="Install script (.py)...", command=pl_pick_script).pack(side="left")
    ttk.Button(pb2, text="Start Cura", command=pl_start).pack(side="left")
    ttk.Button(pb2, text="Check", command=pl_check).pack(side="left", padx=8)
    ttk.Button(pb2, text="Remove selected", command=pl_remove).pack(side="left")
    ttk.Button(pb2, text="Open Cura's plug-in folder", command=lambda: (
        open_folder(os.path.join(pl_target().roots["data"], "plugins")) if pl_target() and os.path.isdir(
            os.path.join(pl_target().roots["data"], "plugins")) else None)).pack(side="right")

    # ======================================================================
    # start-up
    # ======================================================================
    for a in pf.get("files") or []:
        if os.path.isfile(a) and not a.endswith(pack.EXT):
            files.append(os.path.abspath(a))
    if pf.get("target"):
        tgt_var.set(pf["target"])
    if pf.get("name"):
        name_var.set(pf["name"])
    if pf.get("out"):
        out_var.set(os.path.abspath(pf["out"]))
    if pf.get("orca_profiles"):
        orca_dir_var.set(pf["orca_profiles"])
    if pf.get("cura_machine"):
        mid = pf["cura_machine"]
        machine_var.set(next((lab for lab, m in label_to_id.items() if m == mid), mid))
    for d in pf.get("folders") or []:
        i = slicers.from_folder(d)
        if i is not None:
            state["custom"].append(i)
    rescan()
    if files:
        refresh_files()
    packs = [a for a in (pf.get("files") or []) if a.endswith(pack.EXT) and os.path.isfile(a)]
    if packs:
        rs_open(os.path.abspath(packs[0]))
    tab = {"slicers": t_home, "convert": t_conv, "backup": t_backup, "restore": t_rest, "plugins": t_plug}.get(
        pf.get("tab") or ("restore" if packs else ("convert" if files else "slicers")))
    nb.select(tab)
    if pf.get("install_into") and installs(tgt_var.get()):
        dest_var.set("install")
        update_options()
    root.update_idletasks()
    if not disclaimer():
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
