import tempfile
import unittest
from pathlib import Path

import db


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"
        db.init_db(self.path)

    def tearDown(self): self.tmp.cleanup()

    def test_end_to_end(self):
        self.assertEqual(db._normalize_supabase_url("abc.supabase.co"), "https://abc.supabase.co")
        self.assertEqual(db._normalize_supabase_url("https://abc.supabase.co/rest/v1"), "https://abc.supabase.co")
        settings = db.get_settings(self.path)
        self.assertEqual(settings["exam_date"], "2026-12-01")
        practice_id = db.add_practice({
            "practice_date":"2026-08-07", "activity_type":"consecutive", "direction":"KO→JA", "title":"테스트", "topic":"경제", "source_url":"https://example.com", "video_speed":1.0,
            "minutes":10, "difficulty":3, "omission":1, "number_omission":0, "logic_error":0,
            "expression_block":2, "unnatural_expression":1, "other_notes":"",
        }, self.path)
        self.assertGreater(practice_id, 0)
        self.assertEqual(db.query("SELECT activity_type FROM practices", db_path=self.path)[0]["activity_type"], "consecutive")
        self.assertEqual(db.query("SELECT source_url FROM practices", db_path=self.path)[0]["source_url"], "https://example.com")
        sight_id = db.add_practice({
            "practice_date":"2026-08-08", "activity_type":"sight_translation", "direction":"JA→KO",
            "title":"시역 기사", "topic":"사회", "source_url":"https://example.com/article", "video_speed":1.0, "minutes":12,
            "difficulty":4, "omission":0, "number_omission":0, "logic_error":0,
            "expression_block":1, "unnatural_expression":0, "other_notes":"",
        }, self.path)
        self.assertGreater(sight_id, 0)
        note_id = db.add_note({"note_date":"2026-08-07", "title":"메모", "content":"공부 내용", "tags":"시험"}, self.path)
        self.assertGreater(note_id, 0)
        feedback_id = db.add_script_feedback({"feedback_date":"2026-08-07", "interpretation_type":"동시통역", "direction":"KO→JA", "title":"비교", "source_script":"10명입니다.", "interpreted_script":"10人です。", "feedback":"숫자 보존"}, self.path)
        self.assertGreater(feedback_id, 0)
        db.update_record("practices", practice_id, {"title":"수정됨", "minutes":20}, self.path)
        self.assertEqual(db.query("SELECT title,minutes FROM practices WHERE id=?", (practice_id,), self.path)[0], {"title":"수정됨", "minutes":20})
        script_id = db.add_script_review("복습", "첫 문장입니다. 둘째 문장입니다.", self.path)
        db.update_record("script_reviews", script_id, {"highlights":'[{"start":0,"end":2,"note":"메모"}]'}, self.path)
        saved_highlights = db.query("SELECT highlights FROM script_reviews WHERE id=?", (script_id,), self.path)[0]["highlights"]
        self.assertIn("메모", saved_highlights)
        pair_id = db.add_pair({"korean":"정책을 추진하다", "japanese":"政策を推進する", "pair_type":"collocation", "mastery":2}, self.path)
        self.assertEqual(db.review_queue(db_path=self.path)[0]["id"], pair_id)
        db.record_review(pair_id, 0, self.path)
        updated = db.query("SELECT * FROM language_pairs WHERE id=?", (pair_id,), self.path)[0]
        self.assertEqual(updated["review_count"], 1)
        self.assertEqual(updated["mastery"], 1)


if __name__ == "__main__": unittest.main()
