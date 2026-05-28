"""
Telegram SQLAlchemy Models - telegram schema
使用独立 schema，与 antiblack 业务 schema 解耦
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime,
    Text, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class TelegramAccount(Base):
    """Telegram 账号表（存储 StringSession）。"""
    __tablename__ = 'telegram_account'
    __table_args__ = (
        {'schema': 'telegram'}
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, unique=True, nullable=False)
    api_id = Column(Integer, nullable=False)
    api_hash = Column(String(64), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    string_session = Column(Text)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    modified_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    monitors = relationship('TelegramMonitor', back_populates='account')


class TelegramChannel(Base):
    """监控的频道/群组表。"""
    __tablename__ = 'telegram_channel'
    __table_args__ = (
        UniqueConstraint('channel_id', name='uq_channel_id'),
        {'schema': 'telegram'}
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    channel_title = Column(String(256))
    channel_username = Column(String(128))
    channel_url = Column(String(256))
    is_private = Column(Boolean, default=False)
    is_mega_group = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    monitors = relationship('TelegramMonitor', back_populates='channel')
    messages = relationship('TelegramMessage', back_populates='channel')


class TelegramKeyword(Base):
    """关键词表（支持正则）。"""
    __tablename__ = 'telegram_keyword'
    __table_args__ = (
        {'schema': 'telegram'}
    )

    id = Column(Integer, primary_key=True)
    keyword = Column(String(256), nullable=False)
    regex_pattern = Column(String(512), nullable=False)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    messages = relationship('TelegramMessage', back_populates='keyword')


class TelegramMessage(Base):
    """消息表。"""
    __tablename__ = 'telegram_message'
    __table_args__ = (
        UniqueConstraint('channel_id', 'message_id', name='uq_channel_message'),
        Index('ix_telegram_message_processed', 'raw_json', postgresql_using='gin'),
        {'schema': 'telegram'}
    )

    id = Column(Integer, primary_key=True)
    message_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, ForeignKey('telegram.telegram_channel.channel_id'), nullable=False)
    user_id = Column(BigInteger)
    username = Column(String(128))
    text = Column(Text)
    timestamp = Column(DateTime)
    matched_keyword_id = Column(Integer, ForeignKey('telegram.telegram_keyword.id'))
    raw_json = Column(JSONB, default={})
    clue_id = Column(BigInteger)  # 关联到 antiblack.clues(id)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    channel = relationship('TelegramChannel', back_populates='messages')
    keyword = relationship('TelegramKeyword', back_populates='messages')


class TelegramMonitor(Base):
    """账号-频道监控映射表。"""
    __tablename__ = 'telegram_monitor'
    __table_args__ = (
        UniqueConstraint('account_id', 'channel_id', name='uq_account_channel'),
        {'schema': 'telegram'}
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('telegram.telegram_account.account_id'), nullable=False)
    channel_id = Column(BigInteger, ForeignKey('telegram.telegram_channel.channel_id'), nullable=False)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    # 关系
    account = relationship('TelegramAccount', back_populates='monitors')
    channel = relationship('TelegramChannel', back_populates='monitors')