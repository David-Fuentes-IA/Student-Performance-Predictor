from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

from data_access.student_repository import MongoStudentRepository
from data_pipeline.etl_processor import ETLProcessor
from feature_store.feature_manager import FeatureManager
from inference_engine.risk_predictor import RandomForestRiskPredictor
from core.audit_observer import Subject, AuditLogObserver, NotificationServiceObserver
from core.exception_handler import StudentPredictorError
from core.logger import system_logger

app = FastAPI(title="Student Performance Predictor API")

repo = MongoStudentRepository()
try:
    predictor = RandomForestRiskPredictor()
except Exception as e:
    system_logger.warning("Predictor not initialized. Model might not exist yet.")
    predictor = None

alert_subject = Subject()
alert_subject.attach(AuditLogObserver())
alert_subject.attach(NotificationServiceObserver())

RISK_THRESHOLD = 75.0

class RiskReportResponse(BaseModel):
    student_id: str
    risk_score: float
    risk_level: str

@app.get("/api/reports/group/{group_id}", response_model=List[RiskReportResponse])
def get_group_risk_report(group_id: str):
    try:
        raw_data = repo.get_students_by_group(group_id)
        if not raw_data:
            raise HTTPException(status_code=404, detail="Group not found or no students in group.")

        df = ETLProcessor.process_data(raw_data)
        features_df = FeatureManager.extract_features(df)
        
        global predictor
        if predictor is None:
            # Try to load it again if it was created after startup
            try:
                predictor = RandomForestRiskPredictor()
            except:
                raise HTTPException(status_code=500, detail="Prediction model is not loaded.")
        
        risk_scores = predictor.predict(features_df)
        
        report = []
        for index, record in enumerate(raw_data):
            score = risk_scores[index]
            level = "High" if score >= 80 else ("Medium" if score >= 50 else "Low")
            
            if score >= RISK_THRESHOLD:
                alert_subject.notify("RISK_ALERT", {
                    "student_id": record["student_id"],
                    "risk_level": score,
                    "group_id": group_id
                })
                
            report.append(RiskReportResponse(
                student_id=record["student_id"],
                risk_score=score,
                risk_level=level
            ))
            
        return report

    except StudentPredictorError as e:
        system_logger.error(f"Business logic error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        system_logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
