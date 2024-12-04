import re

def verify_icao_location(location: str, required_prefix: str = None) -> bool:
    """
    Verify if a location string looks like a valid ICAO code.
    Returns True if the location is valid (either a 4-letter ICAO code or 'maasto').
    
    Args:
        location: The location string to verify
        required_prefix: If set, only accepts ICAO codes starting with this prefix
    """
    if not location:
        return False
    
    # Check for 'maasto' (case insensitive)
    if location.lower() == 'maasto':
        return True
    
    # Convert to uppercase for comparison
    location = location.upper()
    
    # ICAO codes are 4 letters
    if not re.match(r'^[A-Z]{4}$', location):
        return False
    
    # If a prefix is required, check for it
    if required_prefix:
        return location.startswith(required_prefix.upper())
    
    return True
