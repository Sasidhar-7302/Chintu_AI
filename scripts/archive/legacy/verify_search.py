
import logging
import sys
import os

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO)

def test_search():
    print("Testing Web Search Engine...")
    try:
        from chintu_backend.search.web_search import search_web, search_news
        
        print("\n--- Testing General Search ('python tutorials') ---")
        results = search_web("python tutorials", max_results=3)
        print(f"Result Length: {len(results)}")
        print(results[:500] + "...")
        
        if "No results found" in results or "not available" in results:
            print("FAIL: General Search returned no results.")
        else:
            print("PASS: General Search working.")

        print("\n--- Testing Shopping Search ('buy bluetooth speaker') ---")
        shopping_results = search_web("buy bluetooth speaker price", max_results=3)
        print(shopping_results[:500] + "...")
        
        if "$" in shopping_results or "price" in shopping_results.lower():
             print("PASS: Shopping search contains pricing info (likely).")
        else:
             print("WARN: Shopping search might be missing prices.")

    except ImportError as e:
        print(f"Import Error: {e}")
    except Exception as e:
        print(f"Runtime Error: {e}")

if __name__ == "__main__":
    test_search()
