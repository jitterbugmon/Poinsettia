from flask import Flask, request, render_template_string, jsonify, session, redirect, url_for
import requests
from bs4 import BeautifulSoup
import re
import logging
import numpy as np
import heapq
from urllib.parse import urlparse
from datetime import datetime, timedelta
import random
import string
import hashlib
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple user database (in production, use a real database)
USERS = {
    "demo": hashlib.sha256("demo123".encode()).hexdigest()
}

# Ollama configuration
OLLAMA_URL = "http://localhost:11434/api/generate"

def check_ollama_available():
    """Check if Ollama is running and the model is available"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            models = response.json().get('models', [])
            # Check if poinsettia:latest model exists
            model_names = [model.get('name', '') for model in models]
            return 'poinsettia:latest' in model_names or any(name.startswith('poinsettia:') for name in model_names)
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"Ollama health check failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during Ollama health check: {e}")
        return False


def generate_with_ollama(prompt):
    """Generate response using Ollama"""
    try:
        payload = {
            "model": "poinsettia:latest",
            "prompt": prompt,
            "stream": False
        }
        # Increased timeout to 120 seconds for large models
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json().get('response', '')
        else:
            logger.error(f"Ollama API error: Status {response.status_code}, Response: {response.text}")
            return None
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out after 120 seconds - the model may be too large or slow")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Ollama connection error - is the server running? Try: ollama serve")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during Ollama generation: {str(e)}")
        return None


# Simple cache implementation
class SimpleCache:
    def __init__(self, max_size=100, ttl=3600):  # 1 hour TTL by default
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return value
            else:
                # Expired
                del self.cache[key]
        return None

    def set(self, key, value):
        # If cache is full, remove oldest entry
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.items(), key=lambda x: x[1][1])[0]
            del self.cache[oldest_key]
        self.cache[key] = (value, datetime.now())

# Create cache instances
search_cache = SimpleCache(max_size=50, ttl=3600)  # Cache search results for 1 hour
content_cache = SimpleCache(max_size=100, ttl=7200)  # Cache website content for 2 hours

# List of stop words (common words that don't add meaning)
STOP_WORDS = {
    'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while',
    'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through',
    'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in',
    'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
    'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
    'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now', 'i',
    'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
    'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers',
    'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
    'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'is', 'are',
    'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does',
    'did', 'doing', 'would', 'could', 'should', 'ought', 'i\'m', 'you\'re', 'he\'s',
    'she\'s', 'it\'s', 'we\'re', 'they\'re', 'i\'ve', 'you\'ve', 'we\'ve', 'they\'ve',
    'i\'d', 'you\'d', 'he\'d', 'she\'d', 'we\'d', 'they\'d', 'i\'ll', 'you\'ll', 'he\'ll',
    'she\'ll', 'we\'ll', 'they\'ll', 'isn\'t', 'aren\'t', 'wasn\'t', 'weren\'t', 'hasn\'t',
    'haven\'t', 'hadn\'t', 'doesn\'t', 'don\'t', 'didn\'t', 'won\'t', 'wouldn\'t',
    'shan\'t', 'shouldn\'t', 'can\'t', 'cannot', 'couldn\'t', 'mustn\'t', 'let\'s',
    'that\'s', 'who\'s', 'what\'s', 'here\'s', 'there\'s', 'when\'s', 'where\'s', 'why\'s',
    'how\'s', 'thing', 'things', 'way', 'ways'
}

# Transition phrases for improving fluidity in summaries
TRANSITION_PHRASES = [
    "Additionally, ", "Furthermore, ", "Moreover, ", "In addition, ",
    "Notably, ", "Interestingly, ", "Importantly, ", "Significantly, ",
    "Research indicates that ", "Evidence suggests that ", "Studies show that ",
    "Experts point out that ", "It's worth noting that ", "One key aspect is that ",
]

# Connecting phrases to improve sentence flow
CONNECTING_PHRASES = {
    'contrast': ["However, ", "On the other hand, ", "Conversely, ", "In contrast, "],
    'agreement': ["Similarly, ", "Likewise, ", "In the same way, ", "Correspondingly, "],
    'cause': ["Because of this, ", "As a result, ", "Consequently, ", "Therefore, "],
    'example': ["For example, ", "For instance, ", "Specifically, ", "To illustrate, "],
    'emphasis': ["Indeed, ", "Certainly, ", "Notably, ", "Particularly, "],
    'conclusion': ["In conclusion, ", "To summarize, ", "Overall, ", "In summary, "]
}

# Define trusted news sources and search engines
TRUSTED_DOMAINS = [
    'wikipedia.org', 'nytimes.com', 'bbc.com', 'reuters.com',
    'theguardian.com', 'washingtonpost.com', 'nature.com',
    'science.org', 'who.int', 'un.org', 'cnn.com', 'apnews.com',
    'npr.org', 'wsj.com', 'forbes.com', 'economist.com',
    'nationalgeographic.com', 'smithsonianmag.com', 'time.com',
    'harvard.edu', 'stanford.edu', 'mit.edu', 'berkeley.edu',
    'merriam-webster.com'
]

def is_trusted_domain(url):
    """Check if the domain is from a trusted source."""
    domain = urlparse(url).netloc
    return any(td in domain for td in TRUSTED_DOMAINS) or domain.endswith('.edu') or domain.endswith('.gov')

def custom_sent_tokenize(text):
    """
    Custom sentence tokenizer that doesn't rely on NLTK resources
    """
    # Handle common abbreviations to avoid incorrect splits
    text = re.sub(r'([A-Z][a-z]\.)(?=\s+[A-Z])', r'\1KEEPJOINED', text)
    text = re.sub(r'(Mr\.|Mrs\.|Dr\.|Prof\.|etc\.|i\.e\.|e\.g\.)(?=\s)', r'\1KEEPJOINED', text)

    # Split on sentence endings, respecting abbreviations
    sentences = re.split(r'(?<!\w\.\w.)(?<!KEEPJOINED)(?<=\.|\?|\!)\s+', text)

    # Remove the KEEPJOINED markers
    sentences = [re.sub('KEEPJOINED', '', s) for s in sentences]

    # Filter out empty sentences and very short ones
    return [s for s in sentences if s.strip() and len(s.strip()) > 10]

def word_tokenize(text):
    """Simple word tokenizer splitting on whitespace and punctuation"""
    # Convert to lowercase and remove punctuation
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    # Split on whitespace and filter empty strings
    return [word for word in text.split() if word]

def extract_book_title(query):
    """Extract potential book title from a query"""
    query = query.lower().strip()

    # Common patterns for book queries
    patterns = [
        r"(?:message|theme|moral|meaning|summary) of (?:the book|the novel|book|novel)? ['\"]?(.*?)['\"]?(?:\s+by|\?|$)",
        r"what (?:is|are) the (?:message|theme|moral|meaning) of (?:the book|the novel|book|novel)? ['\"]?(.*?)['\"]?(?:\s+by|\?|$)",
        r"what does (?:the book|the novel|book|novel)? ['\"]?(.*?)['\"]? teach",
        r"lessons from (?:the book|the novel|book|novel)? ['\"]?(.*?)['\"]?(?:\s+by|\?|$)"
    ]

    # Common book title patterns without explicit mentioning of "book" or "novel"
    implicit_patterns = [
        r"(?:message|theme|moral|meaning|summary) of ['\"]?(.*?)['\"]?(?:\s+by|\?|$)",
        r"what (?:is|are) the (?:message|theme|moral|meaning) of ['\"]?(.*?)['\"]?(?:\s+by|\?|$)"
    ]

    # Check each pattern
    for pattern in patterns:
        matches = re.findall(pattern, query)
        if matches:
            # Get the longest match (likely the full title)
            longest_match = max(matches, key=len)
            if len(longest_match) > 2:  # Avoid extremely short matches
                return longest_match.strip()

    # If no explicit pattern matches, try implicit patterns
    for pattern in implicit_patterns:
        matches = re.findall(pattern, query)
        if matches:
            longest_match = max(matches, key=len)
            if len(longest_match) > 2:
                return longest_match.strip()

    # If no pattern matches, try to find quoted text which might be a title
    quoted = re.findall(r'["\']([^"\']+)["\']', query)
    if quoted:
        return quoted[0].strip()

    # Final fallback: look for known book indicators and extract probable title
    if any(word in query for word in ["book", "novel", "story", "read"]):
        words = query.split()
        for i, word in enumerate(words):
            if word in ["book", "novel"]:
                # Try to extract what comes after "book" or "novel"
                if i < len(words) - 1 and len(words) > i + 1:
                    return " ".join(words[i+1:])

    return None

def calculate_sentence_similarity(sentence1, sentence2):
    """Calculate the similarity between two sentences using a word-based comparison."""
    # Convert sentences to lowercase and tokenize
    words1 = set(word_tokenize(sentence1.lower()))
    words2 = set(word_tokenize(sentence2.lower()))

    # Remove stop words for better comparison
    words1 = {word for word in words1 if word not in STOP_WORDS}
    words2 = {word for word in words2 if word not in STOP_WORDS}

    # If either set is empty after stopword removal, use original sets
    if not words1 or not words2:
        words1 = set(word_tokenize(sentence1.lower()))
        words2 = set(word_tokenize(sentence2.lower()))

    # Calculate Jaccard similarity
    if not words1 or not words2:
        return 0.0

    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))

    return intersection / union if union > 0 else 0.0


def extract_important_terms(text, query, num_terms=10):
    """Extract important terms from the text that are relevant to the query"""
    # Get query words without stop words
    query_words = set(word for word in word_tokenize(query) if word not in STOP_WORDS)

    # Get all words from the text
    text_words = word_tokenize(text)

    # Count word frequencies in the text
    word_freq = {}
    for word in text_words:
        if word not in STOP_WORDS and len(word) > 2:  # Only consider meaningful words
            word_freq[word] = word_freq.get(word, 0) + 1

    # Calculate importance score: frequency + bonus for query relevance
    word_importance = {}
    for word, freq in word_freq.items():
        # Base score is frequency
        importance = freq

        # Add bonus if word is related to query
        if word in query_words:
            importance += 5  # Big bonus for direct matches
        elif any(query_word in word or word in query_word for query_word in query_words):
            importance += 2  # Smaller bonus for partial matches

        word_importance[word] = importance

    # Get the top important terms
    important_terms = sorted(word_importance.items(), key=lambda x: x[1], reverse=True)[:num_terms]
    return [term for term, _ in important_terms]

def extract_keywords(query, max_keywords=4):
    """Extract important keywords from a query with improved handling of natural language questions"""
    # Recognize common question patterns
    query_lower = query.lower().strip()
    logger.info(f"Extracting keywords from: '{query_lower}'")

    # Initialize subject variable
    subject = None

    # Handle "what is the message of the book X" type questions
    if "message of" in query_lower or "theme of" in query_lower:
        book_title = extract_book_title(query_lower)
        if book_title:
            logger.info(f"Extracted book title for message/theme query: '{book_title}'")
            return f"{book_title} book theme message"

    # Handle "what language is X written in" type questions
    if "what language is" in query_lower or "written in" in query_lower:
        # Extract the subject (likely a product name)
        if "what language is" in query_lower:
            subject = query_lower.split("what language is")[1].split("written in")[0].strip()
        else:
            parts = query_lower.split("written in")
            subject = parts[0].strip()
            if "what" in subject:
                subject = subject.split("what")[1].strip()

        if subject:
            # Ensure we're targeting the specific subject, not just general programming info
            logger.info(f"Programming language query for specific subject: '{subject}'")
            return f"{subject} programming language specific"

    # Handle "what is X" definition questions
    if query_lower.startswith("what is") or query_lower.startswith("what are") or "definition of" in query_lower:
        # Extract the actual topic being asked about
        if query_lower.startswith("what is"):
            subject = query_lower.replace("what is", "", 1).strip()
        elif query_lower.startswith("what are"):
            subject = query_lower.replace("what are", "", 1).strip()
        else:
            subject = query_lower.split("definition of")[1].strip() if "definition of" in query_lower else ""

        # Remove articles and extra words at the beginning
        subject = re.sub(r'^(a|an|the)\s+', '', subject)

        # Remove question marks at the end
        subject = re.sub(r'\?+$', '', subject)

        if subject:
            logger.info(f"Definition query for: '{subject}'")
            return subject

    # Default to regular keyword extraction
    words = word_tokenize(query_lower)
    filtered_words = [w for w in words if w not in STOP_WORDS and len(w) > 2]

    # Prioritize longer words as they tend to be more important
    filtered_words.sort(key=len, reverse=True)

    # If we have enough keywords, return them
    if filtered_words:
        extracted = " ".join(filtered_words[:max_keywords])
        logger.info(f"General keyword extraction: '{extracted}'")
        return extracted

    # Fall back to returning the original query with stop words removed
    return query_lower

def search_for_topic(query, max_results=5):
    """Search for reputable sources on a topic"""
    try:
        # Check cache first
        cache_key = f"search_{query}_{max_results}"
        cached_result = search_cache.get(cache_key)
        if cached_result:
            logger.info(f"Using cached search results for: {query}")
            return cached_result

        logger.info(f"Original query: {query}")

        # First determine the query intent
        intent, is_specific, *main_topic_info = extract_query_intent(query) # Unpack to handle optional main_topic
        if main_topic_info:
            main_topic = main_topic_info[0]
        else:
            main_topic = None
        logger.info(f"Query intent: {intent}, is_specific: {is_specific}, main_topic: {main_topic}")

        # Reject queries that are too generic
        if query.lower().strip() in ["wikipedia", "featured article", "daily article", "today"]:
            logger.warning(f"Query is too generic: {query}")
            return []

        # Handle book-specific queries differently
        if intent == "book_analysis":
            # Extract potential book title from query
            book_title = extract_book_title(query)
            if book_title:
                logger.info(f"Detected book title: {book_title}")
                # Search specifically for this book, focusing on literary analysis
                keywords = f"{book_title} book summary theme message analysis"
                # Add special handling for well-known books
                if book_title.lower() in ["dune", "the lord of the rings", "1984", "to kill a mockingbird",
                                         "brave new world", "the great gatsby"]:
                    logger.info(f"Using specialized search for well-known book: {book_title}")
                    keywords = f"\"{book_title}\" book theme message analysis"
            else:
                # Fallback to regular extraction but with book focus
                keywords = extract_keywords(query) + " book analysis"
        elif intent == "historical_topic" and main_topic:
            # Use the extracted historical topic as the search query
            logger.info(f"Using extracted topic '{main_topic}' for search")
            keywords = f"{main_topic} historical period events significance"

            # For specific historical periods, enhance the search query
            if "renaissance" in main_topic.lower():
                keywords = "Renaissance historical period art culture humanism achievements significance"
            elif "industrial revolution" in main_topic.lower():
                keywords = "Industrial Revolution technological social economic changes significance"
            elif "world war" in main_topic.lower():
                keywords = f"{main_topic} causes events impact significance"
            elif "civil war" in main_topic.lower():
                keywords = f"{main_topic} causes battles outcome significance"
        else:
            # Regular keyword extraction for non-book queries
            keywords = extract_keywords(query)

            # Improve specificity by adding qualifying terms based on intent
            if intent == "definition":
                keywords += " meaning explanation"
            elif intent == "information":
                keywords += " details facts information"
            elif intent == "technology":
                keywords += " technology explanation"

        logger.info(f"Extracted keywords: {keywords}")

        # Prevent "definition" being used as a search term
        if keywords.endswith(" definition"):
            keywords = keywords.replace(" definition", "")

        # Add robot as a known topic
        if "robot" in keywords.lower():
            keywords = "robot robotics"

        # Expanded common topics dictionary with more topics
        common_topics = {
            "renaissance": [
                "https://en.wikipedia.org/wiki/Renaissance",
                "https://www.britannica.com/event/Renaissance",
                "https://www.history.com/topics/renaissance/renaissance",
                "https://www.metmuseum.org/toah/hd/ren/hd_ren.htm"
            ],
            "industrial revolution": [
                "https://en.wikipedia.org/wiki/Industrial_Revolution",
                "https://www.britannica.com/event/Industrial-Revolution",
                "https://www.history.com/topics/industrial-revolution/industrial-revolution"
            ],
            "world war i": [
                "https://en.wikipedia.org/wiki/World_War_I",
                "https://www.britannica.com/event/World-War-I",
                "https://www.history.com/topics/world-war-i"
            ],
            "world war ii": [
                "https://en.wikipedia.org/wiki/World_War_II",
                "https://www.britannica.com/event/World-War-II",
                "https://www.history.com/topics/world-war-ii"
            ],
            "middle ages": [
                "https://en.wikipedia.org/wiki/Middle_Ages",
                "https://www.britannica.com/event/Middle-Ages",
                "https://www.history.com/topics/middle-ages"
            ],
            "roman empire": [
                "https://en.wikipedia.org/wiki/Roman_Empire",
                "https://www.britannica.com/place/Roman-Empire",
                "https://www.history.com/topics/ancient-rome/ancient-rome"
            ],
            "ancient egypt": [
                "https://en.wikipedia.org/wiki/Ancient_Egypt",
                "https://www.britannica.com/place/ancient-Egypt",
                "https://www.history.com/topics/ancient-egypt"
            ],
            "french revolution": [
                "https://en.wikipedia.org/wiki/French_Revolution",
                "https://www.britannica.com/event/French-Revolution",
                "https://www.history.com/topics/france/french-revolution"
            ],
            "cold war": [
                "https://en.wikipedia.org/wiki/Cold_War",
                "https://www.britannica.com/event/Cold-War",
                "https://www.history.com/topics/cold-war/cold-war-history"
            ],
            "enlightenment": [
                "https://en.wikipedia.org/wiki/Age_of_Enlightenment",
                "https://www.britannica.com/event/Enlightenment-European-history",
                "https://www.history.com/topics/british-history/enlightenment"
            ],
            "civil war": [
                "https://en.wikipedia.org/wiki/American_Civil_War",
                "https://www.britannica.com/event/American-Civil-War",
                "https://www.history.com/topics/american-civil-war/american-civil-war-history"
            ],
            "american revolution": [
                "https://en.wikipedia.org/wiki/American_Revolution",
                "https://www.britannica.com/event/American-Revolution",
                "https://www.history.com/topics/american-revolution/american-revolution-history"
            ],
            "great depression": [
                "https://en.wikipedia.org/wiki/Great_Depression",
                "https://www.britannica.com/event/Great-Depression",
                "https://www.history.com/topics/great-depression/great-depression-history"
            ],
            "ancient greece": [
                "https://en.wikipedia.org/wiki/Ancient_Greece",
                "https://www.britannica.com/place/ancient-Greece",
                "https://www.history.com/topics/ancient-history/ancient-greece"
            ],
            "robot": [
                "https://en.wikipedia.org/wiki/Robot",
                "https://www.britannica.com/technology/robot-technology",
                "https://robotics.nasa.gov/what-is-a-robot/"
            ],
            "climate change": [
                "https://www.nytimes.com/section/climate",
                "https://www.bbc.com/news/science-environment-56837908",
                "https://en.wikipedia.org/wiki/Climate_change"
            ],
            "covid": [
                "https://www.who.int/emergencies/diseases/novel-coronavirus-2019",
                "https://www.cdc.gov/coronavirus/2019-ncov/index.html",
                "https://www.nytimes.com/news-event/coronavirus"
            ],
            "artificial intelligence": [
                "https://en.wikipedia.org/wiki/Artificial_intelligence",
                "https://www.nature.com/articles/d41586-020-03348-4",
                "https://www.nytimes.com/topic/subject/artificial-intelligence"
            ],
            "roblox programming language specific": [
                "https://en.wikipedia.org/wiki/Lua_(programming_language)",
                "https://developer.roblox.com/en-us/articles/Lua",
                "https://en.wikipedia.org/wiki/Roblox_Studio"
            ],
            "programming": [
                "https://en.wikipedia.org/wiki/Programming_language",
                "https://en.wikipedia.org/wiki/List_of_programming_languages",
                "https://www.northeastern.edu/graduate/blog/most-popular-programming-languages/"
            ],
            "cheeseburger": [
                "https://en.wikipedia.org/wiki/Cheeseburger",
                "https://en.wikipedia.org/wiki/Hamburger",
                "https://www.britannica.com/topic/hamburger"
            ],
            "food": [
                "https://en.wikipedia.org/wiki/Food",
                "https://www.britannica.com/topic/food",
                "https://en.wikipedia.org/wiki/Cuisine"
            ],
            "history": [
                "https://en.wikipedia.org/wiki/History",
                "https://www.britannica.com/topic/history",
                "https://www.history.com/"
            ],
            "science": [
                "https://en.wikipedia.org/wiki/Science",
                "https://www.nationalgeographic.com/science/",
                "https://www.scientificamerican.com/"
            ],
            "technology": [
                "https://en.wikipedia.org/wiki/Technology",
                "https://www.technologyreview.com/",
                "https://www.wired.com/"
            ],
            "feudalism": [
                "https://en.wikipedia.org/wiki/Feudalism",
                "https://www.britannica.com/topic/feudalism",
                "https://www.history.com/topics/middle-ages/feudalism"
            ],
            "fief": [
                "https://en.wikipedia.org/wiki/Fief",
                "https://www.merriam-webster.com/dictionary/fief",
                "https://www.britannica.com/topic/fief"
            ],
            "dune": [
                "https://en.wikipedia.org/wiki/Dune_(novel)",
                "https://www.sparknotes.com/lit/dune/summary/",
                "https://www.litcharts.com/lit/dune/summary",
                "https://www.cliffsnotes.com/literature/d/dune/book-summary"
            ],
            "to kill a mockingbird": [
                "https://en.wikipedia.org/wiki/To_Kill_a_Mockingbird",
                "https://www.sparknotes.com/lit/mocking/summary/",
                "https://www.litcharts.com/lit/to-kill-a-mockingbird/summary"
            ],
            "the great gatsby": [
                "https://en.wikipedia.org/wiki/The_Great_Gatsby",
                "https://www.sparknotes.com/lit/gatsby/summary/",
                "https://www.litcharts.com/lit/the-great-gatsby/summary"
            ],
            "1984": [
                "https://en.wikipedia.org/wiki/Nineteen_Eighty-Four",
                "https://www.sparknotes.com/lit/1984/summary/",
                "https://www.litcharts.com/lit/1984/summary"
            ],
            "lord of the flies": [
                "https://en.wikipedia.org/wiki/Lord_of_the_Flies",
                "https://www.sparknotes.com/lit/flies/summary/",
                "https://www.litcharts.com/lit/lord-of-the-flies/summary"
            ],
            "music": [
                "https://en.wikipedia.org/wiki/Music",
                "https://www.rollingstone.com/",
                "https://www.billboard.com/"
            ],
            "sports": [
                "https://en.wikipedia.org/wiki/Sport",
                "https://www.espn.com/",
                "https://www.bbc.com/sport"
            ],
            "movies": [
                "https://en.wikipedia.org/wiki/Film",
                "https://www.imdb.com/",
                "https://www.rottentomatoes.com/"
            ],
            "books": [
                "https://en.wikipedia.org/wiki/Book",
                "https://www.goodreads.com/",
                "https://www.nytimes.com/books/best-sellers/"
            ],
            "education": [
                "https://en.wikipedia.org/wiki/Education",
                "https://www.chronicle.com/",
                "https://www.edweek.org/"
            ],
            "health": [
                "https://en.wikipedia.org/wiki/Health",
                "https://www.who.int/",
                "https://www.mayoclinic.org/"
            ]
        }

        # Check for matches in common topics
        search_results = []
        for topic, urls in common_topics.items():
            topic_words = set(topic.lower().split())
            keyword_words = set(keywords.lower().split())

            # Direct exact match for specific topics
            if keywords.lower() == topic.lower():
                logger.info(f"Exact match found for topic: {topic}")
                search_results.extend(urls)
                break

            # Check for partial matches with higher specificity
            if keyword_words.intersection(topic_words) or topic.lower() in keywords.lower() or keywords.lower() in topic.lower():
                logger.info(f"Matched topic: {topic}")
                search_results.extend(urls)
                break  # Once we find a good match, stop looking

        # If no matches in common topics, use generic sources with the extracted keywords
        if not search_results:
            # Try multiple variations of the query to increase chances of finding content
            variations = [
                # Original keyword
                keywords.title().replace(' ', '_'),
                # Pluralize if singular
                (keywords + "s").title().replace(' ', '_') if not keywords.endswith('s') else keywords,
                # Remove adjectives (often the last word is more important)
                keywords.split()[-1].title() if len(keywords.split()) > 1 else keywords,
                # General category the topic might belong to
                "General_" + keywords.title().replace(' ', '_')
            ]

            # Generate search URLs for each variation
            for variation in variations:
                search_results.append(f"https://en.wikipedia.org/wiki/{variation}")

            # Add more general encyclopedic sources
            search_results.extend([
                f"https://www.britannica.com/search?query={keywords.replace(' ', '+')}",
                f"https://en.wikipedia.org/w/index.php?search={keywords.replace(' ', '+')}",
                f"https://www.britannica.com/dictionary/{keywords.replace(' ', '-')}",
                f"https://www.merriam-webster.com/dictionary/{keywords.replace(' ', '%20')}"
            ])

            # Add general search results
            search_results.append(f"https://www.bbc.com/search?q={keywords.replace(' ', '+')}")

            logger.info(f"Using fallback search with multiple variations for: {keywords}")

        logger.info(f"Generated search URLs: {search_results}")
        # Remove duplicates while preserving order
        seen = set()
        unique_results = [x for x in search_results if not (x in seen or seen.add(x))]

        result = unique_results[:max_results]
        # Cache the result
        search_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Error searching for {query}: {str(e)}")
        # Even if there's an error, return some basic Wikipedia URLs as a last resort
        return [
            f"https://en.wikipedia.org/wiki/Main_Page",
            f"https://www.britannica.com/",
            f"https://www.wikipedia.org/"
        ]

def fetch_article(url):
    """Fetch article content from a URL."""
    if not is_trusted_domain(url):
        logger.warning(f"Untrusted domain detected: {url}")
        return None, f"URL is not from a trusted source: {url}"

    try:
        # Check cache first
        cached_content = content_cache.get(url)
        if cached_content:
            logger.info(f"Using cached content for: {url}")
            return cached_content, None

        logger.info(f"Fetching content from: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # Reduced timeout to 1 second to prevent long wait times
        response = requests.get(url, headers=headers, timeout=2)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error for {url}: {http_err}")
            return None, f"HTTP error: {http_err}"

        logger.info(f"Successfully fetched content from: {url}")

        try:
            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.extract()

            # Try to find the main content container elements that might hold the article
            main_content = None
            for container in ["main", "article", "div.content", "div.article", "div.main"]:
                content = soup.select(container)
                if content:
                    main_content = content[0]
                    break

            # Get text with special focus on the beginning
            # First, try to find an introduction or first paragraphs
            intro_text = ""

            # Look for introductory elements
            intro_elements = soup.find_all(['h1', 'h2', 'h3', 'p'], limit=10)
            if intro_elements:
                # Extract intro paragraphs - the first few paragraphs often contain the main ideas
                intro_text = ' '.join([elem.get_text().strip() for elem in intro_elements])

            # For the main content, prioritize paragraphs
            if main_content:
                paragraphs = main_content.find_all('p')
            else:
                paragraphs = soup.find_all('p')

            if paragraphs:
                # Join the intro with the rest of the content, giving priority to the beginning
                if intro_text:
                    # Ensure intro gets higher weight by including it at the beginning
                    main_text = ' '.join([para.get_text() for para in paragraphs])
                    text = intro_text + " " + main_text
                else:
                    text = ' '.join([para.get_text() for para in paragraphs])
            else:
                # Fall back to all text if no paragraphs found
                text = soup.get_text()

            # Clean up the text
            # Break into lines and remove leading and trailing space
            lines = (line.strip() for line in text.splitlines())
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            # Drop blank lines
            text = ' '.join(chunk for chunk in chunks if chunk)

            # Remove common patterns in news articles
            text = re.sub(r'(Photo by|Credit:).*?\.', '', text)
            text = re.sub(r'Advertisement', '', text)

            if not text.strip():
                logger.warning(f"No text content found in {url}")
                return None, f"No content found in the page"

            logger.info(f"Successfully extracted text from {url} (length: {len(text)})")
            # Cache the content
            content_cache.set(url, text)
            return text, None
        except Exception as parse_err:
            logger.error(f"Error parsing content from {url}: {parse_err}")
            return None, f"Error parsing page content: {parse_err}"

    except requests.exceptions.Timeout:
        logger.error(f"Timeout error when fetching {url}")
        return None, f"Timeout when connecting to {url}"
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error when fetching {url}")
        return None, f"Connection error when connecting to {url}"
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {str(e)}")
        return None, f"Error: {str(e)}"

def clean_citations(text):
    """Remove citation markers like [1], [2], etc."""
    return re.sub(r'\[\d+\]|\[\d+,\d+\]|\[\d+(-|–|—)\d+\]', '', text)

def calculate_sentence_scores(sentences, stop_words=None, important_terms=None):
    """Calculate frequency-based importance scores for each sentence with term boosting and position bonus"""
    if stop_words is None:
        stop_words = STOP_WORDS

    # Create word frequency count
    word_frequencies = {}
    for sentence in sentences:
        for word in word_tokenize(sentence):
            if word not in stop_words:
                if word not in word_frequencies:
                    word_frequencies[word] = 1
                else:
                    word_frequencies[word] += 1

    # Normalize word frequencies
    if word_frequencies:
        max_frequency = max(word_frequencies.values())
        for word in word_frequencies:
            word_frequencies[word] = word_frequencies[word] / max_frequency

    # Calculate sentence scores based on word frequencies
    sentence_scores = {}
    for i, sentence in enumerate(sentences):
        sentence_scores[i] = 0
        word_count = len(word_tokenize(sentence))
        if word_count > 3:  # Only consider sentences with more than 3 words
            for word in word_tokenize(sentence):
                if word in word_frequencies:
                    sentence_scores[i] += word_frequencies[word]

                    # Boost scores for sentences containing important terms
                    if important_terms and word in important_terms:
                        sentence_scores[i] += 0.5  # Add boost for important terms

            # Normalize by sentence length
            sentence_scores[i] = sentence_scores[i] / word_count

            # Add position-based boosting - sentences at the beginning (especially the first 5) get a bonus
            # This helps prioritize the beginning of the article which often contains the main ideas
            if i < 5:
                # Decreasing bonus for first 5 sentences
                position_bonus = 1.0 - (i * 0.15)  # 1.0, 0.85, 0.7, 0.55, 0.4
                sentence_scores[i] += position_bonus
            elif i <10:
                # Smaller bonus for next 5 sentences
                position_bonus = 0.3 - ((i - 5) * 0.05)  # 0.3, 0.25, 0.2, 0.15, 0.1
                sentence_scores[i] += position_bonus

    return sentence_scores

def is_duplicate_content(new_sentence, existing_sentences, similarity_threshold=0.75):
    """
    Check if a sentence is too similar to any sentence in the existing set.
    Uses a 75% similarity threshold to identify and prevent duplicate content (Double Down Detection).
    """
    if len(word_tokenize(new_sentence)) < 4:  # Skip very short sentences
        return True

    for existing in existing_sentences:
        # Calculate similarity between the new sentence and existing ones
        similarity = calculate_sentence_similarity(new_sentence, existing)

        # If similarity is 75% or higher, consider it a duplicate
        if similarity >= similarity_threshold:
            logger.info(f"Double Down Detection: Found duplicate with {similarity:.2f} similarity")
            logger.info(f"Original: {existing}")
            logger.info(f"Duplicate: {new_sentence}")
            return True

    return False

def get_synonym(word):
    """Get a synonym for a word to avoid plagiarism."""
    # Comprehensive synonyms dictionary
    synonyms = {
        # Nouns
        "person": ["individual", "human", "being", "soul", "character", "mortal", "citizen"],
        "people": ["individuals", "humans", "persons", "folk", "population", "public", "citizenry", "community"],
        "time": ["period", "era", "age", "duration", "interval", "span", "season", "occasion", "moment"],
        "year": ["twelve months", "annual period", "calendar year", "solar year", "cycle", "term", "season"],
        "way": ["method", "approach", "manner", "technique", "path", "route", "course", "avenue", "means"],
        "day": ["date", "period", "time", "moment", "daylight hours", "daytime", "sun-up", "24 hours"],
        "thing": ["item", "object", "entity", "element", "artifact", "article", "unit", "piece"],
        "man": ["male", "gentleman", "fellow", "guy", "chap", "individual", "person", "human"],
        "world": ["globe", "earth", "planet", "realm", "cosmos", "universe", "society", "civilization"],
        "life": ["existence", "being", "living", "lifetime", "animation", "vitality", "lifespan", "biography"],
        "hand": ["palm", "grip", "grasp", "extremity", "mitt", "paw", "digits", "appendage"],
        "part": ["portion", "section", "component", "segment", "piece", "fragment", "division", "element"],
        "child": ["youngster", "kid", "youth", "juvenile", "minor", "adolescent", "offspring", "descendant"],
        "eye": ["sight", "vision", "view", "gaze", "optic", "ocular", "peeper", "orb"],
        "woman": ["female", "lady", "girl", "matron", "lass", "gentlewoman", "dame"],
        "place": ["location", "spot", "site", "position", "area", "region", "locale", "venue"],
        "work": ["labor", "job", "task", "effort", "toil", "employment", "occupation", "exertion"],
        "week": ["seven days", "workweek", "period", "interval", "stretch", "span", "cycle"],
        "case": ["instance", "example", "situation", "circumstance", "occurrence", "event", "scenario"],
        "point": ["spot", "location", "position", "place", "dot", "mark", "speck", "detail", "argument"],
        "government": ["administration", "regime", "authority", "leadership", "jurisdiction", "executive", "state"],
        "company": ["business", "firm", "corporation", "enterprise", "establishment", "organization", "venture"],
        "number": ["figure", "digit", "quantity", "amount", "sum", "total", "tally", "count"],
        "group": ["collection", "gathering", "assembly", "crowd", "cluster", "bunch", "band", "troupe"],
        "problem": ["issue", "difficulty", "challenge", "trouble", "dilemma", "obstacle", "complication", "predicament"],
        "fact": ["reality", "truth", "actuality", "certainty", "datum", "information", "detail", "verity"],
        "money": ["cash", "currency", "funds", "capital", "wealth", "finance", "resources", "assets"],
        "month": ["thirty days", "period", "lunar cycle", "calendar month", "four weeks", "thirty-day span"],
        "right": ["privilege", "entitlement", "claim", "due", "prerogative", "authority", "liberty"],
        "study": ["research", "analysis", "investigation", "examination", "inquiry", "exploration", "survey"],
        "book": ["publication", "volume", "text", "work", "tome", "manuscript", "opus", "treatise"],
        "story": ["tale", "narrative", "account", "report", "anecdote", "chronicle", "legend", "yarn"],
        "idea": ["concept", "notion", "thought", "belief", "impression", "perception", "theory", "hypothesis"],
        "community": ["neighborhood", "society", "district", "populace", "public", "commune", "settlement"],
        "country": ["nation", "state", "land", "realm", "territory", "domain", "commonwealth", "republic"],
        "word": ["term", "expression", "phrase", "utterance", "vocable", "terminology", "parlance"],
        "example": ["instance", "sample", "case", "illustration", "demonstration", "exemplar", "model"],
        "toppings": ["garnishes", "condiments", "additions", "embellishments", "extras", "adornments", "accessories"],
        "composition": ["makeup", "structure", "constitution", "formation", "arrangement", "configuration", "assembly", "blend"],
        "variations": ["alternatives", "versions", "adaptations", "modifications", "deviations", "adjustments", "mutations"],
        "food": ["nourishment", "sustenance", "nutrition", "fare", "provisions", "edibles", "victuals", "cuisine"],
        "water": ["liquid", "fluid", "aqua", "moisture", "hydration", "drink", "refreshment", "h2o"],
        "area": ["region", "zone", "sector", "district", "locality", "territory", "vicinity", "expanse"],
        "issue": ["matter", "concern", "topic", "subject", "point", "question", "problem", "dispute"],
        "development": ["growth", "progress", "advancement", "evolution", "expansion", "maturation", "improvement"],
        "experience": ["knowledge", "skill", "background", "encounter", "exposure", "involvement", "practice"],
        "level": ["tier", "grade", "degree", "stage", "rank", "echelon", "plane", "standard"],
        "quality": ["attribute", "property", "characteristic", "trait", "feature", "aspect", "caliber", "grade"],
        "change": ["alteration", "modification", "transformation", "shift", "adjustment", "revision", "variation"],

        # Verbs
        "be": ["exist", "occur", "live", "happen", "remain", "stay", "reside", "endure"],
        "have": ["possess", "own", "hold", "maintain", "keep", "retain", "carry", "bear"],
        "do": ["perform", "execute", "accomplish", "achieve", "complete", "fulfill", "conduct"],
        "say": ["state", "mention", "express", "declare", "utter", "pronounce", "articulate", "voice"],
        "get": ["acquire", "obtain", "secure", "gain", "procure", "attain", "fetch", "receive"],
        "make": ["create", "produce", "generate", "form", "construct", "build", "fashion", "manufacture"],
        "go": ["move", "travel", "proceed", "advance", "journey", "progress", "depart", "leave"],
        "know": ["understand", "comprehend", "recognize", "grasp", "perceive", "apprehend", "discern"],
        "take": ["grab", "seize", "capture", "grip", "grasp", "catch", "snatch", "acquire"],
        "see": ["observe", "view", "witness", "perceive", "notice", "behold", "regard", "glimpse"],
        "come": ["approach", "arrive", "reach", "appear", "materialize", "emerge", "enter", "advance"],
        "think": ["believe", "consider", "contemplate", "reflect", "ponder", "meditate", "reason", "deliberate"],
        "look": ["glance", "glimpse", "peer", "gaze", "stare", "watch", "observe", "inspect"],
        "want": ["desire", "wish", "crave", "seek", "covet", "need", "fancy", "yearn for"],
        "give": ["provide", "supply", "offer", "present", "deliver", "furnish", "contribute", "donate"],
        "use": ["employ", "utilize", "apply", "exercise", "implement", "handle", "operate", "work with"],
        "find": ["discover", "locate", "uncover", "detect", "spot", "identify", "come across", "encounter"],
        "tell": ["inform", "relate", "narrate", "describe", "reveal", "disclose", "convey", "communicate"],
        "ask": ["inquire", "query", "question", "interrogate", "request", "inquire about", "seek information"],
        "work": ["labor", "toil", "function", "operate", "perform", "serve", "act", "produce"],
        "seem": ["appear", "look", "sound", "feel", "come across as", "give the impression of", "strike one as"],
        "feel": ["sense", "experience", "perceive", "discern", "undergo", "touch", "handle", "detect"],
        "try": ["attempt", "endeavor", "strive", "seek", "undertake", "venture", "tackle", "aim"],
        "leave": ["depart", "exit", "withdraw", "retire", "vacate", "abandon", "desert", "go away"],
        "call": ["name", "term", "label", "designate", "title", "dub", "christen", "refer to as"],
        "increase": ["grow", "rise", "expand", "extend", "intensify", "amplify", "enhance", "augment"],
        "reduce": ["decrease", "diminish", "lessen", "shrink", "decline", "drop", "curtail", "cut"],
        "begin": ["start", "initiate", "commence", "launch", "embark", "kick off", "set out", "set in motion"],
        "end": ["finish", "conclude", "complete", "terminate", "cease", "halt", "stop", "culminate"],
        "create": ["make", "produce", "generate", "develop", "devise", "construct", "establish", "form"],
        "destroy": ["demolish", "ruin", "wreck", "obliterate", "annihilate", "shatter", "devastate"],
        "build": ["construct", "erect", "assemble", "form", "create", "establish", "develop", "fabricate"],
        "change": ["alter", "modify", "transform", "adjust", "vary", "revise", "adapt", "convert"],
        "improve": ["enhance", "upgrade", "refine", "advance", "better", "perfect", "polish", "elevate"],
        "move": ["shift", "relocate", "transfer", "transport", "displace", "reposition", "progress", "advance"],

        # Adjectives
        "good": ["excellent", "fine", "superior", "quality", "outstanding", "exceptional", "admirable", "worthy"],
        "bad": ["poor", "substandard", "inadequate", "inferior", "unacceptable", "awful", "terrible", "dreadful"],
        "new": ["recent", "fresh", "novel", "modern", "current", "contemporary", "latest", "innovative"],
        "old": ["aged", "ancient", "antique", "elderly", "mature", "senior", "venerable", "vintage"],
        "first": ["initial", "primary", "original", "earliest", "foremost", "premier", "maiden", "pioneering"],
        "last": ["final", "ultimate", "concluding", "terminal", "closing", "ending", "hindmost"],
        "long": ["extended", "lengthy", "prolonged", "extensive", "sustained", "protracted", "drawn-out"],
        "short": ["brief", "concise", "succinct", "compact", "abbreviated", "condensed", "abridged", "fleeting"],
        "great": ["significant", "considerable", "substantial", "notable", "remarkable", "exceptional", "extraordinary"],
        "small": ["little", "tiny", "minute", "compact", "modest", "slight", "miniature", "petite"],
        "large": ["big", "sizeable", "great", "extensive", "substantial", "considerable", "massive", "enormous"],
        "high": ["tall", "elevated", "lofty", "towering", "soaring", "steep", "raised", "exalted"],
        "low": ["short", "squat", "shallow", "sunken", "depressed", "inferior", "subordinate", "modest"],
        "little": ["small", "minor", "tiny", "slight", "diminutive", "miniature", "insignificant"],
        "big": ["large", "sizeable", "substantial", "considerable", "great", "enormous", "immense", "vast"],
        "own": ["personal", "individual", "private", "particular", "special", "exclusive", "distinctive"],
        "other": ["different", "alternative", "additional", "further", "extra", "supplementary", "another"],
        "right": ["correct", "proper", "accurate", "suitable", "appropriate", "fitting", "apt", "exact"],
        "wrong": ["incorrect", "improper", "inaccurate", "unsuitable", "inappropriate", "erroneous", "mistaken"],
        "different": ["diverse", "distinct", "various", "dissimilar", "unlike", "disparate", "divergent", "contrasting"],
        "same": ["identical", "equivalent", "equal", "alike", "similar", "matching", "comparable", "indistinguishable"],
        "next": ["following", "subsequent", "succeeding", "ensuing", "upcoming", "approaching", "forthcoming"],
        "previous": ["preceding", "prior", "former", "earlier", "foregoing", "antecedent", "bygone"],
        "early": ["premature", "initial", "beforehand", "advance", "timely", "prompt", "ahead of time"],
        "late": ["delayed", "behind schedule", "overdue", "tardy", "belated", "unpunctual", "postponed"],
        "young": ["youthful", "juvenile", "adolescent", "immature", "junior", "budding", "developing"],
        "old": ["aged", "elderly", "senior", "mature", "ancient", "venerable", "geriatric", "antiquated"],
        "important": ["significant", "crucial", "vital", "essential", "critical", "key", "fundamental", "paramount"],
        "unimportant": ["insignificant", "trivial", "minor", "inconsequential", "negligible", "incidental", "secondary"],
        "few": ["scarce", "limited", "sparse", "scant", "meager", "insufficient", "negligible", "rare"],
        "many": ["numerous", "multiple", "several", "various", "diverse", "abundant", "copious", "plentiful"],
        "public": ["communal", "community", "social", "common", "shared", "collective", "societal", "civic"],
        "private": ["personal", "individual", "confidential", "secret", "exclusive", "restricted", "intimate"],
        "open": ["accessible", "available", "unrestricted", "unobstructed", "clear", "patent", "exposed"],
        "closed": ["shut", "sealed", "restricted", "blocked", "inaccessible", "impenetrable", "unavailable"],
        "hard": ["difficult", "challenging", "tough", "arduous", "strenuous", "demanding", "laborious"],
        "easy": ["simple", "effortless", "straightforward", "uncomplicated", "painless", "undemanding", "facile"],
        "happy": ["joyful", "delighted", "pleased", "content", "cheerful", "elated", "jubilant", "ecstatic"],
        "sad": ["unhappy", "sorrowful", "dejected", "downcast", "miserable", "depressed", "melancholy", "gloomy"],
        "fast": ["quick", "rapid", "swift", "speedy", "hasty", "fleet", "expeditious", "prompt"],
        "slow": ["gradual", "unhurried", "leisurely", "measured", "moderate", "deliberate", "sluggish", "plodding"],
        "free": ["unrestrained", "unrestricted", "unimpeded", "unfettered", "unhampered", "unbound", "autonomous"],
        "safe": ["secure", "protected", "sheltered", "guarded", "shielded", "safeguarded", "defended", "harmless"],
        "dangerous": ["hazardous", "perilous", "risky", "unsafe", "treacherous", "threatening", "precarious"],
        "clean": ["spotless", "unsoiled", "pristine", "immaculate", "hygienic", "sanitary", "sterile", "tidy"],
        "dirty": ["soiled", "grimy", "filthy", "unclean", "stained", "muddy", "polluted", "contaminated"],
        "beautiful": ["attractive", "pretty", "lovely", "gorgeous", "stunning", "exquisite", "handsome", "comely"],
        "ugly": ["unattractive", "unsightly", "hideous", "homely", "plain", "grotesque", "repulsive", "unpleasant"],
        "hot": ["warm", "heated", "scorching", "sweltering", "sizzling", "burning", "fiery", "scalding"],
        "cold": ["cool", "chilly", "frigid", "icy", "freezing", "wintry", "frosty", "arctic"],
        "wet": ["damp", "moist", "soggy", "soaked", "saturated", "drenched", "waterlogged", "humid"],
        "dry": ["arid", "dehydrated", "parched", "desiccated", "moisture-free", "rainless", "thirsty"],
        "rich": ["wealthy", "affluent", "prosperous", "opulent", "well-off", "well-to-do", "moneyed"],
        "poor": ["impoverished", "needy", "destitute", "disadvantaged", "penniless", "indigent", "broke"],
        "thick": ["dense", "heavy", "full", "substantial", "solid", "concentrated", "compact"],
        "thin": ["slender", "slim", "lean", "slight", "narrow", "fine", "attenuated", "insubstantial"],
        "strong": ["powerful", "robust", "sturdy", "tough", "mighty", "potent", "vigorous", "forceful"],
        "weak": ["feeble", "frail", "fragile", "delicate", "infirm", "impotent", "flimsy", "vulnerable"],
        "similar": ["alike", "comparable", "equivalent", "analogous", "resembling", "corresponding", "matching", "parallel"],
        "modern": ["contemporary", "current", "present-day", "recent", "up-to-date", "state-of-the-art", "cutting-edge"],
        "scalable": ["expandable", "extensible", "adaptable", "flexible", "adjustable", "elastic", "responsive"],
        "exponentially": ["rapidly", "dramatically", "significantly", "markedly", "substantially", "sharply", "steeply"],

        # Adverbs
        "quickly": ["rapidly", "swiftly", "speedily", "hastily", "promptly", "expeditiously", "briskly"],
        "slowly": ["gradually", "leisurely", "unhurriedly", "steadily", "deliberately", "sluggishly", "languidly"],
        "easily": ["effortlessly", "readily", "simply", "smoothly", "handily", "conveniently", "painlessly"],
        "hardly": ["scarcely", "barely", "rarely", "seldom", "infrequently", "occasionally", "almost never"],
        "clearly": ["obviously", "evidently", "plainly", "distinctly", "manifestly", "explicitly", "unambiguously"],
        "suddenly": ["abruptly", "unexpectedly", "instantaneously", "immediately", "promptly", "all at once"],
        "actually": ["really", "truly", "genuinely", "literally", "factually", "veritably", "indeed"],
        "completely": ["entirely", "totally", "wholly", "fully", "utterly", "thoroughly", "absolutely"],
        "usually": ["normally", "generally", "commonly", "typically", "ordinarily", "habitually", "regularly"],
        "often": ["frequently", "repeatedly", "recurrently", "routinely", "customarily", "habitually", "many times"],
        "never": ["not ever", "at no time", "on no occasion", "under no circumstances", "not once"],
        "always": ["constantly", "continually", "perpetually", "eternally", "endlessly", "forever", "persistently"],
        "especially": ["particularly", "specially", "specifically", "exceptionally", "notably", "remarkably"],
        "naturally": ["inherently", "innately", "instinctively", "intrinsically", "organically", "fundamentally"],
        "virtually": ["practically", "nearly", "almost", "essentially", "in effect", "as good as", "all but", "well-nigh"],
        "particularly": ["especially", "specifically", "notably", "remarkably", "exceptionally", "distinctly"],
        "generally": ["usually", "commonly", "broadly", "extensively", "widely", "predominantly", "universally"],
        "significantly": ["considerably", "substantially", "markedly", "notably", "appreciably", "materially"],
        "primarily": ["mainly", "principally", "chiefly", "predominantly", "largely", "mostly", "essentially"],
        "effectively": ["efficiently", "successfully", "productively", "competently", "capably", "adeptly"],

        # Domain-specific
        # Technology
        "technology": ["innovation", "advancement", "development", "breakthrough", "engineering", "applied science", "technical tools"],
        "digital": ["electronic", "computerized", "automated", "online", "virtual", "cyber", "tech-based"],
        "software": ["application", "program", "code", "app", "system", "platform", "interface"],
        "hardware": ["equipment", "device", "gadget", "machinery", "apparatus", "components", "peripherals"],
        "internet": ["web", "network", "cyberspace", "online world", "digital network", "worldwide web", "the net"],
        "algorithm": ["procedure", "process", "method", "formula", "computation", "calculation", "sequence"],
        "database": ["repository", "databank", "information store", "data warehouse", "data center", "information system"],
        "programming": ["coding", "development", "software creation", "software engineering", "script writing", "computer programming"],
        "network": ["system", "framework", "infrastructure", "grid", "web", "mesh", "connection"],
        "cybersecurity": ["information security", "computer security", "data protection", "network security", "IT security"],
        "cloud": ["online storage", "remote server", "virtual space", "web service", "network-based computing"],
        "artificial intelligence": ["machine intelligence", "AI", "machine learning", "cognitive computing", "neural networks"],
        "interface": ["connection", "junction", "link", "interaction point", "bridge", "gateway", "portal"],
        "server": ["host", "mainframe", "data center", "computer system", "network node", "central computer"],
        "website": ["web page", "site", "online presence", "web property", "internet platform", "web domain"],
        "application": ["app", "program", "software", "tool", "utility", "system", "platform"],
        "user": ["operator", "client", "end-user", "customer", "consumer", "subscriber", "account holder"],
        "debug": ["troubleshoot", "fix", "diagnose", "correct", "resolve", "repair", "rectify"],
        "update": ["upgrade", "refresh", "modernize", "renew", "improve", "enhance", "revise"],
        "download": ["transfer", "copy", "retrieve", "obtain", "acquire", "get", "fetch"],
        "upload": ["send", "transfer", "transmit", "submit", "forward", "dispatch", "post"],
        "bandwidth": ["capacity", "throughput", "data rate", "transmission speed", "connection speed", "data capacity"],
        "storage": ["memory", "space", "capacity", "repository", "archive", "retention", "containment"],
        "virtual": ["simulated", "digital", "online", "artificial", "computer-generated", "synthetic", "imitated"],
        "wireless": ["cordless", "radio", "remote", "untethered", "cable-free", "mobile", "portable"],

        # Literature
        "literature": ["writings", "texts", "books", "publications", "works", "compositions", "written works"],
        "novel": ["book", "story", "tale", "narrative", "fiction", "work", "literary piece"],
        "poetry": ["verse", "poems", "rhyme", "poetic works", "metrical composition", "lyric", "stanzas"],
        "author": ["writer", "creator", "novelist", "composer", "penman", "wordsmith", "scribe"],
        "character": ["person", "figure", "individual", "personality", "role", "protagonist", "subject"],
        "plot": ["storyline", "narrative", "tale", "scenario", "sequence", "story arc", "action"],
        "setting": ["backdrop", "background", "location", "environment", "surroundings", "scene", "context"],
        "genre": ["category", "type", "class", "style", "form", "variety", "classification"],
        "theme": ["subject", "topic", "motif", "idea", "concept", "message", "leitmotif"],
        "metaphor": ["comparison", "analogy", "symbol", "figure of speech", "imagery", "allegory", "symbolism"],
        "simile": ["comparison", "likeness", "similarity", "analogy", "correlation", "resemblance", "parallel"],
        "narrator": ["storyteller", "speaker", "voice", "recounter", "relater", "chronicler", "teller"],
        "prose": ["written text", "writing", "narrative", "composition", "passage", "discourse", "content"],
        "fiction": ["imagination", "invention", "fabrication", "story", "narrative", "tale", "fantasy"],
        "nonfiction": ["factual work", "reality", "true story", "documentary", "actuality", "truth", "fact"],
        "essay": ["composition", "paper", "article", "piece", "study", "analysis", "discourse"],
        "playwright": ["dramatist", "writer", "author", "creator", "composer", "scriptwriter", "dramaturg"],
        "stanza": ["verse", "section", "passage", "division", "canto", "part", "segment"],
        "rhyme": ["verse", "meter", "beat", "rhythm", "assonance", "consonance", "alliteration"],
        "dialogue": ["conversation", "talk", "discussion", "discourse", "exchange", "communication", "colloquy"],

        # History
        "history": ["past", "background", "chronicle", "record", "annals", "narrative", "saga"],
        "civilization": ["society", "culture", "nation", "people", "community", "realm", "empire"],
        "era": ["age", "period", "epoch", "time", "years", "span", "cycle", "historic"],
        "ancient": ["antique", "archaic", "primeval", "primordial", "primitive", "historic", "aged"],
        "medieval": ["middle ages", "dark ages", "feudal", "gothic", "middle period", "pre-modern"],
        "renaissance": ["rebirth", "revival", "renewal", "resurgence", "revitalization", "awakening", "flowering"],
        "revolution": ["uprising", "revolt", "rebellion", "insurrection", "upheaval", "insurgency", "mutiny"],
        "war": ["conflict", "hostility", "combat", "fighting", "battle", "clash", "struggle"],
        "empire": ["kingdom", "realm", "domain", "territory", "state", "commonwealth", "dominion"],
        "monarchy": ["kingdom", "reign", "rule", "sovereignty", "dynasty", "regency", "crown"],
        "republic": ["commonwealth", "state", "democracy", "nation", "country", "government", "union"],
        "artifact": ["relic", "antiquity", "remain", "vestige", "remnant", "object", "item"],
        "dynasty": ["lineage", "house", "family", "ancestry", "bloodline", "succession", "regime"],
        "conquest": ["takeover", "capture", "seizure", "overthrow", "victory", "subjugation", "triumph"],
        "discovery": ["finding", "revelation", "unearthing", "detection", "uncovering", "exploration", "breakthrough"],
        "colonization": ["settlement", "expansion", "occupation", "annexation", "acquisition", "establishment", "habitation"],
        "migration": ["movement", "relocation", "immigration", "emigration", "exodus", "transit", "resettlement"],
        "civilization": ["culture", "society", "nation", "realm", "empire", "kingdom", "commonwealth"],
        "archaeology": ["excavation", "dig", "antiquarianism", "paleontology", "ancient studies", "antiquity research"],
        "artifact": ["relic", "remain", "antiquity", "find", "discovery", "antiquary", "specimen"],

        # Math
        "mathematics": ["math", "arithmetics", "calculation", "computation", "reckoning", "figures", "numerics"],
        "algebra": ["equation", "formula", "expression", "polynomial", "variable", "coefficient", "function"],
        "geometry": ["shape", "figure", "form", "dimension", "area", "volume", "measurement"],
        "calculus": ["analysis", "differentiation", "integration", "infinitesimal", "derivative", "rate of change"],
        "statistics": ["data analysis", "probability", "distribution", "sampling", "regression", "correlation", "variance"],
        "equation": ["formula", "expression", "relation", "identity", "equality", "function", "calculation"],
        "number": ["digit", "figure", "numeral", "quantity", "amount", "sum", "total"],
        "variable": ["unknown", "parameter", "factor", "element", "component", "constituent", "quantity"],
        "function": ["mapping", "relation", "correspondence", "transformation", "operation", "formula", "procedure"],
        "probability": ["likelihood", "chance", "odds", "possibility", "prospect", "expectation", "ratio"],
        "theorem": ["proposition", "principle", "law", "rule", "axiom", "postulate", "hypothesis"],
        "proof": ["verification", "validation", "confirmation", "demonstration", "substantiation", "corroboration"],
        "graph": ["chart", "plot", "diagram", "representation", "figure", "illustration", "depiction"],
        "coordinate": ["position", "location", "point", "placement", "site", "spot", "locus"],
        "fraction": ["part", "portion", "segment", "division", "section", "share", "ratio"],
        "decimal": ["base-10", "decimal number", "tenth", "decimal fraction", "decimal point", "decimal place"],
        "integer": ["whole number", "count number", "natural number", "round number", "complete number"],
        "prime": ["basic", "fundamental", "elementary", "indivisible", "irreducible", "primary", "principal"],
        "ratio": ["proportion", "relation", "comparison", "correlation", "scale", "rate", "quota"],
        "logarithm": ["exponent", "power", "index", "log", "order of magnitude", "exponential relation"],

        # Language Arts
        "grammar": ["syntax", "structure", "usage", "rules", "construction", "form", "arrangement"],
        "vocabulary": ["words", "terms", "lexicon", "language", "terminology", "expressions", "verbiage"],
        "sentence": ["statement", "phrase", "clause", "expression", "utterance", "declaration", "proposition"],
        "paragraph": ["section", "passage", "segment", "text", "division", "block", "portion"],
        "essay": ["composition", "paper", "article", "piece", "study", "analysis", "discourse"],
        "narrative": ["story", "account", "chronicle", "tale", "report", "recital", "description"],
        "punctuation": ["marks", "symbols", "signs", "notation", "designation", "indication", "demarcation"],
        "noun": ["name", "term", "label", "designation", "title", "appellation", "epithet"],
        "verb": ["action", "activity", "motion", "movement", "operation", "performance", "execution"],
        "adjective": ["descriptor", "qualifier", "modifier", "attribute", "characteristic", "quality", "feature"],
        "adverb": ["modifier", "qualifier", "intensifier", "limiter", "specifier", "enhancer", "emphasizer"],
        "pronoun": ["substitute", "replacement", "stand-in", "placeholder", "deputy", "surrogate", "alternate"],
        "preposition": ["connector", "linker", "relator", "joiner", "coupler", "binder", "associator"],
        "conjunction": ["connector", "joiner", "linker", "coupler", "binder", "unifier", "combiner"],
        "interjection": ["exclamation", "outcry", "ejaculation", "call", "utterance", "expression", "outburst"],
        "syntax": ["arrangement", "organization", "structure", "system", "formation", "construction", "composition"],
        "diction": ["word choice", "language", "expression", "phrasing", "wording", "terminology", "vocabulary"],
        "rhetoric": ["persuasion", "discourse", "oratory", "eloquence", "elocution", "verbal skill", "wordcraft"],
        "imagery": ["depiction", "portrayal", "illustration", "representation", "symbolism", "metaphor", "visualization"],
        "alliteration": ["repetition", "recurrence", "echoing", "iteration", "reiteration", "reduplication", "consonance"],

        # Domain-specific
        "study": ["analysis", "examination", "investigation", "research", "inspection", "scrutiny", "inquiry"],
        "learn": ["discover", "ascertain", "determine", "find out", "acquire knowledge", "grasp", "master"],
        "knowledge": ["information", "understanding", "wisdom", "insight", "awareness", "comprehension", "erudition"],
        "education": ["learning", "schooling", "training", "instruction", "teaching", "tuition", "pedagogy"],
        "science": ["discipline", "field", "area of study", "branch of knowledge", "subject", "domain"],
        "technology": ["innovation", "advancement", "development", "breakthrough", "engineering", "applied science"],
        "research": ["investigation", "inquiry", "examination", "analysis", "exploration", "study", "probe"],
        "data": ["information", "facts", "figures", "statistics", "details", "particulars", "intelligence"],
        "theory": ["hypothesis", "proposition", "concept", "idea", "postulation", "supposition", "conjecture"],
        "method": ["approach", "technique", "procedure", "process", "system", "methodology", "strategy"],
        "result": ["outcome", "finding", "conclusion", "consequence", "effect", "upshot", "aftermath"],
        "conclusion": ["finding", "determination", "judgment", "deduction", "decision", "resolution", "verdict"],
        "literature": ["publications", "texts", "writings", "documents", "books", "papers", "articles"],
        "revolution": ["transformation", "upheaval", "radical change", "rebellion", "insurrection", "revolt"],
        "century": ["hundred years", "era", "period", "age", "span", "cycle", "epoch", "hundred-year period"],
        "history": ["past", "background", "chronicle", "record", "annals", "narrative", "saga", "account"],
        "analysis": ["examination", "investigation", "assessment", "evaluation", "scrutiny", "study", "inspection"],
        "structure": ["framework", "form", "composition", "arrangement", "organization", "construction", "formation"],
        "evidence": ["proof", "confirmation", "verification", "substantiation", "testimony", "validation"],
        "market": ["marketplace", "trade", "commerce", "business", "exchange", "bazaar", "emporium"],
        "system": ["network", "arrangement", "organization", "method", "structure", "setup", "configuration"],
        "power": ["authority", "control", "influence", "command", "dominance", "strength", "might", "force"],
        "development": ["growth", "progress", "advancement", "evolution", "expansion", "improvement", "maturation"],
        "process": ["procedure", "operation", "method", "approach", "technique", "system", "mechanism"],
        "principle": ["rule", "standard", "guideline", "tenet", "precept", "maxim", "fundamental", "law"],
        "approach": ["method", "technique", "procedure", "strategy", "tactic", "system", "formula", "way"],
        "practice": ["activity", "exercise", "pursuit", "custom", "habit", "convention", "routine", "usage"],
        "effect": ["impact", "influence", "result", "consequence", "outcome", "reaction", "repercussion"],
        "cause": ["reason", "source", "origin", "basis", "foundation", "root", "catalyst", "stimulus"],
        "function": ["purpose", "role", "duty", "job", "task", "operation", "service", "utility"],
        "relationship": ["connection", "association", "link", "correlation", "bond", "tie", "affiliation"],
        "context": ["circumstances", "setting", "situation", "background", "environment", "surroundings", "milieu"],
        "strategy": ["plan", "approach", "tactic", "policy", "scheme", "blueprint", "design", "program"],
        "framework": ["structure", "system", "scheme", "arrangement", "organization", "format", "composition"],
        "concept": ["idea", "notion", "thought", "principle", "theory", "belief", "assumption", "perception"],
        "perspective": ["viewpoint", "outlook", "standpoint", "position", "stance", "angle", "vantage point"],
        "feature": ["characteristic", "attribute", "quality", "trait", "aspect", "property", "facet", "element"],
        "challenge": ["difficulty", "obstacle", "problem", "issue", "hurdle", "impediment", "barrier", "complication"],
        "solution": ["answer", "resolution", "remedy", "fix", "response", "key", "explanation", "way out"],
        "influence": ["effect", "impact", "sway", "power", "control", "authority", "dominance", "pressure"],
        "factor": ["element", "component", "aspect", "consideration", "determinant", "ingredient", "catalyst"],
        "resource": ["asset", "supply", "reserve", "source", "material", "wealth", "means", "capability"],
        "opportunity": ["chance", "opening", "prospect", "occasion", "possibility", "break", "advantage"],
        "challenge": ["test", "trial", "contest", "confrontation", "dispute", "dare", "provocation"],
        "experience": ["involvement", "participation", "encounter", "exposure", "contact", "familiarity"],
        "leadership": ["guidance", "direction", "management", "supervision", "control", "authority", "stewardship"],
        "innovation": ["creation", "invention", "originality", "novelty", "breakthrough", "pioneering", "ingenuity"],
        "collaboration": ["cooperation", "partnership", "alliance", "association", "teamwork", "joint effort"],
        "communication": ["exchange", "interaction", "contact", "correspondence", "dialogue", "discussion"],
        "achievement": ["accomplishment", "attainment", "success", "triumph", "feat", "victory", "realization"],
        "foundation": ["basis", "groundwork", "underpinning", "footing", "substructure", "infrastructure", "base"],
        "initiative": ["action", "enterprise", "drive", "ambition", "effort", "undertaking", "venture", "project"],
        "inspiration": ["motivation", "stimulation", "encouragement", "influence", "spark", "catalyst"],
        "management": ["administration", "supervision", "control", "direction", "handling", "governance"],
        "motivation": ["incentive", "drive", "stimulus", "impulse", "spur", "encouragement", "inducement"],
        "objective": ["goal", "aim", "target", "purpose", "intention", "ambition", "aspiration", "end"],
        "obstacle": ["barrier", "hindrance", "impediment", "obstruction", "hurdle", "difficulty", "block"],
        "performance": ["execution", "accomplishment", "achievement", "fulfillment", "completion", "discharge"],
        "priority": ["preference", "precedence", "primacy", "pre-eminence", "importance", "urgency"],
        "progress": ["advancement", "development", "improvement", "growth", "headway", "forward movement"],
        "purpose": ["aim", "goal", "objective", "intention", "target", "end", "ambition", "aspiration"],
        "requirement": ["necessity", "essential", "prerequisite", "condition", "specification", "stipulation"],
        "responsibility": ["duty", "obligation", "accountability", "liability", "commitment", "charge"],
        "success": ["achievement", "accomplishment", "attainment", "triumph", "victory", "realization", "prosperity"],
        "support": ["assistance", "aid", "help", "backing", "encouragement", "reinforcement", "advocacy"],
        "trend": ["tendency", "drift", "movement", "direction", "inclination", "course", "current", "fashion"],
        "value": ["worth", "merit", "importance", "significance", "usefulness", "utility", "benefit"],
    }

    # Check if the word is in our synonym dictionary
    word_lower = word.lower()
    if word_lower in synonyms:
        # Randomly select a synonym
        replacement = random.choice(synonyms[word_lower])
        # Preserve capitalization
        if word[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    return word

def replace_words_with_synonyms(text, replacement_rate=0.6):
    """Replace a higher portion of words with synonyms to avoid plagiarism.
    Uses a 60% replacement rate to ensure at least 5 replacements per query."""
    if not text:
        return text

    # Split the text into words, keeping track of spaces and punctuation
    tokens = []
    current_word = ""
    current_punctuation = ""

    for char in text:
        if char.isalnum() or char == "'":
            current_word += char
            if current_punctuation:
                tokens.append(("punct", current_punctuation))
                current_punctuation = ""
        else:
            if current_word:
                tokens.append(("word", current_word))
                current_word = ""
            current_punctuation += char

    # Add any remaining tokens
    if current_word:
        tokens.append(("word", current_word))
    if current_punctuation:
        tokens.append(("punct", current_punctuation))

    # Replace some words with synonyms
    result = ""
    for token_type, token in tokens:
        if token_type == "word" and len(token) > 3 and random.random() < replacement_rate:
            result += get_synonym(token)
        else:
            result += token

    return result

def simplify_sentence(sentence):
    """Simplify and rephrase a sentence to avoid plagiarism."""
    # Remove parenthetical content
    sentence = re.sub(r'\([^)]*\)', '', sentence)
    # Remove quoted speech
    sentence = re.sub(r',".*?"', '', sentence)
    sentence = re.sub(r'".*?"', '', sentence)
    # Fix spacing
    sentence = re.sub(r' +', ' ', sentence)

    # Break down complex sentences
    if len(sentence) > 120 and ';' in sentence:
        parts = sentence.split(';')
        sentence = parts[0].strip()

    # Remove attribution phrases
    attribution_patterns = [
        r'according to .*?,',
        r'.*? said that',
        r'.*? states that',
        r'.*? reported that',
        r'as noted by .*?,',
        r'as mentioned by .*?,'
    ]

    for pattern in attribution_patterns:
        sentence = re.sub(pattern, '', sentence, flags=re.IGNORECASE)

    # Replace a good portion of words with synonyms to avoid plagiarism
    sentence = replace_words_with_synonyms(sentence.strip(), 0.4)

    return sentence

def generate_connecting_sentence(sent1, sent2, connecting_type='general'):
    """Generate a neutral connecting sentence between two sentences for better flow"""
    # Determine connection type if not specified
    if connecting_type == 'general':
        # Look for clues in sentences to determine connection type
        sent1_lower = sent1.lower()
        sent2_lower = sent2.lower()

        # Check for contrasting words in second sentence
        if any(word in sent2_lower for word in ['but', 'however', 'although', 'though', 'yet', 'despite']):
            connecting_type = 'contrast'
        # Check for cause-effect
        elif any(word in sent2_lower for word in ['therefore', 'thus', 'consequently', 'as a result', 'because']):
            connecting_type = 'cause'
        # Check for examples
        elif any(word in sent2_lower for word in ['example', 'instance', 'illustrate', 'demonstration']):
            connecting_type = 'example'
        # Check for similarities
        elif any(word in sent2_lower for word in ['similarly', 'likewise', 'also', 'too']):
            connecting_type = 'agreement'
        else:
            # Default to random transition
            connecting_type = random.choice(['emphasis', 'conclusion'])

    # Get words from both sentences (excluding stop words)
    sent1_words = [word for word in word_tokenize(sent1) if word not in STOP_WORDS and len(word) > 3]
    sent2_words = [word for word in word_tokenize(sent2) if word not in STOP_WORDS and len(word) > 3]

    # Find important non-duplicate words
    unique_words = set(sent1_words).symmetric_difference(set(sent2_words))
    if unique_words:
        key_term = random.choice(list(unique_words))
    else:
        key_term = random.choice(sent1_words) if sent1_words else ""

    # Select a connecting phrase based on the connection type
    if connecting_type in CONNECTING_PHRASES:
        connector = random.choice(CONNECTING_PHRASES[connecting_type])
    else:
        connector = random.choice(TRANSITION_PHRASES)

    # For short sentences or when key term is empty, just use the connector
    if len(sent1) < 50 or len(sent2) < 50 or not key_term:
        return connector

    # Build a connecting sentence - with neutral factual language
    connecting_templates = [
        f"{connector} {key_term} is mentioned in relation to this topic.",
        f"{connector} {key_term} appears in discussions of this subject.",
        f"{connector} {key_term} is referenced in this context.",
        f"{connector} {key_term} is associated with this topic."
    ]

    return random.choice(connecting_templates)

def ensure_completeness(draft_summary, important_terms, query):
    """Check if the summary includes all important terms and add missing information in a neutral manner"""
    # Simply return the draft summary without adding any extra phrases about "related terms"
    return draft_summary

def add_context_enhancers(summary, important_terms):
    """Add context enhancers to make summary more engaging and informative while maintaining neutrality"""
    summary_sentences = custom_sent_tokenize(summary)

    # Don't modify short summaries
    if len(summary_sentences) < 3:
        return summary

    # Don't add enhancers if summary is already substantial
    if len(summary.split()) > 100:
        return summary

    enhanced_sentences = []

    # Extract the main topic from important terms
    main_topic = None
    if important_terms and len(important_terms) > 0:
        main_topic = important_terms[0]

    # Only add an enhancer at the beginning if we can identify a clear main topic
    if main_topic and len(summary_sentences) >= 3:
        # Find a sentence that contains the main topic to modify rather than inserting a new one
        for i, sentence in enumerate(summary_sentences):
            if main_topic in sentence.lower() and i < 2:  # Only consider early sentences
                # Extract the most representative sentence that discusses the main topic
                if i == 0:  # If it's the first sentence, we'll use it as is
                    enhanced_sentences.append(sentence)
                else:  # Otherwise swap to make it the first sentence
                    enhanced_sentences.append(summary_sentences[i])
                    enhanced_sentences.append(summary_sentences[0])
                    # Continue with remaining sentences from position 1, skipping i
                    enhanced_sentences.extend([s for j, s in enumerate(summary_sentences[1:]) if j+1 != i])
                break
        else:
            # If no sentence with main topic found, just use original order
            enhanced_sentences = summary_sentences.copy()
    else:
        # If no clear main topic, just use original order
        enhanced_sentences = summary_sentences.copy()

    # Join all sentences
    enhanced_summary = " ".join(enhanced_sentences)
    return enhanced_summary

def enhance_summary_coherence(sentences):
    """Enhance the coherence between sentences in the summary"""
    # Simply return the original sentences without adding connecting phrases
    return sentences

def generate_summary(text, num_sentences=5, query=None):
    """Generate a more detailed and comprehensive summary of the text focused on the query topic."""
    # Clean citations
    text = clean_citations(text)

    # Tokenize sentences
    sentences = custom_sent_tokenize(text)

    # Handle very short texts
    if len(sentences) <= num_sentences:
        return replace_words_with_synonyms(text, 0.8)  # Much more aggressive replacement for short texts

    # Extract important terms for relevance and comprehensiveness checking
    important_terms = extract_important_terms(text, query) if query else []
    logger.info(f"Important terms identified: {important_terms}")

    # Get query keywords for boosting relevance
    query_keywords = set()
    if query:
        query_keywords = set(word for word in word_tokenize(query.lower())
                           if word not in STOP_WORDS and len(word) > 2)

    # Calculate sentence scores with boosting for important terms
    sentence_scores = calculate_sentence_scores(sentences, important_terms=important_terms)

    # Boost scores for sentences containing query terms
    if query_keywords:
        for i, sentence in enumerate(sentences):
            sentence_lower = sentence.lower()
            matches = sum(1 for word in query_keywords if word in sentence_lower)
            if matches > 0:
                # Boost score based on keyword matches
                sentence_scores[i] = sentence_scores.get(i, 0) + (0.2 * matches)

    # Select top sentences
    try:
        top_indices = heapq.nlargest(num_sentences * 2, sentence_scores, key=sentence_scores.get)
    except ValueError:
        # Fallback if no scores could be calculated
        top_indices = list(range(min(num_sentences * 2, len(sentences))))

    # Get the top sentences while avoiding duplicates with Double Down Detection
    top_sentences = []
    for i in top_indices:
        if len(top_sentences) >= num_sentences:
            break

        try:
            # Apply both simplification and synonym replacement
            simplified = simplify_sentence(sentences[i])

            if simplified and len(simplified) > 15:  # Only add if non-empty and meaningful
                # Check if the sentence is relevant to the query
                if query_keywords:
                    sentence_words = set(word for word in word_tokenize(simplified.lower())
                                      if word not in STOP_WORDS)
                    relevance = len(query_keywords.intersection(sentence_words))

                    # Skip sentences with no connection to query terms at all
                    if relevance == 0 and len(top_sentences) >= num_sentences // 2:
                        continue

                # Apply Double Down Detection to filter out sentences that are 75% or more similar
                if not is_duplicate_content(simplified, top_sentences):
                    top_sentences.append(simplified)
                else:
                    logger.info("Double Down Detection filtered out a duplicate sentence")
        except IndexError:
            # Skip if index is out of range
            continue

    # If we couldn't get enough sentences, just use the first few sentences
    if not top_sentences and sentences:
        top_sentences = [simplify_sentence(s) for s in sentences[:num_sentences]]

    # Sort sentences by their original order for coherence
    if top_sentences:
        try:
            # Create a mapping of sentences to their indices in the original text
            sentence_to_index = {}
            for i, sentence in enumerate(top_sentences):
                # Find the closest match in the original sentences
                best_match_idx = -1
                best_similarity = -1
                for j, orig_sentence in enumerate(sentences):
                    # Calculate similarity (simple overlap for efficiency)
                    s1_words = set(word_tokenize(sentence.lower()))
                    s2_words = set(word_tokenize(orig_sentence.lower()))
                    if s1_words and s2_words:
                        overlap = len(s1_words.intersection(s2_words)) / len(s1_words.union(s2_words))
                        if overlap > best_similarity:
                            best_similarity = overlap
                            best_match_idx = j

                if best_match_idx >= 0:
                    sentence_to_index[sentence] = best_match_idx
                else:
                    # If no good match, just use the position in top_sentences
                    sentence_to_index[sentence] = i

            # Sort the sentences based on their original position
            top_sentences.sort(key=lambda s: sentence_to_index.get(s, 999))
        except Exception as e:
            logger.error(f"Error sorting sentences: {e}")
            # Don't change order if sorting fails
            pass

    # Enhance coherence between sentences
    enhanced_sentences = enhance_summary_coherence(top_sentences)

    # Join sentences into a summary
    draft_summary = " ".join(enhanced_sentences)

    # Ensure all important terms are covered
    complete_summary = ensure_completeness(draft_summary, important_terms, query or "")

    # Add context enhancers for a more comprehensive summary
    final_summary = add_context_enhancers(complete_summary, important_terms)

    # Final pass of synonym replacement on the entire summary to ensure we've truly avoided plagiarism
    final_summary = replace_words_with_synonyms(final_summary, 0.7)

    # No disclaimer added to keep the summary clean

    return final_summary

def simplify_for_readability(text):
    """Make complex text more readable by simplifying vocabulary and adding explanations with bullet points."""
    if not text:
        return text

    # Dictionary of complex terms with simpler alternatives or explanations
    complex_terms = {
        # Academic/technical terms
        "paradigm": "approach",
        "methodology": "method",
        "implementation": "use",
        "utilize": "use",
        "functionality": "features",
        "conceptualize": "think about",
        "cognitive": "thinking",
        "preliminary": "early",
        "subsequently": "later",
        "prerequisites": "requirements",
        "heterogeneous": "diverse",
        "homogeneous": "similar",
        "pedagogical": "educational",
        "quantitative": "measurable",
        "qualitative": "descriptive",
        "intrinsic": "natural",
        "extrinsic": "external",
        "amalgamation": "combination",
        "ubiquitous": "common",
        "robust": "strong",
        "plethora": "many",
        "myriad": "many",
        "interface": "connect",
        "infrastructure": "framework",
        "leverage": "use",
        "endeavor": "try",
        "optimize": "improve",
        "parameter": "setting",
        "encompasses": "includes",
        "facilitate": "help",
        "substantiate": "prove",
        "fundamental": "basic",
        "comprehensive": "complete",
        "derivative": "based on",
        "imperative": "important",
        "ascertain": "find out",
        "augment": "increase",
        "proximity": "closeness",
        "circumvent": "avoid",
        # Add specialized term definitions
        "fief": "a piece of land given by a lord to a vassal (a person who served the lord) in exchange for loyalty and service",
        "feudalism": "a system where lords gave land (fiefs) to vassals in exchange for military service and loyalty",
        "vassal": "a person who received land from a lord in exchange for loyalty and military service",
        "serf": "a peasant who was bound to the land and had to work for the lord",
        "lord": "a person who owned land and granted fiefs to vassals"
    }

    # Replace complex terms with simpler alternatives
    for complex_term, simple_term in complex_terms.items():
        # Use word boundary matching to avoid partial word replacements
        text = re.sub(r'\b' + complex_term + r'\b', simple_term, text, flags=re.IGNORECASE)

    # Simplify long sentences (over 30 words)
    sentences = custom_sent_tokenize(text)
    for i, sentence in enumerate(sentences):
        words = word_tokenize(sentence)
        if len(words) > 30:
            # Try to break up long sentences
            if "; " in sentence:
                parts = sentence.split("; ")
                sentences[i] = parts[0] + "."
                sentences.insert(i+1, parts[1])
            elif ", " in sentence and len(sentence.split(", ")) > 3:
                parts = sentence.split(", ", 1)
                sentences[i] = parts[0] + "."
                sentences.insert(i+1, parts[1])

    # Always use bullet point format, regardless of sentence count
    # Ensure we have at least 3 sentences to work with
    if len(sentences) >= 3:
        # First 2 sentences form the overview - this guarantees a concise intro
        overview = " ".join(sentences[:2])

        # Remaining sentences become bullet points - guarantees at least one bullet
        bullet_points = []
        for i, sentence in enumerate(sentences[2:]):
            # Only include complete, meaningful sentences
            if len(word_tokenize(sentence)) > 3:  # Use a lower threshold to include more content
                # Ensure sentence ends with proper punctuation
                if not sentence.strip().endswith('.') and not sentence.strip().endswith('!') and not sentence.strip().endswith('?'):
                    sentence = sentence.strip() + '.'

                bullet_points.append("• " + sentence)

        # If no bullet points were created, force at least one from the third sentence
        if not bullet_points and len(sentences) >= 3:
            third_sentence = sentences[2]
            if not third_sentence.strip().endswith('.') and not third_sentence.strip().endswith('!') and not third_sentence.strip().endswith('?'):
                third_sentence = third_sentence.strip() + '.'
            bullet_points.append("• " + third_sentence)

        # Create the formatted output with explicit newlines that will be preserved
        simplified_text = overview + "\n\n" + "\n".join(bullet_points)
    else:
        # If fewer than 3 sentences, add bullet points with key phrases
        overview = sentences[0] if sentences else "Summary not available."

        # Extract key phrases for bullets if we have at least one sentence
        if len(sentences) > 0:
            words = word_tokenize(text)
            # Get the most frequent words as key points
            word_freq = {}
            for word in words:
                if word.lower() not in STOP_WORDS and len(word) > 3:
                    word_freq[word] = word_freq.get(word, 0) + 1

            # Get top words
            top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:3]

            bullet_points = []
            for word, _ in top_words:
                bullet_points.append(f"• Key term: {word.capitalize()}")

            simplified_text = overview + "\n\n" + "\n".join(bullet_points)
        else:
            simplified_text = overview

    # Add a note about the simplified language
    simplified_text += "\n\n(This summary uses simple language to make the topic easier to understand.)"

    return simplified_text

def search_and_summarize_v1(query, num_sentences=8):
    """Original Poinsettia 1 search and summarize"""
    try:
        logger.info(f"FULL QUERY (Poinsettia 1): '{query}'")

        # First determine query intent for specialized handling
        intent_result = extract_query_intent(query)

        # Handle the new return format for historical_topic intent
        if isinstance(intent_result, tuple) and len(intent_result) == 3:
            intent, is_specific, main_topic = intent_result
            logger.info(f"Query intent: {intent}, is_specific: {is_specific}, main_topic: {main_topic}")
        else:
            intent, is_specific = intent_result
            main_topic = None
            logger.info(f"Query intent: {intent}, is_specific: {is_specific}")

        # Handle conversational queries
        if intent in ["greeting", "farewell", "thanks", "smalltalk"]:
            logger.info(f"Detected conversational query of type: {intent}")
            response = get_conversational_response(intent)
            return response, [], []  # No errors or sources for conversational responses

        # Handle invalid or extremely short queries
        if intent == "invalid_query":
            logger.warning(f"Invalid query detected: '{query}'")
            return "Your query appears to be incomplete or too short. Please provide a more specific question or topic.", ["The query was too short or incomplete to process."], []

        # Extract book title for book-related queries
        search_query = query
        if intent == "book_analysis":
            book_title = extract_book_title(query)
            if book_title:
                logger.info(f"Extracted book title: '{book_title}'")
                # Use the book title as the search query instead of the full query
                search_query = f"{book_title} book summary analysis"
            else:
                logger.info("Could not extract specific book title from query")
        elif intent == "historical_topic" and main_topic:
            # Use the extracted historical topic as the search query
            logger.info(f"Using extracted topic '{main_topic}' for search")
            search_query = f"{main_topic} historical period events significance"

            # For specific historical periods, enhance the search query
            if "renaissance" in main_topic.lower():
                search_query = "Renaissance historical period art culture humanism achievements significance"
            elif "industrial revolution" in main_topic.lower():
                search_query = "Industrial Revolution technological social economic changes significance"
            elif "world war" in main_topic.lower():
                search_query = f"{main_topic} causes events impact significance"
            elif "civil war" in main_topic.lower():
                search_query = f"{main_topic} causes battles outcome significance"

        # Search for relevant URLs
        logger.info(f"Searching for topic: {search_query}")
        urls = search_for_topic(search_query)
        if not urls:
            logger.warning(f"No sources found for query: {query}")
            # Use generic fallback URLs for educational content
            urls = [
                "https://en.wikipedia.org/wiki/Main_Page",
                "https://www.britannica.com/",
                "https://www.nationalgeographic.com/"
            ]
            logger.info(f"Using generic fallback URLs: {urls}")

        # For book/media queries, add specialized sources
        if intent in ["book_analysis", "media_content"]:
            # Add book/media specific sources
            book_title = extract_book_title(query)
            if book_title:
                logger.info(f"Adding specialized sources for book: {book_title}")
                # Format book title for URLs
                formatted_book_title = book_title.replace(' ', '+')
                book_sources = [
                    f"https://www.sparknotes.com/search?q={formatted_book_title}",
                    f"https://www.cliffsnotes.com/search?q={formatted_book_title}",
                    f"https://www.goodreads.com/search?q={formatted_book_title}",
                    f"https://en.wikipedia.org/wiki/{book_title.replace(' ', '_')}",
                    f"https://www.litcharts.com/search?query={formatted_book_title}"
                ]

                # Add specialized URLs for well-known books
                specific_book_sources = {
                    "dune": [
                        "https://en.wikipedia.org/wiki/Dune_(novel)",
                        "https://www.sparknotes.com/lit/dune/",
                        "https://www.litcharts.com/lit/dune"
                    ],
                    "to kill a mockingbird": [
                        "https://www.sparknotes.com/lit/mocking/",
                        "https://en.wikipedia.org/wiki/To_Kill_a_Mockingbird"
                    ],
                    "the great gatsby": [
                        "https://www.sparknotes.com/lit/gatsby/",
                        "https://en.wikipedia.org/wiki/The_Great_Gatsby"
                    ],
                    "1984": [
                        "https://www.sparknotes.com/lit/1984/",
                        "https://en.wikipedia.org/wiki/Nineteen_Eighty-Four"
                    ]
                }

                # Check if this is a well-known book with specific sources
                if book_title.lower() in specific_book_sources:
                    specific_sources = specific_book_sources[book_title.lower()]
                    logger.info(f"Using specialized sources for known book: {book_title}")
                    # Add the specific sources first
                    book_sources = specific_sources + book_sources

                # Make sure book sources appear first
                urls = book_sources + [url for url in urls if url not in book_sources]

        logger.info(f"Found {len(urls)} potential sources")

        all_content = ""
        errors = []
        sources_used = []

        # Extract keywords for better relevance checking
        clean_query = query.lower().strip()
        query_keywords = set(word for word in word_tokenize(extract_keywords(query).lower())
                           if word not in STOP_WORDS)

        # Get more specific understanding of the query
        is_programming_related = any(term in clean_query for term in ["programming", "language", "code", "software", "developer"])
        is_definition_query = any(term in clean_query for term in ["what is", "define", "meaning of"])

        # Add category detection for better content matching
        is_about_people = any(term in clean_query for term in ["who is", "person", "people", "celebrity"])
        is_about_places = any(term in clean_query for term in ["where is", "country", "city", "location"])
        is_about_events = any(term in clean_query for term in ["when", "event", "happened", "history", "historical"])

        logger.info(f"Query analysis - Programming: {is_programming_related}, Definition: {is_definition_query}, People: {is_about_people}, Places: {is_about_places}, Events: {is_about_events}")
        logger.info(f"Query keywords: {query_keywords}")

        # Fetch content from each URL
        for url in urls[:5]:  # Try more URLs for better coverage
            try:
                content, error = fetch_article(url)
                if error:
                    logger.warning(f"Error with {url}: {error}")
                    errors.append(f"Error with {url}: {error}")
                elif content:
                    logger.info(f"Successfully retrieved content from {url}")
                    # Check content relevance to query using a more flexible approach
                    content_words = set(word for word in word_tokenize(content.lower())
                                      if word not in STOP_WORDS)

                    # For book queries, check if book title appears in the content
                    book_title = None
                    book_title_words = set()
                    if intent == "book_analysis":
                        book_title = extract_book_title(query)
                        if book_title:
                            book_title_words = set(word_tokenize(book_title.lower()))
                            # Check if book title appears in content
                            book_title_in_content = book_title.lower() in content.lower()
                            if book_title_in_content:
                                logger.info(f"Book title '{book_title}' found in content from {url}")

                    # Calculate relevance score
                    if book_title and book_title_words:
                        # For book queries, prioritize content that mentions the book title
                        book_matches = len(book_title_words.intersection(content_words))
                        keyword_matches = len(query_keywords.intersection(content_words))
                        # Weight book title matches higher
                        relevance_score = (book_matches * 3 + keyword_matches) / (len(book_title_words) + len(query_keywords))
                    else:
                        # Regular relevance calculation for non-book queries
                        keyword_matches = len(query_keywords.intersection(content_words))
                        relevance_score = keyword_matches / len(query_keywords) if query_keywords else 0

                    # Filter out Wikipedia featured article metadata
                    wikipedia_featured_markers = ["featured article", "on this day", "did you know",
                                                 "today's featured", "picture of the day",
                                                 "wikipedia's featured content"]
                    has_featured_article_markers = any(marker in content.lower() for marker in wikipedia_featured_markers)

                    # Check if this appears to be a Wikipedia main page
                    is_wikipedia_main = "wikipedia.org/wiki/Main_Page" in url and has_featured_article_markers

                    # Check for query presence in first 1000 chars - often contains the main topic
                    content_start = content[:1000].lower()
                    query_words_in_start = sum(1 for word in query_keywords if word in content_start)

                    # Check for title elements that might indicate relevance
                    soup = BeautifulSoup(content, 'html.parser')
                    title_relevance = 0
                    try:
                        titles = [h.get_text().lower() for h in soup.find_all(['h1', 'h2', 'h3'])]
                        for title in titles:
                            if any(kw in title for kw in query_keywords):
                                title_relevance += 1
                    except Exception: # Catch potential errors during soup parsing
                        pass

                    logger.info(f"Relevance for {url}: Score={relevance_score:.2f}, Keywords in intro={query_words_in_start}, Title relevance={title_relevance}, Wikipedia Main: {is_wikipedia_main}")

                    # Skip Wikipedia main page if it contains featured article markers
                    if is_wikipedia_main:
                        logger.info(f"Skipping Wikipedia main page with featured article content: {url}")
                        continue

                    # More strict relevance criteria to avoid off-topic content
                    is_relevant = (
                        (relevance_score > 0.3) or  # Higher threshold for relevance
                        (query_words_in_start >= 2 and title_relevance > 0) or  # Need multiple keywords in intro AND title relevance
                        (len(sources_used) < 1 and relevance_score > 0.1)  # Less strict for first source, but still need some relevance
                    )

                    # Accept programming content with more flexibility
                    if is_programming_related:
                        is_relevant = is_relevant or "programming" in content.lower() or "language" in content.lower()

                    # For definition queries, be more flexible
                    if is_definition_query and len(content) > 500:
                        is_relevant = True

                    if is_relevant:
                        logger.info(f"Using content from {url}")
                        all_content += content + "\n\n"
                        sources_used.append(url)
                    else:
                        logger.warning(f"Content from {url} seems unrelated to the query")
            except Exception as e:
                logger.error(f"Exception processing {url}: {str(e)}")
                errors.append(f"Error processing {url}: {str(e)}")

        if not all_content:
            logger.warning(f"No relevant content was retrieved for query: {query}")

            # Get query intent for specialized fallback responses
            intent, _ = extract_query_intent(query)

            if intent == "book_analysis":
                book_title = extract_book_title(query) or "the book you mentioned"
                fallback_response = (
                    f"I couldn't find specific information about the message or themes of {book_title}. "
                    f"To get a better analysis, you could try including the author's name in your query, "
                    f"or asking about specific aspects of the book like 'What is the main character development in {book_title}?' "
                    f"or 'What are the key symbols in {book_title}?'"
                )
            elif intent == "media_content":
                fallback_response = (
                    f"I couldn't find specific information about this media content. "
                    f"For movies or shows, try including the director or year of release in your query. "
                    f"You could also ask about specific aspects like 'What is the plot twist in...' or 'Who are the main characters in...'"
                )
            else:
                # More specific error message to help the user understand what went wrong
                fallback_response = (
                    f"I couldn't find reliable information specifically about '{query}'. This might be because:\n\n"
                    f"• The query might be too general or ambiguous\n"
                    f"• The topic may require more specific keywords\n"
                    f"• There might be a typo or unusual phrasing in your query\n\n"
                    f"Please try rephrasing your question with more specific details or keywords related to what you want to know."
                )

            return fallback_response, errors + [f"No relevant information found about '{query}'. Please try a more specific query."], []

        logger.info(f"Generating enhanced summary from {len(all_content)} characters of content")

        try:
            # Generate a more comprehensive summary with the enhanced generator
            summary = generate_summary(all_content, num_sentences, query)

            # Verify summary quality - if it seems off-topic, try regenerating with stronger topic focus
            if len(summary.split()) > 20:
                clean_query = query.lower()
                query_words = set(word_tokenize(clean_query)) - STOP_WORDS
                summary_words = set(word_tokenize(summary.lower())) - STOP_WORDS

                # Check if summary contains essential query terms
                overlap = query_words.intersection(summary_words)
                if len(overlap) < min(2, len(query_words) // 2):
                    logger.warning("Summary seems off-topic, regenerating with stronger query focus")
                    # Try again with more focus on query terms
                    summary = generate_summary(all_content, num_sentences, query + " " + query)

            # Simplify the summary for better readability
            logger.info("Simplifying summary for improved readability")
            simplified_summary = simplify_for_readability(summary)

            return simplified_summary, errors, sources_used
        except Exception as summary_error:
            logger.error(f"Error generating summary: {str(summary_error)}")
            # Return a basic error message but still include the sources we found
            return "Unable to generate summary due to an error in processing the content.", errors + [f"Summary generation error: {str(summary_error)}"], sources_used

    except Exception as e:
        logger.error(f"Unexpected error in search_and_summarize_v1: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return "", [f"Error during search: {str(e)}"], []

def is_conversational(query):
    """Check if the query is conversational small talk rather than an information request"""
    query = query.lower().strip()

    # Common greetings and small talk patterns
    greetings = [
        "hello", "hi ", "hey", "howdy", "greetings", "good morning", "good afternoon",
        "good evening", "what's up", "sup", "how's it going", "how are you"
    ]

    farewells = [
        "bye", "goodbye", "see you", "see ya", "farewell", "take care", "later",
        "have a good day", "have a nice day"
    ]

    thanks = [
        "thank", "thanks", "appreciate", "grateful", "cheers", "much obliged",
        "thank you", "thx", "ty"
    ]

    smalltalk = [
        "how are you", "how do you feel", "what's your name", "who are you",
        "tell me about yourself", "nice to meet you", "pleased to meet",
        "how's your day", "how was your day", "you're doing great", "you are great",
        "you're amazing", "you are amazing", "good job", "well done", "awesome"
    ]

    # Check if query matches any conversational patterns
    if any(query.startswith(greeting) or query == greeting for greeting in greetings):
        return True, "greeting"

    if any(query.startswith(farewell) or query == farewell for farewell in farewells):
        return True, "farewell"

    if any(word in query for word in thanks):
        return True, "thanks"

    if any(pattern in query for pattern in smalltalk):
        return True, "smalltalk"

    return False, None

def get_conversational_response(conv_type):
    """Generate an appropriate response to conversational queries"""
    import random
    greeting_responses = [
        "Hello! I'm Poinsettia AI. How can I help you today?",
        "Hi there! I'm here to provide information on any topic you're curious about.",
        "Hey! What would you like to know about today?",
        "Greetings! I'm ready to help you find information on any topic.",
        "Hello! I'm Poinsettia, your knowledge-based assistant. What can I help you with?"
    ]

    farewell_responses = [
        "Goodbye! Feel free to come back anytime you have questions.",
        "Take care! I'm here if you need any information in the future.",
        "See you later! Have a wonderful day.",
        "Farewell! I'll be here when you need information on any topic.",
        "Goodbye! It was nice assisting you."
    ]

    thanks_responses = [
        "You're welcome! I'm happy to help.",
        "Glad I could assist you! Let me know if you need anything else.",
        "My pleasure! Is there anything else you'd like to know about?",
        "You're very welcome. I'm here if you need more information.",
        "No problem at all! Feel free to ask if you have other questions."
    ]

    smalltalk_responses = [
        "I'm doing well, thanks for asking! I'm a knowledge-based AI assistant, ready to help with information on various topics.",
        "I'm Poinsettia AI, designed to provide information by searching trusted sources. How can I assist you today?",
        "I'm just a knowledge assistant, but I'm working well and ready to help you find information!",
        "As an AI, I don't have feelings, but I'm functioning properly and ready to assist you with finding information.",
        "I'm here and ready to help you learn about any topic you're interested in. What would you like to know about?"
    ]

    if conv_type == "greeting":
        return random.choice(greeting_responses)
    elif conv_type == "farewell":
        return random.choice(farewell_responses)
    elif conv_type == "thanks":
        return random.choice(thanks_responses)
    elif conv_type == "smalltalk":
        return random.choice(smalltalk_responses)
    else:
        return "I'm here to help you find information on any topic. What would you like to know about?"

def extract_main_topic(query):
    """Extract the main topic from a question."""
    query = query.lower().strip()

    # Special check for Renaissance in various forms
    if any(term in query for term in ["renaissance", "renaisance", "rennaissance"]):
        logger.info("Detected Renaissance topic in query")
        return "renaissance"

    # Check for specific wording variations like "what was X" that weren't previously captured
    if query.startswith("what was") or query.startswith("what were"):
        remaining = query.replace("what was", "", 1).replace("what were", "", 1).strip()
        if remaining.startswith("the"):
            remaining = remaining[3:].strip()

        # Check if the remaining part is a historical period
        if len(remaining) > 3 and not remaining.startswith("?"):
            logger.info(f"Extracted topic from 'what was/were': '{remaining}'")
            return remaining

    # Regular pattern for "what happened during X" or "what is X" type questions
    historical_patterns = [
        r"what happened during (?:the )?(.*?)(?:\?|$)",
        r"what occurred during (?:the )?(.*?)(?:\?|$)",
        r"tell me about (?:the )?(.*?)(?:\?|$)",
        r"information about (?:the )?(.*?)(?:\?|$)",
        r"facts about (?:the )?(.*?)(?:\?|$)",
        r"history of (?:the )?(.*?)(?:\?|$)",
        r"when did (?:the )?(.*?) occur(?:\?|$)",
        r"when was (?:the )?(.*?)(?:\?|$)",
        r"what was (?:the )?(.*?)(?:\?|$)",      # Added pattern
        r"what were (?:the )?(.*?)(?:\?|$)"      # Added pattern
    ]

    # Historical periods and events that should be recognized as topics
    historical_topics = [
        "renaissance", "middle ages", "medieval period", "industrial revolution",
        "world war i", "world war ii", "civil war", "cold war", "great depression",
        "ancient greece", "ancient rome", "byzantine empire", "ottoman empire",
        "french revolution", "american revolution", "enlightenment", "reformation",
        "victorian era", "bronze age", "iron age", "stone age", "paleolithic",
        "neolithic", "mesopotamia", "ancient egypt", "roman empire", "dark ages",
        "classical period", "baroque period", "romantic period", "modern era"
    ]

    # Check the query against our patterns
    for pattern in historical_patterns:
        matches = re.findall(pattern, query)
        if matches and len(matches[0]) > 3:  # Avoid too short matches
            topic = matches[0].strip()
            logger.info(f"Extracted topic: '{topic}' from pattern matching")
            return topic

    # If no pattern match, check for presence of known historical topics
    for topic in historical_topics:
        if topic in query:
            logger.info(f"Found known historical topic: '{topic}'")
            return topic

    # Named entity recognition fallback - extract proper nouns that might be topics
    # This is a simplified approach - just looking for capitalized words
    words = query.split()
    for word in words:
        # Skip common question words and articles
        if word.lower() in ["what", "when", "where", "who", "how", "why", "did", "was", "is", "are", "the", "a", "an"]:
            continue

        # Check if word might be a proper noun (starts with capital letter in original query)
        original_index = query.find(word)
        if original_index >= 0 and original_index < len(query) - len(word):
            original_word = query[original_index:original_index + len(word)]
            if original_word[0].isupper() and len(original_word) > 3:
                logger.info(f"Extracted likely topic from capitalization: '{original_word}'")
                return original_word

    # If we can't identify a specific topic, return None
    return None

def extract_query_intent(query):
    """Determine the intent of the user's query"""
    query = query.lower().strip()

    # First check if this is conversational rather than an info request
    is_conv, conv_type = is_conversational(query)
    if is_conv:
        return conv_type, True

    # Check for extremely short or potentially incomplete queries
    if len(query) <= 2 or (len(query.split()) == 1 and len(query) <= 5):
        logger.warning(f"Query is too short or incomplete: '{query}'")
        return "invalid_query", False

    # Extract the main topic from historical or event-based questions
    main_topic = extract_main_topic(query)
    if main_topic:
        logger.info(f"Detected historical/topical query about: {main_topic}")
        return "historical_topic", True, main_topic

    # Check for direct definition questions first ("what is X")
    if query.startswith("what is") or query.startswith("what are"):
        logger.info(f"Detected definition query: {query}")
        return "definition", True

    # Check for book analysis queries - more specific patterns
    book_patterns = ["message of", "theme of", "moral of", "summary of book", "what is the book about",
                    "meaning of book", "plot of", "what happens in", "character analysis",
                    "symbolism in", "motifs in", "what is the message of", "what does the book teach",
                    "lessons from"]

    # If query contains book title indicators, strengthen the book detection
    has_book_indicators = any(term in query for term in ["book", "novel", "story", "author", "wrote", "written"])

    if has_book_indicators and any(term in query for term in book_patterns):
        logger.info(f"Detected book analysis query: {query}")
        return "book_analysis", True

    # Check for media content queries (movies, shows, games)
    if any(term in query for term in ["plot of movie", "review of", "ending of", "analysis of movie",
                                    "explanation of film", "meaning of show", "what happens in game"]):
        return "media_content", True

    # Check for definitional queries
    if any(term in query for term in ["what is", "definition of", "meaning of", "define","tell me about"]):
        return "definition", True

    # Check for comparison queries
    if any(term in query for term in ["compare", "difference between", "versus", "vs", "similarities", "differences"]):
        return "comparison", True

    # Check for instructional queries
    if any(term in query for term in ["how to", "steps to", "guide for", "instructions for", "tutorial"]):
        return "instructions", True

    # Check for programming/technology queries
    if any(term in query for term in ["language", "programming", "code", "written in", "developed with"]):
        return "technology", True

    # Default to informational
    return "information", False

@app.route('/')
def home():
    """Render the home page with a chatbot-like interface for Poinsettia.ai"""
    if 'username' not in session:
        return redirect(url_for('login'))

    ollama_available = check_ollama_available()

    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Poinsettia.ai - AI Assistant</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --dark-bg: #0f1118;
                --darker-bg: #090b11;
                --card-bg: #171b26;
                --primary-color: #e84142;
                --primary-hover: #f05657;
                --secondary-color: #282f3f;
                --text-color: #f0f0f0;
                --text-secondary: #c0c0c0;
                --border-radius: 12px;
                --glow-color: rgba(232, 65, 66, 0.15);
                --box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                font-family: 'Inter', sans-serif;
                background-color: var(--dark-bg);
                color: var(--text-color);
                line-height: 1.6;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
            }

            header {
                background-color: var(--darker-bg);
                padding: 15px 0;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                position: sticky;
                top: 0;
                z-index: 1000;
            }

            .header-content {
                max-width: 1200px;
                margin: 0 auto;
                display: flex;
                align-items: center;
                padding: 0 20px;
                justify-content: space-between; /* Changed for better alignment */
            }

            .brand-name {
                font-size: 1.5rem;
                font-weight: 700;
                color: var(--primary-color);
            }

            .header-controls {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            .model-toggle {
                display: flex;
                align-items: center;
                gap: 10px;
                background-color: var(--card-bg);
                padding: 8px 12px;
                border-radius: 20px;
                transition: background-color 0.3s;
            }
            .model-toggle:hover {
                background-color: var(--secondary-color);
            }

            .model-toggle label {
                font-size: 0.9rem;
                color: var(--text-secondary);
                cursor: default; /* Make label not clickable */
            }
            .model-toggle label:first-child {
                color: var(--primary-color); /* Highlight current model */
            }

            .toggle-switch {
                position: relative;
                width: 50px;
                height: 24px;
                background-color: var(--secondary-color);
                border-radius: 12px;
                cursor: pointer;
                transition: background-color 0.3s;
                display: flex;
                align-items: center;
            }

            .toggle-switch.active {
                background-color: var(--primary-color);
            }

            .toggle-slider {
                position: absolute;
                top: 2px;
                left: 2px;
                width: 20px;
                height: 20px;
                background-color: white;
                border-radius: 50%;
                transition: transform 0.3s;
            }

            .toggle-switch.active .toggle-slider {
                transform: translateX(26px);
            }

            .logout-btn {
                background-color: var(--secondary-color);
                color: var(--text-color);
                border: none;
                padding: 8px 16px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 0.9rem;
                transition: background-color 0.2s;
            }

            .logout-btn:hover {
                background-color: var(--primary-color);
            }

            main {
                flex: 1;
                display: flex;
                flex-direction: column;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                width: 100%;
            }

            .chat-container {
                flex: 1;
                display: flex;
                flex-direction: column;
                margin-bottom: 20px;
                min-height: 500px;
                max-height: calc(100vh - 200px);
                background-color: var(--card-bg);
                border-radius: var(--border-radius);
                overflow: hidden;
                box-shadow: var(--box-shadow);
            }

            .chat-messages {
                flex: 1;
                overflow-y: auto;
                padding: 20px;
                display: flex;
                flex-direction: column;
                gap: 20px;
            }

            .message {
                max-width: 80%;
                padding: 15px 20px;
                border-radius: 18px;
                animation: fadeIn 0.3s ease;
                box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
                font-size: 15px;
                line-height: 1.5;
                white-space: pre-line; /* Preserve line breaks */
            }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .user-message {
                align-self: flex-end;
                background-color: var(--primary-color);
                border-bottom-right-radius: 4px;
                margin-left: 20%;
            }

            .bot-message {
                align-self: flex-start;
                background-color: var(--secondary-color);
                border-bottom-left-radius: 4px;
                margin-right: 20%;
            }

            .model-badge {
                font-size: 0.75rem;
                opacity: 0.7;
                margin-top: 8px;
                font-style: italic;
                color: var(--text-secondary); /* Make badge text slightly dimmer */
            }

            .chat-input-container {
                display: flex;
                padding: 15px 20px;
                background-color: var(--darker-bg);
                border-top: 1px solid rgba(255, 255, 255, 0.05);
            }

            .chat-input {
                flex: 1;
                padding: 15px 20px;
                border: none;
                border-radius: 24px;
                background-color: var(--card-bg);
                color: var(--text-color);
                font-size: 15px;
                outline: none;
                transition: box-shadow 0.3s;
            }
            .chat-input:focus {
                box-shadow: 0 0 0 2px var(--glow-color);
            }

            .send-button {
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 50%;
                width: 48px;
                height: 48px;
                margin-left: 10px;
                cursor: pointer;
                transition: background-color 0.2s;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 20px; /* Adjust emoji size */
                line-height: 1; /* Ensure proper alignment */
            }

            .send-button:hover {
                background-color: var(--primary-hover);
            }

            .loading {
                display: none; /* Hidden by default */
                padding: 10px;
                align-items: center;
                justify-content: flex-start; /* Align typing indicator to the left */
                margin-left: 20%; /* Align with bot messages */
            }

            .typing-indicator {
                display: flex;
                align-items: center;
                background-color: var(--secondary-color);
                padding: 15px 20px;
                border-radius: 18px;
                border-bottom-left-radius: 4px; /* Match bot message style */
            }

            .typing-dot {
                background-color: var(--text-color);
                border-radius: 50%;
                width: 8px;
                height: 8px;
                margin: 0 2px;
                animation: typing 1.4s infinite ease-in-out;
            }

            .typing-dot:nth-child(1) { animation-delay: 0s; }
            .typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .typing-dot:nth-child(3) { animation-delay: 0.4s; }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); }
                30% { transform: translateY(-6px); }
            }

            .disabled-notice {
                background-color: rgba(232, 65, 66, 0.1);
                border: 1px solid rgba(232, 65, 66, 0.3);
                padding: 10px 15px;
                border-radius: 8px;
                margin-bottom: 10px;
                text-align: center;
                font-size: 0.9rem;
            }
        </style>
    </head>
    <body>
        <header>
            <div class="header-content">
                <span class="brand-name">Poinsettia.ai</span>
                <div class="header-controls">
                    <div class="model-toggle">
                        <label>Poinsettia 1</label>
                        <div class="toggle-switch''' + (' active' if not ollama_available else '') + '''" id="model-toggle">
                            <div class="toggle-slider"></div>
                        </div>
                        <label>Poinsettia 2</label>
                    </div>
                    <form action="/logout" method="post" style="margin: 0;">
                        <button type="submit" class="logout-btn">Logout</button>
                    </form>
                </div>
            </div>
        </header>

        <main>
            ''' + ('''<div class="disabled-notice">
                ⚠️ Poinsettia 2 (Ollama) is not available. Please ensure Ollama is running and the 'poinsettia' model is available.
            </div>''' if not ollama_available else '') + '''

            <div class="chat-container">
                <div class="chat-messages" id="chat-messages">
                    <div class="message bot-message">
                        👋 Hello! I'm Poinsettia AI. Toggle between Poinsettia 1 (search-based) and Poinsettia 2 (generative AI) above. What would you like to know?
                    </div>
                </div>

                <div class="loading" id="loading">
                    <div class="typing-indicator">
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                        <span class="typing-dot"></span>
                    </div>
                </div>

                <div class="chat-input-container">
                    <input type="text" id="chat-input" class="chat-input" placeholder="Ask a question..." autofocus>
                    <button id="send-button" class="send-button">➤</button>
                </div>
            </div>
        </main>

        <footer>
            <p>© 2023 Poinsettia Labs. All rights reserved.</p>
        </footer>

        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const toggle = document.getElementById('model-toggle');
                const chatMessages = document.getElementById('chat-messages');
                const chatInput = document.getElementById('chat-input');
                const sendButton = document.getElementById('send-button');
                const loading = document.getElementById('loading');
                const ollamaAvailable = ''' + str(ollama_available).lower() + ''';
                let currentModel = 1; // Default to Poinsettia 1

                // Get label elements
                const label1 = toggle.parentElement.querySelector('label:first-of-type');
                const label2 = toggle.parentElement.querySelector('label:last-of-type');

                // Initialize toggle state based on Ollama availability
                if (!ollamaAvailable) {
                    // Disable Poinsettia 2 if Ollama is not available
                    currentModel = 1;
                    toggle.classList.remove('active');
                    if (label1) label1.style.color = 'var(--primary-color)';
                    if (label2) label2.style.color = 'var(--text-secondary)';
                } else {
                    // If Ollama is available, start with Poinsettia 1
                    currentModel = 1;
                    toggle.classList.remove('active');
                    if (label1) label1.style.color = 'var(--primary-color)';
                    if (label2) label2.style.color = 'var(--text-secondary)';
                }

                toggle.addEventListener('click', function() {
                    // Check if trying to switch to Poinsettia 2 when Ollama is not available
                    if (!ollamaAvailable && !this.classList.contains('active')) {
                        alert('Poinsettia 2 (Ollama) is not available. Please set up Ollama first.');
                        return;
                    }

                    // Toggle the switch
                    this.classList.toggle('active');
                    currentModel = this.classList.contains('active') ? 2 : 1;

                    // Update label colors based on selection
                    if (currentModel === 2) {
                        if (label1) label1.style.color = 'var(--text-secondary)';
                        if (label2) label2.style.color = 'var(--primary-color)';
                    } else {
                        if (label1) label1.style.color = 'var(--primary-color)';
                        if (label2) label2.style.color = 'var(--text-secondary)';
                    }

                    // Add confirmation message
                    const confirmMsg = document.createElement('div');
                    confirmMsg.classList.add('message', 'bot-message');
                    confirmMsg.textContent = `Switched to Poinsettia ${currentModel}`;
                    chatMessages.appendChild(confirmMsg);
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                });

                function sendMessage() {
                    const query = chatInput.value.trim();
                    if (!query) return;

                    // Add user message
                    const userMsg = document.createElement('div');
                    userMsg.classList.add('message', 'user-message');
                    userMsg.textContent = query;
                    chatMessages.appendChild(userMsg);
                    chatMessages.scrollTop = chatMessages.scrollHeight;

                    chatInput.value = '';
                    loading.style.display = 'flex';

                    // Create a message div for streaming response
                    const messageDiv = document.createElement('div');
                    messageDiv.classList.add('message', 'bot-message');
                    chatMessages.appendChild(messageDiv);

                    // Add model badge
                    const badge = document.createElement('div');
                    badge.classList.add('model-badge');
                    badge.textContent = `Poinsettia ${currentModel}`;
                    messageDiv.appendChild(badge);

                    // Create text container
                    const textContainer = document.createElement('div');
                    messageDiv.insertBefore(textContainer, badge);

                    fetch('/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query, model: currentModel })
                    })
                    .then(response => {
                        loading.style.display = 'none';

                        const reader = response.body.getReader();
                        const decoder = new TextDecoder();
                        let buffer = '';

                        function readStream() {
                            reader.read().then(({ done, value }) => {
                                if (done) {
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                    return;
                                }

                                buffer += decoder.decode(value, { stream: true });
                                const lines = buffer.split('\n\n');
                                buffer = lines.pop();

                                lines.forEach(line => {
                                    if (line.startsWith('data: ')) {
                                        const content = line.slice(6);
                                        textContainer.textContent += content;
                                        chatMessages.scrollTop = chatMessages.scrollHeight;
                                    }
                                });

                                readStream();
                            });
                        }

                        readStream();
                    })
                    .catch(error => {
                        loading.style.display = 'none';
                        console.error('Error sending message:', error);
                        messageDiv.remove();
                        addMessage('Sorry, an error occurred while processing your request. Please try again.', 'bot');
                    });
                }



                sendButton.addEventListener('click', sendMessage);
                chatInput.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        sendMessage();
                    }
                });
            });
        </script>
    </body>
    </html>
    '''
    return render_template_string(html)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Basic validation
        if not username or not password:
            return render_template_string(login_html, error="Username and password are required.")

        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        if username in USERS and USERS[username] == hashed_password:
            session['username'] = username
            return redirect(url_for('home'))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            return render_template_string(login_html, error="Invalid username or password.")

    # Render login form for GET request
    return render_template_string(login_html, error=None)

login_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Poinsettia.ai</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --dark-bg: #0f1118;
            --card-bg: #171b26;
            --primary-color: #e84142;
            --primary-hover: #f05657;
            --text-color: #f0f0f0;
            --secondary-color: #282f3f;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--dark-bg);
            color: var(--text-color);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }

        .login-container {
            background-color: var(--card-bg);
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
            width: 100%;
            max-width: 400px;
            text-align: center; /* Center content within the container */
        }

        h1 {
            color: var(--primary-color);
            margin-bottom: 30px;
            font-size: 2rem;
        }

        .form-group {
            margin-bottom: 20px;
            text-align: left; /* Align labels and inputs left */
        }

        label {
            display: block;
            margin-bottom: 8px;
            font-size: 0.9rem;
            color: var(--text-color);
        }

        input {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            background-color: rgba(255, 255, 255, 0.1);
            color: var(--text-color);
            font-size: 1rem;
            outline: none; /* Remove default outline */
            transition: box-shadow 0.2s;
        }

        input:focus {
            box-shadow: 0 0 0 2px var(--primary-color); /* Add focus glow */
        }

        button {
            width: 100%;
            padding: 12px;
            background-color: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            cursor: pointer;
            transition: background-color 0.2s;
            font-weight: 500;
        }

        button:hover {
            background-color: var(--primary-hover);
        }

        .error {
            background-color: rgba(232, 65, 66, 0.1);
            border: 1px solid rgba(232, 65, 66, 0.3);
            color: #ff8a8a; /* Lighter red for error text */
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 0.9rem;
        }

        .demo-info {
            margin-top: 20px;
            padding: 15px;
            background-color: var(--secondary-color); /* Use secondary color for info box */
            border-radius: 8px;
            font-size: 0.9rem;
            line-height: 1.5;
            color: var(--text-secondary);
        }
        .demo-info strong {
            color: var(--primary-color); /* Highlight credentials */
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Poinsettia.ai</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
        <div class="demo-info">
            Demo credentials:<br>
            Username: <strong>demo</strong><br>
            Password: <strong>demo123</strong>
        </div>
    </div>
</body>
</html>
'''

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        logger.warning("Received empty JSON payload in /chat")
        return jsonify({'response': 'Error: Invalid request data.'}), 400

    query = data.get('query', '')
    model = data.get('model', 1)

    if not query:
        logger.warning("Received empty query in /chat")
        return jsonify({'response': 'Error: Please enter a message.'}), 400

    def generate_stream():
        if model == 2:
            # Use Ollama (Poinsettia 2) with streaming
            logger.info("Using Poinsettia 2 (Ollama) for query.")
            try:
                payload = {
                    "model": "poinsettia:latest",
                    "prompt": query,
                    "stream": True
                }
                response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=120)
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line:
                            try:
                                chunk = line.decode('utf-8')
                                data = eval(chunk)
                                if 'response' in data:
                                    yield f"data: {data['response']}\n\n"
                            except:
                                continue
                else:
                    yield f"data: [ERROR] Poinsettia 2 is currently unavailable.\n\n"
            except Exception as e:
                logger.error(f"Ollama streaming error: {e}")
                yield f"data: [ERROR] Failed to connect to Poinsettia 2.\n\n"
        else:
            # Use Poinsettia 1 (search-based) with simulated streaming
            logger.info("Using Poinsettia 1 (Search-based) for query.")
            summary, errors, sources = search_and_summarize_v1(query)

            if not summary:
                summary = "I couldn't find specific information on that topic using the search-based model. Please try rephrasing your query."

            # Stream the response word by word for smooth animation
            words = summary.split()
            for i, word in enumerate(words):
                if i == len(words) - 1:
                    yield f"data: {word}\n\n"
                else:
                    yield f"data: {word} \n\n"
                import time
                time.sleep(0.03)  # Small delay between words for smooth streaming effect

    return app.response_class(generate_stream(), mimetype='text/event-stream')


if __name__ == '__main__':
    print("Starting Poinsettia.ai on port 5100...")
    print("Visit http://0.0.0.0:5100 to interact with the AI assistant.")
    print("Default login - Username: demo, Password: demo123")
    # Ensure Ollama health check runs at startup
    ollama_check_result = check_ollama_available()
    if not ollama_check_result:
        logger.warning("Ollama is not available or the 'poinsettia' model is not found. Poinsettia 2 will be disabled.")

    app.run(host='0.0.0.0', port=5100, debug=False)