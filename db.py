import os, json, pymysql
from dotenv import load_dotenv
load_dotenv()

def conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=True)


def q(sql, args=None):
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args or ())
        return cur.fetchall()

def save_proposal(product_id, ptype, payload, product_updated_at, model, note=None):

    print("save_proposal", product_id, ptype, payload, product_updated_at, model, note)
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO agent_proposals
               (product_id,type,payload,product_updated_at,model,note,agent_user_id,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
            (product_id, ptype, json.dumps(payload, ensure_ascii=False),
             product_updated_at, model, note, int(os.getenv("AGENT_USER_ID"))))