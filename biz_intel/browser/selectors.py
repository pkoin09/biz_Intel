"""
Common selectors.

These are intentionally generic.

Site-specific selectors should eventually live in:

selectors/
    google.py
    yelp.py
    etc.
"""

# Generic

LOAD_MORE_BUTTON = "button"

EMAIL_LINK = "a[href^='mailto:']"

PHONE_LINK = "a[href^='tel:']"

WEBSITE_LINK = "a[href^='http']"

FACEBOOK_LINK = "a[href*='facebook.com']"

INSTAGRAM_LINK = "a[href*='instagram.com']"

LINKEDIN_LINK = "a[href*='linkedin.com']"

TWITTER_LINK = "a[href*='twitter.com']," "a[href*='x.com']"
