"""
Echonet Active Mode Control

Service functions for controlling Echonet listen modes from the policy server.
Allows LLM to request additional voice input by putting Echonet into "open_listen" mode.
"""

import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class EchonetModeService:
    """
    Service for controlling Echonet listen modes.
    
    Enables the LLM to request voice input by activating Echonet's
    open listening mode, which allows continuous conversation without
    wake words.
    """
    
    def __init__(self, api_key: str = "dontgiveitupluffy"):
        self.api_key = api_key
        self.timeout = 10.0
    
    async def activate_listening(
        self,
        echonet_url: str,
        target_name: str,
        source: str = "llm",
        reason: str = "Requesting additional information"
    ) -> Dict[str, Any]:
        """
        Activate open listening mode on an Echonet instance.
        
        This puts the Echonet into "open_listen" state, allowing the user
        to speak without needing to say the wake word again.
        
        Args:
            echonet_url: Base URL of Echonet instance (e.g., http://192.168.1.50:8123)
            target_name: Target name (e.g., "echobell")
            source: Source of the request (default: "llm")
            reason: Human-readable reason for activation
        
        Returns:
            Response dict with status and message
        
        Raises:
            httpx.HTTPError: If request fails
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    f"{echonet_url}/state",
                    headers={
                        "X-API-Key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "target": target_name,
                        "state": "open_listen",
                        "source": source,
                        "reason": reason
                    }
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(
                    f"Activated open_listen on {echonet_url} for target '{target_name}': {reason}"
                )
                
                return {
                    "success": True,
                    "echonet_url": echonet_url,
                    "target": target_name,
                    "mode": "open_listen",
                    "message": result.get("message", "Listening mode activated"),
                    "response": result
                }
                
        except httpx.HTTPError as e:
            logger.error(f"Failed to activate listening on {echonet_url}: {e}")
            return {
                "success": False,
                "echonet_url": echonet_url,
                "target": target_name,
                "error": str(e),
                "message": f"Failed to activate listening mode: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error activating listening on {echonet_url}: {e}")
            return {
                "success": False,
                "echonet_url": echonet_url,
                "target": target_name,
                "error": str(e),
                "message": f"Unexpected error: {str(e)}"
            }
    
    async def deactivate_listening(
        self,
        echonet_url: str,
        target_name: str,
        source: str = "llm",
        reason: str = "Conversation complete"
    ) -> Dict[str, Any]:
        """
        Deactivate open listening mode (return to trigger mode).
        
        Args:
            echonet_url: Base URL of Echonet instance
            target_name: Target name (e.g., "echobell")
            source: Source of the request (default: "llm")
            reason: Human-readable reason for deactivation
        
        Returns:
            Response dict with status and message
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.put(
                    f"{echonet_url}/state",
                    headers={
                        "X-API-Key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "target": target_name,
                        "state": "trigger",
                        "source": source,
                        "reason": reason
                    }
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(
                    f"Deactivated open_listen on {echonet_url} for target '{target_name}': {reason}"
                )
                
                return {
                    "success": True,
                    "echonet_url": echonet_url,
                    "target": target_name,
                    "mode": "trigger",
                    "message": result.get("message", "Returned to trigger mode"),
                    "response": result
                }
                
        except httpx.HTTPError as e:
            logger.error(f"Failed to deactivate listening on {echonet_url}: {e}")
            return {
                "success": False,
                "echonet_url": echonet_url,
                "target": target_name,
                "error": str(e),
                "message": f"Failed to deactivate listening mode: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Unexpected error deactivating listening on {echonet_url}: {e}")
            return {
                "success": False,
                "echonet_url": echonet_url,
                "target": target_name,
                "error": str(e),
                "message": f"Unexpected error: {str(e)}"
            }
    
    async def get_echonet_state(
        self,
        echonet_url: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get current state of an Echonet instance.
        
        Args:
            echonet_url: Base URL of Echonet instance
        
        Returns:
            State dict or None if request fails
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{echonet_url}/state",
                    headers={"X-API-Key": self.api_key}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get state from {echonet_url}: {e}")
            return None


# Global instance (initialized in server.py if needed)
echonet_mode_service: Optional[EchonetModeService] = None


def get_echonet_mode_service() -> EchonetModeService:
    """Get or initialize the Echonet mode service"""
    global echonet_mode_service
    if echonet_mode_service is None:
        echonet_mode_service = EchonetModeService()
    return echonet_mode_service


def init_echonet_mode_service(api_key: str = "dontgiveitupluffy") -> EchonetModeService:
    """Initialize the Echonet mode service"""
    global echonet_mode_service
    echonet_mode_service = EchonetModeService(api_key=api_key)
    return echonet_mode_service
