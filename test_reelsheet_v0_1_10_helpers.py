import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_module():
    module_path = Path(__file__).with_name("reelsheet_v0.1.24.py")
    spec = importlib.util.spec_from_file_location("reelsheet_v0_1_24", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HelperTests(unittest.TestCase):
    def test_unique_export_path_skips_existing_names(self):
        rs = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "clip_frame_00-01-02.jpg").write_text("exists")
            (tmp_path / "clip_frame_00-01-02_001.jpg").write_text("exists")

            candidate = rs.unique_export_path(
                tmp_path, "clip_frame_00-01-02", ".jpg")

            self.assertEqual(candidate, tmp_path / "clip_frame_00-01-02_002.jpg")

    def test_fit_rect_preserves_aspect_ratio(self):
        rs = load_module()

        self.assertEqual(rs.fit_rect(1920, 1080, 200, 68), (120, 68))
        self.assertEqual(rs.fit_rect(1080, 1920, 200, 68), (38, 68))

    def test_stereo_vu_levels_idle_and_active(self):
        rs = load_module()

        self.assertEqual(rs.stereo_vu_levels(False, 0.8, 0.0), (0.0, 0.0))
        left, right = rs.stereo_vu_levels(True, 0.8, 1.25)

        self.assertGreaterEqual(left, 0.05)
        self.assertLessEqual(left, 0.8)
        self.assertGreaterEqual(right, 0.05)
        self.assertLessEqual(right, 0.8)
        self.assertNotEqual(left, right)


if __name__ == "__main__":
    unittest.main()
