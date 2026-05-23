import ipaddress
import urllib.request
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def get_client_ip(request):
    """
    Extract client IP address from request headers or REMOTE_ADDR.
    """
    # Try Cloudflare connecting IP first
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()

    # Try X-Forwarded-For
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, the first one is the client
        return x_forwarded_for.split(",")[0].strip()

    # Fallback to Remote Addr
    return request.META.get("REMOTE_ADDR", "").strip()


def is_public_ip(ip_str):
    """
    Verify if the IP is a valid public IP.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def resolve_country_code(request):
    """
    Resolve the country code of the user/request.
    Priority:
    1. User's active organization country code (if logged in and has an org)
    2. Cloudflare GeoIP Header (HTTP_CF_IPCOUNTRY)
    3. Custom headers (HTTP_X_COUNTRY_CODE, HTTP_X_REAL_COUNTRY)
    4. Session cached country code
    5. Geolocation API based on client IP
    6. Fallback: "CO" (Colombia) or a setting if defined
    """
    # 1. User's active organization
    if hasattr(request, "user") and request.user and request.user.is_authenticated:
        membership = request.user.memberships.filter(is_active=True).first()
        if membership and membership.organization and membership.organization.country_code:
            return membership.organization.country_code.upper()

    # 2. Cloudflare GeoIP Header (standard for CF deployments)
    cf_country = request.META.get("HTTP_CF_IPCOUNTRY")
    if cf_country and len(cf_country.strip()) == 2:
        return cf_country.strip().upper()

    # 3. Custom headers
    for header in ["HTTP_X_COUNTRY_CODE", "HTTP_X_REAL_COUNTRY"]:
        val = request.META.get(header)
        if val and len(val.strip()) == 2:
            return val.strip().upper()

    # 4. Session cache
    if hasattr(request, "session") and request.session is not None:
        cached = request.session.get("country_code")
        if cached:
            return cached.upper()

    # 5. Geolocation API based on client IP
    client_ip = get_client_ip(request)
    if client_ip and is_public_ip(client_ip):
        try:
            # Using ip-api.com which is free, fast, and does not require credentials
            url = f"http://ip-api.com/json/{client_ip}"
            req = urllib.request.Request(url, headers={"User-Agent": "BarberSync/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as response:
                data = json.loads(response.read().decode("utf-8"))
                if data.get("status") == "success":
                    country_code = data.get("countryCode")
                    if country_code and len(country_code) == 2:
                        code = country_code.upper()
                        # Cache in session if available
                        if hasattr(request, "session") and request.session is not None:
                            request.session["country_code"] = code
                        return code
        except Exception as e:
            logger.warning(f"Error resolving country for IP {client_ip}: {e}")

    # 6. Fallback default country
    return "CO"
