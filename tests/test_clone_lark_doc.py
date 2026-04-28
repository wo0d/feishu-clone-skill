import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_lark_doc import check_dependencies, find_lark_skill, split_top_level_blocks


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


if __name__ == "__main__":
    unittest.main()
