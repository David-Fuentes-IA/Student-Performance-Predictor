import pandas as pd
from .fail_fast_validator import FailFastValidator

class ETLProcessor:
    @staticmethod
    def process_data(raw_data: list) -> pd.DataFrame:
        # Step 1: Fail Fast Validation
        validated_data = FailFastValidator.validate_raw_data(raw_data)
        
        # Step 2: Load into Pandas
        df = pd.DataFrame(validated_data)
        
        # Step 3: Transform (e.g. calculate average grade)
        df['avg_grade'] = df['grades'].apply(lambda grades: sum(grades) / len(grades) if grades else 0)
        
        # We can drop the raw grades list now that we have the average
        # df = df.drop(columns=['grades']) # keeping it in df might be useful for tracking, but we don't need it for ML
        
        # Any other cleaning or imputation would happen here
        df.fillna(0, inplace=True)
        
        return df
