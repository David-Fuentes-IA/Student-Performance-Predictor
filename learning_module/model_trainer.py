import os
import joblib
from sklearn.ensemble import RandomForestClassifier
import pandas as pd
from core.logger import system_logger

class ModelTrainer:
    def __init__(self, model_path="risk_model.pkl"):
        self.model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), model_path)
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        
    def train(self, X: pd.DataFrame, y: pd.Series):
        system_logger.info("Starting model training...")
        self.model.fit(X, y)
        system_logger.info("Model training completed.")
        self.save_model()
        
    def save_model(self):
        joblib.dump(self.model, self.model_path)
        system_logger.info(f"Model saved to {self.model_path}")
