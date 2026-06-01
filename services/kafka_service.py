"""
Kafka integration for AntiBlack pipeline.
Handles message queue producer and consumer operations.
"""
import json
import logging
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Kafka producer for sending messages to topics."""

    def __init__(self, bootstrap_servers: str, config: Dict[str, Any] = None):
        self.bootstrap_servers = bootstrap_servers
        self.config = config or {}
        self._producer = None

    async def start(self) -> None:
        """Initialize producer connection."""
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if k else None,
                acks=self.config.get('producer', {}).get('acks', 'all'),
                retries=self.config.get('producer', {}).get('retries', 3)
            )
            await self._producer.start()
            logger.info(f"Kafka producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise e

    async def stop(self) -> None:
        """Stop producer connection."""
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def send(self, topic: str, value: Dict[str, Any], key: str = None) -> bool:
        """Send a message to a topic."""
        if not self._producer:
            logger.error("Kafka producer is not initialized.")
            return False

        try:
            await self._producer.send_and_wait(topic, value, key=key)
            logger.debug(f"Sent message to topic {topic}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {topic}: {e}")
            return False

    async def send_batch(self, topic: str, messages: List[Dict[str, Any]]) -> int:
        """Send multiple messages to a topic."""
        sent = 0
        for msg in messages:
            if await self.send(topic, msg, msg.get('message_id')):
                sent += 1
        return sent


class KafkaConsumer:
    """Kafka consumer for receiving messages from topics."""

    def __init__(self, bootstrap_servers: str, topics: List[str], group_id: str, config: Dict[str, Any] = None):
        self.bootstrap_servers = bootstrap_servers
        self.topics = topics
        self.group_id = group_id
        self.config = config or {}
        self._consumer = None
        self._running = False

    async def start(self) -> None:
        """Initialize consumer connection."""
        try:
            from aiokafka import AIOKafkaConsumer
            self._consumer = AIOKafkaConsumer(
                *self.topics,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset=self.config.get('consumer', {}).get('auto_offset_reset', 'earliest'),
                enable_auto_commit=self.config.get('consumer', {}).get('enable_auto_commit', True)
            )
            await self._consumer.start()
            self._running = True
            logger.info(f"Kafka consumer connected to {self.bootstrap_servers}, topics: {self.topics}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise e

    async def stop(self) -> None:
        """Stop consumer connection."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    async def consume(self, handler: Callable[[Dict[str, Any]], None], max_messages: int = 100) -> int:
        """Consume messages and process with handler."""
        if not self._consumer:
            logger.error("Kafka consumer is not initialized.")
            return 0

        processed = 0
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                try:
                    await handler(msg.value)
                    processed += 1
                    if processed >= max_messages:
                        break
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except Exception as e:
            logger.error(f"Error consuming messages: {e}")

        return processed


class KafkaManager:
    """Manager for Kafka producer and consumer operations."""

    def __init__(self, bootstrap_servers: str, config: Dict[str, Any] = None):
        self.bootstrap_servers = bootstrap_servers
        self.config = config or {}
        self.producer = KafkaProducer(bootstrap_servers, config)
        self._consumers: Dict[str, KafkaConsumer] = {}

    async def start(self) -> None:
        """Start Kafka manager."""
        await self.producer.start()

    async def stop(self) -> None:
        """Stop Kafka manager and all consumers."""
        for consumer in self._consumers.values():
            await consumer.stop()
        await self.producer.stop()

    def get_consumer(self, topic: str, group_id: str) -> KafkaConsumer:
        """Get or create a consumer for a topic."""
        key = f"{topic}_{group_id}"
        if key not in self._consumers:
            consumer = KafkaConsumer(
                bootstrap_servers=self.bootstrap_servers,
                topics=[topic],
                group_id=group_id,
                config=self.config
            )
            self._consumers[key] = consumer
        return self._consumers[key]

    async def send_to_topic(self, topic: str, message: Dict[str, Any]) -> bool:
        """Send a message to a topic."""
        return await self.producer.send(topic, message)

    async def send_batch_to_topic(self, topic: str, messages: List[Dict[str, Any]]) -> int:
        """Send multiple messages to a topic."""
        return await self.producer.send_batch(topic, messages)