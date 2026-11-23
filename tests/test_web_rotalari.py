"""web_uygulamasi() gerçekten kurulabiliyor mu.

Bir kez canlıda çöktü: main.py hem `import sesli` yapıyordu hem de modül
seviyesinde `sesli = None` tanımlıyordu, route kurulurken AttributeError
attı ve Render eski sürümde kaldı. Bu test o sınıf hatayı yakalar.
"""

import unittest
from unittest import mock

import main


class WebRotalari(unittest.TestCase):

    def _uygulama(self):
        bot = mock.MagicMock()
        app = mock.MagicMock()
        app.bot = bot
        return main.web_uygulamasi(app)

    def test_kurulabiliyor_ve_dinle_var(self):
        yollar = {getattr(r, "path", None) for r in self._uygulama().routes}
        self.assertIn("/health", yollar)
        self.assertIn("/dinle/{token}", yollar)
        self.assertIn("/telefon/{token}", yollar)
        self.assertIn("/seslendir/{token}", yollar)
        self.assertIn("/sor/{token}", yollar)


if __name__ == "__main__":
    unittest.main()
