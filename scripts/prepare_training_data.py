#!/usr/bin/env python
"""
Training data preparation script for XGBoost classifier.
Generates embeddings from text samples and prepares training data.
"""
import os
import sys
import json
import pickle
import logging
from typing import List, Dict, Any, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_training_data(data_path: str) -> List[Dict[str, Any]]:
    """Load training data from JSON file."""
    with open(data_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_embeddings(texts: List[str], model_name: str = "BAAI/bge-small-zh-v1.5") -> List[List[float]]:
    """Generate embeddings for texts using sentence-transformers."""
    from models.embedding import EmbeddingModel

    logger.info(f"Loading embedding model: {model_name}")
    embed_model = EmbeddingModel(model_name=model_name)
    embed_model.load()

    logger.info(f"Generating embeddings for {len(texts)} texts...")
    embeddings = embed_model.encode(texts, batch_size=32, show_progress=True)

    return embeddings


def prepare_training_data(
    data: List[Dict[str, Any]],
    label_col: str = "label",
    text_col: str = "text"
) -> Tuple[List[List[float]], List[str]]:
    """
    Prepare training data for classifier.

    Args:
        data: List of samples with text and label
        label_col: Key for label in each sample
        text_col: Key for text in each sample

    Returns:
        X: List of embedding vectors
        y: List of labels
    """
    texts = [item[text_col] for item in data]
    labels = [item[label_col] for item in data]

    embeddings = generate_embeddings(texts)

    return embeddings, labels


def train_xgboost_classifier(
    X: List[List[float]],
    y: List[str],
    model_path: str = "./models/xgboost_classifier.pkl",
    label_encoder_path: str = "./models/label_encoder.pkl"
) -> None:
    """
    Train XGBoost classifier and save model.

    Args:
        X: Training features (embeddings)
        y: Training labels
        model_path: Path to save XGBoost model
        label_encoder_path: Path to save label encoder
    """
    from sklearn.preprocessing import LabelEncoder
    import xgboost as xgb

    # Encode labels
    logger.info("Encoding labels...")
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)

    logger.info(f"Classes: {label_encoder.classes_}")
    logger.info(f"Training samples: {len(X)}")

    # Train XGBoost
    logger.info("Training XGBoost classifier...")
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        objective='multi:softmax',
        num_class=len(label_encoder.classes_),
        n_jobs=-1,
        eval_metric='mlogloss'
    )

    model.fit(X, y_encoded)

    # Save model
    logger.info(f"Saving model to {model_path}")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)

    # Save label encoder
    logger.info(f"Saving label encoder to {label_encoder_path}")
    with open(label_encoder_path, 'wb') as f:
        pickle.dump(label_encoder, f)

    logger.info("Training complete!")


def create_sample_data(output_path: str = "./data/sample_training_data.json") -> None:
    """
    Create sample training data for demonstration.
    In production, this would come from silver/platinum samples.
    """
    samples = [
        # 账号交易 - 抖音号买卖
        {"text": "出一批实名抖音号,8+以上粉丝,私信报价", "label": "DOUYIN_ACCOUNT_SALE"},
        {"text": "大量回收未实名抖音号,价格美丽", "label": "DOUYIN_ACCOUNT_SALE"},
        {"text": "出小黄车权限抖音号,需要来", "label": "DOUYIN_ACCOUNT_SALE"},
        {"text": "代实名抖音号,稳定出号", "label": "DOUYIN_ACCOUNT_SALE"},
        # 账号交易 - 账号租借
        {"text": "长期求租抖音号,日结", "label": "ACCOUNT_RENTAL"},
        {"text": "租用抖音号,粉丝1w+,有偿", "label": "ACCOUNT_RENTAL"},
        {"text": "抖音号出租,安全快速", "label": "ACCOUNT_RENTAL"},
        # 账号交易 - 账号转让
        {"text": "抖音号转让,粉丝5000+,诚心出", "label": "ACCOUNT_TRANSFER"},
        {"text": "永久转让抖音号,手续齐全", "label": "ACCOUNT_TRANSFER"},
        # 诈骗引流 - 刷单引流
        {"text": "兼职刷单,一单一结,扫码进群", "label": "BRUSH_ORDER"},
        {"text": "电商刷单,一单一结,一单5-50元", "label": "BRUSH_ORDER"},
        {"text": "抖音关注点赞,日入200+,加我", "label": "BRUSH_ORDER"},
        {"text": "刷单兼职,正规平台,一单8元起", "label": "BRUSH_ORDER"},
        # 诈骗引流 - 杀猪盘
        {"text": "感情骗子,谎称投资诈骗,大家小心", "label": "PIG_BUTCHER"},
        {"text": "杀猪盘新套路,先谈恋爱后投资", "label": "PIG_BUTCHER"},
        {"text": "防范杀猪盘,不要轻信网友投资", "label": "PIG_BUTCHER"},
        # 诈骗引流 - 兼职诈骗
        {"text": "招打字员,日赚300,押金先交", "label": "PART_TIME_FRAUD"},
        {"text": "兼职录入员,在家可做,收费500", "label": "PART_TIME_FRAUD"},
        {"text": "高薪兼职,先交培训费,退款不退", "label": "PART_TIME_FRAUD"},
        # 流量作弊 - 刷粉
        {"text": "抖音快手刷粉,1000粉只需50元", "label": "FAKE_FOLLOWERS"},
        {"text": "全网最低价刷粉,安全不封号", "label": "FAKE_FOLLOWERS"},
        {"text": "专业刷粉,真实粉丝,永久不掉", "label": "FAKE_FOLLOWERS"},
        # 流量作弊 - 刷赞
        {"text": "抖音刷赞,1元100赞,量大优惠", "label": "FAKE_LIKES"},
        {"text": "快手刷赞,安全快速,包售后", "label": "FAKE_LIKES"},
        {"text": "刷赞自助下单,永久有效", "label": "FAKE_LIKES"},
        # 流量作弊 - 刷播放量
        {"text": "视频播放量提升,1000播放只要5元", "label": "FAKE_VIEWS"},
        {"text": "专业刷播放量,真人一比一", "label": "FAKE_VIEWS"},
        {"text": "短视频播放量代刷,当日见效", "label": "FAKE_VIEWS"},
        # 黑产工具 - 接码平台
        {"text": "接码平台,抖音快手验证码,稳定在线", "label": "PHONE_OTP"},
        {"text": "专业接码,大量靓号,支持语音验证码", "label": "PHONE_OTP"},
        {"text": "最新接码平台,首充10元送20", "label": "PHONE_OTP"},
        # 黑产工具 - 群控工具
        {"text": "群控系统,一台电脑控制100台手机", "label": "BATCH_CONTROL"},
        {"text": "抖音群控,自动点赞评论,日引流500+", "label": "BATCH_CONTROL"},
        {"text": "专业群控设备,适用于所有平台", "label": "BATCH_CONTROL"},
        # 正常样本
        {"text": "今天天气真好,出门散步", "label": "NORMAL"},
        {"text": "周末计划去爬山,有人一起吗", "label": "NORMAL"},
        {"text": "分享一道美食做法,简单易学", "label": "NORMAL"},
        {"text": "求推荐好看的电影", "label": "NORMAL"},
        {"text": "今天加班到很晚,累死了", "label": "NORMAL"},
        {"text": "学习Python编程的第一天", "label": "NORMAL"},
        {"text": "新买的手机到了,开箱测评", "label": "NORMAL"},
        {"text": "周末自驾游,风景真美", "label": "NORMAL"},
    ]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)

    logger.info(f"Sample training data saved to {output_path}")
    logger.info(f"Total samples: {len(samples)}")
    logger.info(f"Labels: {set(s['label'] for s in samples)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare training data for XGBoost classifier")
    parser.add_argument("--data", "-d", help="Path to training data JSON file")
    parser.add_argument("--model", "-m", help="Path to save trained model")
    parser.add_argument("--create-sample", "-s", action="store_true", help="Create sample training data")
    parser.add_argument("--output", "-o", default="./data/sample_training_data.json", help="Output path for sample data")

    args = parser.parse_args()

    if args.create_sample:
        create_sample_data(args.output)
    elif args.data:
        # Load data
        data = load_training_data(args.data)

        # Prepare training data
        X, y = prepare_training_data(data)

        # Train and save model
        model_path = args.model or "./models/xgboost_classifier.pkl"
        label_encoder_path = model_path.replace(".pkl", "_label_encoder.pkl")
        train_xgboost_classifier(X, y, model_path, label_encoder_path)
    else:
        parser.print_help()
