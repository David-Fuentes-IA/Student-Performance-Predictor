import logging
import sys
import os

def setup_logger():
    logger = logging.getLogger("StudentPredictor")
    logger.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    
    # Ensure logs go to project directory
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "system_audit.log")
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)
        
    return logger

system_logger = setup_logger()
