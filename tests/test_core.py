import tempfile
import unittest
from pathlib import Path

from zeroai.builtin_workflows import BUILTIN_H3_URI, align_h3_frames, adapt_h3_canvas
from zeroai.comfy import load_workflow, prepare_workflow
from zeroai.h3_setup import detect_comfyui_root, runtime_model_roots_from_stats
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

    def test_builtin_h3_workflow_adapts_canvas_and_references(self):
        template = load_workflow(BUILTIN_H3_URI)
        result = prepare_workflow(
            template,
            prompt="<Picture 1> and <Picture 2> talk to camera",
            width=768,
            height=1360,
            duration=10,
            references=["one.png", "two.png"],
            seed=777,
        )
        h3 = result["136"]["inputs"]
        self.assertEqual(h3["width"], 768)
        self.assertEqual(h3["height"], 1344)
        self.assertEqual(h3["length"], 243)
        self.assertEqual(result["129"]["inputs"]["noise_seed"], 777)
        self.assertIn("ref_images.ref_image_0", h3)
        self.assertIn("ref_images.ref_image_1", h3)
        self.assertNotIn("ref_images.ref_image_2", h3)
        load_images = [node for node in result.values() if node.get("class_type") == "LoadImage"]
        self.assertEqual(len(load_images), 2)
        self.assertEqual(load_images[0]["inputs"]["image"], "one.png")
        self.assertEqual(load_images[1]["inputs"]["image"], "two.png")

    def test_h3_grid_helpers(self):
        self.assertEqual(align_h3_frames(240), 243)
        self.assertEqual(adapt_h3_canvas(1360, 768), (1344, 768))
        self.assertEqual(adapt_h3_canvas(1024, 1024), (768, 768))

    def test_detect_comfyui_preferred_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ComfyUI"
            (root / "models").mkdir(parents=True)
            (root / "main.py").write_text("", encoding="utf-8")
            self.assertEqual(detect_comfyui_root(root, "http://127.0.0.1:9"), root)

    def test_runtime_model_roots_reads_desktop_extra_model_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared_models = base / "ComfyUI-Shared" / "models"
            (shared_models / "vae").mkdir(parents=True)
            config = base / "shared_model_paths.yaml"
            config.write_text(
                "comfy.desktop_0:\n"
                f"  base_path: '{shared_models}'\n"
                "  is_default: true\n"
                "  'vae': 'vae/'\n"
                "  'diffusion_models': 'diffusion_models/'\n",
                encoding="utf-8",
            )
            stats = {
                "system": {
                    "argv": [
                        "main.py",
                        "--extra-model-paths-config",
                        str(config),
                    ]
                }
            }
            roots = runtime_model_roots_from_stats(stats)
            self.assertTrue(roots)
            self.assertEqual(roots[0], shared_models)

    def test_runtime_models_directory_has_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models"
            models.mkdir()
            stats = {"system": {"argv": ["main.py", "--models-directory", str(models)]}}
            self.assertEqual(runtime_model_roots_from_stats(stats)[0], models)


if __name__ == "__main__":
    unittest.main()
