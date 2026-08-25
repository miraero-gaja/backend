from pipeline.profiling.workbook_profile import _schema_header_kind


def test_20260824_official_schema_headers_are_recognized() -> None:
    assert _schema_header_kind("컬럼명") == "column_name"
    assert _schema_header_kind("데이터타입") == "declared_type"
    assert _schema_header_kind("Nullable") == "declared_nullable"
    assert _schema_header_kind("컬럼코멘트") == "display_name"