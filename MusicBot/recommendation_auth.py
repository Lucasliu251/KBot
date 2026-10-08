"""Legacy Music OAuth URLs now use the TrashBox login service.

The Music bot has no OAuth client credentials. Provider linking and callback
validation belong to TrashBox Backend.
"""
from central_auth import login_url


def oauth_configured() -> bool:
    return True
