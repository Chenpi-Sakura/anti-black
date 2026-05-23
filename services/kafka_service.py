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

        # In demo mode, we use a mock producer
        self._demo_mode = True
        self._pending_messages: Dict[str, List[Dict]] = {}

    async def start(self) -> None:
        """Initialize producer connection."""
        if self._demo_mode:
            logger.info("Kafka producer running in demo mode")
            return

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
            logger.warning(f"Failed to connect to Kafka, using demo mode: {e}")
            self._demo_mode = True

    async def stop(self) -> None:
        """Stop producer connection."""
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def send(self, topic: str, value: Dict[str, Any], key: str = None) -> bool:
        """Send a message to a topic."""
        if self._demo_mode:
            if topic not in self._pending_messages:
                self._pending_messages[topic] = []
            self._pending_messages[topic].append({
                'key': key,
                'value': value,
                'timestamp': datetime.utcnow().isoformat()
            })
            logger.debug(f"Demo: stored message in topic {topic}")
            return True

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

        # In demo mode, use mock data
        self._demo_mode = True

    async def start(self) -> None:
        """Initialize consumer connection."""
        if self._demo_mode:
            logger.info("Kafka consumer running in demo mode")
            return

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
            logger.warning(f"Failed to connect to Kafka, using demo mode: {e}")
            self._demo_mode = True

    async def stop(self) -> None:
        """Stop consumer connection."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    async def consume(self, handler: Callable[[Dict[str, Any]], None], max_messages: int = 100) -> int:
        """Consume messages and process with handler."""
        if self._demo_mode:
            return await self._consume_demo(handler, max_messages)

        processed = 0
        try:
            async for msg in self._consumer:
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

    async def _consume_demo(self, handler: Callable[[Dict[str, Any]], Any], max_messages: int) -> int:
        """Demo mode consumption - generate mock messages."""
        processed = 0
        mock_messages = self._generate_mock_messages(max_messages)

        for msg in mock_messages:
            try:
                await handler(msg)
                processed += 1
            except Exception as e:
                logger.error(f"Error processing mock message: {e}")

        return processed

    def _generate_mock_messages(self, count: int) -> List[Dict[str, Any]]:
        """Generate mock messages for demo."""
        messages = []
        templates = [
            {
                'message_id': 'msg_001',
                'source_channel': 'telegram',
                'group_id': 'tg_group_001',
                'author_id': 'user_001',
                'raw_text': '出抖号，千粉，换绑稳，加V:dyhao668',
                'published_at': '2026-05-23T10:00:00+08:00'
            },
            {
                'message_id': 'msg_002',
                'source_channel': 'telegram',
                'group_id': 'tg_group_001',
                'author_id': 'user_002',
                'raw_text': '接码平台新开，联系电话13800138000',
                'published_at': '2026-05-23T10:05:00+08:00'
            },
            {
                'message_id': 'msg_003',
                'source_channel': 'forum',
                'group_id': 'forum_tieba_001',
                'author_id': 'forum_user_001',
                'raw_text': '专业刷粉，价格优惠，微信:brushdan001',
                'published_at': '2026-05-23T10:10:00+08:00'
            }
        ]

        for i in range(count):
            template = templates[i % len(templates)]
            msg = template.copy()
            msg['message_id'] = f"{template['message_id']}_{i}"
            messages.append(msg)

        return messages


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
        consumer = KafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            topics=[topic],
            group_id=group_id,
            config=self.config
        )
        return consumer

    async def send_to_topic(self, topic: str, message: Dict[str, Any]) -> bool:
        """Send a message to a topic."""
        return await self.producer.send(topic, message)

    async def send_batch_to_topic(self, topic: str, messages: List[Dict[str, Any]]) -> int:
        """Send multiple messages to a topic."""
        return await self.producer.send_batch(topic, messages)