"""Shared messaging implementation for agent-to-agent communication."""

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Deque, DefaultDict, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

MessageType = Literal["task", "result", "revision_request", "confirmation"]


class AgentMessage(BaseModel):
    """Schema for all messages exchanged between agents."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    from_agent: str
    to_agent: str
    message_type: MessageType
    payload: Dict[str, Any]
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    parent_message_id: Optional[str] = None


class MessageBus:
    """In-memory topic-based message bus used by all agents."""

    def __init__(self) -> None:
        self._topics: DefaultDict[str, Deque[Any]] = defaultdict(deque)
        self._all_messages: List[AgentMessage] = []

    def send_message(
        self,
        to_agent: str,
        from_agent: str,
        message_type: str,
        payload: Dict[str, Any],
        parent_message_id: Optional[str] = None,
    ) -> AgentMessage:
        """Validate and send a message to a destination agent queue."""
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            payload=payload,
            parent_message_id=parent_message_id,
        )
        self._topics[to_agent].append(message)
        self._all_messages.append(message)
        return message

    def receive_messages(self, agent_name: str) -> List[AgentMessage]:
        """Return and clear queued messages for a specific agent."""
        queued = list(self._topics[agent_name])
        self._topics[agent_name].clear()

        normalized: List[AgentMessage] = []
        for item in queued:
            if isinstance(item, AgentMessage):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(AgentMessage.model_validate(item))
        return normalized

    def full_history(self) -> List[AgentMessage]:
        """Return the complete immutable message history."""
        return list(self._all_messages)

    def publish(self, topic: str, message: Dict[str, Any]) -> None:
        self._topics[topic].append(message)

    def consume(self, topic: str) -> List[Dict[str, Any]]:
        messages = list(self._topics[topic])
        self._topics[topic].clear()
        return messages

    def peek(self, topic: str) -> List[Dict[str, Any]]:
        return list(self._topics[topic])

    def has_messages(self, topic: str) -> bool:
        return len(self._topics[topic]) > 0
