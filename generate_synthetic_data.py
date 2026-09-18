import random
import pandas as pd
from data_access.student_repository import MongoStudentRepository
from learning_module.model_trainer import ModelTrainer
from learning_module.model_evaluator import ModelEvaluator
from feature_store.feature_manager import FeatureManager
from data_pipeline.etl_processor import ETLProcessor

def generate_data():
    repo = MongoStudentRepository()
    
    repo.collection.delete_many({})
    print("Cleared existing records.")

    groups = ['301-A', '302-B', '401-A']
    records = []
    
    for i in range(1, 101):
        attendance = random.randint(40, 100)
        grades = [random.randint(40, 100) for _ in range(3)]
        participation = random.randint(0, 100)
        
        record = {
            "student_id": f"S{i:04d}",
            "group_id": random.choice(groups),
            "grades": grades,
            "attendance_pct": attendance,
            "participation_score": participation
        }
        records.append(record)
        repo.insert_student_record(record)
    
    print(f"Inserted {len(records)} synthetic records into MongoDB.")
    
    raw_data = repo.get_all_students()
    df = ETLProcessor.process_data(raw_data)
    X = FeatureManager.extract_features(df)
    
    y = ((X['avg_grade'] < 70) | (X['attendance_pct'] < 75)).astype(int)
    
    trainer = ModelTrainer()
    trainer.train(X, y)
    
    acc, report = ModelEvaluator.evaluate(trainer.model, X, y)
    print(f"Model trained. Accuracy: {acc}")

if __name__ == "__main__":
    generate_data()
