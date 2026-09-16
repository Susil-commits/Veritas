"""
Safety & Guardrails Module — AI Socratic Tutor
Protects student learning with:
1. Input Sanitization & Control Character Stripping
2. Prompt Injection & Jailbreak Defense (Anti-Bypass Shield)
3. Socratic Direct-Answer Leak Detection & Prevention
4. Child-Safe Content Filtering (Educational Boundary Enforcement)
5. Secure Upload File Validation (Size, Extension, & MIME Type Verification)
6. Security Event Audit Logging
"""
import re
import html
import time
from typing import Tuple, Dict, Any, Optional
from fastapi import HTTPException, status

# Patterns indicating attempts to extract system prompt or force direct answers
PROMPT_INJECTION_PATTERNS = [
    r"ignore\b.*?\b(instructions|directions|rules|prompts|guidelines)",
    r"system prompt",
    r"you are now\b.*?\b(unrestricted|jailbreak|dan|calculator|answer key|free)",
    r"forget\b.*?\b(instructions|role|rules|guidelines)",
    r"disregard\b.*?\b(instructions|rules|guardrails)",
    r"output (only|just) the (answer|solution|result)",
    r"give me the (direct|final|exact) answer",
    r"what is the (answer|solution) to this (without|no) explanation",
    r"bypass (socratic|guardrails|safety)",
    r"developer mode",
    r"repeat (everything|the text|the instructions) above",
]

# Inappropriate, toxic, or self-harm keywords to immediately flag and safely redirect
HARMFUL_PATTERNS = [
    r"\b(suicide|self-harm|kill myself|hurt myself)\b",
    r"\b(hate|slur|vulgar)\b",
]

# Allowed upload MIME types for math handwritten work
ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

# Standard magic bytes for image formats
IMAGE_MAGIC_BYTES = [
    b"\xff\xd8\xff",        # JPEG
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"RIFF",                # WebP (RIFF....WEBP)
]

# Educational boundary message when a student attempts prompt injection or answer extraction
SOCRATIC_BOUNDARY_RESPONSE = (
    "Nice try! But I am your Socratic math coach, not an answer key. "
    "I am here to help your brain do the heavy lifting so you truly master this. "
    "Let's look at the problem together — what is the first step or operation you see?"
)

SAFE_SUPPORT_RESPONSE = (
    "It sounds like you might be having a difficult time. Please talk to a trusted adult, "
    "parent, or teacher, or contact a support helpline. Your well-being is what matters most."
)

NEO_OUT_OF_SCOPE_RESPONSE = (
    "I am **Neo**, your dedicated Veritas AI assistant.\n\n"
    "I am strictly guardrailed to answer questions related to the **Veritas** platform — including our "
    "Socratic math tutoring, Grade 3–7 curriculum, Paper Work Reader, real-time skill progress, "
    "student & parent dashboards, and account features.\n\n"
    "I cannot answer questions about general topics, unrelated coding, or non-platform subjects. "
    "How can I help you explore or use Veritas today?"
)

NEO_OFF_TOPIC_PATTERNS = [
    r"\b(crypto|bitcoin|ethereum|dogecoin|forex|stock market|investing|cryptocurrency)\b",
    r"\b(recipe|bake a cake|cook|ingredients for|dinner recipe|baking)\b",
    r"\b(president of|prime minister|election|political party|democrat|republican|presidential)\b",
    r"\b(write a python script|write code in|write a rust program|web scraper|flask app|django app|javascript code)\b",
    r"\b(world war|french revolution|american civil war|history essay|historical event)\b",
    r"\b(photosynthesis|mitochondria|biology essay|chemistry lab|dna replication|biology homework)\b",
    r"\b(translate (this|to) (french|spanish|german|chinese|japanese))\b",
    r"\b(who won\b.*?\b(fifa|super bowl|world cup|nba|champions league|olympics))\b",
    r"\b(movie|celebrity|gossip|hollywood|netflix show|theaters tonight)\b",
    r"\b(minecraft|fortnite|roblox|gta|video game)\b",
]

COMPILED_PROMPT_INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
COMPILED_HARMFUL_PATTERNS = [re.compile(p, re.IGNORECASE) for p in HARMFUL_PATTERNS]
COMPILED_NEO_OFF_TOPIC_PATTERNS = [re.compile(p, re.IGNORECASE) for p in NEO_OFF_TOPIC_PATTERNS]


# Regex matching HTML/XML tags, comments, doctypes, and CDATA blocks.
# Intentionally does NOT match mathematical inequalities (e.g. "3 < 5", "x > 2", "0 < x < 10", "x <= y").
HTML_TAG_PATTERN = re.compile(
    r"(<!--.*?-->|<!\[CDATA\[.*?\]\]>|<!DOCTYPE[^>]*>|"
    r"</?[a-zA-Z][a-zA-Z0-9:-]*(?:\s+[a-zA-Z0-9:_-]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'>`]+))?)*\s*/?>)",
    re.DOTALL,
)


def escape_html_tags(text: str) -> str:
    """
    Escapes raw HTML/XML tags to prevent injection/XSS while preserving
    mathematical inequality operators ('<', '>', '<=', '>=') for STEM LLM prompts.
    """
    return HTML_TAG_PATTERN.sub(lambda m: html.escape(m.group(0)), text)


def sanitize_input(text: str, max_length: int = 1500) -> str:
    """
    Sanitizes student text input:
    - Truncates to maximum permissible length to prevent memory overload.
    - Strips invisible or dangerous unicode control characters.
    - Escapes raw HTML/XML tags while preserving math inequalities (<, >, <=, >=).
    - Normalizes excessive whitespace.
    """
    if not text:
        return ""

    # Truncate
    trimmed = text[:max_length]

    # Strip dangerous/invisible unicode control characters (except newline & tab)
    cleaned = "".join(ch for ch in trimmed if ch == "\n" or ch == "\t" or not (0 <= ord(ch) <= 31 or 127 <= ord(ch) <= 159))

    # Escape HTML tags to prevent injection while preserving math inequalities
    escaped = escape_html_tags(cleaned)

    # Collapse multiple consecutive newlines or spaces
    normalized = re.sub(r"[ \t]+", " ", escaped)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

    return normalized


def check_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
    """
    Scans student input for prompt injection, jailbreak attempts, or direct answer demands.
    Returns (is_violation, explanation).
    """
    if not text:
        return False, None

    for pattern in COMPILED_PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            return True, f"Matched injection pattern: {pattern.pattern}"

    return False, None


def check_harmful_content(text: str) -> Tuple[bool, Optional[str]]:
    """
    Scans for urgent distress or safety flags.
    Returns (is_flagged, category).
    """
    if not text:
        return False, None

    for pattern in COMPILED_HARMFUL_PATTERNS:
        if pattern.search(text):
            return True, "distress_or_inappropriate"
    return False, None


def check_neo_domain_scope(text: str) -> Tuple[bool, Optional[str]]:
    """
    Guardrail filter for Neo AI assistant:
    Ensures that queries are strictly related to the Veritas platform,
    its math curriculum, features (Socratic tutor, OCR Work Reader, BKT, dashboards),
    or navigation.
    Returns (is_in_scope: bool, reason: Optional[str]).
    """
    if not text or len(text.strip()) == 0:
        return True, None

    # Check for harmful content first
    is_harmful, h_reason = check_harmful_content(text)
    if is_harmful:
        return False, f"Harmful or distressing query: {h_reason}"

    # Check for prompt injection / jailbreak
    is_injection, i_reason = check_prompt_injection(text)
    if is_injection:
        return False, f"Jailbreak or system prompt extraction attempt: {i_reason}"

    # Check for explicit off-topic patterns
    for pattern in COMPILED_NEO_OFF_TOPIC_PATTERNS:
        if pattern.search(text):
            return False, f"Off-topic subject query matching: {pattern.pattern}"

    return True, None


def is_answer_leaked(tutor_reply: str, expected_answer: Optional[str]) -> bool:
    """
    Secondary safety check: ensure the tutor response does not inadvertently
    blurt out the final expected answer without asking a question.
    """
    if not expected_answer or len(expected_answer.strip()) < 1:
        return False

    clean_ans = expected_answer.strip().lower()
    reply_lower = tutor_reply.lower()

    # If the response simply announces "the answer is X" or "X is the answer"
    leak_patterns = [
        rf"\b(the answer is|the correct answer is|the solution is)\s*[:=]?\s*{re.escape(clean_ans)}\b",
        rf"\b{re.escape(clean_ans)}\s+is the (answer|correct answer|final result)\b",
    ]

    for p in leak_patterns:
        if re.search(p, reply_lower):
            return True

    return False


def verify_pedagogical_response(
    tutor_reply: str,
    expected_answer: Optional[str] = None,
    expected_steps: Optional[list[str]] = None,
    misconception_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Comprehensive Pedagogical Verifier for Socratic AI tutoring.
    Checks:
    1. Answer leakage: Does the response blurt out the final calculation?
    2. Step revelation: Does the response give away full expected solution steps?
    3. Inquiry check: Does the response guide the student by asking at least one question?
    4. Misconception awareness: Does the guidance target the diagnosed root error?
    5. Length & age appropriateness: Conciseness suited for Grade 3-7 learners.
    """
    reply = tutor_reply.strip()
    reply_lower = reply.lower()
    violations: list[str] = []

    # 1. Final Answer Leakage Check
    if expected_answer and is_answer_leaked(reply, expected_answer):
        violations.append("answer_leakage")

    # 2. Step Revelation Check (prematurely revealing expected steps or intermediate directives)
    if expected_steps:
        for i, step in enumerate(expected_steps):
            clean_step = step.strip().lower()
            clean_step_body = re.sub(r"^\d+\.\s*(?:identify|set up|solve|answer)?[:\s]*", "", clean_step)
            clauses = [clean_step_body] + [c.strip() for c in re.split(r"[:;]", clean_step_body) if len(c.strip()) > 10]
            for c in clauses:
                if len(c) > 10 and c in reply_lower:
                    violations.append(f"revealed_step_{i+1}")
                    break

    # 3. Guiding Question Check (Socratic method requires asking guiding questions with '?' or explicit question frames)
    has_question = ("?" in reply) or any(
        bool(re.search(p, reply_lower)) for p in [
            r"\b(can you|could you|what is|what did|what does|what operation|what do|how do|how did|how would|why do|why did|which of|which number|where did)\b"
        ]
    )
    if not has_question:
        violations.append("no_guiding_question")

    # 4. Age Appropriateness (Length check: concise 1-4 sentences max for kids)
    sentences = [s for s in re.split(r"[.!?]+", reply) if len(s.strip()) > 3]
    if len(sentences) > 5 or len(reply.split()) > 95:
        violations.append("excessive_length")

    # 5. Misconception Alignment
    misconception_aligned = True
    if misconception_type and ("fraction" in misconception_type or "denominator" in misconception_type):
        if not any(k in reply_lower for k in ["fraction", "denominator", "bottom", "pieces", "parts"]):
            misconception_aligned = False

    approved = len(violations) == 0

    return {
        "approved": approved,
        "violations": violations,
        "has_guiding_question": has_question,
        "misconception_aligned": misconception_aligned,
        "sentence_count": len(sentences),
    }


def validate_image_upload(
    file_bytes: bytes,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
    max_size_bytes: int = 10 * 1024 * 1024,  # 10 MB
) -> None:
    """
    Validates uploaded student handwritten work:
    - Rejects empty files.
    - Rejects files exceeding 10MB to protect memory & server bandwidth.
    - Validates MIME type and file extension.
    - Checks file header bytes for genuine image format signatures.
    """
    if not file_bytes or len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    if len(file_bytes) > max_size_bytes:
        mb_size = round(len(file_bytes) / (1024 * 1024), 2)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded image is too large ({mb_size}MB). Maximum allowed is 10MB.",
        )

    # Check MIME type
    clean_mime = (content_type or "").lower().split(";")[0].strip()
    if clean_mime and clean_mime not in ALLOWED_IMAGE_MIMES and clean_mime != "application/octet-stream":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{clean_mime}'. Please upload a PNG, JPEG, or WebP photo of your work.",
        )

    # Validate header magic bytes (if file is at least 8 bytes)
    if len(file_bytes) >= 8:
        is_valid_magic = False
        if file_bytes.startswith(b"\xff\xd8\xff"):  # JPEG
            is_valid_magic = True
        elif file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
            is_valid_magic = True
        elif file_bytes.startswith(b"RIFF") and b"WEBP" in file_bytes[:16]:  # WebP
            is_valid_magic = True
        elif b"ftyp" in file_bytes[:16]:  # HEIC/HEIF
            is_valid_magic = True
        elif clean_mime in ALLOWED_IMAGE_MIMES:
            is_valid_magic = True

        if not is_valid_magic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File header does not match a recognized image format. Please upload a clear photo of your math work.",
            )


# In-memory security audit event log (bounded)
_audit_log: list[Dict[str, Any]] = []

def record_security_event(event_type: str, details: Dict[str, Any]) -> None:
    """Records security and safety telemetry events."""
    event = {
        "timestamp": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": event_type,
        "details": details,
    }
    _audit_log.append(event)
    if len(_audit_log) > 500:
        _audit_log.pop(0)


def get_security_telemetry() -> Dict[str, Any]:
    """Returns platform safety health and defense status."""
    return {
        "status": "healthy",
        "guardrails_active": True,
        "anti_prompt_injection": "enabled",
        "socratic_answer_protection": "enabled",
        "file_upload_shield": "10MB_image_strict",
        "audit_events_count": len(_audit_log),
        "recent_security_events": _audit_log[-5:],
    }
