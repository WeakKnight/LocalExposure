"""Surface negotiation and resize checks without a GPU or native window."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import slangpy as spy

from main import Viewer, select_surface_format


class ViewerSurfaceTests(unittest.TestCase):
    def test_rgba_surface_retains_existing_output_format(self):
        self.assertEqual(select_surface_format([
            spy.Format.bgra8_unorm, spy.Format.rgba8_unorm_srgb, spy.Format.rgba8_unorm,
        ]), spy.Format.rgba8_unorm)

    def test_bgra_surface_ignores_srgb_preference_and_list_order(self):
        # Metal advertises an sRGB preferred format alongside plain BGRA8.
        self.assertEqual(select_surface_format([
            spy.Format.bgra8_unorm_srgb, spy.Format.rgba16_float, spy.Format.bgra8_unorm,
        ]), spy.Format.bgra8_unorm)

    def test_unsupported_surfaces_fail_instead_of_double_encoding(self):
        for formats in ([], [spy.Format.bgra8_unorm_srgb], [spy.Format.rgba16_float]):
            with self.subTest(formats=formats), self.assertRaisesRegex(RuntimeError, 'UNORM surface'):
                select_surface_format(formats)

    def test_resize_minimize_restore_renegotiates_supported_format(self):
        viewer = Viewer.__new__(Viewer)
        viewer.device = Mock()
        viewer.surface = Mock()
        viewer.surface.info = SimpleNamespace(formats=[spy.Format.bgra8_unorm])
        viewer.resize(1440, 810)
        viewer.surface.configure.assert_called_once_with(
            width=1440, height=810, format=spy.Format.bgra8_unorm, vsync=True)
        viewer.resize(0, 0)
        viewer.surface.unconfigure.assert_called_once_with()
        self.assertEqual(viewer.surface.configure.call_count, 1)
        viewer.surface.info.formats = [spy.Format.rgba8_unorm]
        viewer.resize(960, 540)
        viewer.surface.configure.assert_called_with(
            width=960, height=540, format=spy.Format.rgba8_unorm, vsync=True)
        self.assertEqual(viewer.device.wait.call_count, 3)


if __name__ == '__main__':
    unittest.main()
