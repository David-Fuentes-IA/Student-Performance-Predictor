from abc import ABC, abstractmethod
from typing import List, Any
from .logger import system_logger
from datetime import datetime

class Observer(ABC):
    @abstractmethod
    def update(self, event_type: str, data: Any):
        pass

class Subject(ABC):
    def __init__(self):
        self._observers: List[Observer] = []

    def attach(self, observer: Observer):
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: Observer):
        self._observers.remove(observer)

    def notify(self, event_type: str, data: Any):
        for observer in self._observers:
            observer.update(event_type, data)

class AuditLogObserver(Observer):
    def update(self, event_type: str, data: Any):
        if event_type == "RISK_ALERT":
            # Strip PII (like names) in audit log per requirements (DR-1)
            system_logger.info(f"AUDIT LOG: Risk Alert - StudentID: {data.get('student_id')}, Risk Level: {data.get('risk_level')}%, Timestamp: {datetime.now().isoformat()}")

class NotificationServiceObserver(Observer):
    def update(self, event_type: str, data: Any):
        if event_type == "RISK_ALERT":
            system_logger.warning(f"NOTIFICATION SERVICE: Alert sent to Academic Tutor for StudentID: {data.get('student_id')} - HIGH RISK DETECTED.")
