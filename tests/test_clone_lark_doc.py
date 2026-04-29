import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_lark_doc import build_image_dimension_repair_blocks, check_dependencies, find_lark_skill, split_top_level_blocks


class SplitTopLevelBlocksTest(unittest.TestCase):
    def test_preserves_original_top_level_block_xml(self) -> None:
        content = (
            "<title>Example &amp; Clone</title>"
            "<p data-z='2' data-a=\"1\">Keep&#160;<b>format</b></p>"
            "<img token=\"abc\"></img>"
        )

        title, blocks = split_top_level_blocks(content)

        self.assertEqual(title, "Example & Clone")
        self.assertEqual(
            blocks,
            [
                "<p data-z='2' data-a=\"1\">Keep&#160;<b>format</b></p>",
                "<img token=\"abc\"></img>",
            ],
        )


class DependencyCheckTest(unittest.TestCase):
    def test_check_dependencies_only_requires_lark_cli(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with patch("clone_lark_doc.Path.home", return_value=Path(home)):
                with patch("clone_lark_doc.shutil.which", return_value="/usr/local/bin/lark-cli"):
                    check_dependencies()

    def test_finds_reference_lark_skills_across_supported_roots(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            home_path = Path(home)
            for root_name in (".agents", ".codex", ".claude"):
                skill_file = home_path / root_name / "skills" / "lark-doc" / "SKILL.md"
                skill_file.parent.mkdir(parents=True)
                skill_file.write_text("# lark-doc\n", encoding="utf-8")

                with patch("clone_lark_doc.Path.home", return_value=home_path):
                    self.assertEqual(find_lark_skill("lark-doc"), skill_file)

                skill_file.unlink()


class ImageDimensionRepairTest(unittest.TestCase):
    def test_builds_repair_blocks_for_top_level_image_blocks(self) -> None:
        source = (
            '<title>Source</title>'
            '<grid id="src-grid"><column width-ratio="0.600000">'
            '<img id="src-img-1" name="wide.png" width="863" height="450" mime="image/png" scale="1.000000" src="src1"/>'
            '</column><column width-ratio="0.400000">'
            '<img id="src-img-2" name="tall.png" width="320" height="640" mime="image/png" scale="1.000000" src="src2"/>'
            "</column></grid>"
            '<table id="src-table"><tbody><tr><td>'
            '<img id="src-img-3" name="table.png" width="1200" height="700" mime="image/png" scale="1.000000" src="src3"/>'
            "</td></tr></tbody></table>"
            '<img id="src-img-4" name="single.png" width="900" height="300" mime="image/png" scale="1.000000" src="src4"/>'
            "<p>No image</p>"
        )
        clone = (
            '<title>Clone</title>'
            '<grid id="clone-grid"><column width-ratio="0.500000">'
            '<img id="clone-img-1" name="wide.png" width="512" height="512" mime="image/png" scale="1.000000" src="clone1"/>'
            '</column><column width-ratio="0.500000">'
            '<img id="clone-img-2" name="tall.png" width="512" height="512" mime="image/png" scale="1.000000" src="clone2"/>'
            "</column></grid>"
            '<table id="clone-table"><tbody><tr><td>'
            '<img id="clone-img-3" name="table.png" width="512" height="512" mime="image/png" scale="1.000000" src="clone3"/>'
            "</td></tr></tbody></table>"
            '<img id="clone-img-4" name="single.png" width="512" height="512" mime="image/png" scale="1.000000" src="clone4"/>'
            "<p>No image</p>"
        )

        repairs = build_image_dimension_repair_blocks(source, clone)

        self.assertEqual([repair["block_id"] for repair in repairs], ["clone-grid", "clone-table", "clone-img-4"])
        self.assertEqual([repair["image_count"] for repair in repairs], [2, 1, 1])
        self.assertIn('width="863"', repairs[0]["content"])
        self.assertIn('height="450"', repairs[0]["content"])
        self.assertIn('width="320"', repairs[0]["content"])
        self.assertIn('height="640"', repairs[0]["content"])
        self.assertIn('width="1200"', repairs[1]["content"])
        self.assertIn('height="700"', repairs[1]["content"])
        self.assertIn('width="900"', repairs[2]["content"])
        self.assertIn('height="300"', repairs[2]["content"])
        self.assertIn('src="clone1"', repairs[0]["content"])
        self.assertIn('src="clone3"', repairs[1]["content"])

    def test_ignores_seed_empty_paragraph_before_appended_blocks(self) -> None:
        source = (
            "<title>Source</title>"
            '<img id="src-img" name="wide.png" width="863" height="450" mime="image/png" scale="1.000000" src="src1"/>'
        )
        clone = (
            "<title>Clone</title>"
            "<p></p>"
            '<img id="clone-img" name="wide.png" width="512" height="512" mime="image/png" scale="1.000000" src="clone1"/>'
        )

        repairs = build_image_dimension_repair_blocks(source, clone)

        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["block_id"], "clone-img")
        self.assertIn('width="863"', repairs[0]["content"])
        self.assertIn('height="450"', repairs[0]["content"])

    def test_adds_missing_dimensions_to_non_self_closing_image_tags(self) -> None:
        source = (
            "<title>Source</title>"
            '<p id="src-p"><img id="src-img" name="wide.png" width="863" height="450" src="src1"></img></p>'
        )
        clone = "<title>Clone</title>" '<p id="clone-p"><img id="clone-img" name="wide.png" src="clone1"></img></p>'

        repairs = build_image_dimension_repair_blocks(source, clone)

        self.assertEqual(len(repairs), 1)
        self.assertIn('<img id="clone-img" name="wide.png" src="clone1" width="863" height="450"></img>', repairs[0]["content"])


if __name__ == "__main__":
    unittest.main()
