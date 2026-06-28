import pytest

from apps.marc.mapping import map_bibliographic_record
from apps.marc.parser import parse_iso2709, validate_parsed_record
from apps.marc.services import import_bibliographic_iso2709


def build_marc_record(fields):
    leader = "00000nam a2200000 i 4500"
    chunks = []
    directory = ""
    position = 0
    for tag, content in fields:
        data = content + "\x1e"
        length = len(data)
        directory += f"{tag}{length:04d}{position:05d}"
        chunks.append(data)
        position += length
    base_address = 24 + len(directory) + 1
    record_body = directory + "\x1e" + "".join(chunks) + "\x1d"
    record_length = 24 + len(record_body)
    leader = f"{record_length:05d}" + leader[5:12] + f"{base_address:05d}" + leader[17:]
    return (leader + record_body).encode()


def sample_bibliographic_record():
    return build_marc_record(
        [
            ("001", "ocn123456789"),
            ("003", "DLC"),
            ("008", "240101s2024    ch            000 0 chi  "),
            ("020", "  " + "\x1f" + "a9789570000001"),
            ("100", "1 " + "\x1f" + "a王大明,"),
            ("245", "10" + "\x1f" + "a圖書資訊學導論 :" + "\x1f" + "c王大明著."),
            ("246", "3 " + "\x1f" + "aIntroduction to library science"),
            ("250", "  " + "\x1f" + "a初版."),
            ("264", " 1" + "\x1f" + "a臺北市 :" + "\x1f" + "b知識出版社," + "\x1f" + "c2024."),
            ("300", "  " + "\x1f" + "a320面 ;"),
            ("336", "  " + "\x1f" + "a文字"),
            ("337", "  " + "\x1f" + "a無媒介"),
            ("338", "  " + "\x1f" + "a冊"),
            ("650", " 0" + "\x1f" + "a圖書資訊學."),
            ("082", "04" + "\x1f" + "a020"),
            ("500", "  " + "\x1f" + "a含參考書目."),
        ]
    )


def test_parse_iso2709_extracts_control_and_data_fields():
    parsed = parse_iso2709(sample_bibliographic_record())

    assert parsed["leader"][6:8] == "am"
    assert parsed["fields"][0] == {"tag": "001", "value": "ocn123456789"}
    title_field = next(field for field in parsed["fields"] if field["tag"] == "245")
    assert title_field["indicators"] == ["1", "0"]
    assert {"code": "a", "value": "圖書資訊學導論 :"} in title_field["subfields"]
    assert validate_parsed_record(parsed) == []


def test_map_bibliographic_record_extracts_core_catalog_metadata():
    mapped = map_bibliographic_record(parse_iso2709(sample_bibliographic_record()))

    assert mapped["control_number"] == "ocn123456789"
    assert mapped["work"]["primary_title"] == "圖書資訊學導論"
    assert mapped["instance"]["publisher"] == "知識出版社"
    assert mapped["instance"]["publication_date"] == "2024"
    assert mapped["instance"]["identifiers"] == [{"scheme": "isbn", "value": "9789570000001"}]
    assert mapped["subjects"] == [{"marc_tag": "650", "label": "圖書資訊學"}]


@pytest.mark.django_db
def test_import_bibliographic_iso2709_creates_work_instance_and_marc_record():
    marc_record = import_bibliographic_iso2709(sample_bibliographic_record(), source="unit-test")

    assert marc_record.validation_status == "valid"
    assert marc_record.bibliographic_record.control_number == "ocn123456789"
    assert marc_record.bibliographic_record.work.primary_title == "圖書資訊學導論"
    assert marc_record.bibliographic_record.instance.title_statement == "圖書資訊學導論"
    assert marc_record.bibliographic_record.instance.identifiers[0]["scheme"] == "isbn"
