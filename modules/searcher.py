import json
import logging
import os
import time
from collections import Counter
from urllib.parse import urlparse

from dotenv import load_dotenv
from groq import Groq, RateLimitError
from tavily import TavilyClient

load_dotenv()

logger = logging.getLogger(__name__)


def _minimal_fallback():
    return {
        "website": None,
        "summary": "No public information found",
        "key_details": [],
    }


def _run_tavily_searches(org: str) -> list:
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    queries = [
        f"{org} Philippines mission programs",
        f"{org} Philippines contact team",
    ]
    results = []
    for query in queries:
        response = client.search(query, max_results=3)
        results.extend(response.get("results", []))
    return results


def _pick_website(results: list) -> str | None:
    domains = []
    for r in results:
        url = r.get("url", "")
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if domain:
                domains.append(domain)
        except Exception:
            continue

    if not domains:
        return None

    counts = Counter(domains)
    max_count = max(counts.values())
    top_domains = {d for d, c in counts.items() if c == max_count}
    for domain in domains:
        if domain in top_domains:
            return domain
    return None


def _summarise_with_groq(org: str, goal: str, results: list) -> dict | None:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    snippets = []
    for i, r in enumerate(results, 1):
        url = r.get("url", "")
        content = r.get("content", "")
        snippets.append(f"[{i}] {url}\n{content}")

    search_block = "\n\n".join(snippets)
    goal_line = f"Goal: {goal}\n\n" if goal else ""

    user_message = (
        f"Org: {org}\n"
        f"{goal_line}"
        f"Search results:\n---\n{search_block}\n---\n\n"
        'Return a JSON object with exactly these keys:\n'
        '- "summary": a 2-3 sentence description of what this organisation does\n'
        '- "key_details": a JSON array of strings, each a specific detail useful for '
        "achieving the goal above (programs, target communities, geography, recent "
        "initiatives, key contacts mentioned)\n\n"
        "Return only the JSON object. No explanation."
    )

    def _call():
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a research assistant. Return only valid JSON with no extra text.",
                },
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    try:
        return _call()
    except RateLimitError:
        logger.error("Groq rate limit hit, retrying after 5s")
        time.sleep(5)
        try:
            return _call()
        except Exception as e:
            logger.error("Groq retry failed: %s", e)
            return None
    except Exception as e:
        logger.error("Groq call failed: %s", e)
        return None


def search_org(org_name: str, goal: str = "") -> dict:
    try:
        results = _run_tavily_searches(org_name)
    except Exception as e:
        logger.error("Tavily search failed: %s", e)
        return _minimal_fallback()

    if not results:
        return _minimal_fallback()

    website = _pick_website(results)
    groq_result = _summarise_with_groq(org_name, goal, results)

    if groq_result is None:
        fallback = _minimal_fallback()
        fallback["website"] = website
        return fallback

    return {
        "website": website,
        "summary": groq_result.get("summary", ""),
        "key_details": groq_result.get("key_details", []),
    }


if __name__ == "__main__":
    import json as _json

    logging.basicConfig(level=logging.INFO)

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def check(label, passed):
        print(f"[{'PASS' if passed else 'FAIL'}] {label}")
        return passed

    with open(os.path.join(BASE, "data/inputs/test_org.json")) as f:
        data = _json.load(f)

    org = data["org"]
    goal = data.get("goal", "")

    print(f"Running searcher for: {org}")
    print()

    result = search_org(org, goal)

    print("Result:")
    print(_json.dumps(result, indent=2))
    print()

    all_pass = True
    all_pass &= check("website is populated", bool(result.get("website")))
    all_pass &= check(
        "summary is populated",
        bool(result.get("summary"))
        and result.get("summary") != "No public information found",
    )
    all_pass &= check(
        "key_details is a non-empty list",
        isinstance(result.get("key_details"), list)
        and len(result.get("key_details", [])) > 0,
    )

    print()
    print("=" * 40)
    print("PASS" if all_pass else "FAIL")
