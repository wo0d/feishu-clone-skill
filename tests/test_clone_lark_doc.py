import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_lark_doc import split_top_level_blocks


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


if __name__ == "__main__":
    unittest.main()
