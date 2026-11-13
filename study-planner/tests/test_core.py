import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calc
from store import Store


class CalcTests(unittest.TestCase):
    def test_weeks(self):
        self.assertEqual(calc.week_of("2026-11-09", "2026-11-09"), 1)
        self.assertEqual(calc.week_of("2026-11-15", "2026-11-09"), 1)
        self.assertEqual(calc.week_of("2026-11-16", "2026-11-09"), 2)
        self.assertEqual(calc.week_of("2026-12-07", "2026-11-09"), 5)
        self.assertIsNone(calc.week_of("2026-11-09", None))
        self.assertEqual(calc.clamp_week(9), 5)
        self.assertEqual(calc.week_days(2, "2026-11-09", "2026-11-17")[0], "2026-11-16")

    def test_stats(self):
        comps = [{"id": "q1", "weight": 20}, {"id": "q2", "weight": 20}, {"id": "l1", "weight": 60}]
        g = {"q1": (80.0, None), "l1": (None, 100.0)}
        s = calc.course_stats(comps, g, target=90)
        self.assertAlmostEqual(s["current"], 80.0)           # only q1 graded
        self.assertAlmostEqual(s["projected"], (16 + 60) / 100 * 100)  # q2 empty counts as 0
        self.assertAlmostEqual(s["missing"], 20)
        self.assertAlmostEqual(s["remaining"], 80)
        # need: (90 - 16) / 80 * 100 = 92.5
        self.assertAlmostEqual(s["need"], 92.5)

    def test_stats_all_graded_and_empty(self):
        self.assertIsNone(calc.course_stats([], {})["projected"])
        s = calc.course_stats([{"id": "a", "weight": 100}], {"a": (70.0, None)})
        self.assertIsNone(s["need"])
        self.assertAlmostEqual(s["projected"], 70.0)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.f.close()
        self.s = Store("sqlite:///" + self.f.name)
        self.s.init_schema()
        self.s.init_schema()  # idempotent

    def tearDown(self):
        os.unlink(self.f.name)

    def test_meta_and_courses(self):
        self.s.set_meta("block", "3"); self.s.set_meta("block", "4"); self.s.set_meta("start", "2026-11-09")
        self.assertEqual(self.s.get_meta(), {"block": "4", "start": "2026-11-09"})
        cid = self.s.add_course("DSCI 999")
        comps = [c for c in self.s.comps() if c["course_id"] == cid]
        self.assertEqual(len(comps), 6)
        self.assertEqual(sum(c["weight"] for c in comps), 100)
        self.s.add_comp(cid, "iClicker", "other", 5)
        self.s.update_comp(comps[0]["id"], "Quiz one", "quiz", 25)
        self.assertEqual(len([c for c in self.s.comps() if c["course_id"] == cid]), 7)
        self.s.delete_course(cid)
        self.assertEqual(self.s.courses(), [])
        self.assertEqual(self.s.comps(), [])

    def test_grades_are_per_person(self):
        cid = self.s.add_course("C"); comp = self.s.comps()[0]["id"]
        self.s.set_grade("ann", comp, 90.0, None)
        self.s.set_grade("ann", comp, 91.0, None)   # update path
        self.s.set_grade("bob", comp, None, 70.0)
        self.assertEqual(self.s.grades("ann"), {comp: (91.0, None)})
        self.assertEqual(self.s.grades("bob"), {comp: (None, 70.0)})
        self.s.set_target("ann", cid, 85); self.s.set_target("ann", cid, 88)
        self.assertEqual(self.s.targets("ann"), {cid: 88})
        self.assertEqual(self.s.targets("bob"), {})
        self.s.delete_comp(comp)
        self.assertEqual(self.s.grades("ann"), {})

    def test_tasks_sessions_ownership(self):
        cid = self.s.add_course("C")
        t = self.s.add_task("ann", "2026-11-12", cid, "Lab", "Lab 3")
        self.s.set_status(t, "bob", "done")             # wrong owner: ignored
        self.assertEqual(self.s.tasks("ann")[0]["status"], "todo")
        self.s.set_status(t, "ann", "done")
        row = self.s.tasks("ann")[0]
        self.assertEqual(row["status"], "done"); self.assertTrue(row["done_at"])
        self.s.set_status(t, "ann", "doing")
        self.assertIsNone(self.s.tasks("ann")[0]["done_at"])
        self.s.delete_task(t, "bob"); self.assertEqual(len(self.s.tasks("ann")), 1)
        self.s.set_status(t, "ann", "done")
        sid = self.s.add_session("bob", "2026-11-12", 45, cid, "Recursion")
        self.s.delete_session(sid, "ann"); self.assertEqual(len(self.s.sessions("bob")), 1)
        feed = self.s.activity(["ann", "bob"])
        self.assertEqual({e["user"] for e in feed}, {"ann", "bob"})
        self.s.delete_task(t, "ann"); self.s.delete_session(sid, "bob")
        self.assertEqual(self.s.activity(["ann", "bob"]), [])


if __name__ == "__main__":
    unittest.main()
