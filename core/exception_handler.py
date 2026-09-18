import logging

class StudentPredictorError(Exception):
    """Base exception for the system."""
    pass

class DataValidationError(StudentPredictorError):
    pass

class DatabaseConnectionError(StudentPredictorError):
    pass

class ModelExecutionError(StudentPredictorError):
    pass

def safe_execute(func):
    """Decorator to safely execute functions with try/except/finally."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in {func.__name__}: {str(e)}")
            raise StudentPredictorError(f"Execution failed: {str(e)}")
        finally:
            pass
    return wrapper
