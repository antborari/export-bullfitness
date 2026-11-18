from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_NAME = "Copiador portable para ASV-GIMNASIOS"
CANDIDATE_EXTENSIONS = {
    ".mdb", ".accdb", ".sqlite", ".sqlite3", ".db",
    ".fdb", ".gdb", ".bak", ".backup", ".zip", ".7z", ".rar",
    ".xls", ".xlsx", ".xlsm", ".csv",
}
ASV_PROGRAM_NAMES = ("asv", "gimnasio", "control de acceso")


@dataclass(frozen=True)
class ScanResult:
    files: list[Path]
    errors: list[str]


@dataclass(frozen=True)
class CopyResult:
    folder: Path
    copied: list[Path]
    errors: list[str]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_candidate_files(root: Path, excluded: tuple[Path, ...] = ()) -> ScanResult:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"La carpeta de búsqueda no existe: {root}")

    excluded_paths = tuple(
        path.expanduser().resolve()
        for path in excluded
        if path.expanduser().resolve() != root
        and _is_relative_to(path.expanduser().resolve(), root)
    )
    candidates: list[Path] = []
    errors: list[str] = []

    def record_error(error: OSError) -> None:
        errors.append(str(error))

    for current, directories, filenames in os.walk(root, onerror=record_error, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories
            if not (current_path / name).is_symlink()
            and not any(
                _is_relative_to((current_path / name).resolve(), excluded_path)
                for excluded_path in excluded_paths
            )
        ]
        if any(_is_relative_to(current_path.resolve(), path) for path in excluded_paths):
            directories.clear()
            continue
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink() or path.suffix.lower() not in CANDIDATE_EXTENSIONS:
                continue
            candidates.append(path)

    candidates.sort(key=lambda path: str(path).casefold())
    return ScanResult(candidates, errors)


def find_asv_installations() -> list[Path]:
    candidates: set[Path] = set()

    if os.name == "nt":
        try:
            import winreg

            registry_roots = (
                winreg.HKEY_LOCAL_MACHINE,
                winreg.HKEY_CURRENT_USER,
            )
            uninstall_paths = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            )
            for hive in registry_roots:
                for registry_path in uninstall_paths:
                    try:
                        with winreg.OpenKey(hive, registry_path) as uninstall:
                            subkey_count = winreg.QueryInfoKey(uninstall)[0]
                            for index in range(subkey_count):
                                try:
                                    subkey_name = winreg.EnumKey(uninstall, index)
                                    with winreg.OpenKey(uninstall, subkey_name) as entry:
                                        display_name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                        install_location = winreg.QueryValueEx(entry, "InstallLocation")[0]
                                    if (
                                        install_location
                                        and any(name in display_name.casefold() for name in ASV_PROGRAM_NAMES)
                                        and Path(install_location).is_dir()
                                    ):
                                        candidates.add(Path(install_location).resolve())
                                except (OSError, ValueError):
                                    continue
                    except OSError:
                        continue
        except ImportError:
            pass

        search_roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramW6432"),
        ]
        for search_root in filter(None, search_roots):
            base = Path(search_root)
            if not base.is_dir():
                continue
            for current, directories, filenames in os.walk(base):
                current_path = Path(current)
                try:
                    depth = len(current_path.relative_to(base).parts)
                except ValueError:
                    directories.clear()
                    continue
                if depth >= 4:
                    directories.clear()
                if any(
                    any(name in filename.casefold() for name in ASV_PROGRAM_NAMES)
                    and filename.casefold().endswith(".exe")
                    for filename in filenames
                ):
                    candidates.add(current_path.resolve())

    return sorted(candidates, key=lambda path: str(path).casefold())


def copy_selected_files(
    source_root: Path,
    destination_root: Path,
    selected_files: list[Path],
) -> CopyResult:
    source_root = source_root.expanduser().resolve()
    destination_root = destination_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"La carpeta de origen no existe: {source_root}")
    if not destination_root.is_dir():
        raise ValueError(f"La carpeta de destino no existe: {destination_root}")
    if not selected_files:
        raise ValueError("Selecciona al menos un archivo para copiar.")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_folder = destination_root / f"ASV-Copia-{timestamp}"
    suffix = 1
    while output_folder.exists():
        output_folder = destination_root / f"ASV-Copia-{timestamp}-{suffix}"
        suffix += 1
    output_folder.mkdir()

    copied: list[Path] = []
    errors: list[str] = []
    for source in selected_files:
        try:
            source = source.expanduser().resolve(strict=True)
            relative = source.relative_to(source_root)
            if not source.is_file():
                raise ValueError("no es un archivo regular")
            target = output_folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
        except (OSError, ValueError) as error:
            errors.append(f"{source}: {error}")
    return CopyResult(output_folder, copied, errors)


class ExporterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1020x680")
        self.root.minsize(760, 500)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.files: list[Path] = []
        self.selected: set[Path] = set()
        self._build_ui()
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        ttk.Label(main, text=APP_NAME, font=("", 17, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            main,
            text=(
                "Localiza la carpeta de ASV-GIMNASIOS, revisa los archivos candidatos "
                "y copia solo los que marques a un USB o a otra carpeta."
            ),
            wraplength=950,
        ).grid(row=1, column=0, sticky="w", pady=(5, 14))

        locations = ttk.LabelFrame(main, text="Origen y destino", padding=10)
        locations.grid(row=2, column=0, sticky="ew")
        locations.columnconfigure(1, weight=1)

        ttk.Label(locations, text="Carpeta de ASV / búsqueda:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.source_var = tk.StringVar()
        ttk.Entry(locations, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        self.detect_button = ttk.Button(
            locations, text="Detectar ASV", command=self._detect_installations
        )
        self.detect_button.grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Button(locations, text="Examinar…", command=self._choose_source).grid(
            row=0, column=3, padx=(8, 0), pady=4
        )

        ttk.Label(locations, text="Copiar a:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.destination_var = tk.StringVar()
        ttk.Entry(locations, textvariable=self.destination_var).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Button(locations, text="Examinar…", command=self._choose_destination).grid(
            row=1, column=3, padx=(8, 0), pady=4
        )

        actions = ttk.Frame(main)
        actions.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.rowconfigure(1, weight=1)
        controls = ttk.Frame(actions)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.scan_button = ttk.Button(
            controls, text="Buscar archivos candidatos", command=self._scan
        )
        self.scan_button.pack(side="left")
        self.select_all_button = ttk.Button(
            controls, text="Seleccionar todos", command=self._select_all
        )
        self.select_all_button.pack(side="left", padx=(8, 0))
        self.select_none_button = ttk.Button(
            controls, text="Quitar selección", command=self._select_none
        )
        self.select_none_button.pack(side="left", padx=(8, 0))
        self.copy_button = ttk.Button(
            controls, text="Copiar seleccionados", command=self._copy
        )
        self.copy_button.pack(side="right")

        table_frame = ttk.Frame(actions)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("selected", "file", "size"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("selected", text="Copiar")
        self.tree.heading("file", text="Ruta del archivo candidato")
        self.tree.heading("size", text="Tamaño")
        self.tree.column("selected", width=70, anchor="center", stretch=False)
        self.tree.column("file", width=760)
        self.tree.column("size", width=100, anchor="e", stretch=False)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Button-1>", self._toggle_row)
        self.tree.bind("<space>", self._toggle_selected_row)

        bottom = ttk.Frame(main)
        bottom.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(
            value="Detecta ASV o selecciona una carpeta para empezar."
        )
        ttk.Label(bottom, textvariable=self.status_var, wraplength=820).grid(
            row=0, column=0, sticky="w"
        )
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e", padx=(8, 0))

        ttk.Label(
            main,
            text=(
                "Solo se buscan bases de datos, copias, archivos de Excel y CSV. "
                "Usa una copia de seguridad cerrada, no archivos que ASV esté utilizando."
            ),
            wraplength=950,
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))

    def _choose_source(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona la carpeta de ASV o de búsqueda")
        if selected:
            self.source_var.set(selected)

    def _choose_destination(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona USB o carpeta de destino")
        if selected:
            self.destination_var.set(selected)

    def _detect_installations(self) -> None:
        self._set_busy(True, "Buscando instalaciones registradas de ASV…")
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self) -> None:
        try:
            paths = find_asv_installations()
            self.events.put(("installations", paths))
        except OSError as error:
            self.events.put(("error", f"No se pudieron buscar instalaciones: {error}"))

    def _scan(self) -> None:
        raw_root = self.source_var.get().strip()
        if not raw_root:
            messagebox.showwarning(APP_NAME, "Selecciona la carpeta de ASV o de búsqueda.")
            return
        destination = self.destination_var.get().strip()
        excluded = (Path(destination),) if destination else ()
        self._set_busy(True, "Buscando archivos candidatos…")
        threading.Thread(
            target=self._scan_worker,
            args=(Path(raw_root), excluded),
            daemon=True,
        ).start()

    def _scan_worker(self, root: Path, excluded: tuple[Path, ...]) -> None:
        try:
            self.events.put(("scan", scan_candidate_files(root, excluded)))
        except (OSError, ValueError) as error:
            self.events.put(("error", f"No se pudo examinar la carpeta: {error}"))

    def _copy(self) -> None:
        selected = [path for path in self.files if path in self.selected]
        if not selected:
            messagebox.showwarning(APP_NAME, "Marca al menos un archivo para copiar.")
            return
        source_root = self.source_var.get().strip()
        destination = self.destination_var.get().strip()
        if not source_root or not destination:
            messagebox.showwarning(APP_NAME, "Indica la carpeta de origen y el destino.")
            return
        if not Path(destination).is_dir():
            messagebox.showwarning(APP_NAME, "Selecciona una carpeta de destino existente.")
            return
        confirmed = messagebox.askyesno(
            APP_NAME,
            f"Se copiarán {len(selected)} archivo(s) a una subcarpeta nueva en:\n{destination}\n\n¿Continuar?",
        )
        if not confirmed:
            return
        self._set_busy(True, f"Copiando {len(selected)} archivo(s)…")
        threading.Thread(
            target=self._copy_worker,
            args=(Path(source_root), Path(destination), selected),
            daemon=True,
        ).start()

    def _copy_worker(self, source_root: Path, destination: Path, selected: list[Path]) -> None:
        try:
            result = copy_selected_files(source_root, destination, selected)
            self.events.put(("copy", result))
        except (OSError, ValueError) as error:
            self.events.put(("error", f"No se pudo iniciar la copia: {error}"))

    def _toggle_row(self, event: tk.Event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row and column == "#1":
            self._toggle_item(row)

    def _toggle_selected_row(self, _event: tk.Event) -> str:
        for row in self.tree.selection():
            self._toggle_item(row)
            break
        return "break"

    def _toggle_item(self, item: str) -> None:
        try:
            path = Path(item)
        except (TypeError, ValueError):
            return
        if path in self.selected:
            self.selected.remove(path)
        else:
            self.selected.add(path)
        self.tree.set(item, "selected", "☑" if path in self.selected else "☐")

    def _select_all(self) -> None:
        self.selected = set(self.files)
        for path in self.files:
            self.tree.set(str(path), "selected", "☑")

    def _select_none(self) -> None:
        self.selected.clear()
        for path in self.files:
            self.tree.set(str(path), "selected", "☐")

    def _set_busy(self, busy: bool, message: str) -> None:
        state = "disabled" if busy else "normal"
        for button in (self.detect_button, self.scan_button, self.copy_button):
            button.configure(state=state)
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_var.set(message)

    def _process_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._set_busy(False, "")
                if kind == "installations":
                    paths = payload
                    if not paths:
                        self.status_var.set(
                            "No se encontró ASV automáticamente. Selecciona manualmente su carpeta."
                        )
                    elif len(paths) == 1:
                        self.source_var.set(str(paths[0]))
                        self.status_var.set(
                            f"Instalación detectada: {paths[0]}. Pulsa «Buscar archivos candidatos»."
                        )
                    else:
                        chosen = self._choose_installation(paths)
                        if chosen:
                            self.source_var.set(str(chosen))
                            self.status_var.set(
                                f"Instalación seleccionada: {chosen}. Pulsa «Buscar archivos candidatos»."
                            )
                elif kind == "scan":
                    result = payload
                    self.files = result.files
                    self.selected = set(self.files)
                    rows = self.tree.get_children()
                    if rows:
                        self.tree.delete(*rows)
                    for path in self.files:
                        try:
                            size = self._format_size(path.stat().st_size)
                        except OSError:
                            size = "No disponible"
                        self.tree.insert(
                            "", "end", iid=str(path),
                            values=("☑", str(path), size),
                        )
                    message = f"Encontrados {len(self.files)} archivo(s); todos seleccionados."
                    if result.errors:
                        message += f" Hubo {len(result.errors)} error(es) de acceso durante la búsqueda."
                        messagebox.showwarning(
                            APP_NAME,
                            "Algunas carpetas no pudieron examinarse:\n\n"
                            + "\n".join(result.errors[:10]),
                        )
                    self.status_var.set(message)
                elif kind == "copy":
                    result = payload
                    message = (
                        f"Copiados {len(result.copied)} archivo(s) en:\n{result.folder}"
                    )
                    if result.errors:
                        message += f"\n\nNo se pudieron copiar {len(result.errors)} archivo(s):\n"
                        message += "\n".join(result.errors[:10])
                        messagebox.showwarning(APP_NAME, message)
                    else:
                        messagebox.showinfo(APP_NAME, message)
                    self.status_var.set(
                        f"Copiados {len(result.copied)} archivo(s). Destino: {result.folder}"
                    )
                elif kind == "error":
                    self.status_var.set(str(payload))
                    messagebox.showerror(APP_NAME, str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _choose_installation(self, paths: list[Path]) -> Path | None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Instalaciones de ASV encontradas")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="Selecciona la carpeta que contiene ASV:").pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        listbox = tk.Listbox(dialog, width=90, height=min(len(paths), 12))
        for path in paths:
            listbox.insert("end", str(path))
        listbox.selection_set(0)
        listbox.pack(fill="both", expand=True, padx=12)
        choice: list[Path | None] = [None]

        def accept() -> None:
            selection = listbox.curselection()
            if selection:
                choice[0] = paths[selection[0]]
            dialog.destroy()

        ttk.Button(dialog, text="Seleccionar", command=accept).pack(
            anchor="e", padx=12, pady=12
        )
        dialog.bind("<Return>", lambda _event: accept())
        self.root.wait_window(dialog)
        return choice[0]

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"


def main() -> None:
    root = tk.Tk()
    ExporterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
