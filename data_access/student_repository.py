from pymongo import MongoClient
from core.exception_handler import DatabaseConnectionError
from core.logger import system_logger

class IAcademicDataRepository:
    def get_students_by_group(self, group_id: str):
        raise NotImplementedError

    def insert_student_record(self, record: dict):
        raise NotImplementedError
        
    def get_all_students(self):
        raise NotImplementedError

class MongoStudentRepository(IAcademicDataRepository):
    def __init__(self, uri="mongodb://localhost:27017", db_name="student_predictor"):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.client[db_name]
            self.collection = self.db["academic_records"]
            # Verify connection
            self.client.admin.command('ping')
            system_logger.info("Connected to MongoDB successfully.")
        except Exception as e:
            system_logger.error(f"Failed to connect to MongoDB: {e}")
            raise DatabaseConnectionError("MongoDB connection failed. Is the server running?")

    def get_students_by_group(self, group_id: str):
        try:
            records = list(self.collection.find({"group_id": group_id}, {"_id": 0}))
            return records
        except Exception as e:
            system_logger.error(f"Error fetching students for group {group_id}: {e}")
            raise DatabaseConnectionError(f"Database read failed: {e}")

    def insert_student_record(self, record: dict):
        try:
            self.collection.insert_one(record)
        except Exception as e:
            system_logger.error(f"Error inserting student record: {e}")
            raise DatabaseConnectionError(f"Database write failed: {e}")
            
    def get_all_students(self):
        try:
            return list(self.collection.find({}, {"_id": 0}))
        except Exception as e:
            raise DatabaseConnectionError(f"Database read failed: {e}")
