from flask import Flask, request, render_template_string, jsonify
import requests
from bs4 import BeautifulSoup
import re
import logging
import numpy as np
import heapq
import random
from urllib.parse import urlparse
from datetime import datetime, timedelta

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def extract_keywords(query, max_keywords=4):
    """Extract important keywords from a query with improved handling of natural language questions"""
    # Recognize common question patterns
    query_lower = query.lower().strip()
    
    # Initialize subject variable
    subject = None

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

    # Handle definition questions
    if query_lower.startswith("what is") or "definition of" in query_lower:
        subject = query_lower.replace("what is", "").replace("definition of", "").strip()
        if subject:
            return f"{subject} definition"

    # Default to regular keyword extraction
    words = word_tokenize(query_lower)
    filtered_words = [w for w in words if w not in STOP_WORDS and len(w) > 2]

    # Prioritize longer words as they tend to be more important
    filtered_words.sort(key=len, reverse=True)

    # If we have enough keywords, return them
    if filtered_words:
        return " ".join(filtered_words[:max_keywords])

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
        keywords = extract_keywords(query)
        logger.info(f"Extracted keywords: {keywords}")

        # Expanded common topics dictionary with more topics
        common_topics = {
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
                
            # Remove common ad and notification elements
            ad_selectors = [
                "div.ad", "div.ads", "div.advertisement", 
                "div.banner", "div.notification", "div.cookie-notice",
                "div.popup", "div.alert", "div.newsletter", 
                "div.subscription", "div.gdpr", "div.modal",
                "aside", "header", "footer", "nav",
                "div.sidebar", "div.comments", "div.related",
                "div.recommended", "div.social", "div.share",
                "[class*='ad-']", "[class*='ads-']", "[class*='advert']", 
                "[class*='promo']", "[class*='banner']", "[class*='popup']",
                "[id*='ad-']", "[id*='ads-']", "[id*='advert']",
                "[id*='promo']", "[id*='banner']", "[id*='popup']"
            ]
            
            for selector in ad_selectors:
                try:
                    for element in soup.select(selector):
                        element.extract()
                except Exception:
                    # Continue if a selector causes an error
                    continue
                    
            # Try to identify the main content container
            main_content = None
            main_selectors = ["article", "main", "div.content", "div.article", "div.post", 
                            ".article-content", ".post-content", ".entry-content", "#content", "#main"]
            
            for selector in main_selectors:
                content = soup.select(selector)
                if content:
                    main_content = content[0]
                    break
            
            # Get text from the main content if found, otherwise from paragraphs
            if main_content:
                paragraphs = main_content.find_all('p')
                if paragraphs:
                    text = ' '.join([para.get_text() for para in paragraphs])
                else:
                    text = main_content.get_text()
            else:
                # Fallback: get all paragraphs, but filter out short ones (likely non-content)
                paragraphs = soup.find_all('p')
                if paragraphs:
                    # Filter out very short paragraphs (likely navigation or ads)
                    filtered_paragraphs = [p.get_text() for p in paragraphs if len(p.get_text().strip()) > 20]
                    if filtered_paragraphs:
                        text = ' '.join(filtered_paragraphs)
                    else:
                        text = ' '.join([p.get_text() for p in paragraphs])
                else:
                    # Last resort: get all text
                    text = soup.get_text()

            # Clean up the text
            # Break into lines and remove leading and trailing space
            lines = (line.strip() for line in text.splitlines())
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            # Drop blank lines
            text = ' '.join(chunk for chunk in chunks if chunk)

            # Remove common patterns in news articles and advertisements
            text = re.sub(r'(Photo by|Credit:).*?\.', '', text)
            text = re.sub(r'Advertisement', '', text)
            text = re.sub(r'Subscribe to.*?newsletter', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Sign up for our newsletter', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Click here for more', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Follow us on .*?(Facebook|Twitter|Instagram)', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Like us on .*?(Facebook|Twitter|Instagram)', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Share this (article|post|story)', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Copyright ©.*?reserved', '', text, flags=re.IGNORECASE)
            text = re.sub(r'All rights reserved', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Terms of (Use|Service)', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Privacy Policy', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Cookie Policy', '', text, flags=re.IGNORECASE)
            text = re.sub(r'We use cookies', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Sponsored Content', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Promoted Stories', '', text, flags=re.IGNORECASE)
            text = re.sub(r'Recommended For You', '', text, flags=re.IGNORECASE)
            text = re.sub(r'You might also like', '', text, flags=re.IGNORECASE)
            
            # Fix spacing issues from removals
            text = re.sub(r' +', ' ', text)

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

def calculate_sentence_scores(sentences, stop_words=None):
    """Calculate frequency-based importance scores for each sentence"""
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
            # Normalize by sentence length
            sentence_scores[i] = sentence_scores[i] / word_count

    return sentence_scores

def is_duplicate_content(new_sentence, existing_sentences, similarity_threshold=0.55):
    """Check if a sentence is too similar to any sentence in the existing set.
    Uses a lower similarity threshold (0.55 instead of 0.7) to ensure more diverse content."""
    new_words = set(word_tokenize(new_sentence))

    if len(new_words) < 4:  # Skip very short sentences
        return True

    for existing in existing_sentences:
        existing_words = set(word_tokenize(existing))

        if len(existing_words) < 4:  # Skip very short sentences
            continue

        # Calculate Jaccard similarity
        if new_words and existing_words:
            intersection = len(new_words.intersection(existing_words))
            union = len(new_words.union(existing_words))
            similarity = intersection / union

            if similarity > similarity_threshold:
                return True

    return False

def get_synonym(word):
    """Get a synonym for a word to avoid plagiarism."""
    # Comprehensive synonym dictionary for common words
    synonyms = {
        # Nouns
        "person": ["individual", "human", "being", "soul"],
        "people": ["individuals", "humans", "population", "folk"],
        "time": ["period", "era", "moment", "duration"],
        "year": ["twelve months", "annual period", "calendar year", "solar year"],
        "way": ["method", "approach", "manner", "technique"],
        "day": ["date", "period", "time", "moment"],
        "thing": ["item", "object", "entity", "element"],
        "man": ["male", "gentleman", "fellow", "guy"],
        "world": ["globe", "earth", "planet", "realm"],
        "life": ["existence", "being", "living", "lifetime"],
        "hand": ["palm", "grip", "grasp", "extremity"],
        "part": ["portion", "section", "component", "segment"],
        "child": ["youngster", "kid", "youth", "juvenile"],
        "eye": ["sight", "vision", "view", "gaze"],
        "woman": ["female", "lady", "girl", "madam"],
        "place": ["location", "spot", "site", "position"],
        "work": ["labor", "job", "task", "effort"],
        "week": ["seven days", "workweek", "period", "interval"],
        "case": ["instance", "example", "situation", "circumstance"],
        "point": ["spot", "location", "position", "place"],
        "government": ["administration", "regime", "authority", "leadership"],
        "company": ["business", "firm", "corporation", "enterprise"],
        "number": ["figure", "digit", "quantity", "amount"],
        "group": ["collection", "gathering", "assembly", "crowd"],
        "problem": ["issue", "difficulty", "challenge", "trouble"],
        "fact": ["reality", "truth", "actuality", "certainty"],
        "money": ["cash", "currency", "funds", "capital"],
        "month": ["thirty days", "period", "lunar cycle", "calendar month"],
        "right": ["privilege", "entitlement", "claim", "due"],
        "study": ["research", "analysis", "investigation", "examination"],
        "book": ["publication", "volume", "text", "work"],
        "story": ["tale", "narrative", "account", "report"],
        "idea": ["concept", "notion", "thought", "belief"],
        "community": ["neighborhood", "society", "district", "populace"],
        "country": ["nation", "state", "land", "realm"],
        "word": ["term", "expression", "phrase", "utterance"],
        "example": ["instance", "sample", "case", "illustration"],
        
        # Verbs
        "be": ["exist", "occur", "live", "happen"],
        "have": ["possess", "own", "hold", "maintain"],
        "do": ["perform", "execute", "accomplish", "achieve"],
        "say": ["state", "mention", "express", "declare"],
        "get": ["acquire", "obtain", "secure", "gain"],
        "make": ["create", "produce", "generate", "form"],
        "go": ["move", "travel", "proceed", "advance"],
        "know": ["understand", "comprehend", "recognize", "grasp"],
        "take": ["grab", "seize", "capture", "grip"],
        "see": ["observe", "view", "witness", "perceive"],
        "come": ["approach", "arrive", "reach", "appear"],
        "think": ["believe", "consider", "contemplate", "reflect"],
        "look": ["glance", "glimpse", "peer", "gaze"],
        "want": ["desire", "wish", "crave", "seek"],
        "give": ["provide", "supply", "offer", "present"],
        "use": ["employ", "utilize", "apply", "exercise"],
        "find": ["discover", "locate", "uncover", "detect"],
        "tell": ["inform", "relate", "narrate", "describe"],
        "ask": ["inquire", "query", "question", "interrogate"],
        "work": ["labor", "toil", "function", "operate"],
        "seem": ["appear", "look", "sound", "feel"],
        "feel": ["sense", "experience", "perceive", "discern"],
        "try": ["attempt", "endeavor", "strive", "seek"],
        "leave": ["depart", "exit", "withdraw", "retire"],
        "call": ["name", "term", "label", "designate"],
        
        # Adjectives
        "good": ["excellent", "fine", "superior", "quality"],
        "new": ["recent", "fresh", "novel", "modern"],
        "first": ["initial", "primary", "original", "earliest"],
        "last": ["final", "ultimate", "concluding", "terminal"],
        "long": ["extended", "lengthy", "prolonged", "extensive"],
        "great": ["significant", "considerable", "substantial", "notable"],
        "little": ["small", "minor", "tiny", "slight"],
        "own": ["personal", "individual", "private", "particular"],
        "other": ["different", "alternative", "additional", "further"],
        "old": ["aged", "ancient", "antique", "elderly"],
        "right": ["correct", "proper", "accurate", "suitable"],
        "big": ["large", "sizeable", "substantial", "considerable"],
        "high": ["tall", "elevated", "lofty", "towering"],
        "different": ["diverse", "distinct", "various", "dissimilar"],
        "small": ["little", "tiny", "minute", "compact"],
        "large": ["big", "sizeable", "great", "extensive"],
        "next": ["following", "subsequent", "succeeding", "ensuing"],
        "early": ["premature", "initial", "beforehand", "advance"],
        "young": ["youthful", "juvenile", "adolescent", "immature"],
        "important": ["significant", "crucial", "vital", "essential"],
        
        # Academic terms
        "analysis": ["examination", "evaluation", "investigation", "assessment"],
        "conclusion": ["finding", "determination", "deduction", "inference"],
        "impact": ["effect", "influence", "consequence", "result"],
        "increase": ["growth", "rise", "expansion", "enlargement"],
        "research": ["investigation", "study", "inquiry", "exploration"],
        "evidence": ["proof", "confirmation", "verification", "support"],
        "suggest": ["indicate", "imply", "propose", "recommend"],
        "occur": ["happen", "take place", "transpire", "arise"],
        "demonstrate": ["show", "reveal", "establish", "prove"],
        "develop": ["evolve", "progress", "advance", "grow"],
        "process": ["procedure", "method", "operation", "system"],
        "function": ["role", "purpose", "duty", "operation"],
        "structure": ["organization", "arrangement", "formation", "construction"],
        "significant": ["important", "notable", "considerable", "substantial"],
        "provide": ["supply", "furnish", "deliver", "contribute"],
        "environment": ["surroundings", "setting", "conditions", "atmosphere"],
        "specific": ["particular", "distinct", "definite", "precise"],
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

def replace_words_with_synonyms(text, replacement_rate=0.85):
    """Replace words with synonyms to avoid plagiarism. Using a higher 85% replacement rate."""
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
    
    # Replace words with synonyms at a high rate
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
    
    # Apply advanced sentence restructuring
    # Convert passive to active voice or vice versa (simplified approach)
    if " is " in sentence and " by " in sentence:
        # Potential passive voice, try to restructure
        sentence = re.sub(r'(.*) is (.*) by (.*)', r'\3 \2 \1', sentence)
    
    # Apply multi-pass synonym replacement for maximum rephrasing
    for _ in range(2):  # Apply twice for maximum effect
        sentence = replace_words_with_synonyms(sentence.strip(), 0.85)
    
    return sentence

def generate_transition_phrase():
    """Generate a transition phrase to improve flow between sentences."""
    transitions = [
        "Additionally, ", "Furthermore, ", "Moreover, ", "In addition, ",
        "Notably, ", "Interestingly, ", "Importantly, ", "Significantly, ",
        "Research indicates that ", "Evidence suggests that ", "Studies show that ",
        "Experts point out that ", "It's worth noting that ", "One key aspect is that ",
    ]
    return random.choice(transitions)

def transform_sentence(sentence):
    """Apply advanced sentence transformations to avoid plagiarism."""
    # Try different transformation techniques
    transformation_type = random.randint(1, 4)
    
    if transformation_type == 1:
        # Passive to active or active to passive transformation
        if " is " in sentence and " by " in sentence:
            return re.sub(r'(.*) is (.*) by (.*)', r'\3 \2 \1', sentence)
        elif " are " in sentence and " by " in sentence:
            return re.sub(r'(.*) are (.*) by (.*)', r'\3 \2 \1', sentence)
    
    elif transformation_type == 2:
        # Add an introductory phrase
        intro_phrases = [
            "It can be observed that ", "As a matter of fact, ", 
            "Taking this into account, ", "When examined closely, "
        ]
        return random.choice(intro_phrases) + sentence
    
    elif transformation_type == 3:
        # Sentence structure inversion if there's a comma
        if ", " in sentence:
            parts = sentence.split(", ", 1)
            return parts[1] + " while " + parts[0].lower()
    
    # If no transformation applied or for type 4, just apply synonym replacement
    return replace_words_with_synonyms(sentence, 0.85)

def add_concluding_sentence(summary, query):
    """Add a unique concluding sentence based on the query topic."""
    concluding_templates = [
        "This overview offers essential insights into {topic}.",
        "Understanding {topic} is valuable in numerous contexts.",
        "These aspects of {topic} illustrate its complexity and significance.",
        "The discussion of {topic} continues to evolve with ongoing research.",
        "The importance of {topic} is evident across multiple domains.",
    ]
    
    # Extract topic from query
    topic = query
    if query and len(query) > 30:
        # For long queries, try to extract the main topic
        words = word_tokenize(query)
        filtered_words = [w for w in words if w.lower() not in STOP_WORDS and len(w) > 3]
        if filtered_words:
            topic = " ".join(filtered_words[:3])
    
    conclusion = random.choice(concluding_templates).format(topic=topic)
    return summary + " " + conclusion

def generate_summary(text, num_sentences=5, query=None):
    """Generate a summary of the text focused on the query topic with enhanced anti-plagiarism features."""
    # Clean citations
    text = clean_citations(text)

    # Tokenize sentences
    sentences = custom_sent_tokenize(text)

    # Handle very short texts
    if len(sentences) <= num_sentences:
        return replace_words_with_synonyms(text, 0.9)  # Apply aggressive synonym replacement

    # Get query keywords for boosting relevance
    query_keywords = set()
    if query:
        query_keywords = set(word for word in word_tokenize(query.lower()) 
                           if word not in STOP_WORDS and len(word) > 2)

    # Calculate sentence scores
    sentence_scores = calculate_sentence_scores(sentences)

    # Boost scores for sentences containing query terms
    if query_keywords:
        for i, sentence in enumerate(sentences):
            sentence_lower = sentence.lower()
            matches = sum(1 for word in query_keywords if word in sentence_lower)
            if matches > 0:
                # Boost score based on keyword matches
                sentence_scores[i] = sentence_scores.get(i, 0) + (0.3 * matches)  # Increased boost

    # Select top sentences
    try:
        top_indices = heapq.nlargest(num_sentences * 2, sentence_scores, key=sentence_scores.get)
    except ValueError:
        # Fallback if no scores could be calculated
        top_indices = list(range(min(num_sentences * 2, len(sentences))))

    # Get the top sentences while avoiding duplicates
    top_sentences = []
    for i in top_indices:
        if len(top_sentences) >= num_sentences:
            break

        try:
            # Apply multiple transformations to each sentence
            simplified = simplify_sentence(sentences[i])
            transformed = transform_sentence(simplified)
            
            if transformed and len(transformed) > 15:  # Only add if non-empty and meaningful
                # Check if the sentence is relevant to the query
                if query_keywords:
                    sentence_words = set(word for word in word_tokenize(transformed.lower()) 
                                      if word not in STOP_WORDS)
                    relevance = len(query_keywords.intersection(sentence_words))

                    # Skip sentences with no connection to query terms at all
                    if relevance == 0 and len(top_sentences) >= num_sentences // 2:
                        continue

                if not is_duplicate_content(transformed, top_sentences):
                    top_sentences.append(transformed)
        except IndexError:
            # Skip if index is out of range
            continue

    # If we couldn't get enough sentences, just use the first few sentences
    if not top_sentences and sentences:
        top_sentences = [transform_sentence(simplify_sentence(s)) for s in sentences[:num_sentences]]

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
            # Don't change order if sorting fails
            pass

    # Add transition phrases between sentences for better flow
    enhanced_sentences = []
    for i, sentence in enumerate(top_sentences):
        if i > 0 and len(sentence) > 30 and random.random() < 0.4:  # Add transitions randomly
            enhanced_sentences.append(generate_transition_phrase() + sentence.lower())
        else:
            enhanced_sentences.append(sentence)

    # Join sentences into a summary
    summary = " ".join(enhanced_sentences)
    
    # Add a unique concluding sentence if we have a query
    if query:
        summary = add_concluding_sentence(summary, query)
    
    # Final pass of synonym replacement on the entire summary
    summary = replace_words_with_synonyms(summary, 0.7)

    # No disclaimer added to keep the summary clean

    return summary

def search_and_summarize(query, num_sentences=8):
    """Search for sources on a topic and generate a summary."""
    try:
        # Search for relevant URLs
        logger.info(f"Searching for topic: {query}")
        urls = search_for_topic(query)
        if not urls:
            logger.warning(f"No sources found for query: {query}")
            # Use generic fallback URLs for educational content
            urls = [
                "https://en.wikipedia.org/wiki/Main_Page",
                "https://www.britannica.com/",
                "https://www.nationalgeographic.com/"
            ]
            logger.info(f"Using generic fallback URLs: {urls}")

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

                    # Calculate relevance score
                    keyword_matches = len(query_keywords.intersection(content_words))
                    relevance_score = keyword_matches / len(query_keywords) if query_keywords else 0

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
                    except:
                        pass

                    logger.info(f"Relevance for {url}: Score={relevance_score:.2f}, Keywords in intro={query_words_in_start}, Title relevance={title_relevance}")

                    # Use more flexible relevance criteria
                    # 1. Accept content with any relevance if we don't have enough content yet
                    # 2. Be more flexible with criteria as we try more URLs
                    is_relevant = (
                        relevance_score > 0.2 or  # Lower threshold for relevance
                        query_words_in_start >= 1 or  # Only need one keyword in intro
                        title_relevance > 0 or  # Any title relevance is good
                        len(sources_used) < 1  # Always accept first source if others failed
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
            # Create a fallback response with general information
            fallback_response = (
                f"I couldn't find specific information about '{query}'. "
                f"This might be because the query is too specific, uses unusual terminology, "
                f"or contains a spelling error. Try rephrasing your question or breaking it into simpler parts."
            )
            return fallback_response, errors + [f"Could not find relevant information about '{query}'. Please try rephrasing your question."], []

        logger.info(f"Generating summary from {len(all_content)} characters of content")

        try:
            # Generate a slightly longer summary to ensure good coverage, passing the query for focus
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

            return summary, errors, sources_used
        except Exception as summary_error:
            logger.error(f"Error generating summary: {str(summary_error)}")
            # Return a basic error message but still include the sources we found
            return "Unable to generate summary due to an error in processing the content.", errors + [f"Summary generation error: {str(summary_error)}"], sources_used

    except Exception as e:
        logger.error(f"Unexpected error in search_and_summarize: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return "", [f"Error during search process: {str(e)}"], []

@app.route('/')
def home():
    """Render the home page."""
    html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Simple Text Summarizer</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #1a1a1a;
                --container-bg: #2a2a2a;
                --text-color: #f0f0f0;
                --primary-color: #5e81ac;
                --secondary-color: #81a1c1;
                --accent-color: #88c0d0;
                --error-color: #bf616a;
                --success-color: #a3be8c;
                --border-radius: 8px;
                --box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                font-family: 'Inter', sans-serif;
                line-height: 1.6;
                background-color: var(--bg-color);
                color: var(--text-color);
                min-height: 100vh;
                padding: 20px;
            }

            .container {
                max-width: 1000px;
                margin: 20px auto;
                padding: 30px;
                background-color: var(--container-bg);
                border-radius: var(--border-radius);
                box-shadow: var(--box-shadow);
            }

            h1 {
                font-size: 2.5rem;
                text-align: center;
                margin-bottom: 1.5rem;
                color: var(--accent-color);
            }

            h2 {
                font-size: 1.8rem;
                margin-bottom: 1rem;
                color: var(--secondary-color);
            }

            .description {
                text-align: center;
                margin-bottom: 2rem;
                font-size: 1.1rem;
                color: var(--text-color);
                opacity: 0.9;
            }

            .search-container {
                margin-bottom: 2rem;
            }

            .search-box {
                display: flex;
                margin-bottom: 1rem;
            }

            input[type="text"] {
                flex-grow: 1;
                padding: 12px 16px;
                border: none;
                border-radius: var(--border-radius) 0 0 var(--border-radius);
                background-color: #3a3a3a;
                color: var(--text-color);
                font-size: 1rem;
                outline: none;
            }

            input[type="number"] {
                width: 100%;
                padding: 10px;
                border: none;
                border-radius: var(--border-radius);
                background-color: #3a3a3a;
                color: var(--text-color);
                font-size: 1rem;
                margin-bottom: 1rem;
            }

            button {
                padding: 12px 20px;
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 0 var(--border-radius) var(--border-radius) 0;
                cursor: pointer;
                font-size: 1rem;
                font-weight: 600;
                transition: background-color 0.2s;
            }

            button:hover {
                background-color: var(--secondary-color);
            }

            .options {
                display: flex;
                align-items: center;
                margin-top: 1rem;
            }

            .options label {
                margin-right: 10px;
                font-size: 0.9rem;
            }

            #loading {
                display: none;
                text-align: center;
                margin: 2rem 0;
            }

            .loading-spinner {
                border: 4px solid rgba(255, 255, 255, 0.1);
                border-left-color: var(--accent-color);
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
                margin: 0 auto 1rem;
            }

            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            .result-container {
                display: none;
                margin-top: 2rem;
                padding: 20px;
                background-color: #333;
                border-radius: var(--border-radius);
                border-left: 4px solid var(--accent-color);
            }

            .summary-content {
                font-size: 1.1rem;
                line-height: 1.7;
                margin-bottom: 1.5rem;
                white-space: pre-line;
            }

            .action-buttons {
                displayflex;
                margin-top: 1rem;
            }

            .action-button {
                margin-right: 10px;
                padding: 8px 16px;
                border-radius: var(--border-radius);
                font-size: 0.9rem;
                cursor: pointer;
            }

            .copy-btn {
                background-color: var(--primary-color);
            }

            .error-container {
                display: none;
                margin-top: 2rem;
                padding: 20px;
                background-color: rgba(191, 97, 106, 0.2);
                border-radius: var(--border-radius);
                border-left: 4px solid var(--error-color);
            }

            .sources-container {
                margin-top: 1.5rem;
                padding-top: 1.5rem;
                border-top: 1px solid #444;
            }

            .sources-list {
                list-style-type: none;
            }

            .sources-list li {
                margin-bottom: 0.5rem;
            }

            .sources-list a {
                color: var(--accent-color);
                text-decoration: none;
            }

            .sources-list a:hover {
                text-decoration: underline;
            }

            .error-list {
                list-style-type: none;
            }

            .error-list li {
                margin-bottom: 0.5rem;
                color: #ddd;
            }

            .footer {
                text-align: center;
                margin-top: 3rem;
                font-size: 0.9rem;
                color: #888;
            }
            #timer {
                margin-top: 10px;
                font-size: 1rem;
            }
            .source-disclaimer {
                font-style: italic;
                margin-bottom: 0.5rem;
                color: #bbb;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Simple Text Summarizer</h1>
            <p class="description">Enter any topic to get an AI-generated summary from reputable sources.</p>

            <div class="search-container">
                <div class="search-box">
                    <input type="text" id="query" placeholder="Enter a topic or question (e.g., 'climate change impacts')" autofocus>
                    <button id="search-btn">Summarize</button>
                </div>

                <div class="options">
                    <label for="num_sentences">Summary length (sentences):</label>
                    <input type="number" id="num_sentences" min="3" max="20" value="5">
                </div>
            </div>

            <div id="loading">
                <div class="loading-spinner"></div>
                <p>Searching sources and generating summary...</p>
                <p id="timer"></p>
            </div>

            <div id="result-container" class="result-container">
                <h2>Summary</h2>
                <div id="summary-text" class="summary-content"></div>
                <div class="disclaimer" style="font-style: italic; margin-top: 10px; color: #999; font-size: 0.9rem;">
                    This content is AI-generated and rephrased to avoid plagiarism.
                </div>

                <div class="action-buttons">
                    <button id="copy-btn" class="action-button copy-btn">Copy Summary</button>
                </div>

                <div id="sources-container" class="sources-container">
                    <h2>Sources</h2>
                    <p class="source-disclaimer">Information summarized from these sources:</p>
                    <ul id="sources-list" class="sources-list"></ul>
                </div>
            </div>

            <div id="error-container" class="error-container">
                <h2>Errors</h2>
                <ul id="error-list" class="error-list"></ul>
            </div>
        </div>

        <div class="footer">
            <p>This tool only uses reputable news sources and educational content.</p>
        </div>

        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const queryInput = document.getElementById('query');
                const numSentencesInput = document.getElementById('num_sentences');
                const searchBtn = document.getElementById('search-btn');
                const resultContainer = document.getElementById('result-container');
                const errorContainer = document.getElementById('error-container');
                const summaryText = document.getElementById('summary-text');
                const errorList = document.getElementById('error-list');
                const loading = document.getElementById('loading');
                const copyBtn = document.getElementById('copy-btn');
                const sourcesList = document.getElementById('sources-list');
                const sourcesContainer = document.getElementById('sources-container');

                // Handle Enter key in search input
                queryInput.addEventListener('keyup', function(event) {
                    if (event.key === 'Enter') {
                        searchBtn.click();
                    }
                });

                // Copy summary to clipboard
                copyBtn.addEventListener('click', function() {
                    navigator.clipboard.writeText(summaryText.textContent)
                        .then(() => {
                            const originalText = copyBtn.textContent;
                            copyBtn.textContent = 'Copied!';
                            setTimeout(() => {
                                copyBtn.textContent = originalText;
                            }, 2000);
                        })
                        .catch(err => {
                            console.error('Failed to copy: ', err);
                        });
                });

                // Handle search button click
                searchBtn.addEventListener('click', function() {
                    const query = queryInput.value.trim();
                    if (!query) {
                        return;
                    }

                    // Show loading indicator
                    loading.style.display = 'block';
                    resultContainer.style.display = 'none';
                    errorContainer.style.display = 'none';

                    // Add timer to show how long the request is taking
                    const timerElement = document.getElementById('timer');
                    let seconds = 0;
                    const timer = setInterval(() => {
                        seconds++;
                        timerElement.textContent = `Time elapsed: ${seconds} seconds`;
                        // Auto-cancel after 60 seconds to prevent indefinite waiting
                        if (seconds >= 60) {
                            clearInterval(timer);
                            loading.style.display = 'none';
                            errorList.innerHTML = '';
                            const li = document.createElement('li');
                            li.textContent = 'Request timed out after 60 seconds. Please try a shorter or more specific query.';
                            errorList.appendChild(li);
                            errorContainer.style.display = 'block';
                        }
                    }, 1000);

                    // Get form data
                    const numSentences = parseInt(numSentencesInput.value, 10) || 5;

                    // Send request to server
                    fetch('/summarize', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            query: query,
                            num_sentences: numSentences
                        })
                    })
                    .then(response => {
                        if (!response.ok) {
                            throw new Error(`HTTP error! Status: ${response.status}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        clearInterval(timer); // Stop the timer when the response arrives
                        loading.style.display = 'none';

                        if (data.summary) {
                            summaryText.textContent = data.summary;
                            resultContainer.style.display = 'block';

                            // Display sources
                            if (data.sources && data.sources.length > 0) {
                                sourcesList.innerHTML = '';
                                data.sources.forEach(source => {
                                    const li = document.createElement('li');
                                    const a = document.createElement('a');
                                    a.href = source;
                                    a.textContent = source;
                                    a.target = '_blank';
                                    li.appendChild(a);
                                    sourcesList.appendChild(li);
                                });
                                sourcesContainer.style.display = 'block';
                            } else {
                                sourcesContainer.style.display = 'none';
                            }
                        }

                        if (data.errors && data.errors.length > 0) {
                            errorList.innerHTML = '';
                            data.errors.forEach(error => {
                                const li = document.createElement('li');
                                li.textContent = error;
                                errorList.appendChild(li);
                            });
                            errorContainer.style.display = 'block';
                        }
                    })
                    .catch(error => {
                        clearInterval(timer); // Stop the timer on error
                        loading.style.display = 'none';
                        errorList.innerHTML = '';
                        const li = document.createElement('li');
                        li.textContent = 'An error occurred: ' + error.message;
                        errorList.appendChild(li);
                        errorContainer.style.display = 'block';
                    });
                });
            });
        </script>
    </body>
    </html>
    '''
    return render_template_string(html)

@app.route('/summarize', methods=['POST'])
def summarize():
    """Generate summary for the provided topic by automatically searching sources."""
    try:
        # Log that we're starting the summarize endpoint
        logger.info("Starting summarize endpoint")

        data = request.get_json()
        if data is None:
            logger.warning("Invalid JSON received")
            return jsonify({'error': 'Invalid JSON', 'errors': ['The request did not contain valid JSON data']})

        # Log the received data
        logger.info(f"Received data: {data}")

        query = data.get('query', '')
        num_sentences = data.get('num_sentences', 5)

        # Validate input
        if not query:
            logger.warning("No search query provided")
            return jsonify({'error': 'No search query provided', 'errors': ['Please enter a topic to summarize']})

        # Log that we're starting the search_and_summarize function
        logger.info(f"Starting search_and_summarize for query: {query}")

        try:
            summary, errors, sources = search_and_summarize(query, num_sentences)

            # Log the result
            logger.info(f"Search completed. Summary length: {len(summary) if summary else 0}, Errors: {len(errors)}, Sources: {len(sources)}")

            return jsonify({
                'summary': summary,
                'errors': errors,
                'sources': sources
            })
        except Exception as search_error:
            logger.error(f"Error in search_and_summarize: {str(search_error)}")
            return jsonify({
                'summary': '',
                'errors': [f"Error during search: {str(search_error)}"],
                'sources': []
            }), 500

    except Exception as e:
        logger.error(f"Unexpected error in summarize endpoint: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            'summary': '',
            'errors': [f"Server error: {str(e)}"],
            'sources': []
        }), 500

if __name__ == '__main__':
    print("Starting Simple Text Summarizer on port 5100...")
    print("NOTE: The first search may take a moment as it needs to fetch content.")
    app.run(host='0.0.0.0', port=5100, debug=False)

if __name__ == '__main__':
    print("Starting Simple Text Summarizer on port 5100...")
    print("NOTE: The first search may take a moment as it needs to fetch content.")
    app.run(host='0.0.0.0', port=5100, debug=False)