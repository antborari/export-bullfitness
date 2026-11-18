import tempfile
import unittest
from pathlib import Path

from exportador_asv import copy_selected_files, scan_candidate_files


class FileCopyTests(unittest.TestCase):
    def test_scan_finds_candidate_types_case_insensitively_and_ignores_other_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "datos.MDB").write_bytes(b"database")
            (root / "tabla.xlsx").write_bytes(b"spreadsheet")
            (root / "notas.txt").write_text("ignore")
            nested = root / "subcarpeta"
            nested.mkdir()
            (nested / "copia.BAK").write_bytes(b"backup")

            result = scan_candidate_files(root)

            self.assertEqual(
                {path.relative_to(root.resolve()).as_posix() for path in result.files},
                {"datos.MDB", "tabla.xlsx", "subcarpeta/copia.BAK"},
            )
            self.assertEqual(result.errors, [])

    def test_scan_excludes_destination_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "usb"
            destination.mkdir()
            (root / "datos.db").write_bytes(b"database")
            (destination / "anterior.db").write_bytes(b"old")

            result = scan_candidate_files(root, (destination,))

            self.assertEqual([path.name for path in result.files], ["datos.db"])

    def test_scan_does_not_exclude_source_when_destination_is_the_same_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "datos.db").write_bytes(b"database")

            result = scan_candidate_files(root, (root,))

            self.assertEqual([path.name for path in result.files], ["datos.db"])

    def test_copy_preserves_relative_paths_and_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "ASV"
            destination = root / "USB"
            (source / "Datos").mkdir(parents=True)
            destination.mkdir()
            source_file = source / "Datos" / "socios.mdb"
            source_file.write_bytes(b"database")
            missing_file = source / "Datos" / "faltante.mdb"

            result = copy_selected_files(
                source, destination, [source_file, missing_file]
            )

            self.assertEqual(len(result.copied), 1)
            self.assertEqual(
                (result.folder / "Datos" / "socios.mdb").read_bytes(),
                b"database",
            )
            self.assertEqual(len(result.errors), 1)

    def test_copy_rejects_files_outside_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "ASV"
            destination = root / "USB"
            source.mkdir()
            destination.mkdir()
            outside_file = root / "otro.mdb"
            outside_file.write_bytes(b"database")

            result = copy_selected_files(source, destination, [outside_file])

            self.assertEqual(result.copied, [])
            self.assertEqual(len(result.errors), 1)


if __name__ == "__main__":
    unittest.main()
