"""Compatibility tests for model router client exports."""

from chintu_backend.core import model_router
from chintu_backend.core import model_clients


def test_model_router_reexports_cloud_clients_for_legacy_imports():
    assert model_router.GroqClient is model_clients.GroqClient
    assert model_router.GeminiClient is model_clients.GeminiClient
    assert model_router.DeepSeekClient is model_clients.DeepSeekClient
    assert model_router.NvidiaClient is model_clients.NvidiaClient
