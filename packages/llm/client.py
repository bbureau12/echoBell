"""
LLM Client Abstraction

Provides a unified interface for different LLM backends:
- Vicuna (local/self-hosted)
- Claude API
- OpenAI API
- Any other LLM
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import json


class LLMClient(ABC):
    """Abstract base class for LLM clients"""
    
    @abstractmethod
    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a message with the LLM.
        
        Args:
            messages: Conversation history
            tools: Available tools (function calling)
            system: System prompt
            max_tokens: Max response tokens
            
        Returns:
            Response with content and optional tool calls
        """
        pass


class VicunaClient(LLMClient):
    """
    Client for Vicuna (local LLM via HTTP API).
    
    Vicuna typically runs via FastChat or similar serving framework.
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        model: str = "vicuna-13b-v1.5"
    ):
        """
        Initialize Vicuna client.
        
        Args:
            base_url: Vicuna server URL
            model: Model name
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.session = None
    
    async def _get_session(self):
        """Get or create aiohttp session"""
        if self.session is None:
            import aiohttp
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call Vicuna API.
        
        Vicuna doesn't natively support tool calling like Claude,
        so we'll use prompt engineering to simulate it.
        """
        session = await self._get_session()
        
        # Build prompt for Vicuna
        prompt = self._build_vicuna_prompt(messages, tools, system)
        
        # Call Vicuna API (FastChat format)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stop": ["</s>", "USER:", "ASSISTANT:"]
        }
        
        async with session.post(
            f"{self.base_url}/v1/completions",
            json=payload
        ) as response:
            result = await response.json()
        
        # Parse response and extract any tool calls
        text = result["choices"][0]["text"].strip()
        
        # Check if response contains tool call (JSON format)
        tool_call = self._extract_tool_call(text)
        
        if tool_call:
            return {
                "content": [{
                    "type": "tool_use",
                    "name": tool_call["name"],
                    "input": tool_call["input"],
                    "id": f"tool_{id(tool_call)}"
                }],
                "stop_reason": "tool_use"
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": text
                }],
                "stop_reason": "end_turn"
            }
    
    def _build_vicuna_prompt(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        system: Optional[str]
    ) -> str:
        """
        Build Vicuna-style prompt with tool calling instructions.
        """
        prompt_parts = []
        
        # System prompt with tool instructions
        if system:
            prompt_parts.append(f"SYSTEM: {system}\n")
        
        if tools:
            prompt_parts.append("\nAvailable Tools:")
            for tool in tools:
                prompt_parts.append(f"\n- {tool['name']}: {tool['description']}")
                prompt_parts.append(f"  Parameters: {json.dumps(tool['input_schema'])}")
            
            prompt_parts.append(
                "\n\nTo use a tool, respond with JSON:\n"
                '{"tool": "tool_name", "parameters": {...}}\n'
            )
        
        prompt_parts.append("\n")
        
        # Conversation history
        for msg in messages:
            role = msg["role"].upper()
            
            if isinstance(msg["content"], str):
                content = msg["content"]
            elif isinstance(msg["content"], list):
                # Handle complex content (tool results, etc.)
                content = self._format_content_blocks(msg["content"])
            else:
                content = str(msg["content"])
            
            prompt_parts.append(f"{role}: {content}\n")
        
        # Add assistant prompt
        prompt_parts.append("ASSISTANT:")
        
        return "".join(prompt_parts)
    
    def _format_content_blocks(self, content: List[Dict]) -> str:
        """Format content blocks into text"""
        parts = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                parts.append(f"[Tool Result: {block['content']}]")
        return " ".join(parts)
    
    def _extract_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract tool call from LLM response.
        
        Looks for JSON pattern: {"tool": "name", "parameters": {...}}
        """
        # Try to find JSON in response
        import re
        json_pattern = r'\{[^}]*"tool"[^}]*\}'
        matches = re.findall(json_pattern, text, re.DOTALL)
        
        if matches:
            try:
                # Parse first JSON match
                tool_call = json.loads(matches[0])
                
                if "tool" in tool_call:
                    return {
                        "name": tool_call["tool"],
                        "input": tool_call.get("parameters", {})
                    }
            except json.JSONDecodeError:
                pass
        
        return None
    
    async def close(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()


class ClaudeClient(LLMClient):
    """
    Client for Claude API (Anthropic).
    
    Kept for compatibility if you want to compare or use Claude later.
    """
    
    def __init__(self, api_key: str):
        """Initialize Claude client"""
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
    
    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        **kwargs
    ) -> Dict[str, Any]:
        """Call Claude API"""
        response = await self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=max_tokens,
            messages=messages,
            tools=tools or [],
            system=system or "",
            **kwargs
        )
        
        return {
            "content": response.content,
            "stop_reason": response.stop_reason
        }


class OpenAIClient(LLMClient):
    """
    Client for OpenAI API (GPT-4, etc).
    
    Uses function calling for tool support.
    """
    
    def __init__(self, api_key: str, model: str = "gpt-4"):
        """Initialize OpenAI client"""
        import openai
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
    
    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        **kwargs
    ) -> Dict[str, Any]:
        """Call OpenAI API"""
        
        # Convert to OpenAI format
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        
        for msg in messages:
            openai_messages.append({
                "role": msg["role"],
                "content": str(msg["content"])
            })
        
        # Convert tools to functions
        functions = None
        if tools:
            functions = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"]
                }
                for t in tools
            ]
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            functions=functions,
            max_tokens=max_tokens,
            **kwargs
        )
        
        message = response.choices[0].message
        
        # Check for function call
        if message.function_call:
            return {
                "content": [{
                    "type": "tool_use",
                    "name": message.function_call.name,
                    "input": json.loads(message.function_call.arguments),
                    "id": f"tool_{response.id}"
                }],
                "stop_reason": "function_call"
            }
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": message.content
                }],
                "stop_reason": "stop"
            }


def create_llm_client(
    provider: str = "vicuna",
    **kwargs
) -> LLMClient:
    """
    Factory function to create LLM client.
    
    Args:
        provider: "vicuna", "claude", or "openai"
        **kwargs: Provider-specific arguments
        
    Returns:
        LLMClient instance
        
    Examples:
        # Vicuna (local)
        client = create_llm_client("vicuna", base_url="http://localhost:8000")
        
        # Claude
        client = create_llm_client("claude", api_key="sk-ant-...")
        
        # OpenAI
        client = create_llm_client("openai", api_key="sk-...", model="gpt-4")
    """
    if provider == "vicuna":
        return VicunaClient(**kwargs)
    elif provider == "claude":
        return ClaudeClient(**kwargs)
    elif provider == "openai":
        return OpenAIClient(**kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider}")
