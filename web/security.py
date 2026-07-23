import hmac, secrets, time
from collections import defaultdict, deque
from flask import abort, request, session
from werkzeug.security import check_password_hash

ATTEMPTS=defaultdict(deque)
def auth_config(config): return config.get("web",{}).get("authentication",{})
def enabled(config):
    a=auth_config(config)
    return bool(a.get("enabled") and a.get("username") and a.get("password_hash"))
def valid(config):
    if not enabled(config): return True
    a=auth_config(config)
    return bool(session.get("authenticated") and session.get("username")==a.get("username") and session.get("session_version")==int(a.get("session_version",1)))
def csrf_token():
    if "csrf_token" not in session: session["csrf_token"]=secrets.token_urlsafe(32)
    return session["csrf_token"]
def verify_csrf():
    provided = request.form.get("_csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(session.get("csrf_token", ""), provided):
        abort(400)
def limited():
    key=request.remote_addr or "unknown"; now=time.time(); q=ATTEMPTS[key]
    while q and now-q[0]>300:q.popleft()
    return len(q)>=5
def failed(): ATTEMPTS[request.remote_addr or "unknown"].append(time.time())
def clear(): ATTEMPTS.pop(request.remote_addr or "unknown",None)
def verify(config,user,password):
    a=auth_config(config)
    return hmac.compare_digest(str(user),str(a.get("username",""))) and check_password_hash(str(a.get("password_hash","")),password)
