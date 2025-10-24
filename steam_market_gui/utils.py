import re
import hashlib
from urllib.parse import urlparse, unquote

def market_hash_from_url(url: str) -> str:
    path = urlparse(url).path
    try:
        idx = path.index('/listings/730/')
        name_enc = path[idx+len('/listings/730/'):]
        return unquote(name_enc)  # let requests re-encode properly
    except ValueError:
        return unquote(path.rsplit('/', 1)[-1])

def slugify(text: str) -> str:
    text = unquote(text)
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
    if not text:
        text = hashlib.sha1(text.encode() if isinstance(text, str) else b'').hexdigest()[:8]
    return text

def parse_price_to_float(price_str: str):
    # Remove currency symbols and spaces; keep digits, dot, comma (convert comma to dot)
    if not price_str:
        return None
    s = price_str.strip()
    s = s.replace(',', '.')  # simplistic: treat comma as decimal
    # Remove all except digits and dot and minus
    s2 = re.sub(r'[^0-9.-]', '', s)
    try:
        return float(s2)
    except:
        return None
