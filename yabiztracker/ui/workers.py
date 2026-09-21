from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class HealthWorker(QThread):
    geocoder=pyqtSignal(bool,str); search=pyqtSignal(bool,str)
    def __init__(self,api,bbox):super().__init__();self.api=api;self.bbox=bbox
    def run(self):
        try:self.geocoder.emit(*self.api.test_geocoder_key())
        except Exception as e:self.geocoder.emit(False,str(e))
        if self.isInterruptionRequested(): return
        try:self.search.emit(*self.api.test_search_key(self.bbox))
        except Exception as e:self.search.emit(False,str(e))

class SuggestWorker(QThread):
    finished=pyqtSignal(int,str,list); failed=pyqtSignal(int,str,str)
    def __init__(self,api,text,request_id):
        super().__init__();self.api=api;self.text=text;self.request_id=request_id
    def run(self):
        try:self.finished.emit(self.request_id,self.text,self.api.suggest_settlements(self.text))
        except Exception as e:self.failed.emit(self.request_id,self.text,str(e))
