import tempfile, unittest
from pathlib import Path
from openpyxl import load_workbook
from yabiztracker.services.export_service import ExportService

class ExportTests(unittest.TestCase):
    def test_fallback_without_openpyxl(self):
        import builtins
        original=builtins.__import__
        def fake_import(name,*args,**kwargs):
            if name.startswith('openpyxl'): raise ModuleNotFoundError('simulated missing openpyxl')
            return original(name,*args,**kwargs)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fallback.xlsx'
            o={"name":"A","website":"https://example.com"}
            old=builtins.__import__; builtins.__import__=fake_import
            try: engine=ExportService().export(str(p),[o])
            finally: builtins.__import__=old
            self.assertEqual(engine,'fallback'); self.assertTrue(p.exists()); self.assertTrue(p.read_bytes().startswith(b'PK'))

    def test_roundtrip_and_sanitisation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.xlsx'; o={"name":"A\x00B","address":"X\x0bY","city_name":"Самара","category":"C","subcategory":"S","age_days":1,"phone":"1","email":"a@b","website":"https://example.com","social_links":"{\"vk\":\"https://vk.com/a\"}","status":"Новый","comment":"C","responsible":"R","next_contact_date":"2026-09-12 12:00","score":10}
            engine=ExportService().export(str(p),[o]); self.assertTrue(p.exists()); wb=load_workbook(p); ws=wb['Организации']; self.assertEqual(ws['A2'].value,'AB'); self.assertEqual(ws['C2'].value,'Самара'); self.assertEqual(ws['H2'].hyperlink.target,'https://example.com'); wb.close(); self.assertIn(engine,('openpyxl','fallback'))

if __name__=='__main__': unittest.main()
