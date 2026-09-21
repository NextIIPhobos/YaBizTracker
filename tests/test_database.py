import tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path
from yabiztracker.database.database import Database, SCHEMA_VERSION

def ORG(oid="1", **kw):
    return {"id": oid, "name": kw.get("name", "Test"), "address": "A", "category": "C", "subcategory": "S", "phone": "+1", "website": "https://example.com", "email": "a@example.com", "social_links": "{\"vk\":\"https://vk.com/a\"}", "latitude": 53.1, "longitude": 50.1}

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Database(str(Path(self.tmp.name)/"organizations.db"))
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_insert_update_duplicate_and_history(self):
        n,u,i,d,_=self.db.upsert_organizations([ORG()],"Samara")
        self.assertEqual((n,u,i,d),(1,0,0,0))
        n,u,i,d,_=self.db.upsert_organizations([ORG()],"Samara")
        self.assertEqual((n,u,i,d),(0,0,0,1))
        n,u,i,d,_=self.db.upsert_organizations([ORG(name="Changed")],"Samara")
        self.assertEqual((n,u,i,d),(0,1,0,0))
        self.assertEqual(self.db.get_by_id("1")["name"],"Changed")
        self.assertTrue(any(h["field"]=="name" for h in self.db.history("1")))
    def test_bulk_crm_rollback_and_validation(self):
        self.db.upsert_organizations([ORG("1"),ORG("2")],"Samara")
        self.assertEqual(self.db.update_crm_many(["1","2"],status="Клиент",responsible="Ivan"),2)
        self.assertEqual(self.db.get_by_id("1")["status"],"Клиент")
        with self.assertRaises(ValueError): self.db.update_crm("1",status="BAD")
        with self.assertRaises(ValueError): self.db.update_crm_many(["1"],status="BAD")
    def test_ignore_and_checkpoint_resume(self):
        self.db.upsert_organizations([ORG()],"Samara")
        self.assertEqual(self.db.ignore_organizations(["1"]),1)
        self.assertEqual(self.db.get_by_id("1"),None)
        rid,resumed=self.db.start_or_resume_scan("sig",[{"name":"Samara"}],["C"])
        self.assertFalse(resumed)
        self.db.save_checkpoint(rid,"Samara","C",50,1)
        self.assertEqual(self.db.get_checkpoint(rid,"Samara","C"),(50,1))
        rid2,resumed2=self.db.start_or_resume_scan("sig",[{"name":"Samara"}],["C"])
        self.assertEqual((rid2,resumed2),(rid,True))
        self.db.finish_scan_run(rid,"completed")
        rid3,resumed3=self.db.start_or_resume_scan("sig",[{"name":"Samara"}],["C"])
        self.assertNotEqual(rid3,rid); self.assertFalse(resumed3)

    def test_stale_reconciliation_requires_three_complete_scans_and_preserves_crm(self):
        self.db.upsert_organizations([ORG("1"), ORG("2")],"Samara")
        self.db.update_crm("2", status="Клиент")
        for _ in range(2):
            r=self.db.reconcile_category("Samara","C",[],scan_complete=True,truncated=False,threshold=3)
            self.assertEqual(r["deleted"],0)
        r=self.db.reconcile_category("Samara","C",[],scan_complete=True,truncated=False,threshold=3)
        self.assertEqual(r["deleted"],1)
        self.assertIsNone(self.db.get_by_id("1"))
        self.assertIsNotNone(self.db.get_by_id("2"))
        self.assertEqual(len(self.db.deleted_history("1")),1)

    def test_stale_reconciliation_never_deletes_truncated_scan(self):
        self.db.upsert_organizations([ORG()],"Samara")
        for _ in range(5):
            r=self.db.reconcile_category("Samara","C",[],scan_complete=True,truncated=True,threshold=1)
            self.assertEqual(r["deleted"],0)
        self.assertIsNotNone(self.db.get_by_id("1"))

    def test_trash_restore_filters_and_manual_cleanup(self):
        self.db.upsert_organizations([ORG("1", name="Bank",), ORG("2", name="Club")],"Samara")
        self.db.update_crm("1", responsible="Ivan", status="Клиент")
        self.assertEqual(self.db.move_to_trash(["1"], reason="manual_exclude", permanently_ignore=True),1)
        trash=self.db.get_trash({"search":"Bank","status":"Клиент","responsible":True})
        self.assertEqual(len(trash),1)
        self.assertIsNone(self.db.get_by_id("1"))
        restored,conflicts=self.db.restore_from_trash([trash[0]["trash_id"]])
        self.assertEqual((restored,conflicts),(1,[]))
        self.assertEqual(self.db.get_by_id("1")["responsible"],"Ivan")
        self.assertFalse(self.db.conn.execute("SELECT 1 FROM ignored_organizations WHERE org_id='1'").fetchone())
        self.db.move_to_trash(["1"], permanently_ignore=True)
        self.assertEqual(self.db.clear_trash(),1)
        self.assertIsNone(self.db.get_by_id("1"))
        self.assertTrue(self.db.conn.execute("SELECT 1 FROM ignored_organizations WHERE org_id='1'").fetchone())

    def test_trash_auto_purge_after_30_days(self):
        self.db.upsert_organizations([ORG("1")],"Samara")
        self.db.move_to_trash(["1"], permanently_ignore=True)
        old=(datetime.now()-timedelta(days=31)).isoformat(timespec="seconds")
        self.db.conn.execute("UPDATE deleted_organizations SET deleted_at=?",(old,)); self.db.conn.commit()
        self.assertEqual(self.db.purge_trash(days=30),1)
        self.assertEqual(self.db.get_trash({}),[])
        self.assertIsNotNone(self.db.conn.execute("SELECT 1 FROM ignored_organizations WHERE org_id='1'").fetchone())

    def test_schema_version(self):
        self.assertEqual(self.db.conn.execute("PRAGMA user_version").fetchone()[0],SCHEMA_VERSION)
    def test_integrity_and_backup_api(self):
        ok,detail=self.db.integrity_check(); self.assertTrue(ok); self.assertEqual(detail.lower(),"ok")
        target=Path(self.tmp.name)/"backup.db"; self.db.backup_to(str(target))
        other=Database(str(Path(self.tmp.name)/"other.db")); self.assertTrue(other.integrity_check()[0]); other.close()

    def test_organization_keeps_configured_settlement_name(self):
        org = ORG("city-1")
        self.db.upsert_organizations([org], "Самара")
        saved = self.db.get_by_id("city-1")
        self.assertEqual(saved["city_name"], "Самара")
        self.assertEqual(self.db.get_active_organizations(["Самара"])[0]["city_name"], "Самара")
        self.assertEqual(self.db.get_active_organizations(["Тольятти"]), [])


if __name__=='__main__': unittest.main()


class DatabaseHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"organizations.db"
        self.db=Database(str(self.path))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_category_order_does_not_create_false_history(self):
        org=ORG("1")
        org["categories"]=["Квесты", "Банк"]
        self.db.upsert_organizations([org], "Samara")
        org2=dict(org)
        org2["categories"]=["Банк", "Квесты"]
        n,u,i,d,_=self.db.upsert_organizations([org2], "Samara")
        self.assertEqual((n,u,i,d),(0,0,0,1))
        self.assertEqual(len(self.db.history("1")),0)

    def test_reconcile_finds_category_beyond_first_two(self):
        org=ORG("1")
        org["category"]="Основная"
        org["subcategory"]="Подкатегория"
        org["categories"]=["Основная", "Подкатегория", "Банк"]
        self.db.upsert_organizations([org], "Samara")
        for _ in range(2):
            self.assertEqual(self.db.reconcile_category("Samara", "Банк", [], scan_complete=True, truncated=False, threshold=3)["deleted"],0)
        self.assertEqual(self.db.reconcile_category("Samara", "Банк", [], scan_complete=True, truncated=False, threshold=3)["deleted"],1)

    def test_trash_expiration_keeps_manual_exclusion_tombstone(self):
        self.db.upsert_organizations([ORG("1")], "Samara")
        self.db.move_to_trash(["1"], permanently_ignore=True)
        old=(datetime.now()-timedelta(days=31)).isoformat(timespec="seconds")
        self.db.conn.execute("UPDATE deleted_organizations SET deleted_at=?",(old,)); self.db.conn.commit()
        self.db.purge_trash(days=30)
        self.assertIsNone(self.db.get_by_id("1"))
        self.assertIsNotNone(self.db.conn.execute("SELECT 1 FROM ignored_organizations WHERE org_id='1'").fetchone())

    def test_restore_fills_schema_defaults_for_legacy_snapshot(self):
        self.db.conn.execute(
            "INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
            ("legacy", "Legacy", datetime.now().isoformat(timespec="seconds"), "manual_exclude", '{"org_id":"legacy","name":"Legacy"}'),
        )
        self.db.conn.commit()
        tid=self.db.conn.execute("SELECT id FROM deleted_organizations").fetchone()[0]
        restored,conflicts=self.db.restore_from_trash([tid])
        self.assertEqual((restored,conflicts),(1,[]))
        row=self.db.get_by_id("legacy")
        self.assertEqual(row["status"],"Новый")
        self.assertEqual(row["categories_json"],"[]")

class DatabaseConcurrencyTests(unittest.TestCase):
    def test_concurrent_upserts_on_single_connection_remain_consistent(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            db=Database(str(Path(d)/"organizations.db"))
            errors=[]
            def worker(start):
                try:
                    db.upsert_organizations([ORG(str(i), name=f"Org {i}") for i in range(start,start+20)], "Samara")
                except Exception as exc:
                    errors.append(exc)
            threads=[threading.Thread(target=worker,args=(i*10,)) for i in range(6)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(errors,[])
            self.assertEqual(len(db.get_all_organizations()),70)
            self.assertTrue(db.integrity_check()[0])
            db.close()

class CategoryLivenessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "organizations.db"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_liveness_is_isolated_per_search_category(self):
        org = ORG("1")
        org["categories"] = ["Квесты", "Банк"]
        self.db.upsert_organizations([org], "Samara")
        # Seen in one category must not reset/invalidate the other category's state.
        self.db.record_category_observations(["1"], "Samara", "Квесты")
        self.db.reconcile_category("Samara", "Банк", [], scan_complete=True, truncated=False, threshold=3)
        self.db.record_category_observations(["1"], "Samara", "Квесты")
        self.db.reconcile_category("Samara", "Банк", [], scan_complete=True, truncated=False, threshold=3)
        self.assertIsNotNone(self.db.get_by_id("1"))
        self.assertEqual(
            self.db.conn.execute(
                "SELECT missing_scan_count FROM organization_category_observations "
                "WHERE org_id='1' AND search_category='Банк'"
            ).fetchone()[0],
            2,
        )

    def test_seen_observation_resets_consecutive_misses(self):
        self.db.upsert_organizations([ORG("1")], "Samara")
        self.db.record_category_observations(["1"], "Samara", "C")
        self.assertEqual(self.db.reconcile_category("Samara", "C", [], scan_complete=True, truncated=False, threshold=3)["deleted"], 0)
        self.assertEqual(self.db.reconcile_category("Samara", "C", ["1"], scan_complete=True, truncated=False, threshold=3)["deleted"], 0)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT missing_scan_count FROM organization_category_observations WHERE org_id='1' AND search_category='C'"
            ).fetchone()[0],
            0,
        )

    def test_incomplete_scan_does_not_create_liveness_miss(self):
        self.db.upsert_organizations([ORG("1")], "Samara")
        self.db.reconcile_category("Samara", "C", [], scan_complete=False, truncated=False, threshold=1)
        self.assertIsNone(
            self.db.conn.execute(
                "SELECT 1 FROM organization_category_observations WHERE org_id='1' AND search_category='C'"
            ).fetchone()
        )
