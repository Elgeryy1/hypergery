from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backend import HyperGeryBackend, HyperGeryError, VmSummary


class HyperGeryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("HyperGery v0.1")
        self.geometry("1220x780")
        self.minsize(980, 620)
        self.backend = HyperGeryBackend()
        self.vms: list[VmSummary] = []
        self.selected_vm: VmSummary | None = None
        self._build_style()
        self._build_ui()
        self.refresh_all()

    def _build_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("Toolbar.TFrame", background="#20242a")
        self.style.configure("Toolbar.TButton", padding=(10, 7), font=("Sans", 10))
        self.style.configure("Title.TLabel", font=("Sans", 13, "bold"))
        self.style.configure("Muted.TLabel", foreground="#59616d")
        self.style.configure("StatusOK.TLabel", foreground="#16723a")
        self.style.configure("StatusWarning.TLabel", foreground="#9a6500")
        self.style.configure("StatusError.TLabel", foreground="#b42318")

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, style="Toolbar.TFrame")
        toolbar.pack(side=tk.TOP, fill=tk.X)
        actions = [
            ("New", self.new_vm),
            ("Settings", self.settings_vm),
            ("Start", self.start_vm),
            ("Stop / ACPI Shutdown", self.shutdown_vm),
            ("Force Off", self.force_off_vm),
            ("Snapshots", self.snapshots_vm),
            ("Clone", self.clone_vm),
            ("Delete", self.delete_vm),
            ("Refresh", self.refresh_all),
            ("Open Console", self.open_console),
        ]
        for label, command in actions:
            ttk.Button(toolbar, text=label, command=command, style="Toolbar.TButton").pack(side=tk.LEFT, padx=2, pady=5)

        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=8)
        outer.add(left, weight=1)
        ttk.Label(left, text="Virtual Machines", style="Title.TLabel").pack(anchor=tk.W)
        self.vm_tree = ttk.Treeview(left, columns=("name", "state", "lab"), show="headings", height=24)
        self.vm_tree.heading("name", text="Name")
        self.vm_tree.heading("state", text="State")
        self.vm_tree.heading("lab", text="Lab")
        self.vm_tree.column("name", width=150, anchor=tk.W)
        self.vm_tree.column("state", width=95, anchor=tk.W)
        self.vm_tree.column("lab", width=110, anchor=tk.W)
        self.vm_tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.vm_tree.bind("<<TreeviewSelect>>", self.on_vm_select)

        right_split = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        outer.add(right_split, weight=4)

        main_area = ttk.Frame(right_split, padding=8)
        right_split.add(main_area, weight=4)

        self.preflight_frame = ttk.LabelFrame(main_area, text="System preflight", padding=8)
        self.preflight_frame.pack(fill=tk.X, pady=(0, 8))
        self.preflight_tree = ttk.Treeview(self.preflight_frame, columns=("status", "detail", "fix"), show="headings", height=6)
        self.preflight_tree.heading("status", text="Status")
        self.preflight_tree.heading("detail", text="Detail")
        self.preflight_tree.heading("fix", text="Suggested command")
        self.preflight_tree.column("status", width=80)
        self.preflight_tree.column("detail", width=460)
        self.preflight_tree.column("fix", width=420)
        self.preflight_tree.pack(fill=tk.X)

        self.notebook = ttk.Notebook(main_area)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tabs: dict[str, tk.Text] = {}
        for name in ("General", "System", "Display", "Storage", "Network", "Snapshots", "Logs"):
            frame = ttk.Frame(self.notebook, padding=10)
            text = tk.Text(frame, wrap=tk.WORD, height=10, borderwidth=0, highlightthickness=0)
            text.pack(fill=tk.BOTH, expand=True)
            text.configure(state=tk.DISABLED)
            self.notebook.add(frame, text=name)
            self.tabs[name] = text

        log_frame = ttk.LabelFrame(right_split, text="Activity log", padding=8)
        right_split.add(log_frame, weight=1)
        self.activity_log = tk.Text(log_frame, wrap=tk.NONE, height=9)
        self.activity_log.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

    def run_background(self, label: str, fn, on_success=None) -> None:
        self.status_var.set(label)

        def worker() -> None:
            try:
                result = fn()
            except Exception as exc:
                self.after(0, lambda exc=exc: self.show_error(exc))
            else:
                if on_success:
                    self.after(0, lambda: on_success(result))
                self.after(0, self.refresh_all)
            finally:
                self.after(0, lambda: self.status_var.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def show_error(self, exc: Exception) -> None:
        if exc.__traceback__:
            logging.error("UI operation failed: %s", exc, exc_info=(type(exc), exc, exc.__traceback__))
        else:
            logging.error("UI operation failed: %s", exc)
        messagebox.showerror("HyperGery", str(exc))
        self.refresh_logs()

    def refresh_all(self) -> None:
        self.refresh_preflight()
        self.refresh_vms()
        self.refresh_logs()
        self.render_selected()

    def refresh_preflight(self) -> None:
        self.preflight_tree.delete(*self.preflight_tree.get_children())
        for item in self.backend.preflight():
            tag = item.status.lower()
            self.preflight_tree.insert("", tk.END, values=(item.status, f"{item.name}: {item.detail}", item.fix), tags=(tag,))
        self.preflight_tree.tag_configure("ok", foreground="#16723a")
        self.preflight_tree.tag_configure("warning", foreground="#9a6500")
        self.preflight_tree.tag_configure("error", foreground="#b42318")

    def refresh_vms(self) -> None:
        current = self.selected_vm.name if self.selected_vm else ""
        try:
            self.vms = self.backend.list_vms()
        except HyperGeryError as exc:
            logging.error("cannot refresh VM list: %s", exc)
            self.status_var.set(str(exc))
            self.vms = []
        self.vm_tree.delete(*self.vm_tree.get_children())
        selected_iid = ""
        for vm in self.vms:
            iid = vm.name
            self.vm_tree.insert("", tk.END, iid=iid, values=(vm.name, vm.state, vm.lab_id or ""))
            if vm.name == current:
                selected_iid = iid
        if selected_iid:
            self.vm_tree.selection_set(selected_iid)
        elif self.vms:
            self.vm_tree.selection_set(self.vms[0].name)
        else:
            self.selected_vm = None

    def refresh_logs(self) -> None:
        self.activity_log.configure(state=tk.NORMAL)
        self.activity_log.delete("1.0", tk.END)
        self.activity_log.insert(tk.END, self.backend.recent_logs())
        self.activity_log.configure(state=tk.DISABLED)

    def on_vm_select(self, _event=None) -> None:
        selection = self.vm_tree.selection()
        if not selection:
            self.selected_vm = None
        else:
            name = selection[0]
            self.selected_vm = next((vm for vm in self.vms if vm.name == name), None)
        self.render_selected()

    def selected_name(self) -> str:
        if not self.selected_vm:
            raise HyperGeryError("Select a VM first.")
        return self.selected_vm.name

    def set_tab_text(self, tab: str, content: str) -> None:
        text = self.tabs[tab]
        text.configure(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        text.insert(tk.END, content)
        text.configure(state=tk.DISABLED)

    def render_selected(self) -> None:
        vm = self.selected_vm
        if not vm:
            for tab in self.tabs:
                self.set_tab_text(tab, "No VM selected.")
            return
        self.set_tab_text(
            "General",
            f"Name: {vm.name}\nState: {vm.state}\nLab: {vm.lab_id or 'unknown'}\nLibvirt URI: qemu:///system\n",
        )
        self.set_tab_text("System", f"RAM: {vm.ram_mib or 'unknown'} MiB\nvCPUs: {vm.vcpus or 'unknown'}\n")
        self.set_tab_text("Display", f"Graphics: {vm.graphics or 'unknown'}\nConsole: virt-viewer or remote-viewer\n")
        self.set_tab_text(
            "Storage",
            f"Disk path: {vm.disk_path or 'unknown'}\nVirtual size: {vm.disk_virtual or 'unknown'}\nActual size: {vm.disk_actual or 'unknown'}\nBoot ISO: {vm.iso_path or 'none'}\n",
        )
        self.set_tab_text("Network", f"Network: {vm.network or 'unknown'}\n")
        try:
            snaps = self.backend.list_snapshots(vm.name)
            body = "\n".join(snaps) if snaps else "No snapshots."
        except Exception as exc:
            body = f"Snapshot status unavailable:\n{exc}"
        self.set_tab_text("Snapshots", body)
        self.set_tab_text("Logs", self.backend.recent_logs(80))

    def new_vm(self) -> None:
        NewVmDialog(self, self.backend)

    def settings_vm(self) -> None:
        vm = self.selected_vm
        if not vm:
            self.show_error(HyperGeryError("Select a VM first."))
            return
        SettingsDialog(self, self.backend, vm)

    def start_vm(self) -> None:
        try:
            name = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        self.run_background(f"Starting {name}", lambda: self.backend.start_vm(name))

    def shutdown_vm(self) -> None:
        try:
            name = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        self.run_background(f"Requesting ACPI shutdown for {name}", lambda: self.backend.shutdown_vm(name))

    def force_off_vm(self) -> None:
        try:
            name = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        if messagebox.askyesno("Force Off", f"Force power off {name}?"):
            self.run_background(f"Forcing off {name}", lambda: self.backend.force_off_vm(name))

    def snapshots_vm(self) -> None:
        vm = self.selected_vm
        if not vm:
            self.show_error(HyperGeryError("Select a VM first."))
            return
        SnapshotDialog(self, self.backend, vm.name)

    def clone_vm(self) -> None:
        try:
            source = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        clone = simpledialog.askstring("Clone VM", "New VM name:", parent=self)
        if not clone:
            return
        self.run_background(f"Cloning {source}", lambda: self.backend.clone_vm(source, clone))

    def delete_vm(self) -> None:
        try:
            name = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        delete_disks = messagebox.askyesno("Delete VM", f"Delete {name} and remove its HyperGery disk if safe?")
        if messagebox.askyesno("Confirm Delete", f"This will undefine {name} from libvirt. Continue?"):
            self.run_background(f"Deleting {name}", lambda: self.backend.delete_vm(name, delete_disks=delete_disks))

    def open_console(self) -> None:
        try:
            name = self.selected_name()
            self.backend.open_console(name)
            self.refresh_logs()
        except Exception as exc:
            self.show_error(exc)


class FieldRow(ttk.Frame):
    def __init__(self, parent, label: str, variable: tk.Variable, *, browse=None, options: list[str] | None = None) -> None:
        super().__init__(parent)
        ttk.Label(self, text=label, width=18).pack(side=tk.LEFT)
        if options:
            ttk.OptionMenu(self, variable, variable.get(), *options).pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            ttk.Entry(self, textvariable=variable).pack(side=tk.LEFT, fill=tk.X, expand=True)
        if browse:
            ttk.Button(self, text="Browse", command=browse).pack(side=tk.LEFT, padx=(6, 0))
        self.pack(fill=tk.X, pady=4)


class NewVmDialog(tk.Toplevel):
    def __init__(self, app: HyperGeryApp, backend: HyperGeryBackend) -> None:
        super().__init__(app)
        self.app = app
        self.backend = backend
        self.title("New HyperGery VM")
        self.transient(app)
        self.grab_set()
        self.geometry("620x430")
        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        self.name = tk.StringVar()
        self.iso = tk.StringVar()
        self.os_type = tk.StringVar(value="Linux")
        self.ram = tk.IntVar(value=4096)
        self.vcpus = tk.IntVar(value=2)
        self.disk = tk.IntVar(value=40)
        self.disk_dir = tk.StringVar()
        self.network = tk.StringVar(value="nat")
        self.display = tk.StringVar(value="spice")
        self.lab_id = tk.StringVar(value="default-lab")
        FieldRow(body, "Name", self.name)
        FieldRow(body, "ISO", self.iso, browse=self.pick_iso)
        FieldRow(body, "OS type", self.os_type, options=["Linux", "Windows", "Other"])
        FieldRow(body, "RAM MiB", self.ram)
        FieldRow(body, "vCPUs", self.vcpus)
        FieldRow(body, "Disk GiB", self.disk)
        FieldRow(body, "Disk directory", self.disk_dir, browse=self.pick_dir)
        FieldRow(body, "Network", self.network, options=["nat", "isolated"])
        FieldRow(body, "Display", self.display, options=["spice", "vnc"])
        FieldRow(body, "Lab ID", self.lab_id)
        ttk.Label(body, text="Empty disk directory uses ~/.local/share/hypergery/vms/<vm-name>/", style="Muted.TLabel").pack(anchor=tk.W, pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(18, 0))
        ttk.Button(buttons, text="Create", command=self.create).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    def pick_iso(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Select ISO", filetypes=[("ISO images", "*.iso"), ("All files", "*")])
        if path:
            self.iso.set(path)

    def pick_dir(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Select disk directory")
        if path:
            self.disk_dir.set(path)

    def create(self) -> None:
        try:
            kwargs = {
                "name": self.name.get(),
                "iso_path": self.iso.get(),
                "os_type": self.os_type.get(),
                "ram_mib": int(self.ram.get()),
                "vcpus": int(self.vcpus.get()),
                "disk_gb": int(self.disk.get()),
                "disk_dir": self.disk_dir.get() or None,
                "network_mode": self.network.get(),
                "display_mode": self.display.get(),
                "lab_id": self.lab_id.get() or "default-lab",
            }
        except (ValueError, tk.TclError) as exc:
            self.app.show_error(HyperGeryError(f"RAM, vCPUs and disk size must be numbers: {exc}"))
            return
        self.destroy()
        self.app.run_background("Creating VM", lambda: self.backend.create_vm(**kwargs))


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: HyperGeryApp, backend: HyperGeryBackend, vm: VmSummary) -> None:
        super().__init__(app)
        self.app = app
        self.backend = backend
        self.vm = vm
        self.title(f"Settings: {vm.name}")
        self.transient(app)
        self.grab_set()
        self.geometry("620x330")
        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        self.ram = tk.IntVar(value=vm.ram_mib or 4096)
        self.vcpus = tk.IntVar(value=vm.vcpus or 2)
        self.iso = tk.StringVar(value=vm.iso_path)
        self.network = tk.StringVar(value="isolated" if vm.network.endswith("-isolated") else "nat")
        self.display = tk.StringVar(value=vm.graphics if vm.graphics in {"spice", "vnc"} else "spice")
        self.lab_id = tk.StringVar(value=vm.lab_id or "default-lab")
        FieldRow(body, "RAM MiB", self.ram)
        FieldRow(body, "vCPUs", self.vcpus)
        FieldRow(body, "Boot ISO", self.iso, browse=self.pick_iso)
        FieldRow(body, "Network", self.network, options=["nat", "isolated"])
        FieldRow(body, "Display", self.display, options=["spice", "vnc"])
        FieldRow(body, "Lab ID", self.lab_id)
        ttk.Label(body, text="Settings are applied through libvirt and require the VM to be shut off.", style="Muted.TLabel").pack(anchor=tk.W, pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(18, 0))
        ttk.Button(buttons, text="Save", command=self.save).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    def pick_iso(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Select ISO", filetypes=[("ISO images", "*.iso"), ("All files", "*")])
        if path:
            self.iso.set(path)

    def save(self) -> None:
        try:
            kwargs = {
                "name": self.vm.name,
                "ram_mib": int(self.ram.get()),
                "vcpus": int(self.vcpus.get()),
                "boot_iso": self.iso.get(),
                "network_mode": self.network.get(),
                "display_mode": self.display.get(),
                "lab_id": self.lab_id.get() or "default-lab",
            }
        except (ValueError, tk.TclError) as exc:
            self.app.show_error(HyperGeryError(f"RAM and vCPU values must be numbers: {exc}"))
            return
        self.destroy()
        self.app.run_background("Saving settings", lambda: self.backend.update_settings(**kwargs))


class SnapshotDialog(tk.Toplevel):
    def __init__(self, app: HyperGeryApp, backend: HyperGeryBackend, vm_name: str) -> None:
        super().__init__(app)
        self.app = app
        self.backend = backend
        self.vm_name = vm_name
        self.title(f"Snapshots: {vm_name}")
        self.transient(app)
        self.grab_set()
        self.geometry("480x380")
        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(body)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Create", command=self.create).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Revert", command=self.revert).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Delete", command=self.delete).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        self.refresh()

    def selected_snapshot(self) -> str:
        selected = self.listbox.curselection()
        if not selected:
            raise HyperGeryError("Select a snapshot first.")
        return self.listbox.get(selected[0])

    def refresh(self) -> None:
        self.listbox.delete(0, tk.END)
        try:
            for snap in self.backend.list_snapshots(self.vm_name):
                self.listbox.insert(tk.END, snap)
        except Exception as exc:
            self.app.show_error(exc)

    def create(self) -> None:
        name = simpledialog.askstring("Create snapshot", "Snapshot name:", parent=self)
        if not name:
            return
        desc = simpledialog.askstring("Create snapshot", "Description:", parent=self) or ""
        self.app.run_background("Creating snapshot", lambda: self.backend.create_snapshot(self.vm_name, name, desc))
        self.after(1200, self.refresh)

    def revert(self) -> None:
        try:
            snap = self.selected_snapshot()
        except Exception as exc:
            self.app.show_error(exc)
            return
        if messagebox.askyesno("Revert snapshot", f"Revert {self.vm_name} to {snap}?", parent=self):
            self.app.run_background("Reverting snapshot", lambda: self.backend.revert_snapshot(self.vm_name, snap))
            self.after(1200, self.refresh)

    def delete(self) -> None:
        try:
            snap = self.selected_snapshot()
        except Exception as exc:
            self.app.show_error(exc)
            return
        if messagebox.askyesno("Delete snapshot", f"Delete snapshot {snap}?", parent=self):
            self.app.run_background("Deleting snapshot", lambda: self.backend.delete_snapshot(self.vm_name, snap))
            self.after(1200, self.refresh)


def main() -> None:
    try:
        app = HyperGeryApp()
    except HyperGeryError as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("HyperGery", str(exc))
            root.destroy()
        except tk.TclError:
            print(f"HyperGery: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    app.mainloop()
