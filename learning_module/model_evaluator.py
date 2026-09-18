from sklearn.metrics import accuracy_score, classification_report
import pandas as pd
from core.logger import system_logger

class ModelEvaluator:
    @staticmethod
    def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series):
        predictions = model.predict(X_test)
        acc = accuracy_score(y_test, predictions)
        report = classification_report(y_test, predictions, zero_division=0)
        
        system_logger.info(f"Model Evaluation - Accuracy: {acc:.2f}")
        system_logger.info(f"Classification Report:\n{report}")
        
        return acc, report
