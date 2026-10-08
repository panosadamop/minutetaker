"""LLM adapters: Claude (default), OpenAI, Ollama, and a deterministic mock."""
from __future__ import annotations

import json
import re

import httpx

from .config import Config


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (tolerates ```json fences)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError("model did not return JSON")
    return json.loads(text[start: end + 1])


class Claude:
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def complete(self, system: str, user: str, max_tokens: int = 8000) -> str:
        key = self.cfg.get_secret("anthropic_api_key")
        if not key:
            raise LLMError("Anthropic API key not set (Settings → API keys)")
        r = httpx.post(self.URL, timeout=600, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": self.cfg.settings.claude_model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise LLMError(f"Claude API error {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


class OpenAI:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def complete(self, system: str, user: str, max_tokens: int = 8000) -> str:
        key = self.cfg.get_secret("openai_api_key")
        if not key:
            raise LLMError("OpenAI API key not set (Settings → API keys)")
        r = httpx.post(self.URL, timeout=600, headers={"Authorization": f"Bearer {key}"},
                       json={"model": self.cfg.settings.openai_model, "max_tokens": max_tokens,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system},
                                          {"role": "user", "content": user}]})
        if r.status_code >= 400:
            raise LLMError(f"OpenAI API error {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]


class Ollama:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def complete(self, system: str, user: str, max_tokens: int = 8000) -> str:
        s = self.cfg.settings
        try:
            r = httpx.post(f"{s.ollama_url.rstrip('/')}/api/chat", timeout=1800,
                           json={"model": s.ollama_model, "stream": False, "format": "json",
                                 "options": {"num_predict": max_tokens, "num_ctx": 32768},
                                 "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": user}]})
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach Ollama at {s.ollama_url} — is it running?") from e
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json()["message"]["content"]


class Mock:
    """Offline heuristic 'LLM' – lets the whole pipeline run without keys (tests, demos)."""

    DECISION = re.compile(r"\b(decid|agree|approv|we will go with|final)\w*|αποφασ|συμφων|εγκρ", re.I)
    ACTION = re.compile(r"\b(will|i'll|we'll|to do|action|by (monday|tuesday|wednesday|thursday|friday|next week|tomorrow))\b|θα ", re.I)
    ISSUE = re.compile(r"\b(risk|issue|problem|concern|blocker|unclear)\b|κίνδυν|πρόβλημα|θέμα", re.I)
    DUE = re.compile(r"\b(by|until|before)\s+([A-Z]?\w+(?:\s\d{1,2})?)", re.I)

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def complete(self, system: str, user: str, max_tokens: int = 8000) -> str:
        if "PARTIAL MINUTES (JSON):" in user:  # reduce step of map-reduce
            parts = json.loads(user.split("PARTIAL MINUTES (JSON):", 1)[1])
            merged: dict = {}
            for p in parts:
                for k, v in p.items():
                    if isinstance(v, list):
                        merged.setdefault(k, [])
                        merged[k] += [x for x in v if x not in merged[k]]
                    elif v and not merged.get(k):
                        merged[k] = v
            return json.dumps(merged, ensure_ascii=False)
        lines = re.findall(r"^\[([\d:\- ]+)\] ([^:]+): (.+)$", user, re.M)
        speakers = list(dict.fromkeys(s for _, s, _ in lines))
        decisions, actions, issues = [], [], []
        for _, spk, text in lines:
            if self.DECISION.search(text):
                decisions.append(text.strip())
            elif self.ACTION.search(text):
                due = self.DUE.search(text)
                actions.append({"task": text.strip(), "owner": spk, "due": due.group(2) if due else ""})
            if self.ISSUE.search(text):
                issues.append(text.strip())
        texts = [t for _, _, t in lines]
        chunk = max(1, len(texts) // 3 or 1)
        discussion = [{"topic": f"Topic {i // chunk + 1}", "points": texts[i:i + chunk][:5]}
                      for i in range(0, len(texts), chunk)][:3]
        tldr = (decisions[:2] + [a["task"] for a in actions[:2]] + texts[:1])[:4] or ["No content."]
        result = {
            "title": "", "attendees": [{"name": s, "role": ""} for s in speakers],
            "agenda": [d["topic"] for d in discussion], "discussion": discussion,
            "decisions": decisions, "action_items": actions, "open_issues": issues,
            "next_meeting": "", "tldr": tldr,
            "executive_summary": f"{len(speakers)} participant(s) discussed {len(discussion)} topic(s); "
                                 f"{len(decisions)} decision(s) and {len(actions)} action item(s) were recorded.",
        }
        if "ONLY_KEY=" in system:
            key = system.split("ONLY_KEY=")[1].split()[0]
            result = {key: result.get(key)}
        return json.dumps(result, ensure_ascii=False)


def get_llm(cfg: Config):
    return {"claude": Claude, "openai": OpenAI, "ollama": Ollama, "mock": Mock}[cfg.settings.llm_provider](cfg)
