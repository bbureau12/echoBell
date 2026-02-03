"""
Echonet Discovery and Registration Service

Auto-discovers Echonet instances on the local network via mDNS/Zeroconf
and registers the policy server as a voice command target.

Features:
- mDNS service discovery (_echonet._tcp.local.)
- Automatic registration on startup
- Health check with re-registration
- Error reporting to Telegram (future)
"""

import os
import logging
import asyncio
import httpx
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime

try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    print("[warning] zeroconf not installed. Echonet auto-discovery disabled. Install with: pip install zeroconf")

logger = logging.getLogger(__name__)


@dataclass
class EchonetInstance:
    """Discovered Echonet instance"""
    name: str
    host: str
    port: int
    zone: Optional[str] = None
    subzone: Optional[str] = None
    version: Optional[str] = None
    capabilities: Optional[str] = None
    
    @property
    def base_url(self) -> str:
        """Get base URL for API calls"""
        return f"http://{self.host}:{self.port}"
    
    @property
    def display_name(self) -> str:
        """Get human-readable name"""
        parts = [self.name]
        if self.zone:
            parts.append(f"zone:{self.zone}")
        if self.subzone:
            parts.append(f"subzone:{self.subzone}")
        return " ".join(parts)


class EchonetDiscoveryListener(ServiceListener):
    """Listens for Echonet service announcements via mDNS"""
    
    def __init__(self):
        self.instances: Dict[str, EchonetInstance] = {}
        self.on_instance_added = None  # Callback when new instance found
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a new service is discovered"""
        info = zc.get_service_info(type_, name)
        if info:
            # Extract instance details
            instance_name = name.replace(f".{type_}", "")
            host = info.parsed_addresses()[0] if info.parsed_addresses() else None
            port = info.port
            
            # Extract properties
            properties = {}
            if info.properties:
                for key, value in info.properties.items():
                    try:
                        properties[key.decode('utf-8')] = value.decode('utf-8')
                    except:
                        pass
            
            if host:
                instance = EchonetInstance(
                    name=instance_name,
                    host=host,
                    port=port,
                    zone=properties.get('zone'),
                    subzone=properties.get('subzone'),
                    version=properties.get('version'),
                    capabilities=properties.get('capabilities')
                )
                
                self.instances[instance_name] = instance
                logger.info(f"Discovered Echonet: {instance.display_name} at {instance.base_url}")
                
                # Trigger callback if set
                if self.on_instance_added:
                    asyncio.create_task(self.on_instance_added(instance))
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service goes offline"""
        instance_name = name.replace(f".{type_}", "")
        if instance_name in self.instances:
            instance = self.instances.pop(instance_name)
            logger.warning(f"Echonet went offline: {instance.display_name}")
    
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service updates its information"""
        # Re-add to update details
        self.add_service(zc, type_, name)


class EchonetRegistrationService:
    """Manages registration with discovered Echonet instances"""
    
    def __init__(
        self,
        target_name: str,
        base_url: str,
        wake_phrases: List[str],
        api_key: str
    ):
        self.target_name = target_name
        self.base_url = base_url
        self.wake_phrases = wake_phrases
        self.api_key = api_key
        self.registered_instances: Set[str] = set()
        self.failed_instances: Dict[str, str] = {}  # instance_name -> error_message
        self.listener: Optional[EchonetDiscoveryListener] = None
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
    
    def start_discovery(self):
        """Start mDNS discovery for Echonet instances"""
        if not ZEROCONF_AVAILABLE:
            logger.warning("Zeroconf not available. Echonet discovery disabled.")
            return
        
        try:
            self.zeroconf = Zeroconf()
            self.listener = EchonetDiscoveryListener()
            self.listener.on_instance_added = self.register_with_instance
            
            self.browser = ServiceBrowser(
                self.zeroconf,
                "_echonet._tcp.local.",
                self.listener
            )
            
            logger.info("Started Echonet discovery via mDNS (_echonet._tcp.local.)")
        except Exception as e:
            logger.error(f"Failed to start Echonet discovery: {e}")
    
    def stop_discovery(self):
        """Stop mDNS discovery"""
        if self.browser:
            self.browser.cancel()
        if self.zeroconf:
            self.zeroconf.close()
        logger.info("Stopped Echonet discovery")
    
    async def register_with_instance(self, instance: EchonetInstance) -> bool:
        """
        Register policy server as a target with an Echonet instance.
        
        Args:
            instance: Echonet instance to register with
        
        Returns:
            True if registration succeeded, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # First check if already registered
                check_url = f"{instance.base_url}/targets/{self.target_name}"
                
                try:
                    response = await client.get(
                        check_url,
                        headers={"X-API-Key": self.api_key}
                    )
                    
                    if response.status_code == 200:
                        # Already registered, check if details match
                        existing = response.json()
                        if existing.get("base_url") == self.base_url:
                            logger.info(f"Already registered with {instance.display_name}")
                            self.registered_instances.add(instance.name)
                            return True
                        else:
                            # Update registration (URL changed)
                            logger.info(f"Re-registering with {instance.display_name} (URL changed)")
                except httpx.HTTPStatusError:
                    # Not registered yet, continue with registration
                    pass
                
                # Register
                register_url = f"{instance.base_url}/register"
                payload = {
                    "name": self.target_name,
                    "base_url": self.base_url,
                    "phrases": self.wake_phrases
                }
                
                response = await client.post(
                    register_url,
                    headers={
                        "X-API-Key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                response.raise_for_status()
                
                logger.info(
                    f"✓ Registered with Echonet: {instance.display_name} "
                    f"(wake phrases: {', '.join(self.wake_phrases)})"
                )
                
                self.registered_instances.add(instance.name)
                if instance.name in self.failed_instances:
                    del self.failed_instances[instance.name]
                
                return True
                
        except httpx.HTTPError as e:
            error_msg = f"HTTP error: {str(e)}"
            logger.warning(f"Failed to register with {instance.display_name}: {error_msg}")
            self.failed_instances[instance.name] = error_msg
            return False
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected error registering with {instance.display_name}: {error_msg}")
            self.failed_instances[instance.name] = error_msg
            return False
    
    async def health_check_and_reregister(self) -> Dict[str, any]:
        """
        Health check: verify all discovered instances are still registered.
        Attempt to re-register any that failed.
        
        Returns:
            Health status dict with registration details
        """
        if not self.listener:
            return {
                "discovery_enabled": False,
                "reason": "Zeroconf not available or not started"
            }
        
        discovered = list(self.listener.instances.values())
        results = []
        
        for instance in discovered:
            if instance.name in self.registered_instances:
                # Verify still registered
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(
                            f"{instance.base_url}/targets/{self.target_name}",
                            headers={"X-API-Key": self.api_key}
                        )
                        
                        if response.status_code == 200:
                            results.append({
                                "instance": instance.display_name,
                                "status": "registered",
                                "url": instance.base_url
                            })
                        else:
                            # Lost registration, re-register
                            logger.warning(f"Lost registration with {instance.display_name}, re-registering...")
                            success = await self.register_with_instance(instance)
                            results.append({
                                "instance": instance.display_name,
                                "status": "re-registered" if success else "failed",
                                "url": instance.base_url
                            })
                except Exception as e:
                    results.append({
                        "instance": instance.display_name,
                        "status": "error",
                        "error": str(e),
                        "url": instance.base_url
                    })
            else:
                # Not registered or failed before, try to register
                success = await self.register_with_instance(instance)
                results.append({
                    "instance": instance.display_name,
                    "status": "registered" if success else "failed",
                    "url": instance.base_url,
                    "error": self.failed_instances.get(instance.name)
                })
        
        return {
            "discovery_enabled": True,
            "discovered_count": len(discovered),
            "registered_count": len(self.registered_instances),
            "failed_count": len(self.failed_instances),
            "instances": results,
            "failed_instances": self.failed_instances,
            "timestamp": datetime.now().isoformat()
        }
    
    def get_status(self) -> Dict[str, any]:
        """Get current registration status"""
        if not self.listener:
            return {
                "discovery_enabled": False,
                "reason": "Zeroconf not available or not started"
            }
        
        discovered = list(self.listener.instances.values())
        
        return {
            "discovery_enabled": True,
            "discovered_count": len(discovered),
            "registered_count": len(self.registered_instances),
            "failed_count": len(self.failed_instances),
            "instances": [
                {
                    "name": inst.display_name,
                    "url": inst.base_url,
                    "zone": inst.zone,
                    "subzone": inst.subzone,
                    "registered": inst.name in self.registered_instances,
                    "error": self.failed_instances.get(inst.name)
                }
                for inst in discovered
            ]
        }


# Global instance (initialized in server.py)
echonet_service: Optional[EchonetRegistrationService] = None


def get_echonet_service() -> Optional[EchonetRegistrationService]:
    """Get the global Echonet registration service"""
    return echonet_service


def init_echonet_service(
    target_name: str = "echobell",
    base_url: str = "http://localhost:8000",
    wake_phrases: List[str] = None,
    api_key: str = "dontgiveitupluffy"
) -> EchonetRegistrationService:
    """
    Initialize the Echonet registration service.
    
    Args:
        target_name: Name to register as (default: "echobell")
        base_url: Policy server base URL
        wake_phrases: List of wake phrases (default: ["echobell"])
        api_key: Echonet API key
    
    Returns:
        EchonetRegistrationService instance
    """
    global echonet_service
    
    if wake_phrases is None:
        wake_phrases = ["echobell"]
    
    echonet_service = EchonetRegistrationService(
        target_name=target_name,
        base_url=base_url,
        wake_phrases=wake_phrases,
        api_key=api_key
    )
    
    return echonet_service
