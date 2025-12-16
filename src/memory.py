"""Memory management using Qdrant vector database."""

import os
import uuid
from datetime import datetime
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct


# Collection names
CHAT_HISTORY_COLLECTION = "chat_history"
USER_FACTS_COLLECTION = "user_facts"

# Vector dimensions for nomic-embed-text
EMBEDDING_DIM = 768


class MemoryManager:
    """Manages chat history and user facts in Qdrant."""
    
    def __init__(
        self,
        embed_func: callable,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        """
        Initialize the memory manager.
        
        Args:
            embed_func: Function that takes text and returns embedding vector
            host: Qdrant host (defaults to QDRANT_HOST env var)
            port: Qdrant port (defaults to QDRANT_PORT env var)
        """
        self.host = host or os.getenv("QDRANT_HOST", "localhost")
        self.port = port or int(os.getenv("QDRANT_PORT", "6333"))
        self.embed = embed_func
        
        self.client = QdrantClient(host=self.host, port=self.port)
        self._ensure_collections()
    
    def _ensure_collections(self) -> None:
        """Create collections if they don't exist."""
        collections = [c.name for c in self.client.get_collections().collections]
        
        if CHAT_HISTORY_COLLECTION not in collections:
            self.client.create_collection(
                collection_name=CHAT_HISTORY_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
        
        if USER_FACTS_COLLECTION not in collections:
            self.client.create_collection(
                collection_name=USER_FACTS_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
    
    def add_message(
        self,
        role: str,
        content: str,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Add a message to chat history.
        
        Args:
            role: "user" or "assistant"
            content: Message content
            timestamp: Message timestamp (defaults to now)
            
        Returns:
            Message ID
        """
        msg_id = str(uuid.uuid4())
        ts = timestamp or datetime.utcnow()
        
        embedding = self.embed(content)
        
        self.client.upsert(
            collection_name=CHAT_HISTORY_COLLECTION,
            points=[
                PointStruct(
                    id=msg_id,
                    vector=embedding,
                    payload={
                        "role": role,
                        "content": content,
                        "timestamp": ts.isoformat(),
                    },
                )
            ],
        )
        
        return msg_id
    
    def add_fact(self, fact: str, source_message_id: Optional[str] = None) -> str:
        """
        Add a fact about the user.
        
        Args:
            fact: The fact to store
            source_message_id: Optional ID of the message this fact was extracted from
            
        Returns:
            Fact ID
        """
        fact_id = str(uuid.uuid4())
        embedding = self.embed(fact)
        
        self.client.upsert(
            collection_name=USER_FACTS_COLLECTION,
            points=[
                PointStruct(
                    id=fact_id,
                    vector=embedding,
                    payload={
                        "fact": fact,
                        "source_message_id": source_message_id,
                        "created_at": datetime.utcnow().isoformat(),
                    },
                )
            ],
        )
        
        return fact_id
    
    def get_relevant_history(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get chat history relevant to the query.
        
        Args:
            query: The query to find relevant messages for
            limit: Maximum number of messages to return
            
        Returns:
            List of messages with role, content, and timestamp
        """
        embedding = self.embed(query)
        
        results = self.client.search(
            collection_name=CHAT_HISTORY_COLLECTION,
            query_vector=embedding,
            limit=limit,
        )
        
        messages = []
        for result in results:
            messages.append({
                "role": result.payload["role"],
                "content": result.payload["content"],
                "timestamp": result.payload["timestamp"],
                "score": result.score,
            })
        
        # Sort by timestamp to maintain conversation order
        messages.sort(key=lambda m: m["timestamp"])
        return messages
    
    def get_recent_history(self, limit: int = 20) -> list[dict]:
        """
        Get the most recent chat messages.
        
        Args:
            limit: Maximum number of messages to return
            
        Returns:
            List of messages sorted by timestamp (oldest first)
        """
        # Scroll through all messages and sort by timestamp
        results, _ = self.client.scroll(
            collection_name=CHAT_HISTORY_COLLECTION,
            limit=limit * 2,  # Get more than needed to ensure we have enough
            with_payload=True,
            with_vectors=False,
        )
        
        messages = []
        for point in results:
            messages.append({
                "role": point.payload["role"],
                "content": point.payload["content"],
                "timestamp": point.payload["timestamp"],
            })
        
        # Sort by timestamp and take the most recent
        messages.sort(key=lambda m: m["timestamp"], reverse=True)
        messages = messages[:limit]
        messages.reverse()  # Return in chronological order
        
        return messages
    
    def get_relevant_facts(self, query: str, limit: int = 5) -> list[str]:
        """
        Get facts about the user relevant to the query.
        
        Args:
            query: The query to find relevant facts for
            limit: Maximum number of facts to return
            
        Returns:
            List of fact strings
        """
        embedding = self.embed(query)
        
        results = self.client.search(
            collection_name=USER_FACTS_COLLECTION,
            query_vector=embedding,
            limit=limit,
        )
        
        return [result.payload["fact"] for result in results]
    
    def get_all_facts(self) -> list[str]:
        """Get all stored facts about the user."""
        results, _ = self.client.scroll(
            collection_name=USER_FACTS_COLLECTION,
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        
        return [point.payload["fact"] for point in results]
    
    def get_last_user_message_time(self) -> Optional[datetime]:
        """Get the timestamp of the last user message."""
        results, _ = self.client.scroll(
            collection_name=CHAT_HISTORY_COLLECTION,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="role",
                        match=models.MatchValue(value="user"),
                    )
                ]
            ),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        
        if not results:
            return None
        
        # Find the most recent timestamp
        timestamps = [
            datetime.fromisoformat(p.payload["timestamp"]) 
            for p in results
        ]
        
        return max(timestamps) if timestamps else None
    
    def message_count(self) -> int:
        """Get the total number of messages in history."""
        collection_info = self.client.get_collection(CHAT_HISTORY_COLLECTION)
        return collection_info.points_count

