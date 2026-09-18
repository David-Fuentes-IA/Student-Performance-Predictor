import pandas as pd

class FeatureManager:
    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts and selects features required by the prediction model.
        Returns a DataFrame ready for model input.
        """
        features = ['avg_grade', 'attendance_pct', 'participation_score']
        
        # Ensure all required features are present
        for feature in features:
            if feature not in df.columns:
                df[feature] = 0
                
        return df[features]
