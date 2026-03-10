"""Static English stopwords set for filtering irrelevant keywords from memory/zeitgeist."""

STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "get", "gets", "getting", "got", "had", "hadn't",
    "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll",
    "he's", "her", "here", "here's", "hers", "herself", "him", "himself",
    "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in",
    "into", "is", "isn't", "it", "it's", "its", "itself", "just", "let's",
    "like", "me", "more", "most", "mustn't", "my", "myself", "no", "nor",
    "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "really", "right", "said",
    "same", "say", "says", "saying", "shan't", "she", "she'd", "she'll",
    "she's", "should", "shouldn't", "so", "some", "such", "than", "that",
    "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until",
    "up", "us", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "will", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll",
    "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Chat source labels / attribution noise
    "user", "assistant", "system", "taokaka", "tao", "irobeth",
    # Filler / conversational noise
    "oh", "yeah", "yes", "no", "ok", "okay", "um", "uh", "ah", "hmm",
    "huh", "well", "hey", "hi", "hello", "bye", "thanks", "thank",
    "please", "sorry", "gonna", "gotta", "wanna", "kinda", "sorta",
    "actually", "basically", "literally", "totally", "definitely",
    "probably", "maybe", "anyway", "anyways", "though", "stuff", "thing",
    "things", "something", "anything", "everything", "nothing", "someone",
    "anyone", "everyone", "know", "think", "thought", "mean", "guess",
    "feel", "go", "going", "went", "come", "came", "make", "made",
    "take", "took", "give", "gave", "tell", "told", "ask", "asked",
    "put", "keep", "let", "begin", "seem", "help", "show", "hear",
    "play", "run", "move", "try", "start", "might", "also", "back",
    "still", "even", "new", "want", "look", "looking", "use", "way",
    "good", "great", "much", "one", "two", "first", "time", "long",
    "little", "big", "kind",
})


def strip_attributions(text):
    """Remove 'Username: ' prefixes from chat lines so usernames don't become keywords."""
    import re
    # Matches lines starting with a display name followed by colon, e.g. "User: hello"
    return re.sub(r"(?m)^\s*\S+:\s+", "", text)


def extract_keywords(text, min_length=3):
    """Extract non-stopword tokens from text, lowercased and deduplicated."""
    import re
    text = strip_attributions(text)
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    seen = set()
    keywords = []
    for t in tokens:
        if len(t) >= min_length and t not in STOPWORDS and t not in seen:
            seen.add(t)
            keywords.append(t)
    return keywords
