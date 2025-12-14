import warnings
# Suppress warning about package rename
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")
from duckduckgo_search import DDGS

def search_duckduckgo(query: str, max_results=3) -> str:
    """
    Searches DuckDuckGo and returns a summary string of the top results.
    """
    try:
        results = DDGS().text(query, max_results=max_results)
        if not results:
            return "No results found."
            
        summary = ""
        for i, r in enumerate(results, 1):
            title = r.get('title', 'No Title')
            body = r.get('body', 'No Description')
            href = r.get('href', '#')
            summary += f"{i}. [{title}]({href}): {body}\n"
            
        return summary
    except Exception as e:
        return f"Search failed: {str(e)}"
