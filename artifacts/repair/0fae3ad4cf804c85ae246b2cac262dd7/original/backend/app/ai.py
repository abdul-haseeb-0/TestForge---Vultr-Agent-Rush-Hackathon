import json
from .config import settings

def diagnose(evidence, report):
    cfg=settings()
    if not cfg.vultr_inference_api_key: return None
    from openai import OpenAI
    client=OpenAI(base_url=cfg.vultr_inference_base_url,api_key=cfg.vultr_inference_api_key,timeout=40,max_retries=1)
    system=("You are TestForge, a senior web QA engineer. Analyze only supplied browser evidence. "
      "Do not invent issues, remove observations, change severity, change evidence, or claim tests passed without evidence. "
      "Return JSON with a short summary and findings in exactly the same order as the deterministic findings. "
      "For each finding provide only description and recommendation. If evidence is inconclusive, say so.")
    r=client.chat.completions.create(model=cfg.vultr_inference_model,messages=[{"role":"system","content":system},{"role":"user","content":json.dumps({"evidence":evidence,"deterministic_report":report})[:22000]}],temperature=0.1,max_completion_tokens=1600,response_format={"type":"json_object"})
    return json.loads(r.choices[0].message.content or "{}")
