
from enhanced_summarizer import app

if __name__ == '__main__':
    print("Starting Enhanced AI Summarizer on port 3000...")
    print("This version uses spaCy instead of NLTK for more reliable text processing.")
    print("The summarizer includes features to add missing details and improve context.")
    app.run(host='0.0.0.0', port=3000, debug=False)
from enhanced_summarizer import search_and_summarize
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_test(query):
    """Run a test query and print the results with Double Down Detection stats."""
    print(f"\n===== Testing query: '{query}' =====")
    summary, errors, sources = search_and_summarize(query, num_sentences=6)
    
    print("\n----- Summary -----")
    print(summary)
    
    print("\n----- Sources -----")
    for source in sources:
        print(source)
    
    print("\n----- Errors/Warnings -----")
    for error in errors:
        print(error)
    
    print("\n===== End of test =====\n")
    return summary

if __name__ == "__main__":
    # Test the Double Down Detection with various queries
    print("Starting enhanced summarizer with Double Down Detection...")
    
    # Run a few test queries that might produce duplicate content
    queries = [
        "What is artificial intelligence?",
        "Tell me about climate change impacts",
        "History of the internet",
        "Benefits of meditation",
        # Conversational queries to test small talk handling
        "Hello, how are you today?",
        "Thank you for the information!",
        "Nice to meet you",
        "Goodbye"
    ]
    
    for query in queries:
        run_test(query)
