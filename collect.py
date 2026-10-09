"""목록 수집기. 새 글을 가져와 data.json 으로 저장한다 (이미 모은 글은 건너뜀).

대상 계정은 환경변수 ACCOUNTS 또는 accounts.txt 에서 읽는다 (코드에 두지 않음).

  python collect.py              # 지난번 이후 새 글만
  python collect.py --pages 40   # 페이지 수 지정

글 형식:
  <날짜6자리> <이름> 옷장
  👕
  🔗링크
  🔎 브랜드
  - ✧ 상품명
  🛒 가격: 135,380원
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

import hashlib, os

TAIL = "".join(map(chr, [0xC190, 0xBBFC, 0xC218]))  # 제목 끝말
_f = Path(__file__).with_name("accounts.txt")
_raw = os.environ.get("ACCOUNTS") or (_f.read_text(encoding="utf8") if _f.exists() else "")
ACCOUNTS = [a.strip() for a in _raw.replace("\n", ",").split(",") if a.strip()]
OUT = Path(__file__).with_name("data.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# 이모지 -> 아이템 종류
CATS = {"👕": "상의", "👚": "상의", "🎽": "상의", "🥼": "아우터", "🧥": "아우터", "🧶": "상의",
        "👖": "하의", "🩳": "하의", "🩲": "하의", "👗": "원피스", "👜": "가방", "👝": "가방", "🎒": "가방",
        "👟": "신발", "👠": "신발", "👢": "신발", "🥿": "신발", "🧢": "모자", "👒": "모자", "🧣": "소품",
        "🧦": "소품", "👓": "소품", "🕶": "소품", "💍": "액세서리", "📿": "액세서리", "⌚": "액세서리",
        "📱": "전자기기", "🎧": "전자기기", "💻": "전자기기", "🍵": "기타", "🧺": "기타"}
# 이모지가 없을 때 상품명으로 추정
KW = [("액세서리", r"necklace|ring\b|earring|bracelet|목걸이|반지|귀걸이|팔찌|이어링|네크리스|brooch|브로치|헤어핀|머리핀|벨트|belt"),
      ("가방", r"bag|백|토트|숄더|크로스|클러치|파우치"), ("신발", r"shoe|sneaker|boot|슈즈|스니커|로퍼|부츠|힐|샌들|플랫|mule|뮬|zoom|줌 "),
      ("모자", r"cap|hat|캡|모자|비니|햇"), ("하의", r"pants|skirt|denim|jean|short|슬랙스|팬츠|스커트|데님|숏|쇼츠|레깅스|트레이닝"),
      ("아우터", r"jacket|coat|jumper|parka|cardigan|자켓|재킷|코트|점퍼|가디건|패딩|트렌치|블레이저|베스트"),
      ("원피스", r"dress|one piece|onepiece|romper|원피스|드레스|롬퍼"),
      ("상의", r"top|tee|shirt|knit|hood|sweat|blouse|tank|sleeve|zip-up|zip up|티셔츠|셔츠|니트|후드|맨투맨|블라우스|나시|탑|스웨터|슬리브|긴팔|반팔")]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf8"))


def guess_cat(name):
    low = name.lower()
    for cat, pat in KW:
        if re.search(pat, low):
            return cat
    return "기타"


def parse_items(text):
    """🔎 브랜드 / - ✧ 상품명 / 🛒 가격 블록을 아이템으로. 앞쪽 🔗 링크와 종류 이모지를 연결."""
    items = []
    cur = None  # 작성자는 이모지를 그룹 맨 앞에 한 번만 붙이므로, 다음 이모지가 나올 때까지 이어받는다
    for m in re.finditer(r"🔎\s*(?P<brand>[^\n]+)\n\s*-?\s*✧?\s*(?P<name>[^\n]+)\n\s*🛒\s*가격\s*:\s*(?P<price>[\d,]+)\s*원", text):
        # 이 블록 시작 지점 = 직전 아이템 끝 이후 ~ 현재 🔎 전까지
        start = items[-1]["_end"] if items else 0
        seg = text[start:m.start()]
        shop = [u for u in re.findall(r"https?://\S+", seg) if not re.match(r"https?://(?:www\.)?(?:x|twitter)\.com/|https?://t\.co/", u)]
        link = (shop or [""])[-1]
        found = [CATS[ch] for ch in seg if ch in CATS]
        if found:
            cur = found[-1]
        items.append({
            "cat": cur or guess_cat(m["name"]),
            "brand": m["brand"].strip(),
            "name": re.sub(r"\s+", " ", m["name"]).strip(),
            "price": int(m["price"].replace(",", "")),
            "link": link,
            "_end": m.end(),
        })
    for i in items:
        i.pop("_end")
    return items


def dedupe(items):
    """같은 상품이 여러 쇼핑몰로 올라오면 가장 싼 것만 남긴다. 스커트/바지는 이모지와 상관없이 하의."""
    best = {}
    for i in items:
        if re.search(r"skirt|스커트|pants|팬츠|슬랙스|데님|jean|short", i["name"].lower()):
            i["cat"] = "하의"
        k = (i["brand"], i["name"])
        if k not in best or i["price"] < best[k]["price"]:
            best[k] = i
    return list(best.values())


def media_urls(media):
    """사진은 원본 URL, 영상/움짤은 썸네일."""
    out = []
    for m in (media or {}).get("all", []):
        u = m.get("url") if m.get("type") == "photo" else m.get("thumbnail_url")
        if u:
            out.append(u)
    return out


def to_coordi(acc, t):
    items = dedupe(parse_items(t["text"]))
    if not items:
        return None
    h = re.search(r"(\d{6})\s+(.+?)\s+(?:옷장|" + TAIL + ")", t["text"])
    q = t.get("quote") or {}
    return {
        "id": t["id"], "created": t.get("created_at", ""),
        "date": h[1] if h else "", "who": h[2].strip() if h else "",
        # 대표 사진: 인용한 원본 트윗의 연예인 사진. 없으면 코디 트윗 자체 사진
        "photos": media_urls(q.get("media")) or media_urls(t.get("media")),
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser()
    # 지난번에 어디까지 모았는지(newest) 기억해서 거기까지 알아서 거슬러 올라간다.
    # 컴퓨터를 며칠 꺼 둬도 그 사이 글을 빠짐없이 가져온다. (무료 경로 한도: 최신 약 800개)
    ap.add_argument("--pages", type=int, default=60, help="최대 페이지 수(1페이지=20개)")
    pages = ap.parse_args().pages
    data = json.loads(OUT.read_text(encoding="utf8")) if OUT.exists() else {"coordis": []}
    seen = {c["id"] for c in data["coordis"]}
    newest = data.setdefault("newest", {})
    added = 0
    for acc in ACCOUNTS:
        cursor, top, reached = None, 0, False
        key = hashlib.sha1(acc.encode()).hexdigest()[:10]  # 계정 이름을 그대로 저장하지 않는다
        prev = int(newest.get(key, 0))
        for _ in range(pages):
            url = f"https://api.fxtwitter.com/2/profile/{acc}/statuses?count=20"
            if cursor:
                url += "&cursor=" + urllib.parse.quote(cursor)
            try:
                page = get(url)
            except Exception as e:
                print("페이지 실패:", e, file=sys.stderr)
                break
            for t in page.get("results", []):
                top = max(top, int(t["id"]))
                if int(t["id"]) <= prev:
                    reached = True  # 지난번에 이미 본 지점
                    continue
                if t["id"] in seen:
                    continue
                seen.add(t["id"])
                c = to_coordi(acc, t)
                if c:
                    data["coordis"].append(c)
                    added += 1
            cursor = (page.get("cursor") or {}).get("bottom")
            if reached or not cursor or not page.get("results"):
                # 끝까지 정상적으로 거슬러 올라갔을 때만 기준점을 올린다 (중간 실패 시 빈틈 방지)
                if top:
                    newest[key] = str(max(top, prev))
                break
            time.sleep(0.6)
    data["coordis"].sort(key=lambda c: int(c["id"]), reverse=True)
    data["updated"] = time.strftime("%Y-%m-%d %H:%M")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    # 파일을 더블클릭해서 열어도 보이도록 같은 데이터를 스크립트로도 저장
    OUT.with_suffix(".js").write_text("window.DATA=" + json.dumps(data, ensure_ascii=False) + ";", encoding="utf8")
    n_items = sum(len(c["items"]) for c in data["coordis"])
    cheap = sum(i["price"] <= 50000 for c in data["coordis"] for i in c["items"])
    print(f"새 코디 {added}개 / 전체 {len(data['coordis'])}개, 아이템 {n_items}개 중 5만원 이하 {cheap}개")


if __name__ == "__main__":
    main()
