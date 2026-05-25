#!/usr/bin/env python
"""
初始化 SlangMapping 表 - 黑话=关键词
将初始黑话词典写入 PostgreSQL antiblack schema，作为 MediaCrawler 的采集关键词来源。
"""
import sys
import os

# Fix encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from datetime import datetime
from config import get_config
from services.database import PostgreSQLService
from models import SlangMapping, SlangStatus


# 初始黑话词典 = 初始采集关键词
INITIAL_SLANG_MAPPINGS = [
    # 账号交易类
    {"slang_raw": "出抖号", "meaning": "出售抖音账号", "source": "preset"},
    {"slang_raw": "抖音号买卖", "meaning": "抖音账号交易", "source": "preset"},
    {"slang_raw": "租号", "meaning": "出租账号", "source": "preset"},
    {"slang_raw": "换绑", "meaning": "更换账号绑定", "source": "preset"},
    {"slang_raw": "千粉", "meaning": "千级别粉丝账号", "source": "preset"},
    {"slang_raw": "万粉", "meaning": "万级别粉丝账号", "source": "preset"},

    # 联系方式类
    {"slang_raw": "加V", "meaning": "添加微信号", "source": "preset"},
    {"slang_raw": "加微", "meaning": "添加微信号", "source": "preset"},
    {"slang_raw": "微信号", "meaning": "微信号", "source": "preset"},
    {"slang_raw": "V", "meaning": "微信号标记", "source": "preset"},

    # 刷量类
    {"slang_raw": "刷粉", "meaning": "刷粉丝", "source": "preset"},
    {"slang_raw": "刷赞", "meaning": "刷点赞", "source": "preset"},
    {"slang_raw": "刷量", "meaning": "刷数据量", "source": "preset"},
    {"slang_raw": "刷播放量", "meaning": "刷视频播放量", "source": "preset"},

    # 黑产工具类
    {"slang_raw": "接码", "meaning": "接码平台服务", "source": "preset"},
    {"slang_raw": "群控", "meaning": "群控工具", "source": "preset"},
    {"slang_raw": "脚本", "meaning": "自动化脚本", "source": "preset"},
    {"slang_raw": "养号", "meaning": "养号操作", "source": "preset"},

    # 交易相关
    {"slang_raw": "出号", "meaning": "出售账号", "source": "preset"},
    {"slang_raw": "收号", "meaning": "收购账号", "source": "preset"},
    {"slang_raw": "换号", "meaning": "更换账号", "source": "preset"},
]


def init_slang_mappings():
    """Initialize SlangMapping with initial slang/keywords."""
    print("=" * 60)
    print("初始化 SlangMapping (黑话=关键词)")
    print("=" * 60)

    config = get_config()
    db = PostgreSQLService.get_instance()

    # Check existing mappings
    existing = db.get_all_slang_mappings(verified_only=False)
    existing_words = {m['slang_raw'] for m in existing}

    print(f"\n当前已有黑话数量: {len(existing_words)}")

    # Add new mappings
    added_count = 0
    for slang_data in INITIAL_SLANG_MAPPINGS:
        slang_raw = slang_data['slang_raw']

        if slang_raw in existing_words:
            print(f"  [跳过] {slang_raw} (已存在)")
            continue

        mapping = SlangMapping(
            mapping_id=f"slang_{slang_raw}_{int(datetime.now().timestamp())}",
            slang_raw=slang_raw,
            meaning=slang_data['meaning'],
            regex_pattern=None,
            source=slang_data['source'],
            verified=True,  # 预置黑话直接标记为已验证
            confidence=1.0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.upsert_slang_mapping(mapping)
        added_count += 1
        print(f"  [添加] {slang_raw} → {slang_data['meaning']}")

    print(f"\n本次新增: {added_count} 条")

    # Show all current mappings
    all_mappings = db.get_all_slang_mappings(verified_only=True)
    print(f"\n当前生效关键词 ({len(all_mappings)} 条):")
    for m in all_mappings:
        print(f"  - {m['slang_raw']}: {m['meaning']}")

    print("\n" + "=" * 60)
    print("初始化完成!")
    print("=" * 60)


if __name__ == '__main__':
    init_slang_mappings()