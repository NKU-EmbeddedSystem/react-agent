import unittest

from pipeline.table_words import format_lines, group_lines, table_lines, words_in

# The header and first five rows of paper 1, Table 1, as Step 0 wrote them (words/p002.jsonl).
# The footnote markers are glued to the entry numbers ("2b") and sit about 1.7 pt higher.
TABLE1 = [
    {"text": "3a/3a′/1a′", "bbox": [484.55, 113.28, 517.62, 121.86]},
    {"text": "entry", "bbox": [322.41, 113.86, 338.16, 121.86]},
    {"text": "cat.", "bbox": [362.04, 113.86, 372.51, 121.86]},
    {"text": "additive", "bbox": [395.72, 113.86, 419.8, 121.86]},
    {"text": "conv.", "bbox": [436.71, 113.86, 452.88, 121.86]},
    {"text": "(%)", "bbox": [455.58, 113.86, 467.65, 121.86]},
    {"text": "(yield,", "bbox": [520.27, 113.86, 539.68, 121.86]},
    {"text": "%)", "bbox": [542.38, 113.86, 551.2, 121.86]},
    {"text": "1", "bbox": [324.57, 126.78, 328.37, 134.78]},
    {"text": "75", "bbox": [448.38, 126.78, 456.0, 134.78]},
    {"text": "12/8/50", "bbox": [504.68, 126.78, 531.0, 134.78]},
    {"text": "2b", "bbox": [324.57, 135.96, 331.97, 145.72]},
    {"text": "FeCl2", "bbox": [358.58, 137.73, 375.99, 146.46]},
    {"text": ">98", "bbox": [446.17, 137.73, 458.16, 145.73]},
    {"text": "49/44/0", "bbox": [504.68, 137.73, 531.0, 145.73]},
    {"text": "3c", "bbox": [324.57, 146.9, 331.06, 156.67]},
    {"text": "C1", "bbox": [362.61, 148.67, 371.94, 156.67]},
    {"text": ">98", "bbox": [446.17, 148.67, 458.16, 156.67]},
    {"text": "78/19/0", "bbox": [504.68, 148.67, 531.0, 156.67]},
    {"text": "4c", "bbox": [324.57, 157.85, 331.06, 167.61]},
    {"text": "C1", "bbox": [362.61, 159.61, 371.94, 167.61]},
    {"text": "LiCl", "bbox": [400.99, 159.61, 414.52, 167.61]},
    {"text": ">98", "bbox": [446.17, 159.61, 458.16, 167.61]},
    {"text": "90/5/0", "bbox": [506.61, 159.61, 529.12, 167.61]},
    {"text": "5", "bbox": [324.57, 170.55, 328.54, 178.55]},
    {"text": "C1", "bbox": [362.61, 170.55, 371.94, 178.55]},
    {"text": "LiCl", "bbox": [400.76, 170.55, 414.78, 178.55]},
    {"text": ">98", "bbox": [446.0, 170.55, 458.33, 178.55]},
    {"text": "90", "bbox": [497.71, 170.55, 505.66, 178.55]},
    {"text": "(81)/4/0", "bbox": [508.36, 170.55, 538.01, 178.55]},
]


class TableWords(unittest.TestCase):
    def test_rows_with_raised_markers(self):
        lines = group_lines(TABLE1)
        texts = [[w["text"] for w in line["words"]] for line in lines]
        self.assertEqual(texts, [
            ["entry", "cat.", "additive", "conv.", "(%)", "3a/3a′/1a′", "(yield,", "%)"],
            ["1", "75", "12/8/50"],
            ["2b", "FeCl2", ">98", "49/44/0"],
            ["3c", "C1", ">98", "78/19/0"],
            ["4c", "C1", "LiCl", ">98", "90/5/0"],
            ["5", "C1", "LiCl", ">98", "90", "(81)/4/0"],
        ])

    def test_format_keeps_x_positions(self):
        line = format_lines(group_lines(TABLE1))[2]
        self.assertTrue(line.startswith("y=14"))
        self.assertIn("| 2b@325  FeCl2@359  >98@446  49/44/0@505", line)

    def test_area_and_threshold(self):
        self.assertEqual(len(words_in(TABLE1, [300, 125, 560, 147])), 7)  # rows 1 and 2
        self.assertIsNone(table_lines(TABLE1, [300, 125, 560, 147], min_words=8))
        self.assertEqual(len(table_lines(TABLE1, [300, 100, 560, 200])), 6)
        self.assertEqual(group_lines([]), [])


if __name__ == "__main__":
    unittest.main()
