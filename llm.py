import os, io, re, json, time, base64, httpx
from openai import OpenAI, RateLimitError, APIError, APIConnectionError
from PIL import Image

def _providers():
    ps = []
    if os.getenv("GROQ_API_KEY"):
        ps.append(dict(name="groq", json_mode=True,
            client=OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"),
            vision=os.getenv("GROQ_VISION_MODEL"), text=os.getenv("GROQ_TEXT_MODEL")))
    if os.getenv("OPENROUTER_API_KEY"):
        ps.append(dict(name="openrouter", json_mode=False,
            client=OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1"),
            vision=os.getenv("OR_VISION_MODEL"), text=os.getenv("OR_TEXT_MODEL")))
    return ps

def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))

def chat_json(messages, kind="text", temperature=0.3):
    """returns (parsed_json, 'provider/model')"""
    last_err = None
    for p in _providers():
        model = p[kind]
        if not model: continue
        for attempt in range(2):
            try:
                kw = dict(model=model, messages=messages, temperature=temperature, max_tokens=4000)
                if p["json_mode"]: kw["response_format"] = {"type": "json_object"}
                r = p["client"].chat.completions.create(**kw)
                return extract_json(r.choices[0].message.content), f'{p["name"]}/{model}'
            except RateLimitError as e:
                last_err = e; time.sleep(5); break      # برو سراغ provider بعدی
            except (APIError, APIConnectionError, json.JSONDecodeError, AttributeError) as e:
                last_err = e; time.sleep(2)
    raise RuntimeError(f"all providers failed: {last_err}")

def image_data_url(path_or_rel):
    """تصویر را کوچک می‌کند تا هم سریع باشد هم در سقف حجم API بماند"""
    base = os.getenv("IMAGE_BASE_URL")
    url = path_or_rel if path_or_rel.startswith("http") else base + path_or_rel.lstrip("/")
    print("image_data_url", url)
    raw = httpx.get(url, timeout=30).content
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()