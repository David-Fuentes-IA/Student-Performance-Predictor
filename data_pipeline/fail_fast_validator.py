from core.exception_handler import DataValidationError

class FailFastValidator:
    @staticmethod
    def validate_raw_data(data: list) -> list:
        if not data:
            raise DataValidationError("No data provided.")
        
        validated_data = []
        for index, record in enumerate(data):
            # Check required fields
            required_fields = ['student_id', 'group_id', 'grades', 'attendance_pct', 'participation_score']
            for field in required_fields:
                if field not in record or record[field] is None:
                    raise DataValidationError(f"Missing required field '{field}' in record {index}.")
            
            # Range checks
            if not (0 <= record['attendance_pct'] <= 100):
                raise DataValidationError(f"Attendance percentage out of range (0-100) in record {index}.")
            
            if not (0 <= record['participation_score'] <= 100):
                raise DataValidationError(f"Participation score out of range (0-100) in record {index}.")
            
            for grade in record['grades']:
                if not (0 <= grade <= 100):
                    raise DataValidationError(f"Grade {grade} out of range (0-100) in record {index}.")
            
            validated_data.append(record)
            
        return validated_data
