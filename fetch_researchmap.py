import json
import urllib.request
import urllib.parse

PERMALINK = "t_yamane"
API_BASE = f"https://api.researchmap.jp/{PERMALINK}"


def fetch_items(endpoint, params=None):
    if params is None:
        params = {}
    base_params = {
        "format": "json",
        "limit": 1000,
        "start": 1,
        "sort": "newest",
        "from_date": "2000",
    }
    base_params.update(params)

    query = urllib.parse.urlencode(base_params)
    url = f"{API_BASE}/{endpoint}?{query}"

    print(f"fetching: {url}")
    with urllib.request.urlopen(url) as res:
        text = res.read().decode("utf-8")
        data = json.loads(text)

    items = []

    # いくつかのパターンに対応して items を取り出す
    if isinstance(data, dict):
        if "@graph" in data:
            graph = data.get("@graph") or []
            if isinstance(graph, list) and graph:
                node = graph[0]
                items = node.get("items", [])
        elif "items" in data and isinstance(data["items"], list):
            # トップレベルに直接 items があるパターン
            items = data["items"]
        else:
            # デバッグ用にキーだけ出しておく
            print(f"  dict keys for {endpoint}: {list(data.keys())}")
    elif isinstance(data, list):
        # いきなり配列で返ってくるパターン
        items = data

    print(f"  -> {len(items)} items")
    return items


def main():
    data = {
        "published_papers": fetch_items("published_papers"),
        "research_projects": fetch_items("research_projects"),
        "awards": fetch_items("awards"),
    }

    with open("researchmap_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("saved: researchmap_data.json")


if __name__ == "__main__":
    main()
