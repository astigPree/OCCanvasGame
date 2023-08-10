
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from kivy.lang.builder import Builder

import home_screen

class MainWindow(MDScreenManager):
	
	def __init__(self , **kwargs):
		super(MainWindow , self).__init__(**kwargs)
		self.add_widget(home_screen.HomeScreen(name = "home"))


class ClashOfCourse(MDApp):
	
	def build(self):
		Builder.load_string(home_screen.home_screen_kv)
		return Builder.load_file("design.kv")
		
		
ClashOfCourse().run()
