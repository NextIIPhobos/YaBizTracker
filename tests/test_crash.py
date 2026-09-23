import tempfile, unittest
from pathlib import Path
from yabiztracker.crash import CrashHandler

class CrashTests(unittest.TestCase):
    def test_crash_report_contains_required_context(self):
        with tempfile.TemporaryDirectory() as d:
            h=CrashHandler(d,lambda:{"version":"1.1.0","state":"scanning","recent_operations":["scan started","page 1"]})
            try: raise ValueError("boom")
            except ValueError as exc:
                path=h.write_crash(type(exc),exc,exc.__traceback__)
            text=Path(path).read_text(encoding='utf8')
            self.assertIn('Timestamp:',text); self.assertIn('Application version: 1.1.0',text); self.assertIn('Python:',text); self.assertIn('Traceback:',text); self.assertIn('boom',text); self.assertIn('scan started',text)

if __name__=='__main__': unittest.main()
