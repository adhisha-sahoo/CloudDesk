import json

import httpx
import pytest
from pydantic import ValidationError

from clouddesk.assistant import Assistant
from clouddesk.config import Settings


def test_retrieved_steps_are_from_cited_runbooks(settings):
    assistant = Assistant(settings)
    answer = assistant.ask("My S3 sandbox returns AccessDenied and access is denied")
    assert answer["mode"] == "extractive"
    assert any(source["id"] == "s3-access" for source in answer["sources"])
    known = {step["id"]: step["text"] for doc in assistant.documents for step in doc["steps"]}
    assert all(known[step["id"]] == step["text"] for step in answer["steps"])


@pytest.mark.parametrize(
    "question",
    ["What is tomorrow's weather?", "Write a poem about cats", "Transfer money to my account"],
)
def test_abstains_without_evidence(settings, question):
    answer = Assistant(settings).ask(question)
    assert answer["mode"] == "abstained" and answer["steps"] == []


def test_ollama_contract_and_no_generated_step_text(settings):
    settings.assistant_mode = "ollama"

    def handler(request):
        assert request.url.host == "127.0.0.1"
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert "tools" not in payload
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"step_ids": ["s3-access-2"]})}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        answer = Assistant(settings, client).ask("My S3 access is denied")
    assert answer["mode"] == "ollama"
    assert answer["steps"][0]["id"] == "s3-access-2"


@pytest.mark.parametrize(
    "content", ['{"step_ids":["invented-step"]}', '{"step_ids":[]}', "not json"]
)
def test_invalid_model_output_falls_back(settings, content):
    settings.assistant_mode = "ollama"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"message": {"content": content}})
        )
    ) as client:
        answer = Assistant(settings, client).ask("My S3 access is denied")
    assert answer["mode"] == "extractive_fallback"
    assert answer["steps"]


def test_unavailable_model_falls_back(settings):
    settings.assistant_mode = "ollama"
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        assert (
            Assistant(settings, client).ask("Jenkins build failed")["mode"] == "extractive_fallback"
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("aws_endpoint", "https://s3.amazonaws.com"),
        ("aws_endpoint", "http://evil.example:5000"),
        ("ollama_url", "https://api.openai.com"),
        ("jenkins_url", "http://localhost.evil.example"),
        ("servicenow_url", "http://dev.service-now.com"),
        ("jenkins_job", "../some-job"),
    ],
)
def test_free_endpoints_and_safe_job_names_enforced(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
