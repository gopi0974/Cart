from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np

from app.ai import feature_extractor
from app.main import _get_detailed_health_data


def test_onnx_session_options_disable_arena_and_pattern(monkeypatch):
    """load_onnx_model must disable CPU mem arena & mem pattern and keep 1 session / 1 thread."""
    captured = {}

    class FakeSessionOptions:
        def __init__(self):
            self.intra_op_num_threads = None
            self.inter_op_num_threads = None
            self.execution_mode = None
            self.graph_optimization_level = None
            self.enable_cpu_mem_arena = True
            self.enable_mem_pattern = True
            captured["opts"] = self

    fake_session = MagicMock()
    fake_session.get_inputs.return_value = [SimpleNamespace(name="pixel_values")]
    fake_session.run.return_value = [np.ones((1, 512), dtype=np.float32)]

    fake_ort = SimpleNamespace(
        SessionOptions=FakeSessionOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="ORT_SEQUENTIAL"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="ORT_ENABLE_ALL"),
        InferenceSession=MagicMock(return_value=fake_session),
    )

    monkeypatch.setattr(feature_extractor, "_onnx_session", None)
    monkeypatch.setattr(feature_extractor, "_model_loaded", False)
    monkeypatch.setattr(feature_extractor, "_model_loading", False)
    monkeypatch.setattr(feature_extractor, "_model_error", None)
    monkeypatch.setattr("os.path.exists", lambda p: True)

    with patch.dict("sys.modules", {"onnxruntime": fake_ort}):
        s1 = feature_extractor.load_onnx_model()
        s2 = feature_extractor.load_onnx_model()

    assert s1 is fake_session
    assert s2 is fake_session
    assert fake_ort.InferenceSession.call_count == 1
    opts = captured["opts"]
    assert opts.intra_op_num_threads == 1
    assert opts.inter_op_num_threads == 1
    assert opts.enable_cpu_mem_arena is False
    assert opts.enable_mem_pattern is False


def test_system_health_exposes_onnx_session_settings(monkeypatch):
    monkeypatch.setattr("app.main.check_db_health", lambda *a, **k: False)
    health = _get_detailed_health_data(db=None)
    onnx_cfg = health["onnx_session_settings"]
    assert onnx_cfg["max_sessions"] == 1
    assert onnx_cfg["intra_op_num_threads"] == 1
    assert onnx_cfg["inter_op_num_threads"] == 1
    assert onnx_cfg["enable_cpu_mem_arena"] is False
    assert onnx_cfg["enable_mem_pattern"] is False
