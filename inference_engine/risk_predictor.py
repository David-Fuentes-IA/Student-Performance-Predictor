import os
import joblib
import pandas as pd
from core.exception_handler import ModelExecutionError
from core.logger import system_logger
from .cache_manager import cached_prediction

class IRiskPredictionEngine:
    def predict(self, features_df: pd.DataFrame) -> list:
        raise NotImplementedError

class RandomForestRiskPredictor(IRiskPredictionEngine):
    def __init__(self, model_path="risk_model.pkl"):
        full_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), model_path)
        try:
            self.model = joblib.load(full_path)
            system_logger.info(f"Model loaded successfully from {full_path}")
        except Exception as e:
            system_logger.error(f"Failed to load model from {full_path}: {e}")
            raise ModelExecutionError(f"Model could not be loaded. Ensure it's trained first. {e}")

    @cached_prediction
    def predict(self, features_df: pd.DataFrame) -> list:
        try:
            probas = self.model.predict_proba(features_df)
            if probas.shape[1] > 1:
                risk_scores = probas[:, 1] * 100
            else:
                risk_scores = [0] * len(features_df)
                
            return [round(score, 2) for score in risk_scores]
        except Exception as e:
            system_logger.error(f"Prediction failed: {e}")
            raise ModelExecutionError(f"Prediction failed: {e}")
