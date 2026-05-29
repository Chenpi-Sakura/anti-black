#!/usr/bin/env python
"""Test XGBoost classifier."""
import sys
sys.path.insert(0, '.')

from models import ClassificationModel, EmbeddingModel

# Initialize
embed_model = EmbeddingModel()
embed_model.load()

clf_model = ClassificationModel(
    model_type="xgboost",
    model_path="./models/ml/assets/xgboost_classifier.pkl",
    label_encoder_path="./models/ml/assets/xgboost_classifier_label_encoder.pkl"
)
clf_model.load()

# Test samples
test_texts = [
    "出一批实名抖音号,8+以上粉丝,私信报价",
    "兼职刷单,一单一结,扫码进群",
    "今天天气真好,出门散步",
    "抖音刷粉,1000粉只需50元",
    "长期求租抖音号,日结"
]

print("Testing XGBoost classifier...")
print("-" * 50)

for text in test_texts:
    embedding = embed_model.encode(text)
    pred = clf_model.predict(embedding)
    proba = clf_model.predict_proba(embedding)
    print(f"Text: {text[:30]}...")
    print(f"Prediction: {pred[0]}")
    print(f"Confidence: {proba[0][0]:.2f}")
    print()
