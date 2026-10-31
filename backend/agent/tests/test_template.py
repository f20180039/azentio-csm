import fitz
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.extract import extract
from app.llm.gateway import Gateway, MockProvider
from app.pdf import parse
from app.schemas import Schema


class Lines(BaseModel):
    lines: list[str]


def _pdf(lines: list[tuple[str, str]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    for i, (text, font) in enumerate(lines):
        page.insert_text((72, 72 + 20 * i), text, fontname=font, fontsize=11)
    doc.set_metadata({"producer": "Test Bank Statement Engine", "creator": "unit-test"})
    return doc.tobytes()


def _schema(parser) -> Schema:
    return Schema(key="t", model=Lines, prompt="", prompt_version="t-v1", mock=lambda text: {"lines": ["mock"]},
                  parser=parser)


def test_parse_reports_metadata_and_fonts_per_line():
    parsed = parse(_pdf([("Opening balance 1,000.00", "helv"), ("Closing balance 2,000.00", "cour")]), 10)
    assert parsed.meta["producer"] == "Test Bank Statement Engine"
    assert parsed.meta["incremental_updates"] == 0
    assert parsed.line_fonts[0] == [["Helvetica"], ["Courier"]]
    assert len(parsed.line_fonts[0]) == len(parsed.pages[0]["text"].splitlines())


def test_incremental_save_is_counted(tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(_pdf([("Balance 1,000.00", "helv")]))
    with fitz.open(path) as doc:
        doc.set_metadata({"producer": "iLovePDF"})
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    meta = parse(path.read_bytes(), 10).meta
    assert meta["incremental_updates"] == 1
    assert meta["producer"] == "iLovePDF"


def test_linearized_pdf_is_not_counted_as_edited():
    linear = fitz.open(stream=_pdf([("Balance 1,000.00", "helv")])).tobytes(linear=True)
    assert parse(linear, 10).meta["incremental_updates"] == 0


def test_template_parser_skips_the_model():
    def parser(pages, parsed):
        return {"lines": pages[0]["text"].splitlines()}

    body = extract(_pdf([("one", "helv"), ("two", "helv")]), _schema(parser), Gateway([MockProvider()]), Settings())
    assert body["extraction_path"] == "template"
    assert body["fields"] == {"lines": ["one", "two"]}
    assert body["model"]["provider"] == "template"
    assert body["usage"]["input_tokens"] == 0


@pytest.mark.parametrize("parser", [lambda pages, parsed: None, lambda pages, parsed: {"lines": "not a list"}])
def test_unrecognised_or_invalid_template_falls_back_to_model(parser):
    body = extract(_pdf([("one", "helv")]), _schema(parser), Gateway([MockProvider()]), Settings())
    assert body["extraction_path"] == "llm"
    assert body["fields"] == {"lines": ["mock"]}
