import time
import traceback

import jobs
from log import log

PAUSE_SECONDS = {"attributes": 4, "articles": 6}  # رعایت rate limit مدل‌های رایگان


def run_job(job: str, limit: int, update: bool = False) -> dict:
    """یک دسته محصول را پردازش می‌کند و آمار برمی‌گرداند."""
    if job == "attributes":
        products = jobs.products_for_attributes(limit)
        handler = lambda product: jobs.run_attributes(product, update)
    elif job == "articles":
        products = jobs.products_for_article(limit)
        handler = jobs.run_article
    else:
        raise ValueError(f"job ناشناخته: {job}")

    log(f"شروع job={job} limit={limit}: {len(products)} محصول پیدا شد")
    stats = {"found": len(products), "ok": 0, "failed": 0, "results": []}

    for index, product in enumerate(products, 1):
        log(f"--- [{index}/{len(products)}] محصول {product['id']}: {product['name']}")
        try:
            result = handler(product)
            stats["ok"] += 1
        except Exception as error:
            traceback.print_exc()
            result = f"error: {error}"
            stats["failed"] += 1
        stats["results"].append({"product_id": product["id"], "result": str(result)})
        if index < len(products):
            time.sleep(PAUSE_SECONDS[job])

    log(f"success: {stats['ok']} , unsuccess: {stats['failed']}")
    return stats