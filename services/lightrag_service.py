"""
LightRAG integration for AntiBlack pipeline.
Handles deep channel processing with knowledge graph construction.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LightRAGIntegrator:
    """Integration with LightRAG for knowledge graph operations."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._rag = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize LightRAG instance."""
        if self._initialized:
            return

        try:
            from lightrag import LightRAG
            from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed

            # Get LightRAG config
            lightrag_config = self.config.get('lightrag', {})
            working_dir = lightrag_config.get('working_dir', './rag_storage')

            # Initialize LightRAG
            self._rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=gpt_4o_mini_complete,
                embedding_func=openai_embed
            )

            # Initialize storage backends
            await self._rag.initialize_storages()
            self._initialized = True
            logger.info("LightRAG initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize LightRAG: {e}")
            self._rag = None

    async def finalize(self) -> None:
        """Finalize LightRAG instance."""
        if self._rag and self._initialized:
            await self._rag.finalize_storages()
            self._initialized = False

    async def insert(self, text: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Insert text into knowledge graph.
        LightRAG will automatically extract entities and relationships.
        """
        if not self._rag or not self._initialized:
            logger.warning("LightRAG not initialized, skipping insert")
            return False

        try:
            await self._rag.ainsert(text)
            logger.debug(f"Inserted text into LightRAG: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to insert into LightRAG: {e}")
            return False

    async def query(
        self,
        query_text: str,
        mode: str = "hybrid",
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Query the knowledge graph.

        Args:
            query_text: Query string
            mode: Query mode (local/global/hybrid/naive/mix)
            top_k: Number of results to return

        Returns:
            Query results with entities and relationships
        """
        if not self._rag or not self._initialized:
            logger.warning("LightRAG not initialized, returning empty results")
            return {"results": [], "entities": [], "relationships": []}

        try:
            from lightrag import QueryParam

            result = await self._rag.aquery(
                query_text,
                param=QueryParam(
                    mode=mode,
                    top_k=top_k
                )
            )

            # Parse result
            return {
                "results": [result] if isinstance(result, str) else result,
                "query": query_text,
                "mode": mode
            }
        except Exception as e:
            logger.error(f"Failed to query LightRAG: {e}")
            return {"results": [], "entities": [], "relationships": []}

    async def insert_custom_kg(
        self,
        text: str,
        source: str = "auto"
    ) -> Dict[str, Any]:
        """
        Insert with custom knowledge graph construction.
        Useful for structured data insertion.
        """
        if not self._rag or not self._initialized:
            return {"success": False, "error": "LightRAG not initialized"}

        try:
            # Use ainsert_custom_kg for controlled KG construction
            await self._rag.ainsert_custom_kg(text)
            return {"success": True, "text": text}
        except Exception as e:
            logger.error(f"Failed to insert custom KG: {e}")
            return {"success": False, "error": str(e)}

    def get_stats(self) -> Dict[str, int]:
        """Get knowledge graph statistics."""
        if not self._rag or not self._initialized:
            return {"nodes": 0, "edges": 0, "documents": 0}

        try:
            # Get stats from storage
            return {
                "nodes": 0,  # Would need to query graph storage
                "edges": 0,
                "documents": 0
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"nodes": 0, "edges": 0, "documents": 0}


class GraphProcessor:
    """Processes messages through the deep channel (LightRAG)."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.lightrag = LightRAGIntegrator(config)

    async def initialize(self) -> None:
        """Initialize graph processor."""
        await self.lightrag.initialize()

    async def finalize(self) -> None:
        """Finalize graph processor."""
        await self.lightrag.finalize()

    async def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a message through the deep channel.

        Args:
            message: Message data with:
                - message_id: Unique message ID
                - raw_text: Original text
                - cleaned_text: Cleaned text
                - classification: Classification result
                - entities: Extracted entities

        Returns:
            Processing result with graph relations
        """
        try:
            # Build enhanced text with context
            enhanced_text = self._build_enhanced_text(message)

            # Insert into knowledge graph
            success = await self.lightrag.insert(enhanced_text, {
                "message_id": message.get('message_id'),
                "source": "deep_channel"
            })

            if success:
                return {
                    "success": True,
                    "message_id": message.get('message_id'),
                    "entities_inserted": len(message.get('entities', [])),
                    "graph_relations": []
                }
            else:
                return {
                    "success": False,
                    "message_id": message.get('message_id'),
                    "error": "Failed to insert into graph"
                }
        except Exception as e:
            logger.error(f"Error processing message through deep channel: {e}")
            return {
                "success": False,
                "message_id": message.get('message_id'),
                "error": str(e)
            }

    def _build_enhanced_text(self, message: Dict[str, Any]) -> str:
        """Build enhanced text with context for LightRAG."""
        parts = []

        # Add classification context
        classification = message.get('classification', {})
        if classification:
            parts.append(f"[风险类型: {classification.get('level1_label', '未知')} / {classification.get('level2_label', '未知')}]")

        # Add known entities
        entities = message.get('entities', [])
        if entities:
            entity_strs = []
            for ent in entities:
                entity_strs.append(f"{ent.get('entity_type', 'UNKNOWN')}:{ent.get('entity_value', '')}")
            if entity_strs:
                parts.append(f"[已知实体: {', '.join(entity_strs)}]")

        # Add original text
        parts.append(f"原文: {message.get('raw_text', '')}")

        return ' '.join(parts)

    async def query_graph(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10
    ) -> Dict[str, Any]:
        """Query the knowledge graph."""
        return await self.lightrag.query(query, mode, top_k)