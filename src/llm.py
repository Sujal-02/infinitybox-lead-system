from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import budget, cfg
from .cache import cached, retry

def models() -> list[str]:
    """Primary model first, then fallbacks (a retired or throttled model must not stop the run)."""
    return [m.strip() for m in cfg.env("GEMINI_MODELS", cfg.env("GEMINI_MODEL", "gemini-3.8-flash") + ",gemini-3.7-flash,gemini-flash-latest").split(",")]


def model() -> str:
    return models()[0]


FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


TRANSIENT = ("429", "500", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "PERMISSION_DENIED")  # 403 has been seen to clear on its own


def _gemini(prompt: str, schema: type[BaseModel]) -> str:
    """Try each model in GEMINI_MODELS in turn; each gets one short retry on transient errors. Charged once per call."""
    import time
    from google import genai
    budget.charge("gemini", 1)
    client = genai.Client(api_key=cfg.env("GEMINI_API_KEY"))
    conf = {"response_mime_type": "application/json", "response_schema": schema, "temperature": 0.2}
    err = None
    for m in models():
        for attempt in range(2):
            try:
                return client.models.generate_content(model=m, contents=prompt, config=conf).text
            except Exception as e:
                err = e
                if not any(t in str(e) for t in TRANSIENT) or attempt == 1:
                    break
                time.sleep(6)
    raise err


def ask(prompt: str, schema: type[BaseModel], tag: str = "", check=None) -> BaseModel:
    """The only LLM entry point (swap Gemini for Claude here). Validates output; one retry with the error."""
    if cfg.dry:
        return schema.model_validate_json((FIXTURES / f"llm_{tag}.json").read_text("utf-8"))
    err = ""
    for _ in range(2):
        p = prompt + err
        raw = cached("llm", [model(), p], lambda: _gemini(p, schema))
        try:
            obj = schema.model_validate_json(raw)
            if check:
                check(obj)
            return obj
        except (ValidationError, ValueError) as e:
            err = f"\n\nYour previous output was invalid: {e}\nReturn corrected JSON only."
    raise ValueError(f"LLM output invalid after retry: {err[:300]}")
