import tempfile, unittest
from pathlib import Path
from yabiztracker.database.database import Database
from yabiztracker.services.backup import BackupService, verify_sqlite_file, restore_backup_to_path
from yabiztracker.backup_bootstrap import prepare_database

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.db=Database(str(self.root/'organizations.db'))
        self.service=BackupService(self.db,str(self.root/'backups'),retention=2)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_create_and_retention(self):
        for i in range(4): self.service.create_backup(label=f"2026-09-12_12-00-0{i}")
        backups=self.service.list_backups(); self.assertEqual(len(backups),2)
        self.assertTrue(all(verify_sqlite_file(x)[0] for x in backups))
    def test_restore_preserves_good_data_and_moves_corrupt(self):
        self.db.conn.execute("CREATE TABLE IF NOT EXISTS t(x TEXT)"); self.db.conn.execute("INSERT INTO t VALUES('good')"); self.db.conn.commit()
        backup=self.service.create_backup(label="2026-09-12_12-00-00")
        self.db.conn.execute("INSERT INTO t VALUES('bad')"); self.db.conn.commit()
        self.db.close(); self.db=Database(str(self.root/'organizations.db'))
        restore_backup_to_path(backup,str(self.root/'organizations.db'))
        check=Database(str(self.root/'organizations.db')); self.assertEqual([tuple(r) for r in check.conn.execute("SELECT x FROM t").fetchall()],[('good',)]) ; check.close()
        self.assertTrue(any('.corrupt_' in x.name for x in self.root.iterdir()))
    def test_pre_migration_backup_is_created(self):
        self.db.close()
        conn=__import__('sqlite3').connect(str(self.root/'organizations.db')); conn.execute('PRAGMA user_version=3'); conn.commit(); conn.close()
        (self.root/'settings.json').write_text('{}',encoding='utf8')
        ok,msg=prepare_database(str(self.root)); self.assertTrue(ok,msg); self.assertTrue(any('pre-migration' in p.name for p in (self.root/'backups').iterdir()))

    def test_newer_schema_is_rejected(self):
        self.db.close(); conn=__import__('sqlite3').connect(str(self.root/'organizations.db')); conn.execute('PRAGMA user_version=999'); conn.commit(); conn.close(); (self.root/'settings.json').write_text('{}',encoding='utf8')
        ok,msg=prepare_database(str(self.root)); self.assertFalse(ok); self.assertIn('более новой',msg)

    def test_corrupt_backup_is_rejected(self):
        p=self.root/'backups'/'organizations_2026-09-12_12-00-01.db'; p.parent.mkdir(exist_ok=True); p.write_bytes(b'not sqlite')
        self.assertFalse(verify_sqlite_file(str(p))[0]); self.assertIsNone(self.service.latest_valid_backup())

if __name__=='__main__': unittest.main()
