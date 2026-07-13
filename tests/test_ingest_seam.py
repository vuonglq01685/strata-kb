"""Ghim tests-gate/fixtures/pending-kb/ vào đầu ra THẬT của scaffold_doc().

Hành trình e2e không chạy được `kb ingest` (cần docling ~2GB + PDF bản quyền),
nên nó bắt đầu từ một fixture mô phỏng đầu ra của ingest. Test này là thứ giữ
cho fixture đó không trôi khỏi sự thật: sinh lại vào tmp, so với cây đã commit.

ĐỎ NGHĨA LÀ GÌ: đầu ra của ingest đã đổi. Đừng sửa test. Chạy lại
`python scripts/gen_e2e_fixture.py`, đọc kỹ diff, rồi commit fixture mới —
và kiểm tra xem tests-gate/e2e/test_journey.py có còn đúng với hình dạng mới không.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
FIXTURE = REPO / "tests-gate" / "fixtures" / "pending-kb"

sys.path.insert(0, str(REPO / "scripts"))
from gen_e2e_fixture import generate  # noqa: E402


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_fixture_file_tree_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    assert _tree(tmp_path / ".kb") == _tree(FIXTURE)


def test_fixture_markdown_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    # Không hardcode tên file: scaffold_doc().chapter_stem() slugify title của
    # unit đầu chương, nên tên là ch1-airspace-records.*. Duyệt cây thật thay vì
    # đoán — test_fixture_file_tree_matches_scaffold_output đã ghim tập tên rồi.
    names = sorted(p.name for p in (FIXTURE / "demo-doc").glob("*.md"))
    assert names, "fixture không có file .md nào"

    for name in names:
        fresh = (tmp_path / ".kb" / "demo-doc" / name).read_text(encoding="utf-8")
        committed = (FIXTURE / "demo-doc" / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} đã trôi khỏi đầu ra của scaffold_doc()"


def test_fixture_manifest_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load(
        (tmp_path / ".kb" / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    committed = yaml.safe_load(
        (FIXTURE / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    # scaffold_doc đặt ingested=date.today() → trôi mỗi ngày, không phải tín hiệu.
    fresh.pop("ingested", None)
    committed.pop("ingested", None)

    assert fresh == committed
