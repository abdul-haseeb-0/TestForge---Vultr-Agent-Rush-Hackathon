import json, re
from .config import settings

def _client_cfg():
    from .aikey import get_ai  # late import: aikey imports this module's chat()
    return get_ai()

def chat(ai, messages, max_tokens=1600, timeout=40, retries=1, json_mode=False, temperature=None):
    """Call any OpenAI-compatible endpoint with the user's key. Providers differ on
    max_completion_tokens vs max_tokens and on response_format, so degrade gracefully."""
    from openai import OpenAI, BadRequestError
    client = OpenAI(base_url=ai["base_url"], api_key=ai["key"], timeout=timeout, max_retries=retries)
    base = dict(model=ai["model"], messages=messages)
    if temperature is not None: base["temperature"] = temperature
    attempts = [dict(max_completion_tokens=max_tokens), dict(max_tokens=max_tokens)]
    last = None
    for tok in attempts:
        for use_json in ([True, False] if json_mode else [False]):
            kw = {**base, **tok}
            if use_json: kw["response_format"] = {"type": "json_object"}
            try:
                return client.chat.completions.create(**kw).choices[0].message.content or ""
            except BadRequestError as e:
                last = e; continue
    raise last

def parse_json(text):
    """Tolerant JSON extraction (some models wrap JSON in ``` fences or add prose)."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try: return json.loads(t or "{}")
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m: return json.loads(m.group(0))
        raise

def diagnose(evidence, report):
    ai = _client_cfg()
    if not ai: return None
    system = ("You are TestForge, a senior web QA engineer. Analyze only supplied browser evidence. "
      "Do not invent issues, remove observations, change severity, change evidence, or claim tests passed without evidence. "
      "Return JSON with a short summary and findings in exactly the same order as the deterministic findings. "
      "For each finding provide only description and recommendation. If evidence is inconclusive, say so.")
    # Trim whole fields instead of slicing the JSON string (slicing produced invalid JSON for big reports).
    slim = {k: (v[:20] if isinstance(v, list) else v) for k, v in evidence.items()}
    user = json.dumps({"evidence": slim, "deterministic_report": report}, default=str)
    if len(user) > 22000: user = json.dumps({"deterministic_report": report}, default=str)[:22000]
    return parse_json(chat(ai, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=1600, timeout=40, json_mode=True, temperature=0.1))
