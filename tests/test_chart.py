import io
import unittest
from unittest.mock import patch

from PIL import Image

from iran_monitor.chart import render_chart
from iran_monitor.plot import draw_chart
from matplotlib.figure import Figure
from tests.test_analysis import assess, payload


class ChartTests(unittest.TestCase):
    def test_persian_title_reaches_native_shaper_in_logical_order(self):
        original = Figure.text
        titles = []

        def capture(figure, x, y, text, *args, **kwargs):
            titles.append(text)
            return original(figure, x, y, text, *args, **kwargs)

        with patch.object(Figure, "text", capture):
            draw_chart(assess(payload()))
        self.assertIn("نبض اینترنت ایران", titles)

    def test_report_generates_a_decodable_nonblank_png(self):
        body = render_chart(assess(payload()), demo=True)
        with Image.open(io.BytesIO(body)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreaterEqual(image.width, 1200)
            self.assertGreaterEqual(image.height, 700)
            self.assertGreater(len(image.convert("RGB").getcolors(2**24)), 100)

    def test_unknown_empty_data_still_renders_an_honest_chart(self):
        body = render_chart(assess(payload((), ())))
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
