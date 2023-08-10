
import os
import json



class AppDataHandler:
	
	filename = "eric.app.clash"
	data = {
		"user id" : "" , "clicked" : 0 , "course" : ""
		}
	
	def loadData(self):
		if not os.path.exists(self.filename):
			with open(self.filename , "w") as file:
				json.dump(self.data , file)
		with open(self.filename , "r") as file:
			self.data = json.load(file)
	
	def saveData(self):
		with open(self.filename , "w") as file:
			json.dump(self.data , file)
	
	def resetData(self):
		self.data["user id"] = ""
		self.data["clicked"] = 0
		self.data["course"] = ""
		self.saveData()
	
	# -----> Updating Data
	def clickedPixel(self):
		self.data["clicked"] += 1
	
	def changeCourse(self , course : str ):
		self.data["course"] = course
	
	# -----> Reading Data 
	@property
	def number_of_clicked(self) -> int :
		return self.data["clicked"]
	
	@property
	def course(self) -> str:
		return self.data["course"]
	
	@property
	def userId(self) -> str:
		return self.data["user id"]
	


if __name__ == "__main__":
	pass

