import copy
class ProfileService:
    def __init__(self,settings): self.settings=settings
    def names(self):return sorted(self.settings.get("profiles",{}))
    def save(self,name,categories,excluded_categories=None):
        self.settings.setdefault("profiles",{})[name]={"categories":list(categories),"excluded_categories":list(excluded_categories or [])}
    def delete(self,name):self.settings.get("profiles",{}).pop(name,None)
    def get(self,name):return copy.deepcopy(self.settings.get("profiles",{}).get(name,{}))
