"""Very small role-based access control for the demo UI and API.

Roles:
  viewer  : dashboards, graph explorer, GraphRAG assistant, benchmark
  analyst : + custom read-only Cypher console
  admin   : + pipeline monitoring
Passwords are stored as SHA-256 hashes (demo accounts, see README).
"""
import hashlib

USERS = {
    "viewer": {"hash": hashlib.sha256(b"viewer123").hexdigest(), "role": "viewer"},
    "analyst": {"hash": hashlib.sha256(b"analyst123").hexdigest(), "role": "analyst"},
    "admin": {"hash": hashlib.sha256(b"admin123").hexdigest(), "role": "admin"},
}
ROLE_LEVEL = {"viewer": 1, "analyst": 2, "admin": 3}

# API keys for the REST API -> role
API_KEYS = {"demo-viewer-key": "viewer", "demo-analyst-key": "analyst"}


def check_login(username, password):
    u = USERS.get(username)
    if u and hashlib.sha256(password.encode()).hexdigest() == u["hash"]:
        return u["role"]
    return None


def allowed(role, needed):
    return ROLE_LEVEL.get(role, 0) >= ROLE_LEVEL[needed]
