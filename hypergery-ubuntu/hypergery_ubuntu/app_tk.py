from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .backend import HyperGeryBackend, HyperGeryError, VmSummary


APP_DISPLAY_VERSION = "0.2.0-dev"
TEXT_FONT = ("Monospace", 10)


def format_mib(value: int | None) -> str:
    return f"{value} MiB" if value else "unknown"


def vm_state_tag(state: str) -> str:
    lowered = state.lower()
    if "running" in lowered:
        return "running"
    if "shut" in lowered or "off" in lowered:
        return "shutoff"
    if "paused" in lowered:
        return "paused"
    return "unknown"


class HyperGeryApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"HyperGery v{APP_DISPLAY_VERSION}")
        self.geometry("1320x840")
        self.minsize(1080, 680)
        self.backend = HyperGeryBackend()
        self.vms: list[VmSummary] = []
        self.selected_vm: VmSummary | None = None
        self.vm_count_var = tk.StringVar(value="No VMs")
        self.preflight_summary_var = tk.StringVar(value="Preflight not run yet")
        self.selection_summary_var = tk.StringVar(value="No VM selected")
        self._build_style()
        self._build_ui()
        self.refresh_all()

    def _build_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(".", font=("Sans", 10))
        self.style.configure("Toolbar.TFrame", background="#20242a")
        self.style.configure("Toolbar.TButton", padding=(10, 7), font=("Sans", 10))
        self.style.configure("Danger.TButton", padding=(10, 7), font=("Sans", 10, "bold"), foreground="#b42318")
        self.style.configure("ToolbarTitle.TLabel", background="#20242a", foreground="#f7f9fb", font=("Sans", 15, "bold"))
        self.style.configure("ToolbarMuted.TLabel", background="#20242a", foreground="#c9d1d9")
        self.style.configure("Title.TLabel", font=("Sans", 13, "bold"))
        self.style.configure("Section.TLabel", font=("Sans", 11, "bold"))
        self.style.configure("Muted.TLabel", foreground="#59616d")
        self.style.configure("StatusOK.TLabel", foreground="#16723a")
        self.style.configure("StatusWarning.TLabel", foreground="#9a6500")
        self.style.configure("StatusError.TLabel", foreground="#b42318")
        self.style.configure("Treeview", rowheight=25)
        self.style.configure("Treeview.Heading", font=("Sans", 10, "bold"))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, style="Toolbar.TFrame")
        toolbar.pack(side=tk.TOP, fill=tk.X)
        brand = ttk.Frame(toolbar, style="Toolbar.TFrame")
        brand.pack(side=tk.LEFT, padx=(12, 18), pady=7)
        ttk.Label(brand, text="HyperGery", style="ToolbarTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(brand, text=f"v{APP_DISPLAY_VERSION}  KVM / QEMU / libvirt", style="ToolbarMuted.TLabel").pack(anchor=tk.W)

        primary_actions = [
            ("New VM", self.new_vm),
            ("Settings", self.settings_vm),
            ("Start", self.start_vm),
            ("ACPI Shutdown", self.shutdown_vm),
            ("Console", self.open_console),
            ("Snapshots", self.snapshots_vm),
            ("Clone", self.clone_vm),
            ("Refresh", self.refresh_all),
        ]
        for label, command in primary_actions:
            ttk.Button(toolbar, text=label, command=command, style="Toolbar.TButton").pack(side=tk.LEFT, padx=2, pady=9)
        ttk.Button(toolbar, text="Force Off", command=self.force_off_vm, style="Danger.TButton").pack(side=tk.LEFT, padx=(12, 2), pady=9)
        ttk.Button(toolbar, text="Delete", command=self.delete_vm, style="Danger.TButton").pack(side=tk.LEFT, padx=2, pady=9)

        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=8)
        outer.add(left, weight=1)
        list_header = ttk.Frame(left)
        list_header.pack(fill=tk.X)
        ttk.Label(list_header, text="Virtual Machines", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(list_header, textvariable=self.vm_count_var, style="Muted.TLabel").pack(side=tk.RIGHT)
        self.vm_tree = ttk.Treeview(left, columns=("name", "state", "lab", "vcpus", "ram"), show="headings", height=20)
        for column, title, width, anchor in (
            ("name", "Name", 170, tk.W),
            ("state", "State", 95, tk.W),
            ("lab", "Lab", 120, tk.W),
            ("vcpus", "CPU", 48, tk.CENTER),
            ("ram", "RAM", 85, tk.E),
        ):
            self.vm_tree.heading(column, text=title)
            self.vm_tree.column(column, width=width, anchor=anchor, stretch=column in {"name", "lab"})
        self.vm_tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.vm_tree.bind("<<TreeviewSelect>>", self.on_vm_select)
        self.vm_tree.tag_configure("running", foreground="#16723a")
        self.vm_tree.tag_configure("shutoff", foreground="#59616d")
        self.vm_tree.tag_configure("paused", foreground="#9a6500")
        self.vm_tree.tag_configure("unknown", foreground="#343a40")

        labs_frame = ttk.LabelFrame(left, text="Labs", padding=8)
        labs_frame.pack(fill=tk.X, pady=(10, 0))
        self.lab_tree = ttk.Treeview(labs_frame, columns=("lab", "vms", "network"), show="headings", height=5)
        self.lab_tree.heading("lab", text="Lab")
        self.lab_tree.heading("vms", text="VMs")
        self.lab_tree.heading("network", text="Network")
        self.lab_tree.column("lab", width=130, anchor=tk.W)
        self.lab_tree.column("vms", width=42, anchor=tk.CENTER, stretch=False)
        self.lab_tree.column("network", width=160, anchor=tk.W)
        self.lab_tree.pack(fill=tk.X)

        right_split = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        outer.add(right_split, weight=4)

        main_area = ttk.Frame(right_split, padding=8)
        right_split.add(main_area, weight=4)

        summary_bar = ttk.Frame(main_area)
        summary_bar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(summary_bar, textvariable=self.selection_summary_var, style="Title.TLabel").pack(side=tk.LEFT)

        self.preflight_frame = ttk.LabelFrame(main_area, text="System preflight", padding=8)
        self.preflight_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(self.preflight_frame, textvariable=self.preflight_summary_var, style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 6))
        self.preflight_tree = ttk.Treeview(self.preflight_frame, columns=("status", "detail", "fix"), show="headings", height=6)
        self.preflight_tree.heading("status", text="Status")
        self.preflight_tree.heading("detail", text="Detail")
        self.preflight_tree.heading("fix", text="Suggested command")
        self.preflight_tree.column("status", width=90, stretch=False)
        self.preflight_tree.column("detail", width=520)
        self.preflight_tree.column("fix", width=450)
        self.preflight_tree.pack(fill=tk.X)

        self.notebook = ttk.Notebook(main_area)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tabs: dict[str, tk.Text] = {}
        for name in ("General", "System", "Display", "Storage", "Network", "Snapshots", "Logs"):
            frame = ttk.Frame(self.notebook, padding=10)
            text = tk.Text(frame, wrap=tk.WORD, height=10, borderwidth=0, highlightthickness=0, font=TEXT_FONT)
            text.pack(fill=tk.BOTH, expand=True)
            text.configure(state=tk.DISABLED)
            self.notebook.add(frame, text=name)
            self.tabs[name] = text

        log_frame = ttk.LabelFrame(right_split, text="Activity log", padding=8)
        right_split.add(log_frame, weight=1)
        log_actions = ttk.Frame(log_frame)
        log_actions.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(log_actions, text="Refresh Logs", command=self.refresh_logs).pack(side=tk.RIGHT)
        self.activity_log = tk.Text(log_frame, wrap=tk.NONE, height=9, font=TEXT_FONT)
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
        self.refresh_labs()
        self.refresh_logs()
        self.render_selected()

    def refresh_preflight(self) -> None:
        self.preflight_tree.delete(*self.preflight_tree.get_children())
        counts = {"OK": 0, "Warning": 0, "Error": 0}
        for item in self.backend.preflight():
            tag = item.status.lower()
            counts[item.status] = counts.get(item.status, 0) + 1
            self.preflight_tree.insert("", tk.END, values=(item.status, f"{item.name}: {item.detail}", item.fix), tags=(tag,))
        if counts["Error"]:
            self.preflight_summary_var.set(f"{counts['Error']} error(s), {counts['Warning']} warning(s). VM operations may fail.")
        elif counts["Warning"]:
            self.preflight_summary_var.set(f"Ready with {counts['Warning']} warning(s). Review before creating production VMs.")
        else:
            self.preflight_summary_var.set("All required host checks passed.")
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
            self.vm_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(vm.name, vm.state, vm.lab_id or "unknown", vm.vcpus or "-", format_mib(vm.ram_mib)),
                tags=(vm_state_tag(vm.state),),
            )
            if vm.name == current:
                selected_iid = iid
        if selected_iid:
            self.vm_tree.selection_set(selected_iid)
        elif self.vms:
            self.vm_tree.selection_set(self.vms[0].name)
        else:
            self.selected_vm = None
        running = sum(1 for vm in self.vms if vm_state_tag(vm.state) == "running")
        label = f"{len(self.vms)} VM"
        if len(self.vms) != 1:
            label += "s"
        self.vm_count_var.set(f"{label}, {running} running")

    def refresh_labs(self) -> None:
        self.lab_tree.delete(*self.lab_tree.get_children())
        try:
            labs = self.backend.load_labs()
        except Exception as exc:
            logging.error("cannot refresh labs: %s", exc)
            self.lab_tree.insert("", tk.END, values=("unavailable", "-", str(exc)))
            return
        for manifest in labs:
            lab_id = manifest.get("lab_id", "unknown")
            vms = manifest.get("vms", [])
            network = manifest.get("network_id", "")
            self.lab_tree.insert("", tk.END, values=(lab_id, len(vms), network))

    def refresh_logs(self) -> None:
        self.activity_log.configure(state=tk.NORMAL)
        self.activity_log.delete("1.0", tk.END)
        self.activity_log.insert(tk.END, self.backend.recent_logs())
        self.activity_log.see(tk.END)
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

    def details_block(self, *rows: tuple[str, str]) -> str:
        width = max((len(label) for label, _value in rows), default=0)
        return "\n".join(f"{label:<{width}}  {value}" for label, value in rows) + "\n"

    def render_selected(self) -> None:
        vm = self.selected_vm
        if not vm:
            self.selection_summary_var.set("No VM selected")
            for tab in self.tabs:
                self.set_tab_text(tab, "No VM selected.")
            return
        self.selection_summary_var.set(f"{vm.name}  -  {vm.state}  -  {vm.lab_id or 'unknown lab'}")
        self.set_tab_text(
            "General",
            self.details_block(
                ("Name", vm.name),
                ("State", vm.state),
                ("Lab", vm.lab_id or "unknown"),
                ("Libvirt URI", "qemu:///system"),
            ),
        )
        self.set_tab_text(
            "System",
            self.details_block(
                ("RAM", format_mib(vm.ram_mib)),
                ("vCPUs", str(vm.vcpus or "unknown")),
            ),
        )
        self.set_tab_text(
            "Display",
            self.details_block(
                ("Graphics", vm.graphics or "unknown"),
                ("Console", "virt-viewer or remote-viewer"),
            ),
        )
        self.set_tab_text(
            "Storage",
            self.details_block(
                ("Disk path", vm.disk_path or "unknown"),
                ("Virtual size", vm.disk_virtual or "unknown"),
                ("Actual size", vm.disk_actual or "unknown"),
                ("Boot ISO", vm.iso_path or "none"),
            ),
        )
        self.set_tab_text("Network", self.details_block(("Network", vm.network or "unknown"), ("Lab", vm.lab_id or "unknown")))
        try:
            snaps = self.backend.list_snapshots(vm.name)
            body = "\n".join(f"- {snap}" for snap in snaps) if snaps else "No snapshots."
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
        if messagebox.askyesno(
            "Force Off",
            f"Force power off {name}?\n\nThis is equivalent to pulling power and can corrupt guest data.",
        ):
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
        if not messagebox.askyesno("Clone VM", f"Create a new VM clone from {source} named {clone}?", parent=self):
            return
        self.run_background(f"Cloning {source}", lambda: self.backend.clone_vm(source, clone))

    def delete_vm(self) -> None:
        try:
            name = self.selected_name()
        except Exception as exc:
            self.show_error(exc)
            return
        delete_disks = messagebox.askyesnocancel(
            "Delete VM",
            f"Delete {name} from libvirt?\n\nYes: delete the VM and its HyperGery-managed disk when safe.\nNo: delete the VM but keep the disk.\nCancel: do nothing.",
        )
        if delete_disks is None:
            return
        confirm_text = f"This will undefine {name} from libvirt."
        if delete_disks:
            confirm_text += "\n\nThe managed disk will also be removed if HyperGery owns it."
        if messagebox.askyesno("Confirm Delete", confirm_text + "\n\nContinue?", parent=self):
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
        self.geometry("760x560")
        self.minsize(680, 500)
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

        ttk.Label(body, text="Create Virtual Machine", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        identity = ttk.Frame(self.notebook, padding=12)
        resources = ttk.Frame(self.notebook, padding=12)
        integration = ttk.Frame(self.notebook, padding=12)
        review = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(identity, text="Identity")
        self.notebook.add(resources, text="Resources")
        self.notebook.add(integration, text="Storage & Network")
        self.notebook.add(review, text="Review")

        FieldRow(identity, "Name", self.name)
        FieldRow(identity, "Boot ISO", self.iso, browse=self.pick_iso)
        FieldRow(identity, "OS type", self.os_type, options=["Linux", "Windows", "Other"])

        FieldRow(resources, "RAM MiB", self.ram)
        FieldRow(resources, "vCPUs", self.vcpus)
        FieldRow(resources, "Disk GiB", self.disk)

        FieldRow(integration, "Disk directory", self.disk_dir, browse=self.pick_dir)
        FieldRow(integration, "Network", self.network, options=["nat", "isolated"])
        FieldRow(integration, "Display", self.display, options=["spice", "vnc"])
        FieldRow(integration, "Lab ID", self.lab_id)
        ttk.Label(
            integration,
            text="Empty disk directory uses ~/.local/share/hypergery/vms/<vm-name>/",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(8, 0))

        self.summary = tk.Text(review, wrap=tk.WORD, height=14, borderwidth=0, highlightthickness=0, font=TEXT_FONT)
        self.summary.pack(fill=tk.BOTH, expand=True)
        self.summary.configure(state=tk.DISABLED)
        for variable in (self.name, self.iso, self.os_type, self.ram, self.vcpus, self.disk, self.disk_dir, self.network, self.display, self.lab_id):
            variable.trace_add("write", lambda *_args: self.update_summary())
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self.update_summary())
        self.update_summary()

        buttons = ttk.Frame(body)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(18, 0))
        ttk.Button(buttons, text="Create", command=self.create).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Review", command=self.show_review).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    def pick_iso(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Select ISO", filetypes=[("ISO images", "*.iso"), ("All files", "*")])
        if path:
            self.iso.set(path)

    def pick_dir(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Select disk directory")
        if path:
            self.disk_dir.set(path)

    def show_review(self) -> None:
        self.update_summary()
        self.notebook.select(self.notebook.tabs()[3])

    def update_summary(self) -> None:
        try:
            ram = int(self.ram.get())
            vcpus = int(self.vcpus.get())
            disk = int(self.disk.get())
        except (ValueError, tk.TclError) as exc:
            content = f"Resource values are not valid yet:\n{exc}\n"
        else:
            content = self.app.details_block(
                ("Name", self.name.get() or "missing"),
                ("Boot ISO", self.iso.get() or "missing"),
                ("OS type", self.os_type.get()),
                ("RAM", f"{ram} MiB"),
                ("vCPUs", str(vcpus)),
                ("Disk", f"{disk} GiB qcow2"),
                ("Disk directory", self.disk_dir.get() or "~/.local/share/hypergery/vms/<vm-name>/"),
                ("Network", self.network.get()),
                ("Display", self.display.get()),
                ("Lab", self.lab_id.get() or "default-lab"),
            )
        self.summary.configure(state=tk.NORMAL)
        self.summary.delete("1.0", tk.END)
        self.summary.insert(tk.END, content)
        self.summary.configure(state=tk.DISABLED)

    def validate(self) -> dict:
        try:
            kwargs = {
                "name": self.name.get().strip(),
                "iso_path": self.iso.get().strip(),
                "os_type": self.os_type.get(),
                "ram_mib": int(self.ram.get()),
                "vcpus": int(self.vcpus.get()),
                "disk_gb": int(self.disk.get()),
                "disk_dir": self.disk_dir.get().strip() or None,
                "network_mode": self.network.get(),
                "display_mode": self.display.get(),
                "lab_id": self.lab_id.get().strip() or "default-lab",
            }
        except (ValueError, tk.TclError) as exc:
            raise HyperGeryError(f"RAM, vCPUs and disk size must be numbers: {exc}") from exc
        if not kwargs["name"]:
            raise HyperGeryError("VM name is required.")
        if not kwargs["iso_path"]:
            raise HyperGeryError("Boot ISO is required.")
        if kwargs["ram_mib"] < 512:
            raise HyperGeryError("RAM must be at least 512 MiB.")
        if kwargs["vcpus"] < 1:
            raise HyperGeryError("vCPUs must be at least 1.")
        if kwargs["disk_gb"] < 1:
            raise HyperGeryError("Disk size must be at least 1 GiB.")
        return kwargs

    def create(self) -> None:
        try:
            kwargs = self.validate()
        except HyperGeryError as exc:
            self.app.show_error(exc)
            return
        self.update_summary()
        if not messagebox.askyesno(
            "Create VM",
            (
                f"Create {kwargs['name']}?\n\n"
                f"ISO: {kwargs['iso_path']}\n"
                f"RAM: {kwargs['ram_mib']} MiB\n"
                f"vCPUs: {kwargs['vcpus']}\n"
                f"Disk: {kwargs['disk_gb']} GiB\n"
                f"Network: {kwargs['network_mode']}\n"
                f"Lab: {kwargs['lab_id']}"
            ),
            parent=self,
        ):
            return
        self.destroy()
        self.app.run_background(f"Creating {kwargs['name']}", lambda: self.backend.create_vm(**kwargs))


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
        if not messagebox.askyesno(
            "Save Settings",
            (
                f"Apply settings to {self.vm.name}?\n\n"
                f"RAM: {kwargs['ram_mib']} MiB\n"
                f"vCPUs: {kwargs['vcpus']}\n"
                f"Network: {kwargs['network_mode']}\n"
                f"Display: {kwargs['display_mode']}\n"
                f"Lab: {kwargs['lab_id']}"
            ),
            parent=self,
        ):
            return
        self.destroy()
        self.app.run_background(f"Saving settings for {self.vm.name}", lambda: self.backend.update_settings(**kwargs))


class SnapshotDialog(tk.Toplevel):
    def __init__(self, app: HyperGeryApp, backend: HyperGeryBackend, vm_name: str) -> None:
        super().__init__(app)
        self.app = app
        self.backend = backend
        self.vm_name = vm_name
        self.title(f"Snapshots: {vm_name}")
        self.transient(app)
        self.grab_set()
        self.geometry("620x420")
        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(body)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text=vm_name, style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)
        self.listbox = tk.Listbox(body, font=TEXT_FONT)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Create", command=self.create).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Revert", command=self.revert).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Delete", command=self.delete, style="Danger.TButton").pack(side=tk.LEFT)
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
        if not messagebox.askyesno("Create snapshot", f"Create snapshot {name} for {self.vm_name}?", parent=self):
            return
        self.app.run_background(f"Creating snapshot {name}", lambda: self.backend.create_snapshot(self.vm_name, name, desc))
        self.after(1200, self.refresh)

    def revert(self) -> None:
        try:
            snap = self.selected_snapshot()
        except Exception as exc:
            self.app.show_error(exc)
            return
        if messagebox.askyesno(
            "Revert snapshot",
            f"Revert {self.vm_name} to {snap}?\n\nCurrent guest disk state will move back to that snapshot.",
            parent=self,
        ):
            self.app.run_background(f"Reverting {self.vm_name} to {snap}", lambda: self.backend.revert_snapshot(self.vm_name, snap))
            self.after(1200, self.refresh)

    def delete(self) -> None:
        try:
            snap = self.selected_snapshot()
        except Exception as exc:
            self.app.show_error(exc)
            return
        if messagebox.askyesno("Delete snapshot", f"Delete snapshot {snap} from {self.vm_name}?", parent=self):
            self.app.run_background(f"Deleting snapshot {snap}", lambda: self.backend.delete_snapshot(self.vm_name, snap))
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


if __name__ == "__main__":
    main()
