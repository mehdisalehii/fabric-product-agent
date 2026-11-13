import os, re, html
from db import q, save_proposal
from llm import chat_json, image_data_url

# ---------- ویژگی‌ها ----------

def allowed_attributes(category_id):
    # فقط ویژگی‌های همان دسته‌بندی؛ ویژگی‌های variation (سایز/رنگ با قیمت و موجودی) دست‌نخورده می‌ماند
    return q("""SELECT a.id, a.name FROM attribute_category ac
                JOIN attributes a ON a.id = ac.attribute_id
                WHERE ac.category_id=%s AND ac.is_variation=0 AND a.is_active=1""", (category_id,))

def products_for_attributes(limit):
    return q("""SELECT p.id, p.name, p.primary_image, p.category_id, p.updated_at, c.name AS category
                FROM products p JOIN categories c ON c.id = p.category_id
                WHERE p.is_active=1 AND p.primary_image IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM agent_proposals ap
                                  WHERE ap.product_id=p.id AND ap.type='attributes'
                                    AND (ap.status='pending' OR ap.status='rejected'))
                ORDER BY p.id LIMIT %s""", (limit,))
def suggestion_exists(category_id: int, name: str) -> bool:
    rows = q(
        """SELECT 1 FROM agent_proposals
           WHERE type='new_attribute' AND status IN ('pending','rejected')
             AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.name')) = %s
             AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.category_id')) AS UNSIGNED) = %s
           LIMIT 1""",
        (name, category_id),
    )
    return bool(rows)

def run_attributes(p, update_existing=False):
    allowed = allowed_attributes(p["category_id"])
    if not allowed:
        return "no-attributes-for-category"
    current = {r["attribute_id"]: r["value"] for r in q(
        "SELECT attribute_id, value FROM product_attributes WHERE product_id=%s AND is_active=1", (p["id"],))}

    targets = [a for a in allowed if update_existing or not current.get(a["id"])]
    if not targets:
        return "nothing-missing"

    attr_list = "\n".join(f'- id={a["id"]} | {a["name"]} | مقدار فعلی: {current.get(a["id"]) or "ندارد"}' for a in targets)
    prompt = f"""تو یک کارشناس محتوای فروشگاه آنلاین پوشاک زنانه هستی.
محصول: «{p["name"]}» از دسته «{p["category"]}».
با نگاه به تصویر، مقدار ویژگی‌های زیر را پر کن.
قوانین:
- فقط ویژگی‌های همین لیست؛ هیچ ویژگی دیگری اضافه نکن.
- اگر از روی تصویر و نام محصول مطمئن نیستی، value را null بگذار. حدس نزن (مثلاً جنس دقیق، ابعاد، برند را از ظاهر حدس نزن).
- مقدارها فارسی،خیلی کوتاه و دقیق باشند.
- اگر فکر می‌کنی یک ویژگی مهم برای این دسته در لیست نیست، در missing_attribute_suggestions فقط نامش و دلیلش را بنویس.
ویژگی‌ها:
{attr_list}

فقط JSON خالص بده:
{{"attributes":[{{"attribute_id":int,"value":str|null,"confidence":0.0-1.0}}],
 "missing_attribute_suggestions":[{{"name":str,"reason":str}}]}}"""

    data, model = chat_json([{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_url(p["primary_image"])}}]}], kind="vision")

    allowed_ids = {a["id"] for a in targets}
    names = {a["id"]: a["name"] for a in allowed}
    items = []
    for it in data.get("attributes", []):
        aid, val, conf = it.get("attribute_id"), it.get("value"), float(it.get("confidence") or 0)
        if aid not in allowed_ids or not val or not isinstance(val, str): continue   # whitelist
        val = val.strip()[:100]
        if conf < 0.6 or val == current.get(aid): continue
        items.append(dict(attribute_id=aid, name=names[aid], old=current.get(aid), new=val, confidence=conf))

    if items:
        save_proposal(p["id"], "attributes", {"items": items}, p["updated_at"], model)

    for s in data.get("missing_attribute_suggestions", [])[:3]:
        if s.get("name") and not suggestion_exists(p["category_id"], s["name"]):
            save_proposal(p["id"], "new_attribute",
                          {"name": s["name"], "reason": s.get("reason", ""), "category_id": p["category_id"]},
                          p["updated_at"], model)
    return f"{len(items)} items"

# ---------- مقاله ----------

def shingles(text, n=5):
    w = re.sub(r"<[^>]+>", " ", text).split()
    return {" ".join(w[i:i+n]) for i in range(max(0, len(w) - n))}

def similarity(a, b):
    A, B = shingles(a), shingles(b)
    return len(A & B) / len(A | B) if A | B else 0

def products_for_article(limit):
    return q("""SELECT p.id, p.name, p.slug, p.details, p.category_id, p.updated_at,
                       c.name AS category, c.slug AS category_slug, b.name AS brand
                FROM products p
                JOIN categories c ON c.id=p.category_id
                LEFT JOIN brands b ON b.id=p.brand_id
                WHERE p.is_active=1 AND (p.content IS NULL OR p.content='')
                  AND NOT EXISTS (SELECT 1 FROM agent_proposals ap
                                  WHERE ap.product_id=p.id AND ap.type='article'
                                    AND ap.status IN ('pending','rejected'))
                ORDER BY p.id LIMIT %s""", (limit,))

def build_link_candidates(p):
    site = os.getenv("SITE_URL")
    links = [dict(title=p["category"], url=os.getenv("CATEGORY_URL").format(site=site, slug=p["category_slug"]))]
    for r in q("""SELECT name, slug FROM products WHERE category_id=%s AND id<>%s AND is_active=1
                  ORDER BY RAND() LIMIT 5""", (p["category_id"], p["id"])):
        links.append(dict(title=r["name"], url=os.getenv("PRODUCT_URL").format(site=site, slug=r["slug"])))
    return links

def sanitize(content_html, links):
    ok = {l["url"] for l in links}
    # لینک‌هایی که از لیست مجاز نیستند حذف می‌شوند و فقط متنشان می‌ماند
    def fix(m):
        return m.group(0) if m.group(1) in ok else m.group(2)
    content_html = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', fix, content_html, flags=re.S)
    content_html = re.sub(r"<(script|style|iframe)[^>]*>.*?</\1>", "", content_html, flags=re.S | re.I)
    return content_html

def run_article(p):
    attrs = q("""SELECT a.name, pa.value FROM product_attributes pa JOIN attributes a ON a.id=pa.attribute_id
                 WHERE pa.product_id=%s AND pa.is_active=1""", (p["id"],))
    links = build_link_candidates(p)
    peers = [r["content"] for r in q(
        "SELECT content FROM products WHERE category_id=%s AND content IS NOT NULL AND content<>'' ORDER BY id DESC LIMIT 15",
        (p["category_id"],))]

    attr_txt = "\n".join(f'- {a["name"]}: {a["value"]}' for a in attrs) or "ندارد"
    link_txt = "\n".join(f'- «{l["title"]}» → {l["url"]}' for l in links)
    prompt = f"""یک مقاله فروشگاهی یونیک و کامل به فارسی برای این محصول بنویس.
محصول: {p["name"]} | دسته: {p["category"]} | برند: {p["brand"] or "نامشخص"}
توضیح موجود: {p["details"] or "ندارد"}
ویژگی‌های ثبت‌شده:
{attr_txt}

قوانین:
- فقط از اطلاعات بالا استفاده کن. جنس، ابعاد، گارانتی، قیمت، تخفیف یا ادعای ساختگی نیاور.
- ساختار: مقدمه، معرفی محصول، ویژگی‌ها و مزایا، نحوه ست و استفاده، نکات نگهداری، جمع‌بندی. حدود ۶۰۰ تا ۸۰۰ کلمه.
- خروجی HTML ساده با h2، h3، p، ul، li.
- ۲ تا ۴ لینک داخلی طبیعی، فقط از این لیست و دقیقاً با همین URL:
{link_txt}
- لحن طبیعی و انسانی؛ از جمله‌های کلیشه‌ای تکراری پرهیز کن.
- seo_title حداکثر ۶۰ کاراکتر و seo_description حداکثر ۱۶۰ کاراکتر.

فقط JSON خالص: {{"seo_title":str,"seo_description":str,"content":str}}"""

    for attempt, temp in enumerate([0.7, 0.9]):
        data, model = chat_json([{"role": "user", "content": prompt}], kind="text", temperature=temp)
        content = sanitize(data["content"], links)
        sim = max((similarity(content, other) for other in peers), default=0)
        if sim < 0.25 and len(content) > 1500:
            save_proposal(p["id"], "article", dict(
                seo_title=data["seo_title"][:60], seo_description=data["seo_description"][:160],
                content=content, similarity=round(sim, 2)), p["updated_at"], model)
            return "ok"
    return "too-similar-or-short"