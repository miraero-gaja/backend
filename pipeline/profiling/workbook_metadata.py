"""Low-memory XLSX package metadata inspection using standard-library XML."""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree


_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_SHEET_TAG = f"{{{_SPREADSHEET_NS}}}sheet"
_ROW_TAG = f"{{{_SPREADSHEET_NS}}}row"
_CELL_TAG = f"{{{_SPREADSHEET_NS}}}c"
_VALUE_TAG = f"{{{_SPREADSHEET_NS}}}v"
_TEXT_TAG = f"{{{_SPREADSHEET_NS}}}t"
_FORMULA_TAG = f"{{{_SPREADSHEET_NS}}}f"
_DIMENSION_TAG = f"{{{_SPREADSHEET_NS}}}dimension"
_MERGED_CELL_TAG = f"{{{_SPREADSHEET_NS}}}mergeCell"
_RELATIONSHIP_TAG = f"{{{_PACKAGE_REL_NS}}}Relationship"
_RELATIONSHIP_ID = f"{{{_OFFICE_REL_NS}}}id"


class WorkbookStructureError(ValueError):
    """Raised when an XLSX package has an invalid or unreadable structure."""


@dataclass(frozen=True, slots=True)
class SheetMetadata:
    """Structural facts read directly from one worksheet XML part."""

    name: str
    dimension_ref: str | None
    dimension_max_row: int | None
    dimension_max_column: int | None
    xml_row_element_count: int
    xml_last_row: int
    xml_last_nonempty_row: int
    blank_trailing_rows: int
    merged_cell_count: int
    formula_cell_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkbookMetadata:
    """Workbook sheet order plus structural facts for every worksheet."""

    sheets: tuple[SheetMetadata, ...]

    @property
    def sheet_names(self) -> list[str]:
        return [sheet.name for sheet in self.sheets]

    def sheet(self, name: str) -> SheetMetadata:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        raise KeyError(name)


def _column_number(column_letters: str) -> int:
    number = 0
    for character in column_letters.upper():
        number = number * 26 + ord(character) - ord("A") + 1
    return number


def _dimension_limits(reference: str | None) -> tuple[int | None, int | None]:
    if not reference:
        return None, None
    end_reference = reference.split(":", maxsplit=1)[-1]
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+)", end_reference)
    if match is None:
        return None, None
    return int(match.group(2)), _column_number(match.group(1))


def _normalise_part_path(target: str) -> str:
    if target.startswith("/"):
        part_path = target.lstrip("/")
    else:
        part_path = posixpath.normpath(posixpath.join("xl", target))
    if part_path.startswith("../") or part_path == "..":
        raise WorkbookStructureError(f"worksheet relationship escapes XLSX package: {target}")
    return part_path


def _sheet_parts(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    try:
        workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationship_root = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
    except (KeyError, ElementTree.ParseError) as error:
        raise WorkbookStructureError("invalid XLSX workbook metadata") from error

    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationship_root.findall(_RELATIONSHIP_TAG)
    }
    parts: list[tuple[str, str]] = []
    for sheet in workbook_root.iter(_SHEET_TAG):
        relationship_id = sheet.attrib.get(_RELATIONSHIP_ID)
        if relationship_id is None or relationship_id not in targets:
            raise WorkbookStructureError(
                f"worksheet {sheet.attrib.get('name')!r} has no valid relationship"
            )
        parts.append(
            (
                sheet.attrib.get("name", ""),
                _normalise_part_path(targets[relationship_id]),
            )
        )
    return parts


def _cell_has_structural_value(cell: ElementTree.Element) -> bool:
    if cell.find(_FORMULA_TAG) is not None:
        return True
    value = cell.find(_VALUE_TAG)
    if value is not None and value.text is not None:
        return True
    return any(text.text not in (None, "") for text in cell.iter(_TEXT_TAG))


def _inspect_sheet(
    archive: zipfile.ZipFile,
    *,
    name: str,
    part_path: str,
) -> SheetMetadata:
    dimension_ref: str | None = None
    xml_row_element_count = 0
    xml_last_row = 0
    xml_last_nonempty_row = 0
    merged_cell_count = 0
    formula_cell_count = 0

    try:
        stream = archive.open(part_path)
    except KeyError as error:
        raise WorkbookStructureError(f"missing worksheet part: {part_path}") from error

    with stream:
        try:
            for event, element in ElementTree.iterparse(stream, events=("start", "end")):
                if event == "start" and element.tag == _DIMENSION_TAG:
                    dimension_ref = element.attrib.get("ref")
                elif event == "end" and element.tag == _ROW_TAG:
                    xml_row_element_count += 1
                    try:
                        row_number = int(element.attrib.get("r", xml_row_element_count))
                    except ValueError:
                        row_number = xml_row_element_count
                    xml_last_row = max(xml_last_row, row_number)
                    row_has_value = False
                    for cell in element.findall(_CELL_TAG):
                        formulas = list(cell.iter(_FORMULA_TAG))
                        formula_cell_count += len(formulas)
                        if _cell_has_structural_value(cell):
                            row_has_value = True
                    if row_has_value:
                        xml_last_nonempty_row = max(xml_last_nonempty_row, row_number)
                    element.clear()
                elif event == "end" and element.tag == _MERGED_CELL_TAG:
                    merged_cell_count += 1
                    element.clear()
        except ElementTree.ParseError as error:
            raise WorkbookStructureError(f"invalid worksheet XML: {part_path}") from error

    dimension_max_row, dimension_max_column = _dimension_limits(dimension_ref)
    structural_max_row = max(xml_last_row, dimension_max_row or 0)
    blank_trailing_rows = max(0, structural_max_row - xml_last_nonempty_row)
    return SheetMetadata(
        name=name,
        dimension_ref=dimension_ref,
        dimension_max_row=dimension_max_row,
        dimension_max_column=dimension_max_column,
        xml_row_element_count=xml_row_element_count,
        xml_last_row=xml_last_row,
        xml_last_nonempty_row=xml_last_nonempty_row,
        blank_trailing_rows=blank_trailing_rows,
        merged_cell_count=merged_cell_count,
        formula_cell_count=formula_cell_count,
    )


def inspect_workbook_metadata(path: str | Path) -> WorkbookMetadata:
    """Inspect sheets, dimensions, merges, formulas, and structural rows read-only."""

    workbook_path = Path(path)
    try:
        with zipfile.ZipFile(workbook_path, mode="r") as archive:
            sheets = tuple(
                _inspect_sheet(archive, name=name, part_path=part_path)
                for name, part_path in _sheet_parts(archive)
            )
    except (OSError, zipfile.BadZipFile) as error:
        raise WorkbookStructureError(f"cannot read XLSX package: {workbook_path}") from error
    return WorkbookMetadata(sheets=sheets)

