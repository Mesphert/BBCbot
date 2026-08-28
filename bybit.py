# bybit.py - update the _fetch_via_proxy function
from supabase import create_client, Client

def _fetch_via_proxy(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """
    POST to the Supabase Edge Function which forwards to Bybit.
    Returns the raw Bybit JSON dict, or None on any error.
    """
    if not config.SUPABASE_FUNCTION_URL:
        logger.error("SUPABASE_FUNCTION_URL is not set in environment variables.")
        return None

    # Initialize Supabase client
    supabase: Client = create_client(
        config.SUPABASE_URL,
        config.SUPABASE_PUBLISHABLE_KEY  # or SUPABASE_SECRET_KEY for admin
    )

    payload = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    try:
        # Use Supabase client to invoke function
        response = supabase.functions.invoke(
            "bybit-proxy",  # Function name (not full URL)
            invoke_options={
                "body": payload
            }
        )
        
        logger.debug(f"Response status: {response.status_code}")
        
        if not response.ok:
            logger.error(f"Error response: {response.text}")
            return None
            
        return response.json()

    except Exception as e:
        logger.error(f"Supabase proxy request failed for {symbol} {interval}: {e}")
        return None
