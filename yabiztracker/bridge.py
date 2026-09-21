from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
class MapBridge(QObject):
    onOrganizationSelected=pyqtSignal(str)
    mapReady=pyqtSignal()
    @pyqtSlot(str)
    def onMarkerClicked(self,org_id):self.onOrganizationSelected.emit(org_id)
    @pyqtSlot()
    def onMapReady(self):self.mapReady.emit()
