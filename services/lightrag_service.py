"""
LightRAG integration for AntiBlack pipeline.
Handles deep channel processing with knowledge graph construction.
"""
import os
import logging
from typing import Any, Dict, List, Optional
from functools import partial

logger = logging.getLogger(__name__)


def create_minimax_complete():
    """Create MiniMax LLM completion function (OpenAI-compatible)."""
    from openai import AsyncOpenAI

    async def minimax_complete(
        prompt,
        system_prompt=None,
        history_messages=None,
        enable_cot: bool = False,
        **kwargs,
    ) -> str:
        if history_messages is None:
            history_messages = []

        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("LLM_API_BASE", "https://api.minimaxi.com/v1")
        model = os.environ.get("LLM_MODEL", "MiniMax-M2.7")

        client = AsyncOpenAI(api_key=api_key, base_url=api_base)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in history_messages:
            messages.append(msg)

        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=120
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"MiniMax API call failed: {e}")
            return f"Error: {str(e)}"

    return minimax_complete


def create_ollama_embed():
    """Create Ollama embedding function (using bge-m3 model)."""
    from openai import AsyncOpenAI
    import numpy as np

    api_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("OLLAMA_API_KEY", "ollama")  # Ollama doesn't need real key
    model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest")

    async def ollama_embed(
        texts: list[str],
        model_name: str = model,
        **kwargs,
    ) -> np.ndarray:
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)

        try:
            response = await client.embeddings.create(
                model=model_name,
                input=texts
            )
            embeddings = [item.embedding for item in response.data]
            return np.array(embeddings)
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            # Return zeros on error
            return np.zeros((len(texts), 1024))

    return ollama_embed


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

            # Get LightRAG config
            lightrag_config = self.config.get('lightrag', {})
            working_dir = lightrag_config.get('working_dir', './rag_storage')

            # Get storage config
            storage_config = lightrag_config.get('storage', {})
            neo4j_config = lightrag_config.get('neo4j', {})
            pg_config = lightrag_config.get('postgresql', {})

            # Build vector_db_storage_cls_kwargs for PGVectorStorage
            vector_db_kwargs = {}
            if pg_config.get('host'):
                vector_db_kwargs["host"] = pg_config.get('host')
                vector_db_kwargs["port"] = pg_config.get('port', 5432)
                vector_db_kwargs["user"] = pg_config.get('user', 'antiblack')
                vector_db_kwargs["password"] = pg_config.get('password', 'antiblack123')
                vector_db_kwargs["database"] = pg_config.get('database', 'antiblack')

            # Build addon_params for Neo4j and other storages
            addon_params = {
                "neo4j": {
                    "uri": neo4j_config.get('uri', 'bolt://localhost:7687'),
                    "username": neo4j_config.get('username', 'neo4j'),
                    "password": neo4j_config.get('password', 'neo4j123'),
                },
                "pg": {
                    "host": pg_config.get('host', 'localhost'),
                    "port": pg_config.get('port', 5432),
                    "user": pg_config.get('user', 'antiblack'),
                    "password": pg_config.get('password', 'antiblack123'),
                    "database": pg_config.get('database', 'antiblack'),
                }
            }

            # Initialize LightRAG with remote storage backends
            # LLM: MiniMax (OpenAI-compatible)
            # Embedding: Ollama bge-m3 (local)
            from lightrag.utils import EmbeddingFunc

            self._rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=create_minimax_complete(),
                embedding_func=EmbeddingFunc(
                    embedding_dim=1024,  # bge-m3 outputs 1024 dim
                    max_token_size=8192,
                    func=create_ollama_embed(),
                ),
                # Storage backends (use correct storage names)
                kv_storage=storage_config.get('kv', 'PGKVStorage'),
                vector_storage=storage_config.get('vector', 'PGVectorStorage'),
                graph_storage=storage_config.get('graph', 'Neo4JStorage'),
                doc_status_storage=storage_config.get('doc_status', 'PGDocStatusStorage'),
                # Storage connection kwargs
                vector_db_storage_cls_kwargs=vector_db_kwargs,
                # Pass connection info via addon_params
                addon_params=addon_params,
            )

            # Initialize storage backends
            await self._rag.initialize_storages()
            self._initialized = True
            logger.info("LightRAG initialized successfully with remote storage")
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