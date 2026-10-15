import unittest

from zeroai.comfy import prepare_workflow
from zeroai.models import AppSettings
from zeroai.planner import create_plan


class PlannerTests(unittest.TestCase):
    def test_long_video_splits_into_h3_sized_scenes(self):
        result = create_plan(
            "Explain why people dream with a strong TikTok hook.",
            60,
            "UGC / TikTok",
            "9:16",
            3,
            AppSettings(),
        )
        self.assertGreater(len(result.scenes), 1)
        self.assertEqual(sum(scene.duration for scene in result.scenes), 60)
        self.assertTrue(all(4 <= scene.duration <= 15 for scene in result.scenes))
        self.assertIn("<Picture 1>", result.scenes[0].prompt)
        self.assertIn("<Picture 3>", result.scenes[0].prompt)

    def test_workflow_placeholders_keep_numeric_types(self):
        template = {
            "1": {"inputs": {"text": "{{PROMPT}}", "width": "{{WIDTH}}", "seed": "{{SEED}}"}},
            "2": {"inputs": {"image": "{{REFERENCE_1}}", "frames": "{{FRAMES}}"}},
        }
        result = prepare_workflow(
            template,
            prompt="hello",
            width=768,
            height=1360,
            duration=10,
            references=["person.png"],
            seed=123,
        )
        self.assertEqual(result["1"]["inputs"]["text"], "hello")
        self.assertEqual(result["1"]["inputs"]["width"], 768)
        self.assertEqual(result["1"]["inputs"]["seed"], 123)
        self.assertEqual(result["2"]["inputs"]["image"], "person.png")
        self.assertEqual(result["2"]["inputs"]["frames"], 240)


if __name__ == "__main__":
    unittest.main()
