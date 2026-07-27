"""T-029: the offline profile runs a typed case end to end against local Ollama.

Offline selection itself is covered in test_router.py; here we prove the whole
CLI case loop completes with the offline flag set and every turn served locally,
cloud never touched. The live-Ollama smoke is manual (see docs/offline-profile.md).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.cli import run_case
from app.config import ProviderConfig
from app.engine.case_flow import CaseFlow
from app.engine.content_models import Case
from app.providers.llm_client import ChatClient
from app.providers.router import Router

FIXT = Path(__file__).parent / "fixtures" / "content" / "valid"
SSE = (
    b'data: {"choices":[{"delta":{"content":"Local"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" reply"}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\n\n"
)
PROVIDERS = [
    ProviderConfig(name="groq", base_url="http://g/v1", model="m", api_key_env="K"),
    ProviderConfig(name="ollama", base_url="http://127.0.0.1:11434/v1", model="qwen"),
]


def _case() -> Case:
    return Case.model_validate(
        json.loads((FIXT / "cases" / "case-cement-profitability.json").read_text())
    )


def _ok(request):
    return httpx.Response(200, content=SSE)


def _reader(lines):
    it = iter(lines)
    return lambda: next(it)


class Sink:
    def __init__(self):
        self.buf: list[str] = []

    def __call__(self, s: str) -> None:
        self.buf.append(s)

    @property
    def text(self) -> str:
        return "".join(self.buf)


def test_offline_profile_runs_typed_case_end_to_end_with_ollama():
    served: list[str] = []

    def factory(p):
        served.append(p.name)
        return ChatClient(p, client=httpx.Client(transport=httpx.MockTransport(_ok)))

    cfg = SimpleNamespace(providers=PROVIDERS, offline=True, retry=None)
    router = Router(cfg, client_factory=factory)

    flow = CaseFlow(_case())  # standard: opening, structuring, analysis, synthesis
    out = Sink()
    run_case(
        flow,
        router.chat,
        _reader(["why did profit fall?", "/next", "/next", "/next", "/next"]),
        out,
    )

    assert flow.is_terminal
    assert "Local reply" in out.text.replace("  ", " ")
    assert set(served) == {"ollama"}  # every turn served locally; cloud untouched
